"""Isolated FRET sandbox. Uses upstream compiler/CLI, never substitutes a solver."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from report import render

ROOT = Path(__file__).resolve().parent
SHA = "cf0f913cc15c41705e803593297e89cd6056b839"
IMAGE = "svod-fret-sandbox:cf0f913"


def normalize(summary, source, image):
    diagnostics = summary.get("diagnosis") or []
    if isinstance(diagnostics, dict):
        diagnostics = [diagnostics]
    conflicts, counterexamples = [], []
    for diagnostic in diagnostics:
        if isinstance(diagnostic, dict):
            conflicts.extend(item["Conflict"] for item in diagnostic.get("Conflicts", []))
            counterexamples.extend(diagnostic.get("Counterexamples", []))
    return {
        "status": summary.get("result", "UNKNOWN"),
        "requirements": source["requirements"],
        "title": source.get("title", ""),
        "project": source.get("project", ""),
        "component": source.get("component", ""),
        "conflicts": conflicts,
        "description": source.get("description", ""),
        "assumptions": source.get("assumptions", []),
        "counterexamples": counterexamples,
        "provenance": {
            "sourceSHA": SHA,
            "image": image,
            "solver": summary.get("solver"),
            "input_sha256": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
        },
    }


def build(cache_dir=None):
    cache = Path(cache_dir or Path.home() / ".cache/svod-fret").expanduser().resolve()
    if cache.is_relative_to(ROOT.parent.resolve()):
        raise ValueError("Cache must be outside the installed skill")
    cache.mkdir(parents=True, exist_ok=True)
    vendor = cache / ("upstream-" + SHA)
    if not vendor.exists():
        vendor.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "https://github.com/NASA-SW-VnV/fret.git", str(vendor)], check=True
        )
    subprocess.run(["git", "-C", str(vendor), "checkout", "--detach", SHA], check=True)
    dirty = subprocess.check_output(["git", "-C", str(vendor), "status", "--porcelain"], text=True)
    if dirty.strip():
        raise RuntimeError("Vendor checkout changed; refusing build")
    context = Path(tempfile.mkdtemp(prefix="build-", dir=cache))
    for name in (
        "Dockerfile",
        "package.json",
        "package-lock.json",
        "jkind.sha256",
        "api.js",
        "webpack.config.cjs",
        "run.cjs",
        "jrealizability-log",
    ):
        shutil.copy2(ROOT / name, context / name)
    target = context / "runtime" / "source"
    target.parent.mkdir()
    shutil.copytree(vendor / "fret-electron", target)
    for name in ("LICENSE.pdf", "CONTRIBUTORS.md"):
        shutil.copy2(vendor / name, context / "runtime" / name)
    subprocess.run(["docker", "build", "-t", IMAGE, str(context)], check=True)


def run(source_path, output):
    source_path = source_path.resolve()
    output = output.resolve()
    if output.is_relative_to(ROOT.parent):
        raise ValueError("Output must be outside the installed skill")
    output.mkdir(parents=True, exist_ok=False)
    source = {"requirements": []}
    try:
        data = source_path.read_bytes()
        (output / "input.json").write_bytes(data)
        source = json.loads(data)
        validate_input(source)
        image = subprocess.check_output(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).strip()
        if not image:
            raise ValueError("Docker image inspect returned no image ID")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        # Keep input.json untouched; only project renderer-safe fields on validation failure.
        safe_source = dict(source) if isinstance(source, dict) else {}
        requirements = safe_source.get("requirements")
        safe_source["requirements"] = (
            [
                r
                for r in requirements
                if isinstance(r, dict)
                and isinstance(r.get("id"), str)
                and isinstance(r.get("text"), str)
            ]
            if isinstance(requirements, list)
            else []
        )
        if not isinstance(safe_source.get("assumptions", []), list):
            safe_source["assumptions"] = []
        result = normalize({"result": "ERROR"}, safe_source, None)
        result["diagnostics"] = [f"{type(exc).__name__}: {exc}"]
        persist_report(result, output)
        return result
    container = "svod-fret-" + uuid.uuid4().hex
    command = [
        "docker",
        "run",
        "--name",
        container,
        "--rm",
        "--network",
        "none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "2g",
        "-v",
        f"{output / 'input.json'}:/input.json:ro",
        "-v",
        f"{output}:/output",
        image,
        "node",
        "/opt/probe/run.cjs",
        "/input.json",
        "/output",
    ]
    with (output / "container.log").open("w") as log:
        try:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            code = completed.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            log.write(f"\n{type(exc).__name__}: {exc}\n")
            log.flush()
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as cleanup:
                log.write(f"Cleanup failed: {cleanup}\n")
            code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 1
    summary_path = output / "summary.json"
    errors = []
    try:
        summary = json.loads(summary_path.read_text())
        if not isinstance(summary, dict) or summary.get("result") not in (
            "REALIZABLE",
            "UNREALIZABLE",
            "UNKNOWN",
            "ERROR",
        ):
            raise ValueError("summary must contain a recognized result")
    except (OSError, ValueError) as exc:
        errors.append(f"Invalid summary.json: {exc}")
        summary = {"result": "ERROR"}
    if code not in (0, 2):
        errors.append(f"Container supervisor failed: exit {code}; see container.log")
        summary["result"] = "ERROR"
    if code == 2 and summary["result"] in ("REALIZABLE", "UNREALIZABLE"):
        errors.append("Nonfinal container exit contradicts final summary")
        summary["result"] = "ERROR"
    try:
        result = normalize(summary, source, image)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(f"Malformed diagnosis: {exc}")
        result = normalize({"result": "ERROR"}, source, image)
    result["diagnostics"] = errors
    semantics_path = output / "requirements-analysis.json"
    try:
        semantics = json.loads(semantics_path.read_text())["requirements"]
        if not isinstance(semantics, list) or [r["id"] for r in semantics] != [
            r["id"] for r in source["requirements"]
        ]:
            raise ValueError("Compiler semantics do not cover source requirements")
        if any(not isinstance(r.get("semantics"), dict) or not r["semantics"] for r in semantics):
            raise ValueError("Missing compiler semantics")
        result["semantics"] = semantics
        if result["status"] != "ERROR":
            validate_evidence(output, summary, source)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(f"Invalid analysis evidence: {exc}")
        result["status"] = "ERROR"
    result["provenance"]["container_exit_code"] = code
    result["provenance"]["input_sha256"] = hashlib.sha256(data).hexdigest()
    persist_report(result, output)
    return result


def persist_report(result, output):
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (output / "report.html").write_text(render(result), encoding="utf-8")
    print(f"{result['status']}: {output / 'report.html'}")


def validate_input(source):
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
    if not isinstance(source, dict):
        raise ValueError("Input must be an object")
    assumptions = source.get("assumptions", [])
    if not isinstance(assumptions, list) or any(not isinstance(a, str) for a in assumptions):
        raise ValueError("assumptions must be an array of strings")
    for key in ("title", "description"):
        if key in source and not isinstance(source[key], str):
            raise ValueError(f"{key} must be a string")
    for key in ("project", "component"):
        if not isinstance(source.get(key), str) or not identifier.fullmatch(source[key]):
            raise ValueError(f"{key} must be an identifier")
    for key in ("requirements", "variables"):
        if not isinstance(source.get(key), list) or not source[key]:
            raise ValueError(f"{key} must be a nonempty array")
    for requirement in source["requirements"]:
        if (
            not isinstance(requirement, dict)
            or not isinstance(requirement.get("id"), str)
            or not identifier.fullmatch(requirement["id"])
        ):
            raise ValueError("Requirement id must be an identifier")
        if not isinstance(requirement.get("text"), str) or not requirement["text"].strip():
            raise ValueError("Requirement text must be a nonempty string")
    if len({r["id"] for r in source["requirements"]}) != len(source["requirements"]):
        raise ValueError("Duplicate requirement ids")
    for variable in source["variables"]:
        if (
            not isinstance(variable, dict)
            or not isinstance(variable.get("name"), str)
            or not identifier.fullmatch(variable["name"])
        ):
            raise ValueError("Variable name must be an identifier")
        if variable.get("role") not in ("Input", "Output") or variable.get("type") not in (
            "boolean",
            "integer",
            "double",
        ):
            raise ValueError(
                "Supported variable roles Input/Output and types boolean/integer/double"
            )
    if len({v["name"] for v in source["variables"]}) != len(source["variables"]):
        raise ValueError("Duplicate variable names")
    timeout = source.get("timeout", 60)
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError("timeout must be integer 1..600 seconds")


def validate_evidence(output, summary, source):
    if any(
        summary.get(key) != value
        for key, value in {
            "sourceSHA": SHA,
            "solver": "jkind",
            "project": source["project"],
            "component": source["component"],
        }.items()
    ):
        raise ValueError("Summary provenance differs from requested analysis")
    raw = json.loads((output / "realizability.json").read_text())
    components = [c for c in raw["systemComponents"] if c["name"] == source["component"]]
    if raw.get("projectName") != source["project"] or len(components) != 1:
        raise ValueError("Raw report project/component mismatch")
    comp = components[0]
    analysis = (
        comp["monolithic"]
        if comp["compositional"]["result"] == "UNCHECKED"
        else comp["compositional"]
    )
    if analysis.get("error") or analysis["result"] != summary["result"]:
        raise ValueError("Raw report error or result contradicts summary")
    exits = list((output / "solver-invocations").glob("*.exit-code"))
    if not exits or any(p.read_text().strip() != "0" for p in exits):
        raise ValueError("Missing or failed solver invocation; no retry is performed")
    for args in (output / "solver-invocations").glob("*.args"):
        if not args.with_suffix(".exit-code").exists():
            raise ValueError("Unfinished solver invocation")
    failure_pattern = re.compile(
        r"process has terminated|segmentation fault|exception|outofmemory|fatal|solver.*crash",
        re.IGNORECASE,
    )
    for log in (output / "solver-invocations").glob("*"):
        if log.suffix in (".stdout", ".stderr") and failure_pattern.search(log.read_text()):
            raise ValueError(f"Solver failure diagnostic: {log.name}")
    answers = []
    for args in (output / "solver-invocations").glob("*.args"):
        arguments = args.read_text().splitlines()
        if arguments == ["-help"]:
            continue
        if not arguments or not arguments[-1].endswith("Spec.lus"):
            raise ValueError(f"Malformed solver arguments: {args.name}")
        path = args.with_suffix(".json")
        snapshot = json.loads(path.read_text())
        answer = snapshot.get("Answer", {}).get("text", "").upper()
        # Upstream JKind emits {} for some UNREALIZABLE runs; its immutable stdout
        # still records the answer. Never infer it from the summary or diagnosis.
        if snapshot == {}:
            stdout = args.with_suffix(".stdout").read_text()
            if re.search(
                r"^UNREALIZABLE \|\| REFINEMENTS = \d+ \|\| Time = [0-9.]+s$", stdout, re.MULTILINE
            ):
                answer = "UNREALIZABLE"
        if answer not in ("REALIZABLE", "UNREALIZABLE", "UNKNOWN"):
            raise ValueError(f"Missing/malformed solver Answer: {path.name}")
        if "_diagnosticQuery_" not in Path(arguments[-1]).name:
            answers.append(answer)
    if summary["result"] == "REALIZABLE" and any(a != "REALIZABLE" for a in answers):
        raise ValueError("Not every raw solver answer supports aggregate REALIZABLE")
    if summary["result"] != "ERROR" and summary["result"] not in answers:
        raise ValueError("No raw solver answer supports the summary")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache/svod-fret")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--output", type=Path, required=True)
    custom = commands.add_parser("run")
    custom.add_argument("input", type=Path)
    custom.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build(args.cache_dir)
        elif args.command == "run":
            result = run(args.input, args.output)
            return 0 if result["status"] in ("REALIZABLE", "UNREALIZABLE") else 1
        else:
            output = args.output.resolve()
            if output.is_relative_to(ROOT.parent):
                raise ValueError("Output must be outside the installed skill")
            output.mkdir(parents=True, exist_ok=False)
            for case, expected in [
                ("compatible", "REALIZABLE"),
                ("conflict", "UNREALIZABLE"),
                ("invalid", "ERROR"),
            ]:
                out = output / case
                result = run(ROOT.parent / "examples" / case / "requirements.json", out)
                if result["status"] != expected:
                    raise ValueError(f"Smoke {case}: expected {expected}, got {result['status']}")
                if case == "invalid":
                    if (
                        not (out / "seed.log").exists()
                        or "FRET seed failed" not in (out / "container.log").read_text()
                    ):
                        raise ValueError(
                            "Invalid FRETish must exercise the compiler, not fail host setup"
                        )
                    continue
                for requirement in result["requirements"]:
                    if "<svg" not in (out / (requirement["id"] + ".svg")).read_text():
                        raise ValueError("Missing native timing SVG")
                if case == "conflict" and (
                    ["R1", "R2"] not in result["conflicts"] or not result["counterexamples"]
                ):
                    raise ValueError("Missing conflict IDs or genuine counterexample")
            print(
                "SMOKE PASS: FRET/JKind outcomes, conflict, counterexample, "
                "native SVGs and invalid FRETish"
            )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Synthetic unit fixtures only: these are NOT FRET/solver acceptance evidence."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "svod/skills/svod-fret/scripts"
spec = importlib.util.spec_from_file_location("fret_launcher_unit", SCRIPTS / "launcher.py")
assert spec and spec.loader
launcher = importlib.util.module_from_spec(spec)
# Isolate the independently-owned renderer during launcher-only unit tests.
with patch.dict(
    sys.modules, {"report": types.SimpleNamespace(render=lambda result: json.dumps(result))}
):
    spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {
            "project": "UnitFixture",
            "component": "controller",
            "variables": [{"name": "active", "role": "Output", "type": "boolean"}],
            "requirements": [{"id": "R1", "text": "controller shall always satisfy active"}],
        }
        self.input = self.root / "requirements.json"
        self.input.write_text(json.dumps(self.source))

    def synthetic_run(self, output, summary="valid", code=0):
        def execute(command, **kwargs):
            if command[:2] == ["docker", "run"]:
                if summary != "missing":
                    (output / "summary.json").write_text(
                        json.dumps(
                            {
                                "result": "REALIZABLE",
                                "sourceSHA": launcher.SHA,
                                "solver": "jkind",
                                "project": "UnitFixture",
                                "component": "controller",
                            }
                        )
                        if summary == "valid"
                        else summary
                    )
                (output / "requirements-analysis.json").write_text(
                    json.dumps(
                        {
                            "requirements": [
                                {
                                    "id": "R1",
                                    "text": self.source["requirements"][0]["text"],
                                    "semantics": {"ft": "unit formula"},
                                }
                            ]
                        }
                    )
                )
                (output / "realizability.json").write_text(
                    json.dumps(
                        {
                            "projectName": "UnitFixture",
                            "systemComponents": [
                                {
                                    "name": "controller",
                                    "compositional": {"result": "UNCHECKED"},
                                    "monolithic": {"result": "REALIZABLE", "error": ""},
                                }
                            ],
                        }
                    )
                )
                solver = output / "solver"
                solver.mkdir(exist_ok=True)
                (solver / "controllerSpec.lus.json").write_text(
                    json.dumps({"Answer": {"text": "realizable"}})
                )
                invocations = output / "solver-invocations"
                invocations.mkdir(exist_ok=True)
                (invocations / "unit.exit-code").write_text("0\n")
                (invocations / "unit.args").write_text("-json\n/unit/controllerSpec.lus\n")
                (invocations / "unit.json").write_text(
                    json.dumps({"Answer": {"text": "realizable"}})
                )
            return types.SimpleNamespace(returncode=code)

        return execute

    def test_missing_or_malformed_summary_is_error_not_final(self):
        for summary in ("missing", "{broken", "[]", "{}"):
            with self.subTest(summary=summary):
                output = self.root / str(len(list(self.root.iterdir())))
                with (
                    patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                    patch.object(
                        launcher.subprocess, "run", side_effect=self.synthetic_run(output, summary)
                    ),
                ):
                    result = launcher.run(self.input, output)
                self.assertEqual(result["status"], "ERROR")
                self.assertTrue(result["diagnostics"])
                self.assertTrue((output / "report.json").exists())

    def test_complete_synthetic_evidence_allows_final_status(self):
        output = self.root / "valid"
        with (
            patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
            patch.object(
                launcher.subprocess, "run", side_effect=self.synthetic_run(output)
            ) as process,
        ):
            result = launcher.run(self.input, output)
        self.assertEqual(result["status"], "REALIZABLE")
        self.assertEqual(
            len([c for c in process.call_args_list if c.args[0][:2] == ["docker", "run"]]), 1
        )

    def test_realizable_requires_every_connected_solver_answer_to_be_realizable(self):
        for other in ("UNKNOWN", "UNREALIZABLE"):
            with self.subTest(other=other):
                output = self.root / f"mixed-{other}"
                original = self.synthetic_run(output)

                def execute(command, original=original, output=output, other=other, **kwargs):
                    completed = original(command, **kwargs)
                    if command[:2] == ["docker", "run"]:
                        (output / "solver/otherSpec.lus.json").write_text(
                            json.dumps({"Answer": {"text": other}})
                        )
                        base = output / "solver-invocations/other"
                        base.with_suffix(".args").write_text(
                            "-json\n/unit/controller_cc1Spec.lus\n"
                        )
                        base.with_suffix(".exit-code").write_text("0\n")
                        base.with_suffix(".json").write_text(
                            json.dumps({"Answer": {"text": other}})
                        )
                    return completed

                with (
                    patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                    patch.object(launcher.subprocess, "run", side_effect=execute),
                ):
                    exit_code = launcher.main(["run", str(self.input), "--output", str(output)])
                self.assertNotEqual(exit_code, 0)
                result = json.loads((output / "report.json").read_text())
                self.assertEqual(result["status"], "ERROR")
                self.assertTrue(result["diagnostics"])
                self.assertEqual(
                    json.loads((output / "solver/otherSpec.lus.json").read_text())["Answer"][
                        "text"
                    ],
                    other,
                )

    def test_invocation_snapshots_survive_upstream_diagnostic_overwrite(self):
        output = self.root / "diagnostic-overwrite"
        original = self.synthetic_run(output)

        def execute(command, **kwargs):
            completed = original(command, **kwargs)
            if command[:2] == ["docker", "run"]:
                for filename in ("summary.json", "realizability.json"):
                    path = output / filename
                    path.write_text(path.read_text().replace("REALIZABLE", "UNREALIZABLE"))
                (output / "solver/controllerSpec.lus.json").write_text("{}")
                invocations = output / "solver-invocations"
                (invocations / "unit.args").write_text(
                    "-json\n-fixpoint\n-timeout\n60\n-tracelength\n4\n"
                    "/tmp/fret-probe-unit/Documents/fret-analysis/controllerSpec.lus\n"
                )
                # Real upstream shape: even the main snapshot is {}, but stdout has the answer.
                (invocations / "unit.json").write_text("{}")
                (invocations / "unit.stdout").write_text(
                    "UNREALIZABLE || REFINEMENTS = 1 || Time = 0.101s\n"
                )
                for name, answer in (
                    ("diagnosticQuery_0", "realizable"),
                    ("diagnosticQuery_2_minimal", "unrealizable"),
                ):
                    base = invocations / name
                    base.with_suffix(".args").write_text(
                        f"-json\n/tmp/fret-analysis/controller_{name}Spec.lus\n"
                    )
                    base.with_suffix(".exit-code").write_text("0\n")
                    base.with_suffix(".json").write_text(json.dumps({"Answer": {"text": answer}}))
            return completed

        with (
            patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
            patch.object(launcher.subprocess, "run", side_effect=execute) as process,
        ):
            result = launcher.run(self.input, output)
        self.assertEqual(result["status"], "UNREALIZABLE")
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(process.call_count, 1)
        self.assertEqual((output / "solver/controllerSpec.lus.json").read_text(), "{}")

    def test_unknown_and_realizable_diagnostic_probes_keep_their_semantics(self):
        for status in ("UNKNOWN", "REALIZABLE"):
            with self.subTest(status=status):
                output = self.root / f"supported-{status}"
                original = self.synthetic_run(output)

                def execute(command, original=original, output=output, status=status, **kwargs):
                    completed = original(command, **kwargs)
                    if command[:2] == ["docker", "run"]:
                        for filename in ("summary.json", "realizability.json"):
                            path = output / filename
                            path.write_text(path.read_text().replace("REALIZABLE", status))
                        (output / "solver-invocations/unit.json").write_text(
                            json.dumps({"Answer": {"text": status}})
                        )
                        base = output / "solver-invocations/diagnostic"
                        base.with_suffix(".args").write_text(
                            "-json\n/unit/controller_diagnosticQuery_0Spec.lus\n"
                        )
                        base.with_suffix(".exit-code").write_text("0\n")
                        base.with_suffix(".json").write_text('{"Answer":{"text":"UNKNOWN"}}')
                    return completed

                with (
                    patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                    patch.object(launcher.subprocess, "run", side_effect=execute),
                ):
                    code = launcher.main(["run", str(self.input), "--output", str(output)])
                self.assertEqual(code, 1 if status == "UNKNOWN" else 0)
                result = json.loads((output / "report.json").read_text())
                self.assertEqual(result["status"], status)
                self.assertEqual(result["diagnostics"], [])

    def test_malformed_raw_lists_persist_error_instead_of_crashing(self):
        for filename, contents in (
            ("realizability.json", []),
            ("realizability.json", {"systemComponents": [[], None]}),
            ("solver-invocations/unit.json", []),
            ("solver-invocations/unit.json", {"Answer": []}),
        ):
            with self.subTest(filename=filename, contents=contents):
                output = self.root / str(len(list(self.root.iterdir())))
                original = self.synthetic_run(output)

                def execute(
                    command,
                    original=original,
                    output=output,
                    filename=filename,
                    contents=contents,
                    **kwargs,
                ):
                    completed = original(command, **kwargs)
                    if command[:2] == ["docker", "run"]:
                        (output / filename).write_text(json.dumps(contents))
                    return completed

                with (
                    patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                    patch.object(launcher.subprocess, "run", side_effect=execute),
                ):
                    result = launcher.run(self.input, output)
                self.assertEqual(result["status"], "ERROR")
                self.assertTrue((output / "report.html").exists())

    def test_raw_evidence_failure_cannot_be_overridden_by_final_summary(self):
        for defect in (
            "missing-raw",
            "bad-raw",
            "contradiction",
            "solver-crash",
            "missing-invocations",
            "bad-semantics",
        ):
            with self.subTest(defect=defect):
                output = self.root / defect
                original = self.synthetic_run(output)

                def execute(command, original=original, defect=defect, output=output, **kwargs):
                    completed = original(command, **kwargs)
                    if command[:2] == ["docker", "run"]:
                        if defect == "missing-raw":
                            (output / "realizability.json").unlink()
                        elif defect == "bad-raw":
                            (output / "solver-invocations/unit.json").write_text("{}")
                        elif defect == "contradiction":
                            (output / "solver-invocations/unit.json").write_text(
                                '{"Answer":{"text":"unrealizable"}}'
                            )
                        elif defect == "solver-crash":
                            (output / "solver-invocations/unit.exit-code").write_text("139")
                        elif defect == "missing-invocations":
                            (output / "solver-invocations/unit.exit-code").unlink()
                        else:
                            (output / "requirements-analysis.json").write_text("[]")
                    return completed

                with (
                    patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                    patch.object(launcher.subprocess, "run", side_effect=execute),
                ):
                    result = launcher.run(self.input, output)
                self.assertEqual(result["status"], "ERROR")
                self.assertTrue(result["diagnostics"])
                self.assertEqual(
                    json.loads((output / "summary.json").read_text())["result"], "REALIZABLE"
                )

    def test_timeout_and_supervisor_exceptions_preserve_error_without_retry(self):
        import subprocess

        for failure in (OSError("unit spawn failure"), subprocess.TimeoutExpired("docker", 1)):
            output = self.root / type(failure).__name__

            def execute(command, failure=failure, **kwargs):
                if command[:2] == ["docker", "run"]:
                    raise failure
                return types.SimpleNamespace(returncode=0)

            with (
                patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                patch.object(launcher.subprocess, "run", side_effect=execute) as process,
            ):
                result = launcher.run(self.input, output)
            self.assertEqual(result["status"], "ERROR")
            self.assertTrue(result["diagnostics"])
            self.assertEqual(
                len([c for c in process.call_args_list if c.args[0][:2] == ["docker", "run"]]), 1
            )
            self.assertIn(type(failure).__name__, (output / "container.log").read_text())

    def test_normalization_preserves_russian_source_and_assumptions(self):
        source = {
            "title": "Ожидание публикации",
            "project": "UnitFixture",
            "component": "controller",
            "description": "Ожидание решения",
            "assumptions": ["Один шаг — событие"],
            "requirements": [
                {
                    "id": "R1",
                    "text": "controller shall always satisfy active",
                    "description": "Пользователь ждёт",
                }
            ],
        }
        result = launcher.normalize(
            {
                "result": "UNREALIZABLE",
                "diagnosis": {
                    "Conflicts": [{"Conflict": ["R1", "R2"]}],
                    "Counterexamples": [{"traceLength": "1"}],
                },
            },
            source,
            "sha256:unit",
        )
        for key in ("title", "project", "component", "description"):
            self.assertEqual(result[key], source[key])
        self.assertEqual(result["assumptions"], source["assumptions"])
        self.assertEqual(result["requirements"], source["requirements"])
        self.assertEqual(result["conflicts"], [["R1", "R2"]])

    def test_invalid_input_is_error_before_docker(self):
        for document in (
            "{broken",
            "[]",
            "{}",
            json.dumps({**self.source, "requirements": [{"id": "../bad", "text": "x"}]}),
            *(json.dumps({**self.source, "assumptions": value}) for value in (None, 42, "x", [42])),
            json.dumps({**self.source, "title": []}),
            json.dumps({**self.source, "description": None}),
        ):
            self.input.write_text(document)
            output = self.root / str(len(list(self.root.iterdir())))
            with (
                patch.object(
                    launcher.subprocess,
                    "check_output",
                    side_effect=AssertionError("Invalid input reached Docker"),
                ) as inspect,
                patch.object(launcher.subprocess, "run") as process,
            ):
                result = launcher.run(self.input, output)
            self.assertEqual(result["status"], "ERROR")
            self.assertTrue((output / "input.json").exists())
            inspect.assert_not_called()
            process.assert_not_called()

    def test_invalid_source_cli_persists_error_with_real_renderer(self):
        for index, invalid in enumerate(
            (
                {"requirements": [{"text": "Русский исходник без ID"}]},
                {"requirements": [{"id": "R1"}]},
                {"requirements": [None, 42, "not an object"]},
                {"assumptions": None},
                {"assumptions": 42},
                {"assumptions": "not an array"},
                {"requirements": None},
            )
        ):
            with self.subTest(invalid=invalid):
                document = json.dumps({**self.source, **invalid}, ensure_ascii=False).encode()
                self.input.write_bytes(document)
                output = self.root / f"invalid-render-{index}"
                # Real CLI/renderer, with Docker unavailable and bytecode disabled.
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SCRIPTS / "launcher.py"),
                        "run",
                        str(self.input),
                        "--output",
                        str(output),
                    ],
                    env={"PATH": ""},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)
                result = json.loads((output / "report.json").read_text())
                self.assertEqual(result["status"], "ERROR")
                self.assertTrue(result["diagnostics"])
                self.assertIn("ERROR", (output / "report.html").read_text())
                self.assertEqual((output / "input.json").read_bytes(), document)
                self.assertEqual(self.input.read_bytes(), document)

    def test_inspect_failure_is_persisted_error(self):
        with patch.object(
            launcher.subprocess, "check_output", side_effect=OSError("unit daemon absent")
        ):
            result = launcher.run(self.input, self.root / "daemon-failed")
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("unit daemon absent", " ".join(result["diagnostics"]))

    def test_refuses_overwrite_or_installed_skill_output(self):
        for output in (self.root, SCRIPTS / "unit-output-must-not-exist"):
            with patch.object(launcher.subprocess, "check_output") as inspect:
                with self.assertRaises((ValueError, FileExistsError)):
                    launcher.run(self.input, output)
                inspect.assert_not_called()

    def test_analysis_uses_recorded_immutable_image_and_only_input_snapshot(self):
        output = self.root / "isolated"
        with (
            patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
            patch.object(
                launcher.subprocess, "run", side_effect=self.synthetic_run(output)
            ) as process,
        ):
            result = launcher.run(self.input, output)
        command = process.call_args.args[0]
        self.assertIn("sha256:unit", command)
        self.assertNotIn(launcher.IMAGE, command)
        self.assertIn("none", command)
        self.assertNotIn(f"{self.input.parent.resolve()}:/input:ro", command)
        self.assertEqual(
            result["provenance"]["input_sha256"],
            __import__("hashlib").sha256(self.input.read_bytes()).hexdigest(),
        )

    def test_build_context_is_allowlisted_external_cache_with_upstream_license(self):
        cache = self.root / "cache"

        def execute(command, **kwargs):
            if command[:2] == ["git", "clone"]:
                vendor = Path(command[-1])
                (vendor / "fret-electron").mkdir(parents=True)
                (vendor / "fret-electron/compiler.js").write_text(
                    "// synthetic unit upstream fixture"
                )
                (vendor / "LICENSE.pdf").write_text("synthetic license fixture")
                (vendor / "CONTRIBUTORS.md").write_text("synthetic attribution fixture")
            return types.SimpleNamespace(returncode=0)

        with (
            patch.object(launcher.subprocess, "run", side_effect=execute) as process,
            patch.object(launcher.subprocess, "check_output", return_value=""),
            patch.object(launcher, "ROOT", self.root / "installed/scripts"),
        ):
            (launcher.ROOT).mkdir(parents=True)
            for name in (
                "Dockerfile",
                "run.cjs",
                "api.js",
                "webpack.config.cjs",
                "jrealizability-log",
                "package.json",
                "package-lock.json",
                "jkind.sha256",
            ):
                (launcher.ROOT / name).write_bytes((SCRIPTS / name).read_bytes())
            launcher.build(cache)
        command = process.call_args.args[0]
        self.assertEqual(command[:2], ["docker", "build"])
        context = Path(command[-1])
        self.assertTrue(context.is_relative_to(cache.resolve()))
        self.assertEqual((context / "runtime/LICENSE.pdf").read_text(), "synthetic license fixture")
        self.assertTrue((context / "runtime/CONTRIBUTORS.md").exists())
        self.assertFalse((context / "launcher.py").exists())
        self.assertFalse((context / "report.py").exists())
        self.assertTrue((context / "runtime/source/compiler.js").exists())
        self.assertIn(
            "COPY runtime/LICENSE.pdf runtime/CONTRIBUTORS.md", (context / "Dockerfile").read_text()
        )

    def test_build_rejects_cache_inside_skill(self):
        with (
            patch.object(launcher, "ROOT", self.root / "installed/scripts"),
            patch.object(
                launcher.subprocess, "run", side_effect=AssertionError("must reject before Git")
            ),
            self.assertRaises(ValueError),
        ):
            launcher.build(launcher.ROOT / "unit-cache-must-not-exist")

    def test_smoke_requires_explicit_external_output_and_checks_invalid_case(self):
        calls = []

        def analyze(source, output):
            case = source.parent.name
            calls.append(case)
            output.mkdir(parents=True)
            status = {"compatible": "REALIZABLE", "conflict": "UNREALIZABLE", "invalid": "ERROR"}[
                case
            ]
            result = {
                "status": status,
                "requirements": [{"id": "R1"}],
                "conflicts": [["R1", "R2"]],
                "counterexamples": [{"Counterexample": [{"Step 0": False}]}],
            }
            (output / "R1.svg").write_text("<svg></svg>")
            (output / "container.log").write_text("synthetic unit fixture: FRET seed failed")
            (output / "seed.log").write_text("synthetic compiler parse error")
            return result

        with patch.object(launcher, "run", side_effect=analyze):
            self.assertEqual(launcher.main(["smoke", "--output", str(self.root / "smoke")]), 0)
        self.assertEqual(calls, ["compatible", "conflict", "invalid"])

    def test_smoke_does_not_accept_error_in_compatible_case(self):
        with patch.object(launcher, "run", return_value={"status": "ERROR"}):
            self.assertEqual(launcher.main(["smoke", "--output", str(self.root / "smoke")]), 1)

    def test_cli_exit_semantics_distinguish_unknown_from_completed_analysis(self):
        for status, expected in (
            ("REALIZABLE", 0),
            ("UNREALIZABLE", 0),
            ("UNKNOWN", 1),
            ("ERROR", 1),
        ):
            with patch.object(launcher, "run", return_value={"status": status}):
                self.assertEqual(
                    launcher.main(["run", str(self.input), "--output", str(self.root / status)]),
                    expected,
                )

    def test_malformed_diagnosis_and_hidden_solver_failure_are_error(self):
        for defect in (
            "diagnosis",
            "stderr-crash",
            "unfinished-invocation",
            "raw-error",
            "exit-two",
        ):
            output = self.root / defect
            original = self.synthetic_run(output)

            def execute(command, original=original, defect=defect, output=output, **kwargs):
                completed = original(command, **kwargs)
                if command[:2] == ["docker", "run"]:
                    if defect == "diagnosis":
                        summary = json.loads((output / "summary.json").read_text())
                        summary["diagnosis"] = {"Conflicts": [42]}
                        (output / "summary.json").write_text(json.dumps(summary))
                    elif defect == "stderr-crash":
                        (output / "solver-invocations/unit.stderr").write_text(
                            "Z3 process has terminated"
                        )
                    elif defect == "unfinished-invocation":
                        (output / "solver-invocations/unfinished.args").write_text("unit args")
                    elif defect == "raw-error":
                        raw = json.loads((output / "realizability.json").read_text())
                        raw["systemComponents"][0]["monolithic"]["result"] = "ERROR"
                        (output / "realizability.json").write_text(json.dumps(raw))
                    else:
                        completed.returncode = 2
                return completed

            with (
                patch.object(launcher.subprocess, "check_output", return_value="sha256:unit"),
                patch.object(launcher.subprocess, "run", side_effect=execute),
            ):
                result = launcher.run(self.input, output)
            self.assertEqual(result["status"], "ERROR")
            self.assertTrue(result["diagnostics"])

    def test_smoke_invalid_runtime_error_cannot_count_as_compiler_rejection(self):
        def analyze(source, output):
            output.mkdir(parents=True)
            (output / "R1.svg").write_text("<svg></svg>")
            (output / "container.log").write_text("synthetic Docker daemon failure")
            return {
                "status": {
                    "compatible": "REALIZABLE",
                    "conflict": "UNREALIZABLE",
                    "invalid": "ERROR",
                }[source.parent.name],
                "requirements": [{"id": "R1"}],
                "conflicts": [["R1", "R2"]],
                "counterexamples": [42],
            }

        with patch.object(launcher, "run", side_effect=analyze):
            self.assertEqual(launcher.main(["smoke", "--output", str(self.root / "smoke")]), 1)


if __name__ == "__main__":
    unittest.main()

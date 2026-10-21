"""Reproducible fresh-process planning benchmark; run directly, not pytest.

100 projects, 1000 linked tasks, 1000 criteria. All data is disposable under TMPDIR.
Outputs real CLI timing/exit/count checks and exercises standard template validation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from svod.scaffold import scaffold


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="svod-plan-benchmark-") as temp:
        root = scaffold(Path(temp) / "store")

        def write(ref: str, value: str | dict) -> None:
            path = root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value if isinstance(value, str) else json.dumps(value))

        for project in range(100):
            owner = f"work/projects/p{project}"
            write(owner + "/card.md", "---\ntype: card\nkind: project\nstatus: open\n---\n")
            write(owner + "/outcome.yaml", {"schema_version": 1, "actual": "Measured fixture",
                                           "evidence": []})
            nodes = []
            criteria = []
            for task in range(10):
                ref = f"work/tasks/p{project}-t{task}"
                identity = f"t{task}"
                write(ref + "/card.md", f"---\ntype: card\nkind: task\nstatus: done\n"
                      f"parent: {owner}\n---\n")
                write(ref + "/outcome.yaml", {"schema_version": 1, "actual": "Fixture result",
                                              "evidence": []})
                nodes.append({"id": identity, "title": identity, "expected": "Result",
                              "record": ref})
                criteria.append({"id": f"c{task}", "statement": "Observable result",
                                 "verification": "Exercise", "works": [identity]})
            write(owner + "/plan.yaml", {"schema_version": 1, "expected": "Product",
                                         "nodes": nodes, "criteria": criteria})
        env = {k: v for k, v in os.environ.items() if not k.startswith("SVOD_")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        print(json.dumps({"projects": 100, "linked_records": 1000, "criteria": 1000}))
        for args in (("validate",), ("plan", "summary", "--all", "--json"),
                     ("plan", "summary", "work/projects/p0", "--json"),
                     ("plan", "validate", "work/projects/p0"),
                     ("plan", "canvas", "work/projects/p0")):
            started = time.perf_counter()
            result = subprocess.run([sys.executable, "-m", "svod.cli", *args], cwd=root,
                                    env=env, text=True, capture_output=True, check=False)
            elapsed = time.perf_counter() - started
            assert result.returncode == 0, (args, result.stdout, result.stderr)
            report = {"argv": args, "seconds": round(elapsed, 6), "exit": result.returncode,
                      "stdout_bytes": len(result.stdout.encode())}
            if "--json" in args:
                data = json.loads(result.stdout)
                report.update(records=len(data["records"]), diagnostics=data["diagnostics"],
                              nodes=sum(len(r["nodes"]) for r in data["records"]),
                              criteria=sum(len(r["criteria"]) for r in data["records"]))
                expected = 100 if "--all" in args else 1
                assert report["records"] == expected
                assert report["nodes"] == report["criteria"] == expected * 10
                report["target_seconds"] = 5 if "--all" in args else 1
                report["target_met"] = elapsed <= report["target_seconds"]
            print(json.dumps(report))
        write("proof.txt", "Benchmark smoke verification only")
        confirmed = subprocess.run([sys.executable, "-m", "svod.cli", "plan", "confirm",
                                    "work/projects/p0", "--criterion", "c0", "--result", "pass",
                                    "--actual", "CLI smoke", "--evidence", "proof.txt"],
                                   cwd=root, env=env, text=True, capture_output=True)
        assert confirmed.returncode == 0, confirmed.stderr
        history = json.loads((root / "work/projects/p0/acceptance.yaml").read_text())
        assert len(history["confirmations"]) == 1
        print(json.dumps({"confirm_exit": confirmed.returncode, "history_entries": 1}))


if __name__ == "__main__":
    main()

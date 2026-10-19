# Local execution packages (pilot)

A package runs a predetermined sequence of **reviewed local profile actions**, without a model
between steps. This is a trusted-script interface, **not a filesystem/network sandbox**. No
standard push/PR/merge/deploy action is admitted by default. Review scripts and their transitive
calls before adding an admission entry. An entry in a package is not itself admission.

## Review and declarations

The profile owner explicitly configures `profile_config.local_packages` in `svod.yaml` (or the
existing local profile configuration). Each named action must already be a profile `.sh` action
and be named by the exact applicable pipeline step. Each entry has exactly:

```yaml
profile_config:
  local_packages:
    offline-build:
      sha256: <SHA-256 of the reviewed script bytes>
      kind: action   # check ONLY for a reviewed safe-to-repeat check
      args: []       # exact predetermined argv arguments, no new shell string interface
      inputs: [input.txt]
      outputs: [output.txt]
```

Admission is deliberately opt-in: no bundled project actions are automatically declared local.
The test pilot is the fixed offline `alpha/beta/gamma` fixtures in `tests/test_packages.py`.
The owner must review all dependencies, including executables, sourced files and environment;
the engine hashes the existing action/config trust snapshot and inherited action environment,
but cannot discover every dependency or prove locality. No shell blacklist can provide that.
Existing trusted-action approval, freeze and position policies remain applicable. Package dispatch
passes through `cli.do_action` and `actions.run_action`; it never sets `--force`.

A JSON package has exactly these top-level and step fields:

```json
{
  "version": 1,
  "id": "offline-pilot",
  "record": "work/tasks/example",
  "steps": [
    {
      "id": "build",
      "step_id": "implement",
      "action": "offline-build",
      "args": [],
      "timeout": 60,
      "inputs": ["input.txt"],
      "outputs": ["output.txt"]
    }
  ]
}
```

IDs match `[a-z][a-z0-9_-]{0,63}`. Steps: 1–100; timeout: finite positive seconds, maximum
600. Lists of inputs/outputs/args must exactly match the reviewed declaration. Input/output paths
are relative regular-file paths within the store, with no traversal or symlink components.
Missing paths are recorded explicitly; directories/special files are not supported. A missing
input is a significant state, not silently ignored: creating it later invalidates continuation.
Inputs and outputs of one step are disjoint. A previous step's output can be a later step's input.
After success, only that step's declared output paths advance the expected manifest boundary.
After failure, **no** changed file becomes newly trusted. The action environment (including record
frontmatter) is hashed without saving secret values and advanced after successful steps; explicit
significant file declarations are still required for all relevant inputs/outputs.

## CLI

```text
svod package validate <record> <package.json>
svod package run <record> <package.json> [--json]
svod package status <record> <run-id> [--json]
svod package resume <record> <run-id> --decision <decision.json> [--json]
svod package read <record> <run-id> --step <step-id> [--offset N --limit N] [--json]
```

Run/resume: exit 0 on complete success, 1 when waiting/stopped, 2 on invalid/stale/unsafe
requests or required storage failures. Validate/status/read: exit 0 on successful request,
2 on failure. The package `record` is the exact query supplied to validate/run; use that same
identifier for status/read/resume. Run IDs are generated, not chosen by the package.

JSON/text reports include ordered statuses, bounded excerpts (512 source bytes per step), exit
code/timeout, remaining IDs, run-local log refs and a read command. JSON contains no transcript.
Step reads concatenate attempts of that step only, in attempt order. A step ID is required;
there is no whole-package log API or full-read CLI mode. The unsupported `--full` flag is rejected.
Original merged stdout/stderr bytes remain in separate local artifacts for human inspection:
`<store>/.svod/package-runs/<run-id>/<log-ref>` (for example `beta-0.log`). Combine the run ID
and each report's log ref with this path; open the file directly in a local editor/viewer.
These artifact paths are not API read commands and do not imply automatic upload of logs.
Paged text uses Unicode-codepoint offsets and a 1–65536 codepoint limit (default 4096), with
`offset`, `next_offset`, `eof` and `unit` in JSON. Invalid UTF-8 becomes replacement characters
only in text projection, never in saved source. Unknown steps, no source, missing/corrupt logs,
unsafe references and invalid ranges are errors. Pending steps have no source.

Status/read load **only saved run state**, even if live pipeline configuration is broken. They do
not call status collection, evaluate gates, repair state, write evidence, or authorize execution.
A live writer's state is a point-in-time view; unfinished logs may still grow. Hash verification
applies once a terminal log hash exists. Inspect unknown-effect logs as partial evidence only.

## Stop and explicit USER decision

Nonzero or timeout stops before the next step. Removing an error signal alone does not resume.
There is no rollback, automatic repair or retry. A decision JSON has exactly:

```json
{"run_id":"run-<id>","revision":5,"operation":"retry-check"}
```

Operations:
- `retry-check`: retry the first failed step **only** if admitted as a reviewed safe check.
- `continue`: proceed from a pending step after a policy boundary clears.
- `stop`: permanently stop a waiting run without executing another step.

The decision must be a USER decision, not an agent's inferred authorization. A file is not proof
of human authorship; the caller must preserve the user decision in its own channel. Synthetic
decisions in tests are test-only fixtures. Run/revision binding rejects stale decisions; current
commands/config/environment/input/output and policy checks outrank simultaneous continuation.
Successful steps are not replayed. Failed mutations cannot be retried even with a decision.
Changed inputs/commands need actual inspection and a new reviewed package/run, not a force flag.

## Durable state and crash limits

Authoritative state and logs live under `<store>/.svod/package-runs/<run-id>/` with 0700 run
directories and 0600 files, a local ignore file, atomic fsync+replace state writes and one POSIX
`flock` writer. `running` intent is durable **before** subprocess spawn; output is flushed/fsynced
before terminal state. Optional evidence is not the recovery store. Readback does not rewrite
an orphaned state: it projects abandoned pending/running state as `unknown`. Resume refuses it.
A required state/log failure ends the chain and is never presented as success.
An OS error after subprocess spawn (including process-group cleanup refusal) leaves durable
running intent rather than a retry-safe failed check. Status projects unknown, resume refuses,
and the log remains partial evidence without a verified terminal hash/size. Pre-spawn refusal
is separate: no action started, so dispatch can report an ordinary start failure.

A SIGKILL/crash can leave effects and a child process alive. Inspect/stop the owned process and
check actual artifacts before planning a new package. No automatic recovery or exactly-once
shell guarantee is claimed. The existing process-group cleanup handles normal capture completion,
timeout and ordinary interruption; a descendant can escape by creating another session.
The engine does not implement cross-run mutual exclusion: a USER must not launch conflicting
new runs while an unknown prior run may still have effects. Locks protect one run only.

Logs are private, outside version control, not automatically sent to a provider, and **not secret
scrubbed**. No automatic retention deletion is performed during the pilot. Keep them until the
pilot ends; any later deletion/export policy needs a separate owner decision. Avoid logging
secrets. There is no unlimited storage promise: disk errors stop execution.

The targeted-only 14-rule FRET model remains design evidence only; the earlier 15-rule variant is historical. Implementation acceptance is the offline
CLI/process/state tests, not a formal-model pass. No new FRET dependency or default hook gate
was introduced.

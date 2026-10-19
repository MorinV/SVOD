# Local-package implementation acceptance

Scope: R01–R10 / T01–T14 from the approved local-execution-context contract.
Framework baseline: `49ba4325d4c7ddf6d3898e7fe7f8c0aca2951963`.
No bundled engine, external service, push, merge or deployment was changed.
The worktree has no root AGENTS.md; the store's AGENTS.md/work.yaml were inspected.

## Reproduction

Use an isolated Python >=3.10 environment containing pytest, PyYAML, ruff and mypy.
The verification environment was Python 3.12 at
`/Users/valerijpoctarev/.hermes/cache/scratch/svod-package-py312`.

```sh
export PATH=/Users/valerijpoctarev/.hermes/cache/scratch/svod-package-py312/bin:$PATH
export TMPDIR=/Users/valerijpoctarev/.hermes/cache/scratch
PYTHONPATH=$PWD python3 -m pytest -q
ruff check svod tests
mypy --ignore-missing-imports svod
```

PATH must select the same Python for fixture shell calls. TMPDIR must precede interpreter
startup to avoid macOS `/var` / `/private/var` aliases. Initial baseline without these settings
had 31 failures (697 passed, 1 skipped), mostly system Python missing YAML and alias-sensitive
fixtures. An initial full verification timed out at the tool's 420-second ceiling; the background
rerun completed with 738 passed, 1 skipped and one reference-documentation failure. The missing
individually-backticked `package` reference was repaired. Final complete verification on the
implementation before the full-read removal: **749 passed, 1 skipped, 1877 subtests passed** in **224.73s**;
then ruff, mypy and `git diff --check` all passed (combined exit 0). Full output is retained at
`/Users/valerijpoctarev/.hermes/cache/scratch/svod-package-suite-head.log`.
The final retained-selection output is at
`/Users/valerijpoctarev/.hermes/cache/scratch/svod-package-final-retained.log`.

## Vertical RED → GREEN evidence

Real CLI behavioral failures were observed before implementation for:
1. Package admission: CLI rejected unknown `package`; exact reviewed admission then passed.
2. Sequential execution: run returned validation JSON without `status`; three steps then passed.
3. Explicit resume: `operation not implemented`; failed safe-check retry then passed without
   replaying alpha.
4. Saved readback: `operation not implemented`; step paging controls passed. Exact original
   bytes are now verified through human-accessible local artifacts, not a full-read API.
5. Failed-check input mutation: resume incorrectly succeeded; preserving pre-failure boundary
   made stale input refusal pass.
6. Changed record environment: stale resume incorrectly dispatched beta; expected environment
   snapshots made refusal pass.
7. Immutable commands across success: restored original commands were considered stale because
   changed scripts had refreshed trust; immutable command component repaired it.
8. Policy integration: package never called do_action; dispatch-through-do control then passed.
9. Capture cleanup: background descendant wrote `late` after reported success; reuse of existing
   stop_group for captured completion made the no-late-effect control pass.
10. Text result lacked an error excerpt; bounded failed-step excerpt then passed.
11. Crash before writer acquisition: status failed on missing lock; eagerly creating the run lock
    made read-only unknown projection pass.
12. Corrupted completed source: resume incorrectly dispatched; pre-resume integrity check passed.
13. Package digest absent; saved immutable-package digest/mismatch check then passed.
14. Invalid step status was printed as success; state validation now fails closed.
15. Final step changed a significant input yet run succeeded; terminal boundary validation passed.
16. Final step changed commands yet run succeeded; terminal command validation passed.
17. All-completed invalid-boundary resume raised StopIteration; explicit refusal then passed.
18. Full-read removal: a real CLI regression first failed because `--full` and `--full --json`
    returned exit 0 with whole-source text/base64. After removal, those requests and
    `--step a --full` return exit 2 without stdout or saved-run changes; help omits `--full`.
    RED output: `/Users/valerijpoctarev/.hermes/cache/scratch/svod-remove-full-red.log`.
19. Post-spawn cleanup refusal: with an injected `stop_group` PermissionError after a real
    fixture script executed, the package incorrectly returned waiting/failed exit 2 and hashed
    its log. RED output: `/Users/valerijpoctarev/.hermes/cache/scratch/svod-lifecycle-red.log`.
    Post-spawn OSErrors now propagate as lifecycle failures through dispatch, leaving durable
    running intent and no terminal log hash/size. Real subprocess status projects unknown and
    resume refuses retry-check without replay. The pre-spawn refusal control remains passing.

Setup defects were separately corrected: the first three-step fixture used `exists` with an
unsupported path parameter, then used field gates because frontmatter_doc subjects are files.
An in-process-to-process continuation fixture had different Python environment hashes; that
control now stays on one boundary. Already-passing retained safety controls were not called RED.

## Acceptance matrix

All entries below are retained tests in `tests/test_packages.py` unless otherwise noted.

| Target | Evidence |
|---|---|
| T01 / R01 | sequential_run_and_saved_compact_status: alpha/beta/gamma once, ordered, saved status |
| T02 / R02 | exact reviewed admission + malformed declarations rejected before run storage/spawn |
| T03 / R03 | failure_latches_until_explicit_check_retry: alpha success, beta failure, gamma pending; removal of signal alone does nothing |
| T04 / R04 | failed_mutation_never_retries; timeout; no rollback/repair branch exists |
| T05 / R05 | successful check retry preserves alpha; stale source/script/environment/output checks |
| T06 / R06 | durable intent seam tests, orphan state projection and actual killed CLI; unknown never resumed |
| T07 / R07 | new_policy_error_outranks_simultaneous_continue_decision (injected policy event); stale input/script races through CLI |
| T08 / R08 | compact JSON state + bounded text error, exact log refs, remaining IDs, USER ownership |
| T09 / R09 | beta-only paged read, offset/next_offset/eof, unknown/range errors, UTF-8 codepoints |
| T10 / R10 (narrowed) | exact raw bytes, including invalid UTF-8, remain in human-accessible artifact paths; no whole-package log API; `--full` rejected; bounded reads work with broken live pipeline and preserve state bytes |
| T11 | single writer lock, before/after-spawn interruption, actual CLI SIGKILL after effect, no replay |
| T12 | package_dispatch_reuses_do_policy; exact later occurrence; retained actions/run/scoped-writes/command-gate/reference controls |
| T13 | declared missing/file hashes, changed input/environment/script, final input/command mutation, corruption/symlink/traversal/private-state controls; required state/log failures |
| T14 | equivalent success and error/resume artifacts using real subprocess CLI; counts/bytes below |

Final removal + lifecycle retained selection: **133 passed, 656 subtests passed** in 73.89s.
This includes 36 package tests (11 parameterized subtests) plus the existing retained modules.
Output: `/Users/valerijpoctarev/.hermes/cache/scratch/svod-remove-full-lifecycle-acceptance.log`.
The focused removal/paging/raw-artifact selection passed: **3 passed, 3 subtests passed** in 3.11s.
The focused lifecycle/pre-spawn selection passed: **2 passed** in 0.82s.
`ruff check svod tests`: all checks passed.
`mypy --ignore-missing-imports svod`: success, 77 source files.
`git diff --check`: passed.

## Measured offline baseline (same final files)

Single-run timings are descriptive, not statistically meaningful. Counts below include every
measured CLI response, stdout plus stderr encoded as UTF-8. JSON reports are deterministic for
one saved run; generated IDs differ across runs.

| Scenario | CLI calls | bytes per call | elapsed |
|---|---:|---|---:|
| Individual success (`do` ×3) | 3 | 5007, 5006, 5007 | 0.4845s |
| Package success: run/status/beta-page | 3 | 2495, 2495, 122 | 1.3072s |
| Individual error + explicit safe retry | 4 | 6, 5, 5, 6 | 0.6157s |
| Package error/status/beta-read/resume | 4 | 895, 895, 93, 1081 | 1.7726s |

Success execution calls alone: 3 → 1. Individual success bytes: 15020. Package run+status+
targeted-read: 5112. Separately, three human log artifacts retain 15020 original raw bytes at
`<store>/.svod/package-runs/<run-id>/<log-ref>`. Direct artifact inspection is not a CLI/API
response: the measurement records zero API calls for these paths and excludes their bytes from
response totals. There is no whole-package log API or full-read mode.
Tiny-output failure/resume case: 22 individual bytes versus 2964
package bytes. The package adds metadata/persistence cost and can be slower/larger; no provider
cost or model-quality savings claim is made. Both controls compare final artifact bytes and
failure/resume confirms alpha was not repeated.

## Limits

- Trusted reviewed local scripts, not an OS sandbox; completeness of dependency/input declarations
  remains owner responsibility. No default project action is automatically admitted.
- Synthetic decisions are fixtures only; human authorship is not authenticated by decision files.
- Per-run POSIX flock, not distributed or cross-run exclusion; no automatic orphan process cleanup
  after SIGKILL. USER must inspect actual state and owned processes before a fresh package.
- Plain logs are private but unsanitized; no pilot automatic deletion, no unlimited storage promise.
- Paginated text may replace invalid UTF-8; local human-accessible raw artifacts preserve bytes.
- Reader validates lexical/symlink/privacy/hash constraints under the trusted-local-owner threat
  model; it is not a hostile concurrent-filesystem sandbox.
- The active targeted-only FRET model has 14 rules; the previous 15-rule variant is historical. Neither is treated as implementation tests.

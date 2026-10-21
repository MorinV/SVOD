# Structured planning transition: isolated integration verification

Verified against the completed core source worktree plus transition-owned README,
skill and tests in a test-only combined copy. No Git branch integration, candidate
commit, real-store installation, live backfill or real approval was performed.
Core source bytes were hashed before copying and compared unchanged afterward.

## Source and execution boundary

- Core: `/Users/valerijpoctarev/PetProjects/svod-task-structured-planning-core`.
- Transition: `/Users/valerijpoctarev/PetProjects/svod-task-structured-planning-transition`.
- Scratch root: `/Users/valerijpoctarev/.hermes/cache/scratch/structured-planning-transition-final`.
- Combined source: `<scratch>/combined-source`; exact core tracked/untracked source
  snapshot with only transition-owned delta overlaid. No `.git`, `.venv`, `uv.lock`,
  build outputs or bytecode copied as inputs. Hashes: `core-source-manifest.json`.
- Runner: `TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=<combined-source>` and
  `uv run --no-project --python 3.12 --with pytest --with pyyaml --with setuptools
  --with ruff --with mypy`. This avoids modifying either worktree's environment.
- Actual package route: native `install --from <test-owned Git source> --to
  transition-test --no-profile`; fresh subprocess import is asserted inside
  `<fixture>/.svod/lib`. Wheel built with the declared setuptools backend, extracted
  outside checkout, imported and exercised with `plan summary --all --json`.

## Results

- Full final `python -m pytest -q --tb=short -rs`: **831 passed, 1 skipped,
  1935 subtests passed in 238.60 seconds** (`full-pytest-final.log`). The skip is
  `test_package_version_matches_pyproject`: this isolated source-run environment
  has no installed svod metadata. The actual wheel is separately built, loaded
  and executed; the skipped source-metadata identity check is not claimed passed.
- Focused integration/distribution/skills/core planning/template selection:
  **49 passed, 52 subtests passed in 5.91 seconds** (`focused-final.log`).
- `ruff check svod tests`: all checks passed (`ruff.log`).
- `mypy --ignore-missing-imports svod`: no issues in 83 source files (`mypy.log`).
- Transition `git diff --check`: clean.

## Exact retained artifacts

Under the scratch root:

- `installed-roundtrip-mv91_rij/verification.json`: full CLI argv, return codes,
  stdout/stderr, inventory, scope and approval bind results. Original execution
  paths inside the report refer to the now-cleaned temporary fixture; preserved
  byte-identical store files are under the adjacent `parent/store/`.
- `installed-roundtrip-mv91_rij/parent/store/.svod/`: actual installed combined
  engine, skills, version and integrity manifest.
- `installed-roundtrip-mv91_rij/parent/store/work/projects/demo/plan.canvas`:
  regenerated stable IDs and retained manual position/size `(1234,-567,456,321)`.
- `installed-roundtrip-mv91_rij/parent/store/work/features/search/acceptance.yaml`:
  one explicit synthetic current verification for title only, not imported history.
- `wheel-distribution-trz22w41/svod-0.8.1-py3-none-any.whl`:
  SHA-256 `cadf8b481ffa669cef32ab53b36618511ca0049cdd92eaa368f320c3b7d6286f`.
  Contains skill, reference and example; planning executes from extracted package.

## Contract observations

The programmatically derived selected closure includes five records: completed
project/demo, feature/search, tasks/index and archive, plus open query. Orphan is
separately inventoried outside the explicitly chosen parent closure; contradictory
legacy orphan/missing references are retained and not adopted or replaced. No
selected exclusions or remaining records; all three explicit source criteria are
mapped. This is full *fixture content coverage*, not full acceptance or live data.

All criteria start unconfirmed regardless of done status. Index has a sourced
historical outcome; four other outcomes remain unknown. Title-only historical
proof never auto-confirms composite title/author or archive retention. Missing
proof confirmation exits 2 and creates no acceptance file. A new explicitly
synthetic title-fact verification exits 0; only title becomes pass. Composite and
retention stay unconfirmed. Historical evidence stays in the provenance note
because schema 1 cannot label an imported confirmation as historical.

Validate, single text/JSON and all text/JSON summaries exit 1 due to missing
outcomes with no structural errors; canvas writes successfully and also returns 1
for those diagnostics. Both canvas runs, source-conflict refusal, manual YAML
refinement, retained node IDs/layout, question note stability and unchanged
acceptance history are asserted. Original source/approval bytes remain identical.

Engine-only install leaves the profile and content unchanged. Separately selected
fixture-only feature bind changes `[brief.md, questions.md, breakdown.md]` to
`[brief.md, questions.md, plan.yaml]`; the actual approval gate passes the former
and fails the latter with `reason: drift`, without changing historical approval
bytes. Core standard-template tests additionally validate actual scaffold/profile,
plan source gates, feature deliver binds and project architecture-before-breakdown.
No extra mandatory workflow gate is introduced by the transition delta.

## Encountered limitations and remaining boundaries

- Initial test-first failure was the absent executable example (`red.log`); the
  shipped finite schema-valid example closes it, not a fake planner.
- A retained-artifact repeat initially collided with read-only Git object files
  in an earlier copied fixture (`focused.log`). Fixed artifact retention to use
  a new scratch directory per run; reran focused and full suites successfully.
- Initial ruff identified six long test lines; corrected and reverified.
- The transition branch alone intentionally lacks core implementation. This is a
  verified local combined artifact, not an authorized Git merge or release.
- Existing transition `uv.lock` was present on entry and remains untouched; it
  was excluded from the combined input and is not part of the deliverable.
- Native task checks require commits, forbidden for this assignment; no hand-made
  task checks/approval evidence or task closure was written. Parent integration,
  publication, real-store profile choice and content backfill remain separate
  authorized actions, not failed fixture checks.

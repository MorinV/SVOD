---
name: svod-fret
description: Clarify temporal requirements with optional formal analysis.
version: 0.1.0
author: MorinV, Hermes Agent
license: Apache-2.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [requirements, fret, optional, temporal]
---

# Optional FRET requirements analysis

Explicitly selected analysis of interacting stateful or temporal requirements, not a SVOD gate. Help the person turn their intent into a small reviewable model; they need not write FRETish. Docker runs genuine upstream FRET and JKind, not an agent-authored substitute solver.

## When to use

- The person selects formal requirements analysis for waiting, continuation, competing conditions or timing rules.
- Several requirements appear individually reasonable but may be mutually impossible.
- Do not run for every task, ordinary CRUD or a request to test existing code. Do not change pipelines or approvals to introduce this skill.

## Prerequisites

Python 3.10+, Git and Docker with a running daemon. No host npm/Node/Java/Z3 installation. Build downloads public pinned sources/dependencies; analysis is network-disabled. Use trusted local inputs only. macOS ARM64 is the original exercised environment; do not claim another platform or architecture has been tested without execution.

Locate this skill directory through `search_files`, not a remembered machine-specific path. Resolve `scripts/launcher.py` relative to it. For exact commands, schema, writable cache/output handling and status semantics read [references/usage.md](references/usage.md).

## Procedure

1. Read the person's current requirements with `read_file`. Separate accepted behavior, unresolved decisions and environmental assumptions. Choose a small bounded component and define what one observation tick means. Do not resolve a product ambiguity silently.
2. Use `write_file` to save a new JSON input outside the installed skill. Preserve Russian natural-language requirements in each requirement's `description`, actual FRETish in `text`, stable `id`, variable Input/Output roles, and top-level `assumptions`. Environmental assumptions are readable context, not automatically solver-enforced constraints. Map every selected requirement; state what the model leaves out.
3. Show the readable interpretation to the person. Ask about material ambiguity before treating the formalization as faithful. In particular, distinguish a one-tick error from a persistent obligation to wait. New failure and continue in the same tick require an explicit priority decision. A details request does not inherently authorize execution.
4. Through `terminal`, explicitly build with `python3 <skill-dir>/scripts/launcher.py build`, then run the input with `python3 <skill-dir>/scripts/launcher.py run <input.json> --output <new-result-directory>`. Do not install host dependencies or execute modeled product actions. Use a generous bounded tool timeout; keep raw artifacts for every actual run.
5. Inspect `report.json`, `input.json`, `summary.json`, compiler semantics and raw solver artifacts with `read_file`/`search_files`. REALIZABLE means a strategy exists for the modeled inputs; UNREALIZABLE means a conflict in this model. UNKNOWN and ERROR are inconclusive, never PASS. Exit 0 can mean either final answer, not compatibility. Preserve all failures, including Z3 crashes, without hidden retries.
6. Present the absolute `report.html` path and the bounded conclusion in Russian. Native timing SVG is a generic compiler template with its legend, not a personalized trace. A conflict graph projects solver conflict IDs, not a workflow state machine. Call a counterexample solver-produced only when it exists in raw diagnostics; never invent a trace.
7. Discuss the identified ambiguity/conflict with the person. Save their clarification with the model's source and create a new input/output version for reanalysis. An intentionally conflicting control tests analysis plumbing, not discovery of an unknown requirements defect. Stop at the selected requirements boundary; code implementation or publishing requires its own authorization.

## Pitfalls

- REALIZABLE does not prove completeness, fidelity to intent or code conformance. Boolean inputs such as freshness/success assume trustworthy producers; FRET does not verify those producers.
- Known sporadic `Z3 terminated unexpectedly` remains an experimental reliability limitation unless a separately evidenced fix is established. Later green runs do not repair it. Do not advertise this as a reliable CI gate.
- Compound Boolean equivalence uses `<=>`. A `when` edge trigger does not necessarily constrain every tick. Inspect actual generated semantics instead of guessing temporal syntax.
- Never overwrite earlier output or write cache/runtime inside site-packages. Do not copy historical logs, downloaded upstream or node_modules into the distributed skill.

## Verification

Run the explicit `smoke` command to exercise compatible/conflicting models with real solver evidence. Also run the invalid example and verify ERROR/nonzero exit. For the person's model inspect all selected requirements, assumptions, compiler legend, raw status and available conflict/trace evidence. Report the actual versions, input digest, result directory and unresolved limits. Normal SVOD must remain usable without Docker/FRET.

---
name: svod-efficient-execution
description: Use when executing Svod tasks. Choose a short critical path, bounded context and checks proportional to risk.
---

# Efficient Svod execution

The selected profile YAML and the task contract define the process. This skill adds no gate, approval, permission to publish or mandatory artifact.

1. Establish the result. Read `svod status <query>`, the selected contract and its immediate blocker. Prefer an exact store-relative path when names are ambiguous. Do not enumerate every task or read historical logs by default. Create or select task records according to the project's own policy; an external tracker is not required by the framework.
2. Find the shortest critical path. Use existing commands and direct sequences before adding an adapter or abstraction. Remove or combine obligations with no distinct benefit before automating them. Keep result, authorized effects, known evidence and the missing fact separate.
3. Budget verification by risk. Text needs link/structure checks; code needs affected behavior and relevant regressions; mechanism changes need synthetic positive/negative tests. External effects need explicit authorization, preflight, exact-target readback and recovery. A receipt's existence or a neighboring green test is not proof of acceptance.
4. Bound context and parallelism. Batch independent reads. Keep full logs in files and return concise failures/counts/version/scope/limitations. For bulk changes, inspect an index and differences first instead of dumping repeating documents. Delegate only separable results with clear ownership, inputs, checks and a stopping condition; do not duplicate broad investigation across workers. Distinguish running workers, completed workers and completed work.
5. Keep source identity honest. Use ordinary Git isolation. Do not reset, stash, clean or automatically copy another person's dirty bytes. A dirty tree's HEAD does not describe its checked bytes. The compact local workflow requires a clean canonical Git root with task records and logs outside it.
6. Execute the selected final command once on unchanged exact source through `svod local checks <query>`. Development RED/GREEN or changed inputs justify new runs; an identical direct final run followed by the recorder does not. `prepare` and `verify` are diagnostics, not extra mandatory handoffs between checks and deliver.
7. Close the original promise. Written is not tested; local delivery is not installation, merge, publication or deployment. Name each material unverified boundary. Never claim ongoing work without a live executor. Save necessary logs before authorized cleanup; never remove someone else's worktree or bypass dirty/locked refusals.

## Learning and process changes

At closure, distinguish successful acceptance from efficient execution. Identify material waste and propose at most a small coherent improvement package when evidence supports it. Do not manufacture suggestions or a separate retrospective receipt. Follow the project's decision process before installing new standing rules. Preserve real decisions and history without replaying retired lifecycle machinery.

For policy changes, use `svod-pipeline`. Declaration composition normally needs validate/render; new mechanisms need focused behavior tests. CI, JUnit, E2E, independent review, worktree managers and source snapshots are not universal requirements.

Time/token savings remain hypotheses until measured on comparable accepted outcomes including retries. Keep real consent, credential boundaries, destructive-operation permissions and external readback even when simplifying the route.

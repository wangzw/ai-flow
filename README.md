# ai-flow

> Recursive task scheduling + multi-Agent collaboration framework on top of
> GitHub Issues + Pull Requests + Actions.

ai-flow is a research framework that models software delivery as a tree of
GitHub Issues. A **Planner** agent decomposes a goal into tasks, **Implementer**
agents code each task, **Reviewer** agents grade the resulting PRs against
seven dimensions, and a **merge queue** serializes integration. The whole
loop runs as GitHub Actions — no external server, no LLM-driven
coordinator.

See [`docs/superpowers/specs/2026-04-29-ai-flow-design.md`](docs/superpowers/specs/2026-04-29-ai-flow-design.md)
for the full specification.

## Status

🚧 **v0.1 — early.** State machine + Planner reconciler + Implementer +
Reviewer matrix + merge queue + slash commands all implemented. See
`.flow/tests/` for what's covered. End-to-end smoke test in progress.

## Quick start

```bash
pip install -e ./.flow                     # install the framework
flow apply-labels --repo <owner/repo>      # create the 7 labels
flow doctor      --repo <owner/repo>       # check secrets / workflows
```

Then file a `type:goal` Issue (using the goal template), label it
`agent-ready`, and let the framework go.

## Design principles

- **Reactive reconciliation, not orchestration.** Every event (label change,
  comment, PR ready) re-reads full state and re-decides — no in-memory state.
- **Channel discipline.** Reviewer reads only spec/diff/tests/code-comments.
  PR descriptions, commit messages, and the Implementer's self-summary are
  hidden from review (spec §11).
- **Fail-closed.** Missing markers, malformed YAML, unknown state transitions
  → `needs-human`, never silent recovery.
- **Three-stage escalation.** Reviewer iterations 1–2 auto-retry the
  Implementer; iteration 3 invokes Planner arbitration; beyond that, human.

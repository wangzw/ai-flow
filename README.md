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

## Use ai-flow in another repository

`flow init` is now self-contained: it creates the target repository's `.flow/`
runtime and `.github/` workflow/template files, so you do not need to copy
files out of this repository by hand.

### 1. Install the local bootstrap tools

Clone this repository somewhere local, then install the CLI from the bundled
package:

```bash
pip install -e ./.flow
```

### 2. Bootstrap the target repository

Run `flow init` from this repository clone and point it at the repository you
want to automate:

```bash
flow init --target /path/to/your-repo
```

`flow init` creates the target repository's `.flow/` runtime
(`.flow/pyproject.toml`, `.flow/src/`, and `.flow/config.yml`) plus the
generated `.github/` workflow/template files (`.github/workflows/flow-*.yml`
and `.github/ISSUE_TEMPLATE/goal.md`).

Before you commit, edit `.flow/config.yml` in the target repository for your
team. In particular, set `authorized_users` so `/agent ...` comments are
accepted from your maintainers and set `blast_radius.core_modules` for the
paths that should count as high-sensitivity changes. Then commit the generated
`.flow/` and `.github/` files to the target repository's default branch.

### 3. Create labels and run the health check

From the target repository root, export `GITHUB_TOKEN` (or `FLOW_GIT_TOKEN`)
with access to the repo, then run:

```bash
flow apply-labels --repo <owner/repo>
flow doctor --repo <owner/repo>
```

`flow doctor --repo <owner/repo>` checks the local CLI dependencies (`git` and
`copilot`), token access, the ai-flow label set, `.flow/config.yml`, and the
event-driven workflow files that the current implementation validates:
`flow-issue.yml`, `flow-comment.yml`, `flow-pr-ready.yml`, and
`flow-merge-queue.yml`.

### 4. GitHub Actions and runtime prerequisites

The generated workflows already bootstrap their runner environments with
`actions/checkout@v4`, `actions/setup-python@v5`, and `pip install -e ./.flow`.
The agent-driven workflows (`flow-issue.yml`, `flow-comment.yml`,
`flow-pr-ready.yml`, and `flow-merge-queue.yml`) also run
`actions/setup-node@v4` followed by `npm install -g @github/copilot`.

The target repository still needs these GitHub-side prerequisites:

| Requirement | Why it is needed |
| --- | --- |
| GitHub Actions enabled on the repository | `flow init` installs workflow-driven automation; nothing runs without Actions. |
| The generated workflow files and vendored `.flow` runtime committed to the default branch | Every run checks out the target repository and installs ai-flow from `./.flow`, so the runtime must live beside `flow-issue.yml`, `flow-comment.yml`, `flow-pr-ready.yml`, `flow-merge-queue.yml`, and `flow-schedule.yml`. |
| Runners compatible with the bundled jobs (`ubuntu-latest`, Python 3.11, Node 20 for agent workflows) | The workflow templates hard-code `actions/setup-python@v5` and, for the agent workflows, `actions/setup-node@v4`. |
| Ability for workflows to run `npm install -g @github/copilot` | Planner / Implementer / Reviewer execution depends on Copilot CLI being installed in the runner at job runtime. |
| `secrets.COPILOT_GITHUB_TOKEN` | Exported as `COPILOT_GITHUB_TOKEN` so the planner / implementer / reviewer jobs can authenticate Copilot CLI. |
| `secrets.ACTION_GITHUB_TOKEN` with permission to call `workflow_dispatch` on the repo | Used to fan out `flow-issue.yml`, `flow-pr-ready.yml`, and `flow-merge-queue.yml` via `workflow_dispatch`. If it is absent, ai-flow falls back to inline orchestration in the issue handler. |
| Workflow `secrets.GITHUB_TOKEN` available to the jobs, with repository Actions settings allowing write access for `contents`, `issues`, `pull-requests`, and `actions` | The workflows export `secrets.GITHUB_TOKEN` as both `GITHUB_TOKEN` and `FLOW_GIT_TOKEN` for label changes, issue updates, PR updates, and merge queue processing. |

### 5. Start the system

After the repo is bootstrapped, pushed, and the workflow prerequisites are in
place, create the first `type:goal` issue with the `agent-ready` label:

1. Open a new issue from `.github/ISSUE_TEMPLATE/goal.md` (the **🎯 Goal**
   template). It pre-labels the issue with `type:goal`.
2. Fill in the goal, done criteria, and any constraints.
3. Add the `agent-ready` label to that goal issue.

`flow-issue.yml` listens for the `agent-ready` label, so adding that label
starts the Planner. From there ai-flow creates task issues, runs Implementer
and Reviewer agents, and drains the merge queue automatically.

## Developing ai-flow itself

If you are working on this repository rather than adopting it elsewhere:

```bash
python -m pip install -e ./.flow[dev]
```

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
Hello, ai-flow!

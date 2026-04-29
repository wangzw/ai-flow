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

## Adopt ai-flow in another repository

The bundled workflows are designed to run **from the target repository**. In
their current form they check out that repository and execute
`pip install -e ./.flow`, so the target repo must commit the ai-flow runtime
under `.flow/` before enabling the workflows. `flow init` adds workflows, the
goal issue template, `.flow/config.yml`, and `.flow/prompts/`; it does **not**
copy `.flow/pyproject.toml` or `.flow/src/` for you.

### 1. Vendor the runtime into the target repo, then install ai-flow locally

```bash
cd /path/to/target-repo
git clone --depth=1 https://github.com/wangzw/ai-flow.git /tmp/ai-flow-bootstrap
mkdir -p .flow
cp /tmp/ai-flow-bootstrap/.flow/pyproject.toml .flow/pyproject.toml
cp -R /tmp/ai-flow-bootstrap/.flow/src .flow/src
python -m pip install -e ./.flow
```

That gives the target repository the same package layout the generated GitHub
Actions jobs expect when they later run `pip install -e ./.flow`.

### 2. Bootstrap repo-local assets

Run the CLI from the target repository root:

```bash
flow init
```

This writes:

- `.github/workflows/flow-issue.yml`
- `.github/workflows/flow-comment.yml`
- `.github/workflows/flow-pr-ready.yml`
- `.github/workflows/flow-merge-queue.yml`
- `.github/workflows/flow-schedule.yml`
- `.github/ISSUE_TEMPLATE/goal.md`
- `.flow/config.yml`
- `.flow/prompts/*.md`

Before you commit, edit `.flow/config.yml` for your repository. In particular,
set `authorized_users` so `/agent ...` slash commands are accepted from your
maintainers.

### 3. Create labels and run the health check

`flow apply-labels` and `flow doctor` require `GITHUB_TOKEN` or
`FLOW_GIT_TOKEN` in your shell.

```bash
export GITHUB_TOKEN=<token-with-access-to-owner/repo>
flow apply-labels --repo <owner/repo>
flow doctor --repo <owner/repo>
```

`flow doctor --repo <owner/repo>` checks the local CLI install, token access,
the ai-flow label set, the generated workflow files, and `.flow/config.yml`.

### 4. GitHub Actions and secrets prerequisites

The generated workflows assume the target repository has:

| Requirement | Why it is needed |
| --- | --- |
| GitHub Actions enabled on the repository | `flow init` installs workflow-driven automation; nothing runs without Actions. |
| The generated workflow files committed to the default branch | `flow-issue.yml`, `flow-comment.yml`, `flow-pr-ready.yml`, `flow-merge-queue.yml`, and `flow-schedule.yml` are the runtime entry points. |
| Runners compatible with the bundled jobs (`ubuntu-latest`, Python 3.11, Node 20) | The workflows use `actions/setup-python@v5`, `actions/setup-node@v4`, and then install dependencies inside the job. |
| Ability for workflows to run `npm install -g @github/copilot` | Every planner / implementer / reviewer workflow installs Copilot CLI inside the runner. |
| `secrets.COPILOT_GITHUB_TOKEN` | Passed to Copilot CLI as `COPILOT_GITHUB_TOKEN` for agent authentication. |
| `secrets.ACTION_GITHUB_TOKEN` with access to `workflow_dispatch` on the repo | Used to fan out `flow-issue.yml`, `flow-pr-ready.yml`, and `flow-merge-queue.yml` via `workflow_dispatch`. |
| The built-in `GITHUB_TOKEN` available to workflows with `contents: write`, `issues: write`, `pull-requests: write`, and `actions: write` where declared | The bundled workflows export it as `GITHUB_TOKEN` and `FLOW_GIT_TOKEN` for GitHub API writes, labels, issue updates, PR updates, and queue processing. |

### 5. Start the system

After the repo is bootstrapped and the workflows are committed:

1. Open a new issue from `.github/ISSUE_TEMPLATE/goal.md` (the **🎯 Goal**
   template). It pre-labels the issue with `type:goal`.
2. Fill in the goal, done criteria, and any constraints.
3. Add the `agent-ready` label to that goal issue.

`flow-issue.yml` is wired to the `agent-ready` label, so adding that label
starts the Planner. From there the bundled workflows drive task creation,
implementation, review, and merge.

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

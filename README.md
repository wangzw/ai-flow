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

The bundled workflows run **inside the repository that is adopting ai-flow**.
Each workflow checks out the target repository and runs `pip install -e ./.flow`,
so adoption means committing both the generated bootstrap files and the `.flow`
runtime package into your repository.

### 1. Install the ai-flow CLI locally

Install the CLI from this repository's `.flow` package:

```bash
python -m pip install "ai-flow @ git+https://github.com/wangzw/ai-flow.git#subdirectory=.flow"
```

This gives you the `flow` command locally so you can bootstrap a different
repository.

### 2. Bootstrap the target repository and vendor the runtime

From the target repository root, run `flow init`, then vendor the runtime from
this repository with Git so the generated workflows have a local `./.flow`
package to install:

```bash
cd /path/to/target-repo
flow init
git remote add ai-flow-upstream https://github.com/wangzw/ai-flow.git
git fetch --depth=1 ai-flow-upstream main
git checkout ai-flow-upstream/main -- .flow/pyproject.toml .flow/src
```

`flow init` writes:

- `.github/workflows/flow-issue.yml`
- `.github/workflows/flow-comment.yml`
- `.github/workflows/flow-pr-ready.yml`
- `.github/workflows/flow-merge-queue.yml`
- `.github/workflows/flow-schedule.yml`
- `.github/ISSUE_TEMPLATE/goal.md`
- `.flow/config.yml`
- `.flow/prompts/*.md`

The `git checkout ... -- .flow/pyproject.toml .flow/src` step vendors the same
runtime package layout the workflows later expect when they run
`pip install -e ./.flow`. This keeps the setup reproducible without asking you
to manually copy files one-by-one.

Before you commit, edit `.flow/config.yml` for your repository. In particular,
set `authorized_users` so `/agent ...` slash commands are accepted from your
maintainers. Then commit and push the generated workflow files, the goal issue
template, `.flow/config.yml`, `.flow/prompts/`, `.flow/pyproject.toml`, and
`.flow/src` to the repository's default branch.

### 3. Create labels and run the health check

`flow apply-labels` and `flow doctor` require `GITHUB_TOKEN` or
`FLOW_GIT_TOKEN` in your shell:

```bash
export GITHUB_TOKEN=<token-with-access-to-owner/repo>
flow apply-labels --repo <owner/repo>
flow doctor --repo <owner/repo>
```

`flow doctor --repo <owner/repo>` checks the local CLI install, token access,
the ai-flow label set, the committed `flow-*.yml` workflow files, and
`.flow/config.yml`.

### 4. GitHub Actions and runtime prerequisites

The generated workflows already include the runtime bootstrap they need
(`actions/checkout`, `actions/setup-python`, `actions/setup-node`, and
`npm install -g @github/copilot`). The target repository still needs the
following GitHub-side prerequisites:

| Requirement | Why it is needed |
| --- | --- |
| GitHub Actions enabled on the repository | `flow init` installs workflow-driven automation; nothing runs without Actions. |
| The generated workflow files and vendored `.flow` runtime committed to the default branch | Each job checks out the target repo and runs `pip install -e ./.flow`, so the runtime must live in the repository alongside `flow-issue.yml`, `flow-comment.yml`, `flow-pr-ready.yml`, `flow-merge-queue.yml`, and `flow-schedule.yml`. |
| Runners compatible with the bundled jobs (`ubuntu-latest`, Python 3.11, Node 20) | The workflows use `actions/setup-python@v5`, `actions/setup-node@v4`, and then install dependencies inside the job. |
| Ability for workflows to run `npm install -g @github/copilot` | Every planner / implementer / reviewer job installs Copilot CLI in the runner before invoking ai-flow. |
| `secrets.COPILOT_GITHUB_TOKEN` | Passed to Copilot CLI as `COPILOT_GITHUB_TOKEN` for agent authentication. |
| `secrets.ACTION_GITHUB_TOKEN` with access to `workflow_dispatch` on the repo | Used to fan out `flow-issue.yml`, `flow-pr-ready.yml`, and `flow-merge-queue.yml` via `workflow_dispatch`. If it is absent, ai-flow falls back to inline orchestration in a single workflow run. |
| Workflow `GITHUB_TOKEN` write access for `contents`, `issues`, `pull-requests`, and `actions` | The bundled workflows export `secrets.GITHUB_TOKEN` as both `GITHUB_TOKEN` and `FLOW_GIT_TOKEN` for GitHub API writes, labels, issue updates, PR updates, and queue processing. |

### 5. Start the system

After the repo is bootstrapped, pushed, and the workflow prerequisites are in
place:

1. Open a new issue from `.github/ISSUE_TEMPLATE/goal.md` (the **🎯 Goal**
   template). It pre-labels the issue with `type:goal`.
2. Fill in the goal, done criteria, and any constraints.
3. Add the `agent-ready` label to that goal issue.

`flow-issue.yml` listens for the `agent-ready` label, so adding that label
starts the Planner. From there the bundled workflows create task issues, run
Implementer and Reviewer agents, and drain the merge queue automatically.

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

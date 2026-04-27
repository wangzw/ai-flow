# GitHub + Copilot CLI Adapter Implementation Plan

**Goal:** Mirror the GitLab CE implementation onto GitHub Actions using GitHub Copilot CLI for Coder/Reviewer agents and PyGithub for API. The shared modules (state_machine, comment_parser, ac_validator, comment_writer) are already platform-agnostic — they require no changes.

**Architecture:**
- New `github_client.py` parallels `gitlab_client.py` with the same method names (`set_state_label`, `comment_on_issue`, etc.)
- New `copilot_cli_client.py` parallels `claude_code_client.py` (subprocess wrapper for `copilot` CLI, with API parity to `ClaudeCodeClient`)
- Handlers (`issue_handler`, `comment_handler`, `mr_handler`) — accept client by injection, no source changes needed
- `coder.py` and `merge_queue.py` use GitLab-specific API idioms (`project.mergerequests.create`, etc.). For the GitHub path, we provide thin GitHub-flavored wrappers that adapt to PyGithub's idioms.
- GitHub Actions workflows (`.github/workflows/*.yml`) replace `gitlab-ci.yml`. **No webhook relay needed** — GitHub Actions is natively event-driven (`on: issues`, `on: pull_request`, `on: issue_comment`).

## Key differences from GitLab path

| Aspect | GitLab CE | GitHub |
|---|---|---|
| API library | `python-gitlab` | `PyGithub` |
| Coder/Reviewer CLI | `claude` (Claude Code) | `copilot` (Copilot CLI) |
| CI definition | `.gitlab-ci.yml` (heredocs) | `.github/workflows/*.yml` (one file per event) |
| Event ingress | Webhook relay (Flask) | Native GitHub Actions triggers |
| Merge queue | Custom (`resource_group`) | Custom (label-driven) — same as GitLab |
| Auth | `GITLAB_API_TOKEN` (PAT) | `${{ github.token }}` (built-in) or PAT for cross-repo |

## DECISIONS (defaults)

1. **Copilot CLI binary**: assume `copilot` (from `@github/copilot` npm package). Documented in CI install step.
2. **GitHub Merge Queue (Premium)**: NOT used. We replicate our custom queue (`merge-queued` label) for parity with GitLab CE behavior.
3. **PyGithub vs ghapi**: PyGithub. Mature, widely used.
4. **No webhook relay**: GitHub Actions handles event ingress natively. Saves a service.
5. **Action workflow per event**: 4 files — `agent-issue.yml`, `agent-comment.yml`, `agent-pr-ready.yml`, `agent-merge-queue.yml`.

## Tasks

### Task 1: Add `pygithub` dep + scaffold modules

- Add `pygithub>=2.1` to `pyproject.toml`
- Create `src/sw/github_client.py` (docstring stub)
- Create `src/sw/copilot_cli_client.py` (docstring stub)
- Commit

### Task 2: `CopilotCliClient` (TDD)

Subprocess wrapper for `copilot` CLI. API parity with `ClaudeCodeClient` (same `run(prompt=, cwd=, env=, ...)` signature, returns `CopilotCliResult`).

### Task 3: `GitHubClient` (TDD)

PyGithub wrapper with API parity to `GitLabClient`:
- `set_state_label(issue, new_label)` — atomic state-label replace
- `comment_on_issue(issue, body)` — adds an Issue comment
- `get_repo(repo_full_name)` — returns the repo handle (parallels `get_project`)

Tests use `MagicMock` for PyGithub objects.

### Task 4: GitHub Actions workflows

Create:
- `.github/workflows/agent-issue.yml` — `on: issues, types: [labeled]`. When `agent-ready` is added, install deps, run handler.
- `.github/workflows/agent-comment.yml` — `on: issue_comment`. Parse `/agent` commands.
- `.github/workflows/agent-pr-ready.yml` — `on: pull_request, types: [ready_for_review]`. Run reviewer matrix.
- `.github/workflows/agent-merge-queue.yml` — `on: pull_request, types: [labeled]`. When `merge-queued` added, run merge_queue. Use `concurrency:` group for serialization.

Each workflow installs Python + Node + Copilot CLI in `before_script`-equivalent steps, then invokes `python -m sw.handlers.<x>` with arguments from `${{ github.event }}`.

### Task 5: README + SMOKE_TEST update

- README: add GitHub adapter section
- SMOKE_TEST: add GitHub-specific paths (Path 5: GitHub happy path)

### Task 6: Tag

`v0.5.0-github-adapter`

## Acceptance

- 92 → ~100+ tests; coverage stays ≥ 85%
- ruff clean
- Workflows YAML-valid (manually inspected)
- Documentation complete
- Tag at HEAD

## Out of scope (future)

- Real end-to-end smoke on a GitHub repo (requires actual GitHub repo + Copilot CLI subscription)
- Refactoring `coder.py` / `merge_queue.py` to be platform-agnostic via Protocol/ABC
- GitHub native Merge Queue integration (Premium feature)
- Workflow-as-CLI tool (the workflows currently inline Python; a small CLI wrapper could DRY this up)

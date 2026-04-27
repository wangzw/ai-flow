# GitHub Real Path Implementation Plan

**Goal:** Replace `github_dispatch.py` placeholders with real implementations so that the GitHub path is fully functional and can be tested locally with `copilot` CLI.

**Strategy:**
- Write `coder_gh.py` (parallel to `coder.py`) using PyGithub + `CopilotCliClient`
- Write `merge_queue_gh.py` (parallel to `merge_queue.py`) using PyGithub
- `reviewer.py` is already platform-agnostic (it only invokes a CLI in a repo path) — callers just pass `CopilotCliClient`
- Update `github_dispatch.py` to wire these in
- Add a `smoke_local.py` script for local testing without GitHub Actions

## Tasks

### Task 1: `coder_gh.py` (TDD)

Mirrors `coder.py`. Differences:
- Uses `repo.get_issue(number)` instead of `project.issues.get(iid)`
- Uses `issue.body` instead of `issue.description`
- Uses `repo.clone_url` instead of `project.http_url_to_repo`
- Uses `repo.default_branch` (same name on both)
- Uses `repo.create_pull(title=, body=, head=, base=, draft=True)` instead of `project.mergerequests.create({...})`
- Uses `CopilotCliClient` by default (configurable)
- Returns the same `CoderResult` dataclass (uses `mr_iid` field as universal "PR/MR number" — pr.number)

### Task 2: `merge_queue_gh.py` (TDD)

Mirrors `merge_queue.py`. Differences:
- Uses `repo.get_pulls(state="open")` and filters by `merge-queued` label
- Uses `pr.merge(merge_method="rebase", delete_branch=True)` — GitHub's merge endpoint with `merge_method="rebase"` does atomic rebase+merge, **no async race**
- Uses `pr.add_to_labels("...")` / `pr.remove_from_labels("...")` for label management
- Detects `Closes #N` in PR body, transitions linked Issue via `client.set_state_label`

### Task 3: Wire `github_dispatch.py`

Replace placeholders:
- `cmd_issue_labeled`: invoke `coder_gh.run_coder` and handle blocker (post needs-human comment + transition)
- `cmd_comment_created`: on resume/retry invoke `coder_gh.run_coder` similarly
- `cmd_pr_ready`: clone repo locally, run `reviewer.run_review_matrix(cli=CopilotCliClient(), repo_path=...)`, on all-pass add `merge-queued` label to PR; on fail no-op
- `cmd_merge_queue`: invoke `merge_queue_gh.process_merge_queue`

### Task 4: Local smoke entry point

`scripts/smoke_local.py` — sets env vars, invokes a flow against a real GitHub repo. User runs:
```bash
GITHUB_TOKEN=... SW_REPO=user/repo python scripts/smoke_local.py issue-labeled --issue 5
```

### Task 5: Tag

`v0.7.0-github-real`

## Acceptance

- 116 → ~125+ tests
- coverage ≥ 80%
- ruff clean
- `github_dispatch.py` placeholders gone
- `scripts/smoke_local.py` runs end-to-end against a real GitHub repo (manual verification)

## DECISIONS

1. **`reviewer.py` parameter name**: leave as `claude` for backward compat. Callers can pass any client with `.run(prompt=, cwd=, env=, timeout=, check=)` signature — `CopilotCliClient` matches.
2. **Rebase**: GitHub's `pr.merge(merge_method="rebase")` is atomic. No race like GitLab CE.
3. **Local clone for review**: `pr-ready` workflow already runs in a checked-out state (`actions/checkout@v4` with `ref: pr.head.sha`). For local smoke, the script does the clone manually.
4. **Auth**: GitHub PAT or App token via `GITHUB_TOKEN` env var. PyGithub handles the rest.

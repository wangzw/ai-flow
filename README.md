# software-workflow

AI Coding 工作流框架 — GitLab CE 实现。

参见：
- 设计：`docs/superpowers/specs/2026-04-27-ai-coding-workflow-design.md`
- 计划：`docs/superpowers/plans/2026-04-27-skeleton-mvp-gitlab-ce.md`

## Quick start

1. 准备一个 GitLab CE 实例和测试项目
2. 在项目 CI/CD Variables 中添加 `GITLAB_API_TOKEN`（api scope, Masked, Protected）
3. 在项目 CI/CD Variables 中添加 `ANTHROPIC_API_KEY`（Masked, Protected）—— 真实 Coder 调 Claude Code 时使用
4. 复制 `ci/gitlab-ci.yml` 到目标项目根目录改名为 `.gitlab-ci.yml`
5. 复制 `templates/` 到目标项目的 `.gitlab/issue_templates/` 和 `.gitlab/merge_request_templates/`
6. 运行 `python -m sw.label_apply --project <group/project>` 应用标签
7. 在 Issue 中按模板填写 AC，添加 `agent-ready` 标签，观察自动化流程

## Local testing (GitHub path)

Test the GitHub dispatch end-to-end on your machine without GitHub Actions:

```bash
export GITHUB_TOKEN=<your PAT with repo+issues scope>
export SW_REPO=owner/test-repo

# 1. Apply labels to the test repo (does not require GitHub Actions)
#    Equivalent to label_apply.py for GitLab — for GitHub, use gh CLI:
gh label create agent-ready --color 1F75CB --description "AC ready"
gh label create agent-working --color FFA500 --description "Agent working"
gh label create needs-human --color D9534F --description "Agent stuck"
gh label create agent-done --color 1A7F37 --description "Done"
gh label create agent-failed --color 5D5D5D --description "Failed"
gh label create merge-queued --color 6C757D --description "Awaiting merge"

# 2. Create an Issue with AC, then trigger the agent locally:
python scripts/smoke_local.py issue-labeled --issue 5

# 3. After the Coder finishes, mark the PR as Ready and run reviewer:
python scripts/smoke_local.py pr-ready --pr 12

# 4. Process the merge queue:
python scripts/smoke_local.py merge-queue
```

The script invokes `sw.github_dispatch` directly with the right env vars set, so the same code paths run locally as in GitHub Actions.

## Cloud testing (GitHub Actions)

Run the framework directly on GitHub via the workflows in `.github/workflows/`. Required one-time setup per target repo:

### 1. Apply labels (same as local section above)

```bash
for L in agent-ready:1F75CB agent-working:FFA500 needs-human:D9534F agent-done:1A7F37 agent-failed:5D5D5D merge-queued:6C757D; do
  name=${L%:*}; color=${L#*:}
  gh label create "$name" --color "$color" --repo <owner/repo>
done
```

### 2. Add `COPILOT_GITHUB_TOKEN` repository secret

The Copilot CLI in the runner authenticates via env var. Default `${{ secrets.GITHUB_TOKEN }}` does NOT have Copilot scope — you must provide a separate fine-grained PAT:

1. Open https://github.com/settings/personal-access-tokens/new
2. **Repository access**: Only selected repositories → your target repo
3. **Permissions** → **Account permissions** → **Copilot Requests**: Read
4. Generate, copy `github_pat_xxx`
5. Add as repo secret:

   ```bash
   gh secret set COPILOT_GITHUB_TOKEN --repo <owner/repo> --body <PAT>
   ```

> Classic PATs (`ghp_…`) are NOT accepted by Copilot CLI — it requires fine-grained PATs only.

### 3. Allow GitHub Actions to create pull requests

Default repo settings forbid `GITHUB_TOKEN` from creating PRs. The Coder Agent needs this. Enable via API:

```bash
gh api -X PUT repos/<owner/repo>/actions/permissions/workflow \
  -F default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true
```

Or via UI: Settings → Actions → General → **Workflow permissions** → check "Read and write permissions" + "Allow GitHub Actions to create and approve pull requests" → Save.

### 4. Trigger an end-to-end run

1. Create an Issue with a clear AC inside the `<!-- ac:start --> ... <!-- ac:end -->` block.
2. Add the `agent-ready` label.
3. Watch the Action: `gh run list --repo <owner/repo> --limit 1` → open the URL.
4. The flow:
   - `agent-issue.yml` triggers → AC validation → Coder clones + invokes `copilot` → pushes branch → opens draft PR.
   - Mark the PR as Ready → `agent-pr-ready.yml` triggers → Reviewer matrix runs 7 dimensions sequentially.
   - On all-pass, the workflow adds the `merge-queued` label → `agent-merge-queue.yml` triggers → ff-merge → Issue label transitions to `agent-done` → Issue auto-closed via `Closes #N`.

### Required secrets summary

| Secret | Purpose | Required |
|---|---|---|
| `GITHUB_TOKEN` (auto) | PyGithub API + git clone/push (HTTPS via `SW_GIT_TOKEN` passthrough) | Built-in |
| `COPILOT_GITHUB_TOKEN` | Copilot CLI authentication | **Yes (manual)** |


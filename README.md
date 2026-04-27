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

# software-workflow

AI Coding 工作流框架 — GitLab CE 实现。

参见：
- 设计：`docs/superpowers/specs/2026-04-27-ai-coding-workflow-design.md`
- 计划：`docs/superpowers/plans/2026-04-27-skeleton-mvp-gitlab-ce.md`

## Quick start

1. 准备一个 GitLab CE 实例和测试项目
2. 在项目 CI/CD Variables 中添加 `GITLAB_API_TOKEN`（api scope, Masked, Protected）
3. 复制 `ci/gitlab-ci.yml` 到目标项目根目录改名为 `.gitlab-ci.yml`
4. 复制 `templates/` 到目标项目的 `.gitlab/issue_templates/` 和 `.gitlab/merge_request_templates/`
5. 运行 `python -m sw.label_apply --project <group/project>` 应用标签
6. 在 Issue 中按模板填写 AC，添加 `agent-ready` 标签，观察自动化流程

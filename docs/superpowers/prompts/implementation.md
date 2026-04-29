# ai-flow 实现工作交接 Prompt

> 这是一份**自包含的交接 prompt**，给在另一个 Claude Code 会话中接手实现工作的 Agent。
> 把以下整段贴到新会话作为初始指令即可。

---

## 你的任务

实现 **ai-flow**：一个基于 GitHub 仓库（Issue + PR + Workflow）的递归任务分解与多 Agent 协作框架。它把"软件开发目标"作为根 Issue 输入，由 Planner Agent 递归拆成子任务、由 Implementer Agent 实现、由 Reviewer Agent 多维度审查，最终全自动合并到 main——人类只在自动化用尽时介入。

## 必读文档（按顺序）

1. **设计规范**（你的实现合同）
   `/Users/wangzw/workspace/ai-flow/docs/superpowers/specs/2026-04-29-ai-flow-design.md`
   全文必读，特别是 §3（状态机）、§4（任务树）、§5（Planner）、§6（Implementer）、§7（Reviewer）、§8（失败处理）、§9（并发）、§13（Bootstrap）、§16（Schema 附录）。

2. **概念引导**（背景理解，可选）
   `/Users/wangzw/Documents/mind/raw/guide/基于 git 仓库的调度系统.md`
   设计哲学层面的解释，避免实现细节。如果你想理解"为什么这样设计"再读。

3. **先前实现：software-workflow**（已被验证可工作的基线）
   `/Users/wangzw/workspace/software-workflow/`
   ai-flow 的叶子执行层（单 Issue → 单 PR → Reviewer 矩阵 → ff-merge）几乎可以原样继承自这里。**优先复用、不要重新发明**：

   | 模块 | 文件 | 复用方式 |
   |---|---|---|
   | State machine | `src/sw/state_machine.py` | 直接搬，扩展事件集 |
   | Comment parser | `src/sw/comment_parser.py` | 直接搬，扩展命令集（加 `decide`、`replan`） |
   | Comment writer | `src/sw/comment_writer.py` | 直接搬 |
   | Reviewer 框架 | `src/sw/reviewer.py` | 直接搬 |
   | Coder client | `src/sw/coder.py` + `claude_code_client.py` + `copilot_cli_client.py` | 直接搬，重命名 `coder` → `implementer` |
   | Merge queue | `src/sw/merge_queue.py` + `merge_queue_gh.py` | 直接搬 |
   | GitHub client | `src/sw/github_client.py` + `github_dispatch.py` | 直接搬，扩展 method 集 |
   | Metrics | `src/sw/metrics.py` | 直接搬，加 `llm_call` 事件 |
   | Label apply | `src/sw/label_apply.py` | 改 label 集合后搬 |
   | AC validator | `src/sw/ac_validator.py` | **重写**——ai-flow 的"AC"是 task spec quality_criteria |
   | Workflow YAML | `.github/workflows/agent-*.yml` | 改名 `agent` → `flow`，结构相同 |

4. **设计文档 §18**：与 software-workflow 的差异速查表

## 关键约束（不要违反）

1. **Python**，平台 GitHub-first（GitLab CE 留 v0.2）
2. **不发布到 PyPI**——框架代码作为目标项目的 `.flow/` 子目录提交
3. **Agent CLI**：GitHub 用 `copilot`（`@github/copilot`），GitLab 用 `claude`（Claude Code）
4. **环境变量名沿用 software-workflow**：`SW_REPO`、`SW_ISSUE_NUMBER`、`COPILOT_GITHUB_TOKEN`、`ANTHROPIC_API_KEY` 等。**不要改名**。
5. **Channel 纪律**（设计 §11）：Reviewer 不读 commit msg / PR description / implementer summary。在 prompt 和 input bundle 构造层都强制。
6. **Fail-closed**：缺 marker / 解析失败 / 状态非法 → 立即转 needs-human 或 failed-env。**不要默认值兜底**。
7. **Reconciler 范式**：Planner 输出**全量** desired_plan，不是 diff。所有副作用由 Coordinator 应用。
8. **Coordinator 是 Python 派发逻辑**，不是 LLM。所有 LLM 调用只发生在 Planner / Implementer / Reviewer 三个角色。

## 实现节奏（建议）

按以下顺序实现，每个里程碑都跑通才动下一个。**每个里程碑结束都开 PR 让人类 review**。

### Milestone M0：项目骨架 + 测试基础设施

- 在 `/Users/wangzw/workspace/ai-flow/` 下创建 `.flow/` 目录结构（pyproject.toml / src/flow/ / tests/ / prompts/）
- 拷贝 software-workflow 的 `state_machine.py` / `comment_parser.py` / `comment_writer.py` / `metrics.py` 到 `src/flow/`，保留并扩展
- 设置 pytest + ruff + mypy
- 跑通 round-trip 测试（comment writer + parser）

### Milestone M1：状态机与 schema 落地

- 实现 ai-flow 状态机（5 状态 + 任务树 转移表，§3.4）
- 实现 task body YAML schema 读写（§4.4）
- 实现 manifest YAML schema 读写（§4.3）
- Unit tests 覆盖所有合法 / 非法转移
- Unit tests 覆盖 manifest round-trip

### Milestone M2：fake AgentClient + handler 派发骨架

- 定义 `AgentClient` Protocol
- 实现 `FakeAgentClient`（返回预设 result.yaml）
- 实现 `IssueHandler`（处理 `agent-ready` 事件，决定派 Planner / Implementer）
- 实现 `CommentHandler`（解析 `/agent` 命令，状态切换）
- 用 fake client 跑通 handler 测试

### Milestone M3：Planner Reconciler

- 实现 Planner subprocess 调用 + result.yaml 解析
- 实现 Reconciler 算法（§5.5）：创建 / 更新 / 取消 task issue
- 实现 dispatch_lock（应用层并发锁，§9.1 Layer 2）
- 实现 §5.6 三段升级（含 review_arbitration）
- Unit tests + integration tests（fake Planner client）

### Milestone M4：Implementer + Reviewer

- 实现 Implementer 调用（继承 software-workflow `coder.py`）
- 实现 Reviewer 矩阵（7 维度，§7）
  - **重要**：input bundle 构造时**显式排除** commit msg / PR description（§11）
- 实现 review iteration 计数 + body state 写入
- Integration test：fake Implementer 报 done → Reviewer 全 pass → merge queue

### Milestone M5：Merge Queue（继承）

- 复制 software-workflow `merge_queue.py` + `merge_queue_gh.py`
- 适配新的 label 集合
- e2e 测试：多 PR 串行 merge

### Milestone M6：失败处理

- 实现 failed-env 分类重试（§8.3）
- 实现 cron schedule workflow（§8.3 重试调度）
- 实现 `goal_failure_threshold` 树级 throttle（§8.4）
- 实现 cron sweeper 检测 stale agent-working
- Unit tests 覆盖每个 retry category

### Milestone M7：Slash 命令 + `/ask`/`/decide`

- 扩展 comment parser 支持新命令（`decide`、`replan`）
- 实现 `/ask` Agent 端协议（Implementer 在 result.yaml 写 `blocker.type: ask`）
- 实现 `/agent decide <id>` 注入决策到下一轮 prompt
- Authorization：`authorized_users` 白名单
- Unit tests 覆盖每个命令的合法 / 非法路径

### Milestone M8：Bootstrap CLI

- `flow init` —— 创建 `.flow/` + workflows + labels
- `flow doctor` —— 检查 secrets / labels / permissions / config 必填项
- `flow apply-labels` —— 幂等应用 7 个 label
- `flow status --goal <num>` —— 显示 goal tree 树形输出
- `flow logs` —— 读 metrics

### Milestone M9：Cost Observability

- 在 AgentClient 调用处 emit `llm_call` 事件
- Token / cost 估算（Claude 真数 / Copilot 估算）
- `flow report cost` 命令（§14.4）

### Milestone M10：e2e Smoke

- 在一个全新 repo 上跑 `flow init`
- 创建一个最小 goal："在 README 末尾加一行"
- 全流程跑通：Planner 拆 1 task → Implementer 开 PR → Reviewer 通过 → merge → goal close
- 5 分钟内完成

## 工作纪律

- **使用 superpowers**：在 Claude Code 中你有 `superpowers:*` 技能可用。**强制使用**：
  - `superpowers:test-driven-development` —— 实现任何功能前先写测试
  - `superpowers:systematic-debugging` —— 遇到 bug 时
  - `superpowers:writing-plans` —— 每个 milestone 开始前写实现计划
  - `superpowers:executing-plans` —— 执行计划时
  - `superpowers:verification-before-completion` —— 声明完成前必跑验证

- **每个 milestone 都开 PR**，等人类 review 通过后才动下一个。

- **测试覆盖**：handler 用 fake client，纯逻辑用 unit test，e2e 用真实 Copilot CLI（可能需要 budget 控制）。

- **Channel 纪律是合同**：你写的代码里凡是构造 Reviewer input 的地方，必须有显式的 exclude 检查（unit test 验证）。这一点不能遗漏。

- **Fail-closed 优先于完整性**：宁可让任务 needs-human 被人介入，也不要让 marker 缺失时按默认值继续跑。

## 当遇到设计问题时

设计文档可能有遗漏 / 矛盾 / 模糊。处理顺序：

1. **先回设计文档**，逐字读相关章节
2. **再回 software-workflow** 的对应实现，看它是怎么处理的
3. **若仍不确定** → 在 PR description 列出问题，等人类回答，**不要自己拍板**
4. **设计文档错误** → 用 `docs-update` skill 提交修订（保留审计日志）

## Smoke test 验证目标

整套实现完成后，对一个空白 repo：

```bash
cd /tmp/test-target-repo
git init
gh repo create acme/test-target --private --source=. --push
flow init
flow doctor          # 应全绿（除 user-required 字段）
# 编辑 .flow/config.yml 填 authorized_users 和 blast_radius
git add .flow .github && git commit -m "chore: bootstrap flow"
git push

# 触发首跑
gh issue create \
  --title "[smoke] add hello to README" \
  --body "在 README.md 末尾加一行 'Hello, ai-flow!'" \
  --label "type:goal,agent-ready"

# 观察
gh run watch
flow status --goal <issue_num>
```

期望路径：

```
agent-ready
  → Planner: 创建 1 个 task issue (T-add-hello)
agent-working (root) + agent-ready (task)
  → Implementer: 开 PR
agent-working (task) + PR open
  → Reviewer 矩阵全绿
PR merged + agent-done (task)
  → Planner: status: done
agent-done (root, closed)
```

总耗时：5–10 分钟。Cost：< $0.50。

---

## 起手第一步

```bash
cd /Users/wangzw/workspace/ai-flow
ls -la       # 应只有 .git 和 docs/
```

读完设计文档和这份 prompt，然后用 `superpowers:writing-plans` skill 写 M0 实现计划，再用 `superpowers:executing-plans` 执行。

祝顺利。

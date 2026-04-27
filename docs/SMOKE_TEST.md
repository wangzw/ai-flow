# Skeleton MVP Smoke Test

Verifies the end-to-end loop on GitLab CE.

## Prerequisites

- GitLab CE instance, version ≥ 16.0
- A test project, e.g. `agent-demo/test-repo`
- A Personal Access Token (or Project Access Token) with `api` scope
- A GitLab Runner registered to the project, allowed to run untagged jobs
- This framework repo cloned and installed in the Runner image (or pip-installable URL set as `SW_FRAMEWORK_GIT_URL`)
- `webhook_relay` service deployed (e.g., on the same host or a sidecar) and reachable from GitLab

## One-time Setup

1. **Configure project CI/CD Variables** (Settings → CI/CD → Variables):
   - `GITLAB_API_TOKEN` — value: your PAT, **Masked**, **Protected**
   - `SW_FRAMEWORK_GIT_URL` — URL of this repo (HTTPS clone URL)

2. **Apply labels**:

   ```bash
   export GITLAB_API_TOKEN=<your-token>
   python -m sw.label_apply --project agent-demo/test-repo --gitlab-url https://gitlab.example.com
   ```

3. **Install templates** in the project:

   - Copy `templates/issue_template.md` → `.gitlab/issue_templates/agent-task.md`
   - Copy `templates/mr_template.md` → `.gitlab/merge_request_templates/agent-mr.md`
   - Copy `ci/gitlab-ci.yml` → `.gitlab-ci.yml`
   - Commit and push to `main`.

4. **Deploy webhook relay**:

   ```bash
   export GITLAB_API_TOKEN=<your-token>
   export WEBHOOK_SECRET=<generate-strong-string>
   export CI_SERVER_URL=https://gitlab.example.com
   python -m sw.webhook_relay
   ```

5. **Configure project Webhook** (Settings → Webhooks):
   - URL: `http://<relay-host>:8080/webhook`
   - Secret token: `<WEBHOOK_SECRET>` from step 4
   - Triggers: ☑ Issues events, ☑ Comments, ☑ Merge request events

## Walkthrough

### Path 1: Happy Path

1. Create a new Issue using the `agent-task` template.
2. Fill the Issue body — include a non-empty AC block:

   ```markdown
   <!-- ac:start -->
   - When project is touched, AGENT_LOG.md exists at root.
   <!-- ac:end -->
   ```

3. Add the `agent-ready` label.
4. Within ~30 seconds, observe:
   - Label changes from `agent-ready` to `agent-working`.
   - A new branch `agent/issue-<iid>` appears.
   - A Draft MR is opened, closing this Issue.
5. Mark the MR as Ready (un-draft it).
6. Within ~30 seconds, observe:
   - Reviewer matrix runs (stub returns all PASS — visible in pipeline logs).
   - MR is rebased and ff-merged into `main`.
   - Issue label transitions to `agent-done`.
   - Issue is closed (because of `Closes #X`).

### Path 2: AC Missing

1. Create an Issue with the template but leave the `<!-- ac:start --><!-- ac:end -->` block empty.
2. Add the `agent-ready` label.
3. Within ~30 seconds, observe:
   - Label transitions to `needs-human`.
   - A comment appears on the Issue with the `🛑 需要人类决策` heading and a YAML block.
4. Edit the Issue to add valid AC.
5. Add a comment: `decision: edit_issue done` followed on a new line by `/agent resume`.
6. Within ~30 seconds, observe:
   - Label returns to `agent-working`.
   - Coder runs again; from here Path 1 continues from step 4.

### Path 3: Manual Abort

1. While an Agent is working, comment `/agent abort`.
2. Within ~30 seconds, observe:
   - Label transitions to `agent-failed`.
   - No further automation runs on this Issue.

### Path 4: Real Coder (happy)

> **Prerequisite**: `ANTHROPIC_API_KEY` set in project CI/CD Variables.

1. Create an Issue with a clear, narrowly-scoped AC, e.g.:

   ```markdown
   <!-- ac:start -->
   - Add a function `hello()` in `scripts/hello.py` that returns `"hello, world"`.
   - Add `tests/scripts/__init__.py` (empty) and `tests/scripts/test_hello.py` asserting `hello() == "hello, world"`.
   <!-- ac:end -->
   ```

2. Add `agent-ready` label.
3. Within ~5–10 minutes (Claude Code time), observe:
   - Agent branch contains a real commit implementing `hello()` and a test.
   - Draft MR opens with summary in description.
   - Reviewer matrix runs (still stub at this stage; replaced in Plan 3).
4. If Coder gets blocked, observe `needs-human` label + structured comment with the blocker.

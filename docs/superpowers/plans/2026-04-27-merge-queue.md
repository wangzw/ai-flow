# Merge Queue Implementation Plan (GitLab CE)

**Goal:** Replace `mr_handler`'s direct ff-merge with a serial **merge queue** mechanism per spec §6.2 + §7.5. When Reviewer matrix passes, MR is added to the queue (via `merge-queued` label). Queue processor (one CI job at a time, enforced via `resource_group`) pops MRs in order: refresh → rebase → re-run Reviewer matrix → ff-merge. Also fixes the `mr.rebase()` async race documented in `mr_handler`.

## DECISIONS

1. **Queue ordering**: by MR `created_at` (FIFO). Ties broken by MR iid.
2. **`resource_group`**: `production_merge_queue` — single concurrent job globally.
3. **Re-review on rebase**: yes (per spec §6.2). Reuses `run_review_matrix`.
4. **Rebase race fix**: poll `mr.rebase_in_progress` after `mr.rebase()` until false (max 60s); raise on timeout.
5. **Failed re-review on rebase**: drop `merge-queued` label, transition Issue to `agent-working` so Coder can fix (or upstream Coder pipeline detects and re-iterates).

## Tasks

### Task 1: Implement `merge_queue.py` (TDD)

`process_merge_queue(*, project, client, reviewer=None)`:
1. List MRs with `merge-queued` label, sorted by `created_at` then `iid`
2. For the head MR:
   a. `mr.rebase()` then poll `mr.rebase_in_progress` until clear
   b. Run `reviewer(...)` against the rebased branch
   c. If all PASS: `mr.merge()`, transition Issue to `agent-done`
   d. If any FAIL: remove `merge-queued`, transition Issue back to `agent-working`
3. Return processed count

Unit tests mock `python-gitlab` API and reviewer.

### Task 2: Update `mr_handler` to enqueue (not merge)

Replace direct merge with:
- Add `merge-queued` label to MR (using `mr.labels.append`)
- Save MR
- Do NOT touch Issue label here — that happens after queue pop

Update tests accordingly.

### Task 3: Add CI job `merge_queue_event`

In `ci/gitlab-ci.yml`, add:
```yaml
merge_queue_event:
  stage: dispatch
  rules:
    - if: '$CI_TRIGGERED_EVENT == "mr_merge_queued"'
  resource_group: "production_merge_queue"
  script:
    - python -c "...invoke process_merge_queue..."
```

### Task 4: Update webhook relay

Trigger `mr_merge_queued` event when MR `labels` changes to add `merge-queued`.

### Task 5: Add `merge-queued` to labels.yaml

(Color: gray-blue; description: "已通过 Review，等待串行入队合并")

### Task 6: Tag

`v0.4.0-merge-queue`

## Acceptance

- `process_merge_queue` correctly serializes pop + rebase + re-review + merge
- `mr.rebase()` race resolved via poll loop
- `mr_handler` enqueues instead of merging
- Tests stay green; new tests added for queue processor

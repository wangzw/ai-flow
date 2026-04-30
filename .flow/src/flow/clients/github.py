"""GitHub client wrapper (spec §12.5).

Adapter over PyGithub. Atomic state-label replacement (spec §3.5).
"""

from flow.state_machine import EXTERNAL_STATES

# 7 labels per spec §16.1.
STATE_LABELS = EXTERNAL_STATES
TYPE_LABELS = {"type:goal", "type:task"}
AUX_LABELS = {"merge-queued"}
ALL_FLOW_LABELS = STATE_LABELS | TYPE_LABELS | AUX_LABELS


class GitHubClient:
    """Thin PyGithub wrapper for the operations Coordinator needs."""

    def __init__(self, gh):
        self._gh = gh

    @classmethod
    def from_token(cls, token: str) -> "GitHubClient":
        from github import Github

        return cls(gh=Github(token))

    @classmethod
    def from_env(cls) -> "GitHubClient":
        """Use GITHUB_TOKEN by default — it has issues:write/contents:write
        within the same repo. Workflow trigger limitations are addressed
        via inline orchestration in handlers, not via PAT use."""
        import os

        token = (
            os.environ.get("GITHUB_TOKEN")
            or os.environ.get("FLOW_GIT_TOKEN")
            or os.environ.get("COPILOT_GITHUB_TOKEN")
        )
        if not token:
            raise RuntimeError(
                "no GitHub token found "
                "(set GITHUB_TOKEN, FLOW_GIT_TOKEN, or COPILOT_GITHUB_TOKEN)"
            )
        return cls.from_token(token)

    def get_repo(self, full_name: str):
        return self._gh.get_repo(full_name)

    # ------------------------------------------------------------------
    # Issue operations
    # ------------------------------------------------------------------

    def set_state_label(self, issue, new_state: str) -> None:
        """Atomic state-label replacement (spec §3.5).

        Single PUT replace-all: compute final label list, set in one call.
        """
        if new_state not in EXTERNAL_STATES:
            raise ValueError(f"{new_state!r} is not a valid external state")
        existing = [lbl.name for lbl in issue.labels]
        non_state = [n for n in existing if n not in EXTERNAL_STATES]
        issue.set_labels(*non_state, new_state)

    def add_label(self, issue, label: str) -> None:
        if not any(lbl.name == label for lbl in issue.labels):
            issue.add_to_labels(label)

    def remove_label(self, issue, label: str) -> None:
        if any(lbl.name == label for lbl in issue.labels):
            issue.remove_from_labels(label)

    def comment(self, issue, body: str):
        return issue.create_comment(body)

    def react_to_comment(
        self, issue, comment_id: int, reaction: str = "+1",
    ) -> bool:
        """React to an existing issue/PR comment with an emoji.

        reaction must be one of GitHub's supported types:
        '+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes'.

        Returns True on success, False if the comment couldn't be found or
        the API rejected the call. Never raises — reactions are best-effort
        UX sugar; if they fail we fall back to a comment at the call site.
        """
        try:
            comment = issue.get_comment(comment_id)
            comment.create_reaction(reaction)
            return True
        except Exception as exc:
            print(f"[github] react_to_comment failed: {exc}", flush=True)
            return False

    def update_comment(self, issue, comment_id: int, body: str):
        """Edit the body of an existing comment by id (PyGithub IssueComment)."""
        comment = issue.get_comment(comment_id)
        comment.edit(body)
        return comment

    def upsert_comment(self, issue, comment_id: int | None, body: str):
        """Update comment if id present and still exists, else create a new one.

        Returns the comment object so callers can persist its id.
        """
        if comment_id is not None:
            try:
                return self.update_comment(issue, comment_id, body)
            except Exception:
                # Comment was deleted or no longer accessible — fall back to create.
                pass
        return self.comment(issue, body)

    def update_issue_body(self, issue, new_body: str) -> None:
        issue.edit(body=new_body)

    def create_issue(self, repo, *, title: str, body: str, labels: list[str]):
        return repo.create_issue(title=title, body=body, labels=labels)

    def close_issue(self, issue) -> None:
        issue.edit(state="closed")

"""PyGithub wrapper with API parity to `gitlab_client.GitLabClient`.

Exposes the same method names so that handlers/coder/merge_queue can be
parameterized over either client without source changes.
"""

from github import Github

AGENT_LABEL_PREFIX = "agent-"
NEEDS_HUMAN_LABEL = "needs-human"
_VALID_STATE_LABELS = {
    "agent-ready",
    "agent-working",
    "agent-done",
    "agent-failed",
    NEEDS_HUMAN_LABEL,
}


def _is_state_label(label: str) -> bool:
    return label.startswith(AGENT_LABEL_PREFIX) or label == NEEDS_HUMAN_LABEL


class GitHubClient:
    def __init__(self, gh: Github):
        self._gh = gh

    @classmethod
    def from_env(cls, token: str) -> "GitHubClient":
        gh = Github(token)
        return cls(gh=gh)

    def set_state_label(self, issue, new_label: str) -> None:
        """Atomically replace state labels with new_label; preserve others."""
        if new_label not in _VALID_STATE_LABELS:
            raise ValueError(
                f"new_label {new_label!r} must start with {AGENT_LABEL_PREFIX} "
                f"or be {NEEDS_HUMAN_LABEL!r}; valid: {sorted(_VALID_STATE_LABELS)}"
            )
        existing = [lbl.name for lbl in issue.labels]
        non_state = [name for name in existing if not _is_state_label(name)]
        issue.set_labels(*non_state, new_label)

    def comment_on_issue(self, issue, body: str) -> None:
        issue.create_comment(body)

    def get_repo(self, repo_full_name: str):
        return self._gh.get_repo(repo_full_name)

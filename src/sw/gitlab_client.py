import gitlab

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


class GitLabClient:
    def __init__(self, gl: gitlab.Gitlab):
        self._gl = gl

    @classmethod
    def from_env(cls, url: str, token: str) -> "GitLabClient":
        gl = gitlab.Gitlab(url=url, private_token=token)
        return cls(gl=gl)

    def set_state_label(self, issue, new_label: str) -> None:
        """Atomically replace any state labels with new_label.

        State labels = labels in {agent-ready, agent-working, agent-done,
        agent-failed, needs-human}. Other labels (e.g. bug, priority/high)
        are preserved.
        """
        if new_label not in _VALID_STATE_LABELS:
            raise ValueError(
                f"new_label {new_label!r} must start with {AGENT_LABEL_PREFIX} "
                f"or be {NEEDS_HUMAN_LABEL!r}; valid: {sorted(_VALID_STATE_LABELS)}"
            )
        non_state = [lbl for lbl in issue.labels if not _is_state_label(lbl)]
        issue.labels = [*non_state, new_label]
        issue.save()

    def comment_on_issue(self, issue, body: str) -> None:
        issue.notes.create({"body": body})

    def get_project(self, project_path: str):
        return self._gl.projects.get(project_path)

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CoderResult:
    success: bool
    mr_iid: int | None
    branch_name: str
    error: str = ""


def run_coder(*, project, issue_iid: int, issue_title: str) -> CoderResult:
    """Stub Coder: creates a branch, adds AGENT_LOG.md, opens draft MR.

    Real implementation will:
    - validate AC
    - call Claude Code with PRD/AC context
    - iterate until tests pass locally
    - write WHY into code comments (per spec §5.3)
    """
    branch_name = f"agent/issue-{issue_iid}"
    base = project.default_branch

    project.branches.create({"branch": branch_name, "ref": base})

    timestamp = datetime.now(timezone.utc).isoformat()
    content = f"# Agent Log\n\n- {timestamp}: stub coder ran for issue #{issue_iid}\n"
    project.commits.create(
        {
            "branch": branch_name,
            "commit_message": f"chore(stub): touched by Coder Agent for issue #{issue_iid}",
            "actions": [
                {
                    "action": "create",
                    "file_path": "AGENT_LOG.md",
                    "content": content,
                }
            ],
        }
    )

    mr = project.mergerequests.create(
        {
            "source_branch": branch_name,
            "target_branch": base,
            "title": f"Draft: stub for issue #{issue_iid} — {issue_title}",
            "description": f"Stub MR auto-generated for issue #{issue_iid}.\n\nCloses #{issue_iid}",
            "remove_source_branch": True,
        }
    )

    return CoderResult(success=True, mr_iid=mr.iid, branch_name=branch_name)

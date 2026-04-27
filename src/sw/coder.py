"""Real Coder Agent: orchestrates Claude Code to implement an Issue's AC.

Workflow:
1. Clone the target project into a temp dir.
2. Build a prompt from Issue body + AC + project context.
3. Invoke Claude Code (via claude_code_client).
4. Parse the result marker file.
5. On success: stage commits, push to agent branch, open draft MR.
6. On block: return CoderResult(success=False, blocker=...).
"""

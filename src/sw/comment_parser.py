import re
from io import StringIO

from ruamel.yaml import YAML

_YAML_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def extract_yaml_block(comment: str) -> dict | None:
    """Extract the first ```yaml fenced block from a comment.

    Returns parsed dict, or None if no block exists or YAML is malformed.
    """
    match = _YAML_FENCE_RE.search(comment)
    if not match:
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(match.group(1)))
    except Exception:
        return None


VALID_COMMANDS = {"start", "resume", "retry", "abort", "escalate"}

_COMMAND_RE = re.compile(r"^/agent\s+(\w+)\s*$", re.MULTILINE)


def extract_agent_command(comment: str) -> str | None:
    """Extract the last valid /agent <command> from a comment.

    Commands must appear at line start. Returns None if no valid command found.
    """
    matches = _COMMAND_RE.findall(comment)
    for cmd in reversed(matches):
        if cmd in VALID_COMMANDS:
            return cmd
    return None

"""Comment parsing: YAML block extraction + /agent slash commands (spec §10.3)."""

import re
from dataclasses import dataclass
from io import StringIO

from ruamel.yaml import YAML

_YAML_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def extract_yaml_block(comment: str) -> dict | None:
    """Extract the first ```yaml fenced block. Returns dict or None on missing/malformed."""
    match = _YAML_FENCE_RE.search(comment)
    if not match:
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(match.group(1)))
    except Exception:
        return None


# Per spec §10.3.
VALID_COMMANDS = {
    "start",
    "resume",
    "retry",
    "abort",
    "escalate",
    "decide",
    "replan",
}

# Commands that take an argument (rest-of-line).
COMMANDS_WITH_ARG = {"decide", "replan"}

# `/agent` must be preceded by start-of-line OR whitespace (so we ignore
# inline-code/quoted occurrences like `\`/agent resume\``). It does NOT
# need to be at the very start of a line — humans often write a short
# preface, e.g. "rebase main then /agent resume". The command + optional
# argument extend to end-of-line, matching the existing rest-of-line
# semantics for `decide <id>` / `replan [hint]`.
_COMMAND_RE = re.compile(
    r"(?:^|(?<=\s))/agent[ \t]+(\w+)(?:[ \t]+([^\n]*?))?[ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class AgentCommand:
    name: str
    arg: str | None = None  # for decide <id> / replan [hint]


def extract_agent_command(comment: str) -> AgentCommand | None:
    """Extract the last valid /agent command from a comment.

    Returns None if no valid command found. `decide` requires an argument;
    other commands ignore extra tokens.
    """
    matches = _COMMAND_RE.findall(comment)
    for name, arg in reversed(matches):
        if name not in VALID_COMMANDS:
            continue
        arg_clean = (arg or "").strip() or None
        if name == "decide" and not arg_clean:
            # /agent decide requires an id arg per spec §10.3
            continue
        if name not in COMMANDS_WITH_ARG:
            arg_clean = None
        return AgentCommand(name=name, arg=arg_clean)
    return None


def is_authorized(actor_login: str | None, authorized_users: list[str]) -> bool:
    """Whitelist check per spec §10.4. Empty list = no one (fail-closed)."""
    if not actor_login:
        return False
    return actor_login in authorized_users

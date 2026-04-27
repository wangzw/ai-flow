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

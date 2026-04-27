from io import StringIO

from ruamel.yaml import YAML

_TEMPLATE = """## 🛑 需要人类决策

{prose}

```yaml
{yaml_block}```

请在评论中明确选择，然后输入 `/agent resume`。
"""


def build_needs_human_comment(*, prose: str, agent_state: dict, decision: dict) -> str:
    """Build a double-layer needs-human comment per spec §4.1."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)

    payload = {
        "agent_state": agent_state,
        "decision": decision,
        "resume_instruction": "回复评论选择决策，然后输入 /agent resume",
    }
    buf = StringIO()
    yaml.dump(payload, buf)

    return _TEMPLATE.format(prose=prose, yaml_block=buf.getvalue())

"""Double-layer needs-human comment template (spec §10.2)."""

from io import StringIO

from ruamel.yaml import YAML

_TEMPLATE = """## 🛑 需要人类决策

{prose}

```yaml
{yaml_block}```

{resume_instruction}
"""

_DEFAULT_RESUME = (
    "请评论 `/agent decide <id>` 选择，或写自定义答案后 `/agent resume`，或 `/agent abort` 终止。"
)


def build_needs_human_comment(
    *,
    prose: str,
    agent_state: dict,
    decision: dict,
    resume_instruction: str = _DEFAULT_RESUME,
) -> str:
    """Build a double-layer needs-human comment per spec §10.2."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)

    payload = {
        "agent_state": agent_state,
        "decision": decision,
        "resume_instruction": resume_instruction,
    }
    buf = StringIO()
    yaml.dump(payload, buf)

    return _TEMPLATE.format(
        prose=prose, yaml_block=buf.getvalue(), resume_instruction=resume_instruction
    )


def build_ack_comment(*, command: str, accepted: bool, reason: str = "") -> str:
    """Bot acknowledgment per spec §10.4 (mandatory after any /agent command)."""
    if accepted:
        return f"✅ 收到 `/agent {command}`，已执行。"
    return f"❌ 拒绝 `/agent {command}`：{reason}"

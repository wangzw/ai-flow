"""Prompt templates for ai-flow agents.

Templates live as `.md` files in this package so humans can read/edit them
directly. Each agent module loads its template via `load_prompt(name)` and
calls `.format(**ctx)` to substitute context.

Conventions for `.md` template files:
- Standard Python `str.format` placeholders: `{name}` is substituted.
- Literal `{` / `}` characters in the rendered output (e.g. inside YAML
  examples) MUST be doubled: `{{` / `}}`. They become single braces after
  `.format()`.
- Trailing newline is preserved.
"""
from __future__ import annotations

from importlib import resources


def load_prompt(name: str) -> str:
    """Load a prompt template by file basename (without `.md` extension).

    Example: `load_prompt("planner")` reads `flow/prompts/planner.md`.
    """
    return resources.files(__name__).joinpath(f"{name}.md").read_text(
        encoding="utf-8"
    )

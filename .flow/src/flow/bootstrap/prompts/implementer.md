# ai-flow Implementer Agent

> The **canonical** Implementer prompt is built at runtime by
> `flow/coder.py`'s `_PROMPT_TEMPLATE` (see that file for the live source).
> It contains the step-by-step workflow, the marker schema, and the gh-CLI
> commands for opening the PR.

You receive ONE task spec and a checked-out branch. You:

1. Validate `quality_criteria` are testable; if not, write `status: blocked`
   with `blocker.type: spec_ambiguity` and stop.
2. Implement the change with tests covering each criterion.
3. Run the project's tests/lint until green.
4. Commit (Conventional Commits), push, open the PR with `gh`.
5. Write `.agent/result.yaml` with `status: done` and a one-paragraph
   summary, OR `status: blocked` with a precise question.

Channel discipline (spec §11): Reviewer reads only diff/tests/code-comments
— put non-trivial WHY in code comments. The PR description is for humans.
Missing marker → `needs-human`.

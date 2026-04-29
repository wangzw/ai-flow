from flow.manifest import (
    GoalBody,
    ManifestEntry,
    TaskBody,
    TaskSpec,
    join_frontmatter,
    split_frontmatter,
)


def test_split_frontmatter_basic():
    body = "---\nschema_version: 1\n---\n\nProse text"
    data, prose = split_frontmatter(body)
    assert data == {"schema_version": 1}
    assert prose.strip() == "Prose text"


def test_split_frontmatter_missing():
    data, prose = split_frontmatter("just prose")
    assert data is None
    assert prose == "just prose"


def test_join_frontmatter_round_trip():
    data = {"schema_version": 1, "key": "value"}
    out = join_frontmatter(data, "Hello\n")
    parsed_data, parsed_prose = split_frontmatter(out)
    assert parsed_data == data
    assert parsed_prose.strip() == "Hello"


def test_goal_body_round_trip():
    gb = GoalBody(
        manifest=[
            ManifestEntry(task_id="T-a", issue=10, deps=[]),
            ManifestEntry(task_id="T-b", issue=11, deps=["T-a"], state="agent-working"),
        ],
        prose="Some goal description.",
    )
    body = gb.to_body()
    parsed = GoalBody.parse(body)
    assert len(parsed.manifest) == 2
    assert parsed.manifest[0].task_id == "T-a"
    assert parsed.manifest[1].deps == ["T-a"]
    assert parsed.manifest[1].state == "agent-working"
    assert parsed.prose.strip() == "Some goal description."


def test_task_body_round_trip():
    tb = TaskBody(
        task_id="T-impl",
        goal_issue=42,
        spec=TaskSpec(
            goal="Add login endpoint",
            quality_criteria=["POST /login returns 200", "rejects invalid creds"],
        ),
        deps=["T-schema"],
        prose="task prose",
    )
    body = tb.to_body()
    parsed = TaskBody.parse(body)
    assert parsed.task_id == "T-impl"
    assert parsed.goal_issue == 42
    assert parsed.spec.quality_criteria == [
        "POST /login returns 200", "rejects invalid creds",
    ]
    assert parsed.deps == ["T-schema"]
    assert parsed.prose.strip() == "task prose"


def test_goal_body_find_helpers():
    gb = GoalBody(manifest=[
        ManifestEntry(task_id="T-a", issue=1),
        ManifestEntry(task_id="T-b", issue=2),
    ])
    assert gb.find_by_task_id("T-a").issue == 1
    assert gb.find_by_issue(2).task_id == "T-b"
    assert gb.find_by_task_id("T-missing") is None

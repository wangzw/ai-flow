import argparse
import os
import sys
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from sw.gitlab_client import GitLabClient


def load_labels_config(path: Path) -> list[dict]:
    yaml = YAML(typ="safe")
    data = yaml.load(StringIO(path.read_text()))
    return data["labels"]


def apply_labels(project, desired: list[dict]) -> None:
    """Sync labels to a GitLab project: create missing, update drifted."""
    existing = {label.name: label for label in project.labels.list(get_all=True)}

    for spec in desired:
        name = spec["name"]
        if name not in existing:
            project.labels.create(spec)
            continue
        lbl = existing[name]
        drift = lbl.color != spec["color"] or lbl.description != spec["description"]
        if drift:
            lbl.color = spec["color"]
            lbl.description = spec["description"]
            lbl.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="GitLab project path, e.g. 'group/repo'")
    parser.add_argument("--config", default="config/labels.yaml")
    parser.add_argument(
        "--gitlab-url", default=os.environ.get("CI_SERVER_URL", "https://gitlab.com")
    )
    parser.add_argument("--token", default=os.environ.get("GITLAB_API_TOKEN"))
    args = parser.parse_args(argv)

    if not args.token:
        parser.error("GITLAB_API_TOKEN env var or --token required")

    desired = load_labels_config(Path(args.config))
    client = GitLabClient.from_env(url=args.gitlab_url, token=args.token)
    project = client.get_project(args.project)
    apply_labels(project, desired)
    print(f"Applied {len(desired)} labels to {args.project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

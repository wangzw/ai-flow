from pathlib import Path
from unittest.mock import MagicMock

from sw.label_apply import apply_labels, load_labels_config


def test_load_labels_config(tmp_path: Path):
    cfg = tmp_path / "labels.yaml"
    cfg.write_text(
        """labels:
  - name: agent-ready
    color: "#1F75CB"
    description: "AC ready"
"""
    )
    labels = load_labels_config(cfg)
    assert labels == [{"name": "agent-ready", "color": "#1F75CB", "description": "AC ready"}]


def test_apply_labels_creates_missing():
    project = MagicMock()
    project.labels.list.return_value = []  # no existing
    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "x"}]

    apply_labels(project, desired)

    project.labels.create.assert_called_once_with(
        {"name": "agent-ready", "color": "#1F75CB", "description": "x"}
    )


def test_apply_labels_updates_existing_on_color_drift():
    existing = MagicMock()
    existing.name = "agent-ready"
    existing.color = "#000000"
    existing.description = "old"
    project = MagicMock()
    project.labels.list.return_value = [existing]

    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "new"}]
    apply_labels(project, desired)

    assert existing.color == "#1F75CB"
    assert existing.description == "new"
    existing.save.assert_called_once()
    project.labels.create.assert_not_called()


def test_apply_labels_no_op_when_synced():
    existing = MagicMock()
    existing.name = "agent-ready"
    existing.color = "#1F75CB"
    existing.description = "AC ready"
    project = MagicMock()
    project.labels.list.return_value = [existing]

    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "AC ready"}]
    apply_labels(project, desired)

    existing.save.assert_not_called()
    project.labels.create.assert_not_called()

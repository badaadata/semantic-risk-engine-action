import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.build_payload import build_payload

MINIMAL_MANIFEST = {
    "metadata": {"project_name": "my_project"},
    "nodes": {},
    "child_map": {},
}


def _make_structure(tmp_path, base_sql=None, head_sql=None, model_path="models/marts/fct_revenue.sql"):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(MINIMAL_MANIFEST))

    base_dir = tmp_path / "base_compiled"
    head_dir = tmp_path / "head_compiled"

    if base_sql is not None:
        p = base_dir / "my_project" / model_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(base_sql)

    if head_sql is not None:
        p = head_dir / "my_project" / model_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(head_sql)

    return base_dir, head_dir, manifest_file


def _write_changed(tmp_path, lines):
    changed_file = tmp_path / "changed.txt"
    changed_file.write_text("\n".join(lines))
    return changed_file


def test_basic_payload_built(tmp_path):
    base_dir_a, head_dir_a, _ = _make_structure(
        tmp_path,
        base_sql="SELECT id FROM orders WHERE status = 'active'",
        head_sql="SELECT id FROM orders",
        model_path="models/marts/fct_revenue.sql",
    )
    # Second model
    model_b = "models/marts/stg_orders.sql"
    b_path = base_dir_a / "my_project" / model_b
    b_path.parent.mkdir(parents=True, exist_ok=True)
    b_path.write_text("SELECT * FROM raw.orders")
    h_path = head_dir_a / "my_project" / model_b
    h_path.parent.mkdir(parents=True, exist_ok=True)
    h_path.write_text("SELECT id, amount FROM raw.orders")

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(MINIMAL_MANIFEST))

    changed_file = _write_changed(
        tmp_path,
        ["models/marts/fct_revenue.sql", "models/marts/stg_orders.sql"],
    )

    payload = build_payload(str(changed_file), str(base_dir_a), str(head_dir_a), str(manifest_file), "snowflake")

    assert payload["dialect"] == "snowflake"
    assert len(payload["models"]) == 2
    names = {m["model_name"] for m in payload["models"]}
    assert names == {"fct_revenue", "stg_orders"}
    rev = next(m for m in payload["models"] if m["model_name"] == "fct_revenue")
    assert "status = 'active'" in rev["old_sql"]
    assert rev["new_sql"] == "SELECT id FROM orders"


def test_new_model_skipped(tmp_path, capsys):
    base_dir, head_dir, manifest_file = _make_structure(
        tmp_path,
        base_sql=None,
        head_sql="SELECT 1",
    )
    changed_file = _write_changed(tmp_path, ["models/marts/fct_revenue.sql"])

    payload = build_payload(str(changed_file), str(base_dir), str(head_dir), str(manifest_file), "snowflake")

    assert payload["models"] == []
    captured = capsys.readouterr()
    assert "new model" in captured.err.lower()


def test_head_missing_skipped(tmp_path, capsys):
    base_dir, head_dir, manifest_file = _make_structure(
        tmp_path,
        base_sql="SELECT 1",
        head_sql=None,
    )
    changed_file = _write_changed(tmp_path, ["models/marts/fct_revenue.sql"])

    payload = build_payload(str(changed_file), str(base_dir), str(head_dir), str(manifest_file), "snowflake")

    assert payload["models"] == []
    captured = capsys.readouterr()
    assert captured.err.strip() != ""  # some diagnostic message printed


def test_empty_changed_file(tmp_path):
    base_dir, head_dir, manifest_file = _make_structure(tmp_path, base_sql="SELECT 1", head_sql="SELECT 1")
    changed_file = _write_changed(tmp_path, [])

    payload = build_payload(str(changed_file), str(base_dir), str(head_dir), str(manifest_file), "bigquery")

    assert payload["models"] == []
    assert payload["dialect"] == "bigquery"


def test_non_sql_lines_ignored(tmp_path):
    base_dir, head_dir, manifest_file = _make_structure(tmp_path, base_sql="SELECT 1", head_sql="SELECT 1")
    changed_file = _write_changed(
        tmp_path,
        ["models/schema.yml", "", "  ", "models/sources.yml"],
    )

    payload = build_payload(str(changed_file), str(base_dir), str(head_dir), str(manifest_file), "duckdb")

    assert payload["models"] == []

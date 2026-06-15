"""Build the API request payload from compiled dbt SQL files."""
import argparse
import json
import re
import sys
from pathlib import Path


def _normalize_for_comparison(sql: str) -> str:
    """Collapse all whitespace variants to single space for cross-platform comparison.

    Handles:
    - Windows (\\r\\n), Unix (\\n), old macOS (\\r) line endings
    - Tabs, multiple spaces, mixed indentation
    - Leading/trailing whitespace
    """
    return re.sub(r"\s+", " ", sql).strip()


def build_payload(
    changed_file: str,
    base_dir: str,
    head_dir: str,
    manifest_file: str,
    dialect: str,
    skipped_file: str | None = None,
) -> dict:
    changed_path = Path(changed_file)
    base = Path(base_dir)
    head = Path(head_dir)

    with open(manifest_file) as f:
        manifest = json.load(f)
    project_name = manifest["metadata"]["project_name"]

    lines = changed_path.read_text().splitlines()
    models = []
    new_models = []
    deleted_models = []

    for line in lines:
        line = line.strip()
        if not line or not line.endswith(".sql"):
            continue

        model_name = Path(line).stem
        base_sql_path = base / project_name / line
        head_sql_path = head / project_name / line

        if not head_sql_path.exists():
            print(f"INFO: {model_name} not found on PR branch — model deleted", file=sys.stderr)
            deleted_models.append(model_name)
            continue

        if not base_sql_path.exists():
            print(f"INFO: {model_name} has no base — new model added", file=sys.stderr)
            new_models.append(model_name)
            continue

        old_sql = base_sql_path.read_text()
        new_sql = head_sql_path.read_text()

        if _normalize_for_comparison(old_sql) == _normalize_for_comparison(new_sql):
            print(f"INFO: {model_name} compiled SQL is identical old→new — skipping", file=sys.stderr)
            continue

        models.append({
            "model_name": model_name,
            "old_sql": old_sql,
            "new_sql": new_sql,
        })

    if skipped_file:
        Path(skipped_file).write_text(
            json.dumps({"new": new_models, "deleted": deleted_models}, indent=2)
        )

    return {"models": models, "dialect": dialect}


def main():
    parser = argparse.ArgumentParser(description="Build API payload from compiled dbt SQL files.")
    parser.add_argument("--changed", required=True, help="File listing changed model paths (one per line)")
    parser.add_argument("--base-dir", required=True, help="Path to base branch compiled dir")
    parser.add_argument("--head-dir", required=True, help="Path to head branch compiled dir")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--dialect", required=True, help="SQL dialect (snowflake, bigquery, etc.)")
    parser.add_argument("--skipped", default=None, help="Path to write new/deleted model names JSON")
    args = parser.parse_args()

    payload = build_payload(
        args.changed, args.base_dir, args.head_dir, args.manifest, args.dialect,
        skipped_file=args.skipped,
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

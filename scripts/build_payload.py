"""Build the API request payload from compiled dbt SQL files."""
import argparse
import json
import sys
from pathlib import Path


def build_payload(changed_file: str, base_dir: str, head_dir: str, manifest_file: str, dialect: str) -> dict:
    changed_path = Path(changed_file)
    base = Path(base_dir)
    head = Path(head_dir)

    with open(manifest_file) as f:
        manifest = json.load(f)
    project_name = manifest["metadata"]["project_name"]

    lines = changed_path.read_text().splitlines()
    models = []

    for line in lines:
        line = line.strip()
        if not line or not line.endswith(".sql"):
            continue

        model_name = Path(line).stem
        base_sql_path = base / project_name / line
        head_sql_path = head / project_name / line

        if not head_sql_path.exists():
            print(f"WARNING: compiled SQL not found for {model_name} on PR branch — skipping", file=sys.stderr)
            continue

        if not base_sql_path.exists():
            print(f"INFO: {model_name} is a new model — skipping (no base to compare)", file=sys.stderr)
            continue

        models.append({
            "model_name": model_name,
            "old_sql": base_sql_path.read_text(),
            "new_sql": head_sql_path.read_text(),
        })

    return {"models": models, "dialect": dialect}


def main():
    parser = argparse.ArgumentParser(description="Build API payload from compiled dbt SQL files.")
    parser.add_argument("--changed", required=True, help="File listing changed model paths (one per line)")
    parser.add_argument("--base-dir", required=True, help="Path to base branch compiled dir")
    parser.add_argument("--head-dir", required=True, help="Path to head branch compiled dir")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--dialect", required=True, help="SQL dialect (snowflake, bigquery, etc.)")
    args = parser.parse_args()

    payload = build_payload(args.changed, args.base_dir, args.head_dir, args.manifest, args.dialect)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

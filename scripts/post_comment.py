"""Format API response and post/update a GitHub PR comment."""
import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import deque

MARKER = "<!-- semantic-risk-engine -->"

SEVERITY_EMOJI = {
    "high": "🔴",
    "medium": "🟡",
    "low": "🟢",
    "info": "ℹ️",
}

CHANGE_EMOJI = {
    "high": "❌",
    "medium": "⚠️",
    "low": "✅",
    "info": "ℹ️",
}


def _build_downstream_map(manifest: dict) -> dict:
    """BFS over child_map to count all downstream model nodes per model."""
    child_map = manifest.get("child_map", {})
    counts = {}

    for node_key in child_map:
        if not node_key.startswith("model."):
            continue
        model_name = node_key.split(".")[-1]
        visited = set()
        queue = deque([node_key])
        while queue:
            current = queue.popleft()
            for child in child_map.get(current, []):
                if child not in visited and child.startswith("model."):
                    visited.add(child)
                    queue.append(child)
        counts[model_name] = len(visited)

    return counts


def _build_downstream_names_map(manifest: dict) -> dict:
    """BFS over child_map to collect downstream model bare names per model."""
    child_map = manifest.get("child_map", {})
    names_map = {}

    for node_key in child_map:
        if not node_key.startswith("model."):
            continue
        model_name = node_key.split(".")[-1]
        visited = set()
        queue = deque([node_key])
        while queue:
            current = queue.popleft()
            for child in child_map.get(current, []):
                if child not in visited and child.startswith("model."):
                    visited.add(child)
                    queue.append(child)
        names_map[model_name] = sorted(child.split(".")[-1] for child in visited)

    return names_map


def _build_criticality_map(manifest: dict) -> dict:
    """Return {bare_model_name: True} for every model flagged semantic_risk_critical.

    Tolerant of placement differences across dbt versions: config.meta, node.meta,
    node.tags, and config.tags are all checked.
    """
    nodes = manifest.get("nodes", {})
    critical = {}

    for node_key, node in nodes.items():
        if not node_key.startswith("model."):
            continue
        model_name = node.get("name") or node_key.split(".")[-1]

        config = node.get("config") or {}
        config_meta = config.get("meta") or {}
        meta = node.get("meta") or {}
        tags = node.get("tags") or []
        config_tags = config.get("tags") or []

        is_critical = (
            bool(config_meta.get("semantic_risk_critical"))
            or bool(meta.get("semantic_risk_critical"))
            or "semantic_risk_critical" in tags
            or "semantic_risk_critical" in config_tags
        )
        if is_critical:
            critical[model_name] = True

    return critical


def _downstream_details_block(model_name: str, downstream_names_map: dict) -> str:
    names = downstream_names_map.get(model_name, [])
    if not names:
        return ""
    names_list = "\n".join(f"- `{n}`" for n in names)
    return (
        f"\n<details>\n<summary>{len(names)} downstream model(s) may be affected</summary>\n\n"
        f"{names_list}\n\n</details>\n"
    )


def _model_cell(model_name: str, criticality_map: dict) -> str:
    if criticality_map.get(model_name):
        return f"⭐ `{model_name}`"
    return f"`{model_name}`"


def _has_risk(result: dict) -> bool:
    return any(result.get(level) for level in ("high", "medium", "low", "info"))


def _format_severity_block(label: str, items: list) -> str:
    if not items:
        return ""
    emoji = SEVERITY_EMOJI.get(label.lower(), "")
    lines = [f"**{emoji} {label.upper()}**\n"]
    for item in items:
        identifier = item.get("identifier", "")
        entity = item.get("entity", "")
        change_type = item.get("change_type", "")
        reason = item.get("reason", "")
        old_val = item.get("old_value")
        new_val = item.get("new_value")

        line = f"- `{entity} {change_type}` — `{identifier}`\n  {reason}"
        if old_val:
            line += f"\n  removed: `{old_val}`"
        if new_val:
            line += f"\n  added: `{new_val}`"
        lines.append(line)

    return "\n".join(lines) + "\n"


def format_comment(response: dict, manifest: dict, sha: str = "", skipped: dict | None = None, api_base_url: str = "") -> str:
    downstream_map = _build_downstream_map(manifest)
    downstream_names_map = _build_downstream_names_map(manifest)
    criticality_map = _build_criticality_map(manifest)
    results = response.get("results", [])
    # Critical models with a risk change are surfaced first.
    results = sorted(
        results,
        key=lambda r: 0 if criticality_map.get(r.get("model_name")) and _has_risk(r) else 1,
    )
    request_id = response.get("request_id", "")
    skipped = skipped or {}
    new_models = skipped.get("new", [])
    deleted_models = skipped.get("deleted", [])

    total_high = response.get("models_with_high_risk", 0) + len(deleted_models)

    feedback_footer = ""
    if request_id and api_base_url:
        base = api_base_url.rstrip("/").removesuffix("/v1")
        feedback_footer = (
            "\n\n---\n"
            "**Was this risk assessment accurate?**  \n"
            f"[👍 Yes]({base}/feedback/{request_id}?vote=up) · "
            f"[👎 No]({base}/feedback/{request_id}?vote=down) · "
            f"[💬 Leave a comment]({base}/feedback/{request_id})"
        )

    # Build summary table rows
    table_rows = []
    details_blocks = []

    # Deleted models — HIGH risk, no API result
    for model_name in deleted_models:
        downstream = downstream_map.get(model_name, 0)
        table_rows.append(
            f"| {_model_cell(model_name, criticality_map)} | 🔴 DELETED | — | — | — | "
            f"{downstream if downstream else '—'} |"
        )
        critical_badge = ""
        if criticality_map.get(model_name):
            critical_badge = " · **⭐ MODEL MARKED AS CRITICAL**"
        details_blocks.append(
            f"<details>\n<summary><code>{model_name}</code> — DELETED{critical_badge}</summary>\n\n"
            "**🔴 HIGH** — Model removed from the project. All downstream consumers of this model will break.\n"
            f"{_downstream_details_block(model_name, downstream_names_map)}\n</details>\n"
        )

    clean_models: list[str] = []

    for result in results:
        model_name = result.get("model_name", "unknown")
        has_error = result.get("has_error", False)
        error_msg = result.get("error_message", "")

        if has_error:
            downstream = downstream_map.get(model_name, 0)
            table_rows.append(
                f"| {_model_cell(model_name, criticality_map)} | COMPILE ERROR | — | — | — | "
                f"{downstream if downstream else '—'} |"
            )
            critical_badge = ""
            if criticality_map.get(model_name):
                critical_badge = " · **⭐ MODEL MARKED AS CRITICAL**"
            details_blocks.append(
                f"<details>\n<summary><code>{model_name}</code> — COMPILE ERROR{critical_badge}</summary>\n\n"
                f"```\n{error_msg}\n```\n"
                f"{_downstream_details_block(model_name, downstream_names_map)}\n</details>\n"
            )
            continue

        high_items = result.get("high", [])
        medium_items = result.get("medium", [])
        low_items = result.get("low", [])
        info_items = result.get("info", [])

        downstream = downstream_map.get(model_name, 0)

        def fmt_count(items, level):
            return f"{CHANGE_EMOJI[level]} {len(items)}" if items else "—"

        has_any = any([high_items, medium_items, low_items, info_items])

        if has_any:
            table_rows.append(
                f"| {_model_cell(model_name, criticality_map)} | {fmt_count(high_items, 'high')} | "
                f"{fmt_count(medium_items, 'medium')} | {fmt_count(low_items, 'low')} | "
                f"{fmt_count(info_items, 'info')} | {downstream if downstream else '—'} |"
            )
        else:
            clean_models.append((model_name, downstream))

        if has_any:
            parts = []
            if high_items:
                parts.append(f"{len(high_items)} HIGH")
            if medium_items:
                parts.append(f"{len(medium_items)} MEDIUM")
            if low_items:
                parts.append(f"{len(low_items)} LOW")
            if info_items:
                parts.append(f"{len(info_items)} INFO")
            summary_line = ", ".join(parts)
            if criticality_map.get(model_name):
                summary_line += " · **⭐ MODEL MARKED AS CRITICAL**"

            detail_body = ""
            for level in ("high", "medium", "low", "info"):
                items = result.get(level, [])
                block = _format_severity_block(level, items)
                if block:
                    detail_body += block + "\n"

            details_blocks.append(
                f"<details>\n<summary><code>{model_name}</code> — {summary_line}</summary>\n\n"
                f"{detail_body}{_downstream_details_block(model_name, downstream_names_map)}"
                "</details>\n"
            )

    sha_suffix = f" · `{sha[:7]}`" if sha else ""
    # New models — INFO, no base to compare
    for model_name in new_models:
        table_rows.append(
            f"| `{model_name}` | — | — | — | ℹ️ NEW | — |"
        )

    header = (
        f"{MARKER}\n"
        f"## 🔍 Semantic SQL Risk Check{sha_suffix}\n\n"
    )

    if not results and not new_models and not deleted_models:
        return f"{header}No SQL model changes were analyzed.\n" + feedback_footer

    table = (
        "| Model | 🔴 HIGH | 🟡 MEDIUM | 🟢 LOW | ℹ️ INFO | Downstream |\n"
        "|-------|---------|----------|--------|---------|------------|\n"
        + "\n".join(table_rows)
        + "\n\n"
    )

    details_section = "\n".join(details_blocks) + "\n" if details_blocks else ""

    clean_section = ""
    if clean_models:
        parts = []
        for m, ds in clean_models:
            entry = f"`{m}`"
            if ds:
                entry += f" ({ds} downstream)"
            parts.append(entry)
        names = ", ".join(parts)
        clean_section = f"✅ **No risk changes detected** in: {names}\n\n"

    # Footer — deleted models count as HIGH
    total_medium = sum(len(r.get("medium", [])) for r in results)
    total_low = sum(len(r.get("low", [])) for r in results)

    if total_high > 0:
        downstream_warnings = []
        for result in results:
            model_name = result.get("model_name", "")
            if result.get("high"):
                d = downstream_map.get(model_name, 0)
                if d:
                    downstream_warnings.append(
                        f"{d} downstream model(s) may be affected by changes in `{model_name}`."
                    )

        footer = f"---\n⚠️ **{total_high} model(s) have HIGH risk changes. Review before merging.**"
        if downstream_warnings:
            footer += "\n" + "\n".join(downstream_warnings)
    elif total_medium > 0 or total_low > 0:
        footer = "---\n🟡 **No high-risk changes, but medium/low-risk changes detected. Review recommended.**"
    else:
        footer = "---\n✅ No significant risk changes detected."

    critical_affected = [
        r.get("model_name", "") for r in results
        if criticality_map.get(r.get("model_name")) and _has_risk(r)
    ] + [m for m in deleted_models if criticality_map.get(m)]
    if critical_affected:
        names = ", ".join(f"`{m}`" for m in critical_affected)
        footer += f"\n🔴 **Critical model(s) affected:** {names}. Review before merging."

    return header + table + details_section + clean_section + footer + feedback_footer


def _github_request(url: str, method: str, token: str, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def find_existing_comment(token: str, repo: str, pr_number: int):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments?per_page=100"
    comments = _github_request(url, "GET", token)
    for comment in comments:
        if MARKER in comment.get("body", ""):
            return comment["id"]
    return None


def post_or_update_comment(body: str, token: str, repo: str, pr_number: int):
    existing_id = find_existing_comment(token, repo, pr_number)
    if existing_id:
        url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        result = _github_request(url, "PATCH", token, data={"body": body})
        print(f"Updated comment {result['id']}")
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        result = _github_request(url, "POST", token, data={"body": body})
        print(f"Posted comment {result['id']}")


def main():
    parser = argparse.ArgumentParser(description="Format API response and post/update GitHub PR comment.")
    parser.add_argument("--response", required=True, help="Path to API response JSON")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--token", required=True, help="GitHub token")
    parser.add_argument("--repo", required=True, help="owner/repo string")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--sha", default="", help="HEAD commit SHA (optional, shown in comment header)")
    parser.add_argument("--skipped", default=None, help="Path to skipped models JSON (new/deleted)")
    parser.add_argument("--api-base-url", default="", help="API base URL (used to build feedback footer links)")
    args = parser.parse_args()

    with open(args.response) as f:
        response = json.load(f)
    with open(args.manifest) as f:
        manifest = json.load(f)

    skipped = {}
    if args.skipped:
        try:
            with open(args.skipped) as f:
                skipped = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # skipped file is optional — missing is fine

    body = format_comment(response, manifest, sha=args.sha, skipped=skipped, api_base_url=args.api_base_url)
    post_or_update_comment(body, args.token, args.repo, args.pr)


if __name__ == "__main__":
    main()

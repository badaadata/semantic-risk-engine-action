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


def format_comment(response: dict, manifest: dict) -> str:
    downstream_map = _build_downstream_map(manifest)
    results = response.get("results", [])

    total_high = response.get("models_with_high_risk", 0)

    # Build summary table rows
    table_rows = []
    details_blocks = []

    for result in results:
        model_name = result.get("model_name", "unknown")
        has_error = result.get("has_error", False)
        error_msg = result.get("error_message", "")

        if has_error:
            downstream = downstream_map.get(model_name, 0)
            table_rows.append(
                f"| `{model_name}` | COMPILE ERROR | — | — | — | {downstream if downstream else '—'} |"
            )
            details_blocks.append(
                f"<details>\n<summary><code>{model_name}</code> — COMPILE ERROR</summary>\n\n"
                f"```\n{error_msg}\n```\n\n</details>\n"
            )
            continue

        high_items = result.get("high", [])
        medium_items = result.get("medium", [])
        low_items = result.get("low", [])
        info_items = result.get("info", [])

        downstream = downstream_map.get(model_name, 0)

        def fmt_count(items, level):
            return f"{CHANGE_EMOJI[level]} {len(items)}" if items else "—"

        table_rows.append(
            f"| `{model_name}` | {fmt_count(high_items, 'high')} | "
            f"{fmt_count(medium_items, 'medium')} | {fmt_count(low_items, 'low')} | "
            f"{fmt_count(info_items, 'info')} | {downstream if downstream else '—'} |"
        )

        if any([high_items, medium_items, low_items, info_items]):
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

            detail_body = ""
            for level in ("high", "medium", "low", "info"):
                items = result.get(level, [])
                block = _format_severity_block(level, items)
                if block:
                    detail_body += block + "\n"

            details_blocks.append(
                f"<details>\n<summary><code>{model_name}</code> — {summary_line}</summary>\n\n"
                f"{detail_body}</details>\n"
            )

    header = (
        f"{MARKER}\n"
        "## 🔍 Semantic SQL Risk Check\n\n"
    )

    if not results:
        return (
            f"{header}"
            "No SQL model changes were analyzed.\n"
        )

    table = (
        "| Model | 🔴 HIGH | 🟡 MEDIUM | 🟢 LOW | ℹ️ INFO | Downstream |\n"
        "|-------|---------|----------|--------|---------|------------|\n"
        + "\n".join(table_rows)
        + "\n\n"
    )

    details_section = "\n".join(details_blocks) + "\n" if details_blocks else ""

    # Footer
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

    return header + table + details_section + footer


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
    args = parser.parse_args()

    with open(args.response) as f:
        response = json.load(f)
    with open(args.manifest) as f:
        manifest = json.load(f)

    body = format_comment(response, manifest)
    post_or_update_comment(body, args.token, args.repo, args.pr)


if __name__ == "__main__":
    main()

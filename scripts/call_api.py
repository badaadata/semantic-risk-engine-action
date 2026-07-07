"""POST the payload JSON to the Semantic Risk Engine API.

Shadow mode: an analysis failure (bad key, API down, timeout, rate limit)
must never fail the build. This script always exits 0. On failure it prints
a GitHub Actions ::warning::/::error:: annotation to stderr (so it shows up
in the job log without corrupting the JSON on stdout) and writes a sentinel
JSON object to stdout so downstream steps can detect and report the skip.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# HTTP codes that indicate a clear user misconfiguration (bad/missing API
# key) rather than a transient/environmental failure — worth an ::error::
# annotation instead of a ::warning::. Still never fails the build.
MISCONFIGURATION_CODES = {401, 403}


def call_api(payload_path: str, api_url: str, api_key: str) -> dict:
    """POST the payload. Always returns a dict; never raises or exits.

    Success: {"ok": True, "body": <raw response text>}
    Failure: {"ok": False, "message": <human-readable reason>, "annotation": "error"|"warning"}
    """
    with open(payload_path, "rb") as f:
        body = f.read()

    req = urllib.request.Request(
        url=api_url,
        data=body,
        method="POST",
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return {"ok": True, "body": resp.read().decode()}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        if e.code in MISCONFIGURATION_CODES:
            return {
                "ok": False,
                "message": f"authentication failed (HTTP {e.code}) — check your API key secret: {error_body}",
                "annotation": "error",
            }
        return {
            "ok": False,
            "message": f"API error {e.code}: {error_body}",
            "annotation": "warning",
        }
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"cannot reach API: {e.reason}", "annotation": "warning"}


def main():
    parser = argparse.ArgumentParser(description="POST payload to Semantic Risk Engine API.")
    parser.add_argument("--payload", required=True, help="Path to payload JSON file")
    parser.add_argument("--api-url", required=True, help="Full API URL (e.g. https://api.badaadata.com/v1/analyze)")
    parser.add_argument("--api-key", required=True, help="API key (sre_...)")
    args = parser.parse_args()

    result = call_api(args.payload, args.api_url, args.api_key)

    if result["ok"]:
        print(result["body"])
        return

    print(f"::{result['annotation']}::Semantic Risk Check: {result['message']}", file=sys.stderr)
    print(json.dumps({"analysis_failed": True, "message": result["message"]}))


if __name__ == "__main__":
    main()

"""POST the payload JSON to the Semantic Risk Engine API."""
import argparse
import sys
import urllib.error
import urllib.request


def call_api(payload_path: str, api_url: str, api_key: str) -> str:
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
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"API error {e.code}: {error_body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach API: {e.reason}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="POST payload to Semantic Risk Engine API.")
    parser.add_argument("--payload", required=True, help="Path to payload JSON file")
    parser.add_argument("--api-url", required=True, help="Full API URL (e.g. https://api.badaadata.com/v1/analyze)")
    parser.add_argument("--api-key", required=True, help="API key (sre_...)")
    args = parser.parse_args()

    result = call_api(args.payload, args.api_url, args.api_key)
    print(result)


if __name__ == "__main__":
    main()

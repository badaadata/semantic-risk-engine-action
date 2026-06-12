# Semantic SQL Risk Check — GitHub Action

Automatically detects breaking semantic changes in your dbt SQL models and posts a risk summary as a PR comment before anything merges.

---

## What it does

When a pull request modifies files in `models/`, this action compiles the changed models on both the PR branch and the base branch, sends the compiled SQL to the [Semantic Risk Engine API](https://badaadata.com), and posts a structured comment listing any high, medium, or low-severity changes detected.

Your Snowflake (or other warehouse) credentials **never leave your runner** — only the compiled SQL is sent to the API.

---

## Prerequisites

- dbt installed in your CI environment (`dbt-snowflake`, `dbt-bigquery`, etc.)
- A Semantic Risk Engine API key (`sre_...`) from [badaadata.com](https://badaadata.com)
- GitHub Actions enabled on your repository

---

## Setup

### Step 1 — Add the workflow file

Create `.github/workflows/semantic-risk.yml` in your dbt project:

```yaml
name: Semantic SQL Risk Check

on:
  pull_request:
    paths:
      - 'models/**/*.sql'

jobs:
  semantic-risk:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # required — needs full git history for diff

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dbt
        run: pip install dbt-snowflake   # change for your warehouse

      - name: Semantic SQL Risk Check
        uses: badaadata/semantic-risk-engine-action@v1
        with:
          api_key:          ${{ secrets.SEMANTIC_RISK_API_KEY }}
          dialect:          snowflake      # snowflake | bigquery | databricks | duckdb
          dbt_profiles_dir: .             # where profiles.yml lives
          dbt_target:       ci            # your CI target in profiles.yml
        env:
          # Snowflake credentials — stay on your runner, never sent to our API
          DBT_SNOWFLAKE_ACCOUNT:   ${{ secrets.SNOWFLAKE_ACCOUNT }}
          DBT_SNOWFLAKE_USER:      ${{ secrets.SNOWFLAKE_USER }}
          DBT_SNOWFLAKE_PASSWORD:  ${{ secrets.SNOWFLAKE_PASSWORD }}
          DBT_SNOWFLAKE_DATABASE:  ${{ secrets.SNOWFLAKE_DATABASE }}
          DBT_SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
          DBT_SNOWFLAKE_SCHEMA:    ${{ secrets.SNOWFLAKE_SCHEMA }}
```

### Step 2 — Add the API key secret

Go to your repository: **Settings → Secrets and variables → Actions → New repository secret**

Add a secret named `SEMANTIC_RISK_API_KEY` with your `sre_...` key from [badaadata.com](https://badaadata.com).

### Step 3 — Open a PR

Open a pull request that changes any file under `models/`. A comment will appear automatically with the risk assessment.

---

## What the comment looks like

```
## 🔍 Semantic SQL Risk Check

| Model | 🔴 HIGH | 🟡 MEDIUM | 🟢 LOW | ℹ️ INFO | Downstream |
|-------|---------|----------|--------|---------|------------|
| `fct_revenue` | ❌ 1 | ⚠️ 2 | — | — | 14 |
| `stg_orders` | — | — | ✅ 1 | — | 3 |

<details>
<summary><code>fct_revenue</code> — 1 HIGH, 2 MEDIUM</summary>

**🔴 HIGH**

- `FILTER REMOVED` — `WHERE:status`
  A WHERE filter was removed. Queries may return more rows than expected.
  removed: `status = 'active'`

</details>

---
⚠️ 1 HIGH risk change(s) detected. Review before merging.
14 downstream models may be affected by changes in fct_revenue.
```

The comment is updated in-place on each new push to the PR — no duplicate comments.

---

## Inputs reference

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api_key` | yes | — | Your `sre_...` API key from badaadata.com |
| `dialect` | no | `snowflake` | SQL dialect passed to the engine |
| `dbt_profiles_dir` | no | `.` | Directory containing `profiles.yml` |
| `dbt_target` | no | `ci` | dbt target name to use for compilation |
| `api_base_url` | no | `https://api.badaadata.com` | API base URL (override for local/ngrok testing) |

---

## How it works

1. Detects which `.sql` files under `models/` changed in the PR using `git diff`
2. Compiles only those models (`dbt compile --select ...`) on the PR branch and the base branch
3. Sends the compiled SQL to the Semantic Risk Engine API — your warehouse credentials never leave your runner
4. Posts (or updates) a structured PR comment with the risk breakdown

---

## Supported warehouses

Snowflake, BigQuery, Databricks, DuckDB, Redshift — any warehouse supported by dbt.

---

## Troubleshooting

**"No SQL model changes detected"**
Check that your `paths:` filter in the workflow YAML matches where your `.sql` models actually live. The default `models/**/*.sql` covers the standard dbt project layout.

**"dbt compile failed"**
Verify that `dbt_target` matches a valid target in your `profiles.yml`. The action automatically retries with `--empty` (no warehouse connection needed) as a fallback. If you don't have a CI target, add one with `type: snowflake` and empty credentials — the `--empty` flag compiles without executing.

**"API error 401"**
Check that the `SEMANTIC_RISK_API_KEY` secret is set correctly in your repository settings (Settings → Secrets → Actions). Make sure there are no leading/trailing spaces in the secret value.

**"API error 402 / quota exceeded"**
Your plan limit has been reached. Contact [support@badaadata.com](mailto:support@badaadata.com) to upgrade.

**New models are skipped**
If a model was added in this PR (it doesn't exist on the base branch), it is skipped with an INFO log — there is no base SQL to compare against. This is expected behavior.

---

## Testing locally

After the API server is running locally with ngrok:

```bash
# 1. Simulate a changed models file
echo "models/marts/fct_revenue.sql" > /tmp/test_changed.txt

# 2. Build a test payload manually
python3 scripts/build_payload.py \
  --changed /tmp/test_changed.txt \
  --base-dir /tmp/sre_base_compiled \
  --head-dir /tmp/sre_head_compiled \
  --manifest /tmp/sre_manifest.json \
  --dialect snowflake \
  > /tmp/test_payload.json

# 3. Call the API (use your ngrok URL)
python3 scripts/call_api.py \
  --payload /tmp/test_payload.json \
  --api-url https://abc123.ngrok-free.app/v1/analyze \
  --api-key sre_YOUR_KEY \
  > /tmp/test_response.json

# 4. Preview the formatted comment (without posting to GitHub)
python3 -c "
import json
from scripts.post_comment import format_comment
response = json.load(open('/tmp/test_response.json'))
manifest = json.load(open('/tmp/sre_manifest.json'))
print(format_comment(response, manifest))
"
```

To override the API URL in the action itself, pass `api_base_url` as an input:

```yaml
- uses: badaadata/semantic-risk-engine-action@v1
  with:
    api_key:     ${{ secrets.SEMANTIC_RISK_API_KEY }}
    api_base_url: https://abc123.ngrok-free.app
```

---

## License

MIT — see [LICENSE](LICENSE).

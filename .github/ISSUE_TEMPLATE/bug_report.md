---
name: Bug report
about: Something about the action itself isn't working (setup, comment formatting, a crash)
title: ""
labels: bug
assignees: ""
---

**What happened**

A clear description of what went wrong.

**Workflow file**

Paste the `uses: badaadata/semantic-risk-engine-action@...` step from your workflow
(redact secrets — the `api_key:` line itself is enough, you don't need the value).

**Action log**

Paste the relevant part of the failing step's log. If it's a bad verdict rather than a
crash, use the 👎 feedback link in the PR comment instead — that routes to the analysis
engine, not this repo.

**Expected behavior**

What you expected to happen instead.

**Environment**

- dbt version:
- Warehouse / dialect:
- `dialect` input value:

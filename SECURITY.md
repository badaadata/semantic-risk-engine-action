# Security Policy

## Reporting a Vulnerability

If you find a security issue in this action (the public client) — script injection,
secret exposure, a way to make it exfiltrate more than the compiled SQL it documents, or
anything else — please report it privately rather than opening a public issue.

**Contact:** info@badaadata.com (subject: "Security report: semantic-risk-engine-action")

Please include:

- What you found and why it's a security issue, not just a bug
- Steps to reproduce, or a proof of concept
- The version/commit you tested against

We'll acknowledge your report and let you know a rough timeline for a fix. We don't
currently run a paid bug bounty, but we credit reporters (with permission) in the
release notes that ship the fix.

## Scope

This repository is the thin client that runs in your CI: it compiles SQL locally, sends
compiled SQL and minimal PR metadata to the Semantic Risk Engine API, and posts a PR
comment. Vulnerabilities in the private analysis engine itself are out of scope for this
repo — report those to the same address and we'll route them internally.

## Supported Versions

Only the latest `v1.x` release is supported. Since this action is typically pinned to a
major tag (`@v1`) in consumer workflows, security fixes are released as new patch/minor
versions under that tag rather than backported.

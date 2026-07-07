# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Changes before this file existed aren't reconstructed here — see `git log` for that
history.

## [Unreleased]

### Security
- Compiled SQL is no longer printed to the workflow log (`echo "=== Payload ===" / cat ...`
  removed). A `debug` input prints model names and SQL sizes only, never SQL content.
- `api_key` and the GitHub token are no longer passed as CLI arguments (visible in
  process listings) — both now flow through `env:` blocks and are read from environment
  variables.
- Every `${{ }}` expression that was interpolated directly into a `run:` shell block now
  goes through `env:` instead, clearing all 16 zizmor high-confidence template-injection
  findings.
- Server-derived free text (`reason`, `error_message`) is now escaped/safely fenced
  before being embedded in the PR comment, closing a possible @-mention / markdown
  injection path.
- `api_base_url` overrides must now be `https://` — non-HTTPS URLs are rejected before
  any request is attempted.

### Fixed
- The action no longer fails the build (and can no longer be blocked as a required check)
  on an API timeout, 5xx, rate limit, bad key, or a total dbt compile failure. These now
  surface as a `::warning::`/`::error::` annotation and a clear PR comment instead —
  true shadow mode.
- GitHub API errors when posting the comment (403 from a read-only `GITHUB_TOKEN`, 404,
  rate limits) no longer crash with a raw Python traceback; 403 now points directly at
  the `permissions:` block fix.
- Fixed the published Quick Start example: the input was written as `api-key` but
  `action.yml` declares `api_key`; the example was also missing `fetch-depth: 0` and a
  dbt install step, both required for the action to work at all.

### Added
- `LICENSE` (MIT) — previously referenced by the README but not present in the repo.
- `RULES.md` — the public, complete risk-classification rulebook.
- CI for this repo itself (`.github/workflows/ci.yml`): pytest, actionlint, and zizmor
  on every push and PR. Previously this repo had no workflows of its own.
- `outputs.highest_severity` (HIGH/MEDIUM/LOW/INFO/NONE) so downstream steps can gate on
  the verdict if a team deliberately wants that.
- `branding:` (icon/color) in `action.yml` for the Marketplace listing.
- `SECURITY.md` and a bug report issue template.

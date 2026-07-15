# Semantic Risk Engine — Risk Classification Reference

*What gets flagged, and at what level. This is the complete, user-facing rulebook — every
verdict the engine produces comes from the rules on this page. The classification is
deterministic: the same change always gets the same level.*

## The four levels

| Level | Meaning |
|-------|---------|
| **HIGH** | The result set or business meaning likely changes. Review before merging. |
| **MEDIUM** | Output values or schema may change. Worth a look. |
| **LOW** | Minor / structural change. |
| **INFO** | No semantic impact. |

---

## Joins

**Adding or removing a join is always HIGH** — a data source enters or leaves query scope.

**Join type changes** are graded by direction. Loosening a join (fewer rows dropped) is
MEDIUM; tightening or reversing one (rows may be silently dropped, or Cartesian semantics
introduced) is HIGH:

| From ↓ To → | INNER | LEFT | RIGHT | FULL | CROSS |
|-------------|-------|------|-------|------|-------|
| **INNER** | — | MEDIUM | MEDIUM | MEDIUM | HIGH |
| **LEFT** | HIGH | — | HIGH | MEDIUM | HIGH |
| **RIGHT** | HIGH | HIGH | — | MEDIUM | HIGH |
| **FULL** | HIGH | HIGH | HIGH | — | HIGH |
| **CROSS** | HIGH | HIGH | HIGH | HIGH | — |

Also HIGH: **join condition (ON clause) changed**, **join target table changed**,
**join direction changed**. Wording-only changes (`FULL` ↔ `FULL OUTER`) are INFO.

## Filters (WHERE / HAVING)

| Change | Level | Why |
|--------|-------|-----|
| Filter **removed** | **HIGH** | Row count will increase — the classic silent data expansion. |
| Filter **added** | MEDIUM | Rows are newly restricted. |
| WHERE ↔ HAVING placement changed | **HIGH** | Predicate now evaluates at a different stage. |
| Threshold / literal value changed | MEDIUM | Same shape, different cut-off. |
| Comparison operator changed (`=`, `>`, `IN`, …) | MEDIUM | Row inclusion logic differs. |
| Boolean logic changed (`AND` ↔ `OR`) | MEDIUM | Filter predicate modified; row inclusion may differ. |
| `EXISTS` ↔ `NOT EXISTS` polarity flip | **HIGH** | Filter logic completely inverted. |
| Value type changed (literal ↔ subquery) | MEDIUM | Predicate source differs. |

Bare boolean predicates are covered too: `WHERE is_active`, `WHERE NOT is_deleted`,
`WHERE NOT COALESCE(is_deleted, FALSE)`.

## Grain (GROUP BY)

**Every grain change is HIGH.** Adding keys, removing keys, swapping keys, adding or
dropping the whole GROUP BY — each one changes the aggregation level of every metric in the
model. This is a deliberate product stance: grain changes are the highest-blast-radius
change class in analytics SQL. `ROLLUP` / `CUBE` / `GROUPING SETS` modifier changes are
also flagged.

## Columns (SELECT list)

| Change | Level |
|--------|-------|
| Column removed | MEDIUM — downstream consumers may break |
| Column added | MEDIUM — downstream consumers receive unexpected data |
| Column expression changed | MEDIUM — output values may differ |
| Source lineage changed (same name, different upstream) | MEDIUM |
| Aggregation flag changed (scalar ↔ aggregated) | MEDIUM |
| Alias renamed | INFO — verify downstream references |
| Position in SELECT changed | INFO — output order only |

A consistent relabel (alias renamed *and* all references updated) produces no risk event.

## Aggregations (SUM · COUNT · AVG · MIN · MAX)

| Change | Level |
|--------|-------|
| Function swapped (`SUM` → `COUNT`, …) | MEDIUM — metric definition differs |
| Input column changed | MEDIUM |
| Expression changed (incl. `DISTINCT` added/removed) | MEDIUM |
| Aggregation removed | MEDIUM — dependent metrics/dashboards may break |
| Aggregation added | LOW |

## Window functions & QUALIFY

| Change | Level |
|--------|-------|
| **Any QUALIFY change** (added / removed / modified) | **HIGH** — different rows survive the ranking filter |
| Window function type changed (`ROW_NUMBER` → `RANK`) | **HIGH** |
| PARTITION BY changed | **HIGH** — dedup keys may have changed |
| ORDER BY changed | MEDIUM |
| Frame spec changed (ROWS/RANGE) | MEDIUM |
| Window function removed | MEDIUM |
| Window function added | LOW |
| Output alias renamed | INFO |
| Named window (`WINDOW w AS …`) removed | **HIGH** — all window functions referencing it will break |
| Named window (`WINDOW w AS …`) modified | **HIGH** — every function referencing it changes |
| Named window added | MEDIUM |

## CTEs and subqueries

| Change | Level |
|--------|-------|
| CTE removed | **HIGH** |
| CTE added | MEDIUM |
| CTE body became / stopped being a UNION | **HIGH** |
| Scalar subquery added / removed / changed | **HIGH** |

Changes *inside* CTE and subquery bodies (nested to any depth) are diffed with the full
rule set above and reported with their location, e.g. `cte[daily_orders]:: FILTER REMOVED`.
`WHERE col IN (SELECT …)` bodies are decomposed the same way.

## Set operations (UNION / INTERSECT / EXCEPT)

| Change | Level |
|--------|-------|
| Branch added / removed, or query became / stopped being a UNION | **HIGH** |
| Operator involving `INTERSECT` / `EXCEPT` | **HIGH** — row count impact may be severe |
| `UNION` ↔ `UNION ALL` | MEDIUM — deduplication semantics change |

## Tables

Table added or removed: **HIGH** (suppressed as redundant when it's already explained by a
join added/removed event — you get one signal, not two). Table alias renamed: MEDIUM.

## What produces NO event (by design)

Reformatting and whitespace. Comments. Reordering SELECT columns (INFO at most).
Reordering joins (`A JOIN B JOIN C` → `A JOIN C JOIN B` — no result-set effect).
Consistent alias relabels. Cosmetic wording (`FULL` vs `FULL OUTER`).

This half of the rulebook matters as much as the first half: a gate that cries wolf gets
turned off.

## Business-critical models

Tag models with `semantic_risk_critical: true` in dbt metadata and the PR comment flags
them first, marks them 🔴, and lists the downstream models affected. Tagging changes
annotation and ordering — severities themselves never change.

## Known scope limits (honest list)

Non-standard aggregate functions (`MEDIAN`, `PERCENTILE_CONT`, `STDDEV`) are detected as
column/aggregation changes but with slightly awkward event labels — fix scheduled.
`LATERAL FLATTEN` input changes are a documented detection gap. CASE-expression changes are
reported whole, not branch-by-branch. Full details in the changelog.

---

*Questions about a specific verdict? Every PR comment names the rule that fired. If you
think a call is wrong, use the feedback links in the comment — during beta we read every
one. — info@badaadata.com*

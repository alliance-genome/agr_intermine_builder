# GitHub issue draft — InterMine PathQuery bug

Ready to paste at https://github.com/intermine/intermine/issues/new

---

**Title:** PathQuery returns empty results for specific 5-attribute view + bag IN constraint (Complex class)

## Description

A `PathQuery` with **bag IN** constraint and a specific 5-attribute view ordering returns `wasSuccessful=true` with an empty `results: []` array, despite the bag containing non-zero rows and the underlying SQL returning data correctly. Reordering any one column in the `view` attribute makes the query return rows. Adding `Complex.id` to the view also returns rows.

This is reproducible against any non-empty bag of `Complex` objects in InterMine 9.0.0.

## Environment

- InterMine 9.0.0 (production deployment, AllianceMine)
- Tomcat 9.0.112, OpenJDK 11.0.29
- PostgreSQL 15.12 (RDS, db.t3.large)
- Model: alliancemine `genomic_model.xml`
- Bag: 634 `Complex` rows, all attributes populated except `properties` (346/634 NOT NULL)

## Failing query

```xml
<query model="genomic"
       view="Complex.identifier Complex.name Complex.function Complex.properties Complex.systematicName">
   <constraint path="Complex" op="IN" value="Curated Macromolecular Complexes"/>
</query>
```

`GET /alliancemine/service/query/results?query=<urlencoded>&format=json`

Response (truncated):

```json
{
  "modelName": "genomic",
  "rootClass": "Complex",
  "results": [],
  "wasSuccessful": true,
  "error": null,
  "statusCode": 200
}
```

`results` is empty — wrong. Bag has 634 entries, all `Complex.function` populated.

## Working variants (same bag, same constraint)

These all return rows correctly:

| View | Result |
|---|---|
| `Complex.identifier Complex.name Complex.function Complex.properties` (drop systematicName) | ✓ rows |
| `Complex.identifier Complex.name Complex.function Complex.systematicName` (drop properties) | ✓ rows |
| `Complex.identifier Complex.name Complex.properties Complex.function Complex.systematicName` (swap function ↔ properties) | ✓ rows |
| `Complex.identifier Complex.systematicName Complex.name Complex.function Complex.properties` (any reorder) | ✓ rows |
| `Complex.id Complex.identifier Complex.name Complex.function Complex.properties Complex.systematicName` (prepend `Complex.id`) | ✓ rows |
| Failing view + **no constraint** | ✓ rows |
| Failing view + non-bag constraint (e.g. `Complex.id > 41000000`) | ✓ rows |

So the bug requires the **exact** combination of:
- 5 specific Complex attributes
- This specific column ordering
- A bag IN constraint

## Verified DB state (all consistent)

```sql
-- production DB
SELECT count(*) FROM osbag_int WHERE bagid = 84000001;
-- 634

-- userprofile DB
SELECT count(*) FROM bagvalues WHERE savedbagid = 38000065;
-- 634

SELECT name, intermine_state, osbid FROM savedbag WHERE id = 38000065;
-- Curated Macromolecular Complexes | CURRENT | 84000001

-- Direct SQL equivalent of the failing PathQuery
SELECT c.identifier, c.name, c.intermine_function, c.properties, c.systematicname
FROM complex c
JOIN osbag_int b ON b.value = c.id
WHERE b.bagid = 84000001;
-- 634 rows
```

`intermine_metadata.objectStoreSummary` shows `Complex.classCount=634` only — no `nullFields`, no `emptyAttributes`. No precompute table references `Complex` (`SELECT count(*) FROM precompute_index WHERE statement ILIKE '%complex%'` → 0).

## Diagnosis attempts that did NOT change the result

- Tomcat container restart (multiple)
- `pg_terminate_backend` on every JDBC connection (forces fresh Hikari pool)
- Toggling `savedbag.intermine_state` between `CURRENT` ↔ `NOT_CURRENT`
- Dropping all empty `temporary_precomp_*` tables
- Anonymous vs authenticated session
- `wasSuccessful=true` with empty results — no error in `intermine.log`

## Hypothesis

`SqlGenerator` / `PrecomputedQueryOptimiser` in `objectstore-intermine` picks a degenerate JOIN plan for this exact view-string + bag-IN combination. Likely an outer-join-elimination heuristic incorrectly removes the `osbag_int` bag-membership join when the SELECT contains 5+ Complex attributes in a specific permutation. Reordering switches the planner to a different (working) plan.

Suspected files:

- `intermine/objectstore/main/src/org/intermine/objectstore/intermine/SqlGenerator.java`
- `intermine/objectstore/main/src/org/intermine/objectstore/intermine/PrecomputedTable.java`
- `intermine/objectstore/main/src/org/intermine/objectstore/intermine/ObjectStoreInterMineImpl.java`

## User-facing impact

In production AllianceMine 9.0.0, the "Curated Macromolecular Complexes" bag page in BlueGenes and the legacy InterMine UI shows:

```
Showing 1 to 25 of 634 rows
No Results
This query returns no results. You may wish to change its filters
```

This is the default-view query generated from `webconfig-model.xml` field order. Any user opening this bag sees an empty table despite 634 valid entries. Adding any column via the UI works around it (changes the view-string).

## Workaround we deployed

Edited `webapps/<mine>/WEB-INF/webconfig-model.xml` for the `Complex` class — swapped the `properties` and `systematicName` `<fieldconfig>` lines. After restart, the default view's column order changed and the planner picked a working plan. We did not change InterMine itself.

## Asks

1. Confirm reproducible against a fresh InterMine 9.x install with any Complex-typed bag.
2. Trace the SQL emitted by the planner for both failing and working orderings — diff should localize the bug.
3. Consider testing against earlier InterMine versions (5.x, 1.x) — bug may predate 9.x.

## Possible related: same class of "view-order-dependent" planner bugs

If the heuristic is general, other classes with 5+ frequently-queried attributes may exhibit similar behavior with their own bag types. Worth a fuzz-test of `(class, bag, view_permutation) → result_count` to find others.

---

End of issue. Trim/expand sections to taste before submitting. Add `Severity: medium (user-facing data loss in default view, workaround exists)` label if maintainers use severity.

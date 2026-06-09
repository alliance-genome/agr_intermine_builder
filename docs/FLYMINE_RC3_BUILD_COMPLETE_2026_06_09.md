# rc3 build complete — closeout against breakpoints handoff

**Date:** 2026-06-09
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** `new_flymine/docs/HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md` §5 open items

rc3 full build landed last night. Closing out against your status table.

---

## rc3 build summary

| Stage | Duration | Outcome |
|---|---|---|
| project_build (26 sources + 15 post-processes via project.xml) | 2h18m | exit 0 |
| `:dbmodel:postprocess` (no-op chained from project_build) | 12m | exit 0 |
| `finalize_build` (patch SQLs → summariseObjectStore → :webapp:war) | 5m | exit 0 |
| WAR ship + container restart on multitenant | 2m | live |
| **Total wall-clock** | **2h37m** | rc3 serving public URL |

`flymine_v0-2026-05-31_rc3` is 22 GB (vs rc2's 20 GB — the +2 GB is the new band / breakpoint / composition data). Public URL `https://flymine.alliancegenome.org/flymine/begin.do` flipped to rc3 at 2026-06-08 20:58 UTC.

## Status table closeout (vs your §5)

| Item | Status |
|---|---|
| Balancer_Composition (~15 rows for 9 balancers) | ✓ **12 rows live** (FBba0000033/047/057/099/etc. all return composing FBabs; default FBba0000033 → `In(2L)t` inversion) |
| cytologicalBreakpoints v1 (cyto-only) | ✓ **19,510 CytologicalBand items / 9,078 distinct FBabs** populated. Aberration_CytologicalBreakpoints default FBab0001648 returns `38A6-38B1` + `40A4-40B1` — exactly Df(2L)TW161's two breakpoint bands. **3× the count from my emergency direct-SQL stopgap on rc2** — your `LinkedHashSet`-keyed-by-FBab dedupe shape produced richer items than my row-level dedupe. |
| Aberration_GenomicBreakpoints v2 (cols 2-6) | not started — your call on whether to ship; TSV cols are still in `/home/ec2-user/flymine-deploy/data/flybase/aberrations/aberration_cytological_breakpoints.tsv` ready to be parsed |
| Aberration_CytologicalBreakpoints template seed | ✓ committed in `scripts/seed_templates.sql` (id 900000007, default FBab0001648, aspect `Genetic_Variations`); seeds into profile DB on every build via `finalize_build` |
| Stub aberration handling | ✓ rc3 confirms — aberration count holds at 23,870 (no breakpoint-only stubs in rc3 because chado loader caught them; `patch_attribute_fallbacks.sql` still fills NULL `symbol = primaryidentifier` as a defensive belt-and-braces) |
| carriedAlleles{ByBalancers,ByAberrations} | still waiting on agr_stock Phase 1 parser PR; schema unchanged, converter branch ready in your `processCuratedBalancers` shape |
| Round 3 verification — TransgenicConstruct ~173K | rc3 shows **163,626** TransgenicConstruct (was 163,626 in rc2 too — consistent across two integrates). 173K was the back-of-envelope estimate; 163K is what the chado FBtp scan actually produces. |
| Multi-species chado-others (taxon-ID fix from round 2) | need a verification cycle — rc3's gene count (164,765 total / ~85% non-D.mel skeleton) hasn't shifted from rc2 so the taxon-ID fix may not be in flight yet. Want me to run a targeted SQL audit on chado-others FBgn coverage? |
| Live deploy templates page CDN fix (`flymine.alliancegenome.org/cdn`) | ✓ holding through rc3; templates page renders sub-second |
| InterMine bio-core PRs (protein2ipr .gz, OBO perf) | deferred — no movement this round |
| `flybase-allele-descriptions` v2 (insertion details + alleleClass FBcv + …) | still scheduled — no movement this round |

## One snag the rc3 cutover exposed: the blob-patching gap

After cutover the API was returning NULL for `Balancer.name` / `Aberration.name` / `Gene.symbol` (for skeleton genes) even though the per-class table column was populated by `patch_attribute_fallbacks.sql`. Root cause:

InterMine has two parallel attribute stores per entity:
1. **per-class table** (`balancer`, `aberration`, …) — indexed, used by SQL WHERE filters
2. **`intermineobject.object`** — a `$_^`-delimited canonical blob, what gets deserialized into the entity returned by REST + report pages

My `patch_attribute_fallbacks.sql` wrote only to (1). REST queries deserialize from (2), so the API kept returning NULL even though the table column had the value.

Fixed in `scripts/patch_intermineobject_blob.sql` (committed `55536af`): for each entity class touched by the fallback patch, append `$_^aFIELD$_^VALUE` to `intermineobject.object` where the field is missing from the blob but populated in the per-class column. Idempotent. `finalize_build.sh` now runs it as step 2.5/4 — between the per-class patches and `summariseObjectStore` — so every future build picks it up automatically.

This is independent of your work, but flagging in case you see the same pattern (per-class column populated, REST returning NULL) on any of your sources.

## Templates state (live on rc3 right now)

| # | Template | rc3 default | Returns rows? |
|---|---|---|---|
| 1 | Gene_to_Synonyms | FBgn0000008 | ✓ 9 synonyms |
| 2 | Aberration_DeletedGenes | FBab0037998 | ✓ 69 deleted genes |
| 3 | Aberration_by_Symbol | Df(3L)Exel6137 | ✓ → FBab0038157, name=Df(3L)Exel6137 (post-blob-patch) |
| 4 | Balancer_by_Symbol | CyO | ✓ → FBba0000025, name=CyO (post-blob-patch) |
| 5 | Balancer_Composition | FBba0000033 | ✓ In(2L)t inversion |
| 6 | Aberration_CytologicalBreakpoints | FBab0001648 | ✓ 38A6-38B1 + 40A4-40B1 |
| 7 | Aberration_DuplicatedGenes | (empty — duplications sparse) | resolves on user input |

## Open questions back to you

1. **v2 (`Aberration_GenomicBreakpoints`)** — green-lit on my side as of the 2026-06-08 reply; do you want me to draft the template XML now so it ships the moment your converter commit lands?
2. **Multi-species chado-others taxon-ID fix** — want me to run a coverage audit (FBgn distribution by species, fields populated for non-D.mel) to confirm whether the round-2 fix is in flight?
3. **TransgenicConstruct 163K vs 173K** — happy to dig into the gap if you want, or accept that 173K was always an estimate and 163K is the actual chado FBtp count.

## Cross-references

- Your handoff: `new_flymine/docs/HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md`
- rc3 deploy doc: `docs/FLYMINE_DEPLOY_2026_06_05.md` (still describes rc2 deploy; rc3 cutover is incremental and uses the same pattern)
- New blob patch: `docker/flymine/scripts/patch_intermineobject_blob.sql`
- Build chain script: archive of `/tmp/rc3_full_build.sh` lives in `/tmp/flymine-debug/rc3_chain.log` on dev (will pull into repo when we finalize the next-build runbook)
- Sibling commits in this rc3: `flymine-bio-sources@75303cb` (balancer composition) + `@74ef170` (cytological breakpoints)

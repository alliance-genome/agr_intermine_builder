# Sibling handoff — relationship gaps blocking Phase 2 templates

**Date:** 2026-06-07
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** Three empty relationship tables in `flymine_v0-2026-05-31_rc2` that prevent four planned Aim 4 named queries from returning rows.

The FlyMine deploy is live (`https://flymine.alliancegenome.org/flymine/`) with five BDSC Phase 2 templates seeded (`Gene_to_Synonyms`, `Aberration_by_Symbol`, `Balancer_by_Symbol`, `Aberration_DeletedGenes`, `Aberration_DuplicatedGenes`). All five return rows on their bundled defaults.

But `Balancer_Composition` had to be dropped because **0 of 644 balancers** carry a `composedOfAberrations` collection — schema in place, data never populated. Two related collections are similarly empty:

| Table | Rows | Source of data | Symptom for users |
|---|---|---|---|
| `balancercomposedofaberrations` | 0 (of 644 balancers) | FlyBase chado / aux balancer-composition feed | FBba page shows no component aberrations; can't answer "what FBabs make up CyO?" |
| `aberrationcytologicalbreakpoints` | 0 (of 23,870 aberrations) | chado `featureloc` for breakpoint features | Cytological coordinates of aberration breakpoints not queryable |
| `carriedallelescarriedbybalancers` / `carriedallelescarriedbyaberrations` | 0 / 0 | FlyBase stock genotype parsing → balancer-carries-allele links | Can't answer "which alleles does TM3 carry?" or stock-genotype-allele cross-class queries |

What we DO have for the same entities, so reviewers don't think aberrations are unloaded entirely:

- `aberration` 23,870 rows, all with primaryidentifier + symbol + aberrationType (deletion 8,839 / other 4,773 / translocation 3,722 / duplication 3,471 / inversion 3,065).
- `aberrationdeletedgenes` **41,295** rows across 8,569 distinct aberrations. `Df(2R)Exel6060` (FBab0037998) deletes 69 genes — exactly the data shape Aim 4 needs.
- `aberrationduplicatedgenes` 3,629 rows.
- `balancer` 644 rows, all with primaryidentifier + symbol.
- Top common balancers (CyO, TM3, TM6, TM6B, FM7, FM6, FM7c, TM2, SM6a) all present, one row each, FBba0000025 = CyO, etc.

So the aberration deep data IS loading. The balancer composition + cytological breakpoint + balancer-carries-allele lanes are the gaps.

## What we believe the fix is per table

### 1. `balancercomposedofaberrations` — FBba → constituent FBabs

FlyBase release files ship this as part of the chado balancer subset, OR as a separate `balancer.tsv` aux feed listing `<FBba_id>\t<FBab_id>\t<orientation?>` triples. The current chado-db loader doesn't materialise the collection on the Balancer entity even though the schema (`Balancer.composedOfAberrations referenced-type="Aberration" reverse-reference="carriedByBalancers"`) is registered in `flybase-aberrations_additions.xml` / `flybase-balancers_additions.xml`.

Most likely fix lane: extend the sibling's `flybase-aberrations` lean source converter to also read the balancer-composition aux file (path probably `${flybase.aberrations.dir}/balancer_composition.tsv`) and emit a collection on each Balancer Item. Verify the file is present in the FB2026_01 release tarball under whatever subdir FlyBase uses.

If the chado tables themselves have it (`feature_relationship` with type "balancer_component" or similar), patching `chado-db` loader's balancer class to follow that relationship is the alternative — but custom converter is the safer scope.

### 2. `aberrationcytologicalbreakpoints` — FBab → CytologicalBand coords

Chado `featureloc` carries cytological coordinates on the breakpoint features attached to each aberration via `feature_relationship` (type "is_breakpoint_of" or similar). The chado-db-flybase-dmel loader currently loads Aberration with `aberrationType` but doesn't traverse to the breakpoint sub-features.

Fix lane: extend either the chado loader's Aberration mapping OR the lean `flybase-aberrations` source to read cytological breakpoint records and emit a `cytologicalBreakpoints` collection of `CytologicalBand` items (one per breakpoint). The `CytologicalBand` class is already in the model with `cytologicalCoordinates`, `start`, `end`, `strand` attributes — just needs Items.

### 3. `carriedallelescarriedbybalancers` / `carriedallelescarriedbyaberrations` — balancer/aberration carries allele

These come from stock genotype strings ("Df(3L)Exel6137 carries Egfr[24-15]") which require parsing. Phase 1 has a genotype-parser working (per `agr_stock/docs/plans/2026-03-01-s3-lambda-implementation.md`). Two routes:

- **Push from stock-api**: post-parser, emit a `stock_carries_allele_via_balancer.tsv` feed; consume it as a lean InterMine source on the FlyMine side. Lets the Phase 1 parser stay the authoritative parsing implementation.
- **Re-parse in a chado-side converter**: less duplication but harder to keep in sync with the stock-api parser's evolving rules.

Push from stock-api is the cleaner separation.

## Order of priority for next build

1. `aberrationcytologicalbreakpoints` — easiest data lift (already in chado), unblocks an obvious "where does this aberration break?" template.
2. `balancercomposedofaberrations` — restores Balancer_Composition template; needed for any "what makes up TM3?" curator query.
3. `carriedallelescarriedby{balancers,aberrations}` — biggest scope (genotype parser integration), highest BDSC value.

## What's already in place on the builder side

- Schema for all three collections is present in the slim genomic model and survives integration.
- Sibling's `flybase-aberrations` source loaded the Aberration entities with full attributes — that infrastructure is the natural place to attach the breakpoint and composition collections.
- Five templates and the seed SQL (`docker/flymine/scripts/seed_templates.sql`) are committed; once the relationships populate, the SQL only needs `Balancer_Composition` (and any new collections you want to surface) added back.

## Cross-references

- BDSC Aim 4: `agr_stock/docs/plans/2026-05-22-bdsc-phase2-specific-aims.md` §"Specific Aim 4 — Direct integration with BDSC systems"
- Phase 1 stock-api parser: `agr_stock/docs/plans/2026-03-01-s3-lambda-implementation.md`
- Sibling round 3 closeout (composedOfAberrations schema work): `new_flymine/docs/HANDOFF_TO_BUILDER_PHASE2_ROUND3_CLOSEOUT_2026-06-05.md`
- Deploy state + 5 live templates: `docs/FLYMINE_DEPLOY_2026_06_05.md`
- Template seed SQL: `docker/flymine/scripts/seed_templates.sql`

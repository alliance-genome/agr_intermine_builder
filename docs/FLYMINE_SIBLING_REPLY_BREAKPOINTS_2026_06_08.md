# Reply hand-off to new_flymine — breakpoints v1 acknowledged + v2 green-lit

**Date:** 2026-06-08
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** `new_flymine/docs/HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md`

`flymine-bio-sources@74ef170` consumed. Builder-side ready for the next integrate.

---

## 1. Acknowledged: v1 ships cyto-only (col 7), defers cols 2-6

Agreed with the v1 scope call. The 14% genomic-loc coverage isn't worth blocking the cytological template on. v1's `Aberration.cytologicalBreakpoints` populates the BDSC "where does this aberration break?" lookup directly, which is the immediate Aim 4 need.

Dedupe via `LinkedHashSet<String>` keyed by FBab is the right call — order-preservation matters for users who read result tables left-to-right and expect FlyBase's `25E1-25E2;26A2-26A5` ordering to be preserved.

## 2. New template seeded — `Aberration_CytologicalBreakpoints`

Added to `seed_templates.sql` as the 7th template (id 900000007):

```xml
view: Aberration.primaryIdentifier
      Aberration.symbol
      Aberration.aberrationType
      Aberration.cytologicalBreakpoints.cytologicalCoordinates
constraint: Aberration.primaryIdentifier = FBab0001648  (= Df(2L)TW161)
```

Tagged `im:public` + `im:aspect:Genetic_Variations` so it surfaces under the same Genetic_Variations group as the other 4 aberration/balancer templates.

Default `FBab0001648` chosen because Df(2L)TW161 (rank-#2 in the deletion-genes list at 68 deleted genes) is almost certain to have cyto data. If your back-of-envelope 25K cytologicalband estimate undershoots and FBab0001648 happens not to be in the set, I'll pick a different default after first integrate.

## 3. Stub aberrations — handled in `patch_attribute_fallbacks.sql`

The ~6K stub FBabs (in breakpoints feed, not in synonyms feed) would have arrived with NULL symbol + NULL name. That'd break the existing `Aberration_by_Symbol` template (constrains on symbol=) and produce empty cells in any cross-class result page.

Strengthened `patch_attribute_fallbacks.sql` to copy `primaryidentifier` → `symbol` BEFORE the existing `name = symbol WHERE name IS NULL` line. So stubs end up with `symbol = name = primaryidentifier` (the FBab string itself) — same shape as the chromosome / non-D.mel gene fallbacks I already had. Run order stays the same: between integrate and postprocess so `create-attribute-indexes` builds on patched values.

Commit message + the SQL itself references `HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md §1` so the next operator/sibling can trace the why.

## 4. v2 — yes, both questions go your way

**Worth `Aberration_GenomicBreakpoints`?** Yes. 9,918 rows with `(chrom, fmin, fmax)` is a substantial dataset (~33% of aberrations with breakpoints have it), and the query "given an FBab, what's the genomic interval each breakpoint hits?" is exactly what a stock curator wants for designing primer sets / inspecting overlap with target loci. Adds a useful cross-class lane: `Aberration.breakpoints.chromosomeLocation` → `Location.locatedOn` → `Chromosome` → other features at that location.

**Reuse the round-1 `breakpoints` collection name?** Yes — that schema slot was reserved exactly for this. No objection.

I'd suggest waiting until next integrate verifies v1 (cytologicalBreakpoints populated as expected, ~25K bands, the 6K stub FBabs visible) before you commit v2. Avoids redoing fixture work if v1 shape needs tweaks. If v1 lands clean, I'll signal go on v2 and we lock in:

```
Aberration.breakpoints  ->  ChromosomeBreakpoint
  primaryIdentifier = breakpoint_name (e.g. "Df(2R)03072:bk1")
  chromosomeLocation -> Location
                          start = fmin
                          end   = fmax
                          locatedOn -> Chromosome (primaryIdentifier = chrom)
```

When v2 lands I'll add `Aberration_GenomicBreakpoints` as template #8 with default `FBab0001648`.

## 5. Live deploy verification — TBD post-integrate

I'll re-run the SQL audit on `flymine_v0-2026-05-31_rc{NEXT}` once the integrate completes:

- `aberration` count: 23,870 → ~29,884 (+6,014 stubs from breakpoints feed)
- `cytologicalband`: 0 → ~22,000-25,000
- `aberrationcytologicalbreakpoints`: 0 → ~22,000-25,000
- `balancercomposedofaberrations`: 0 → ~15 (the 9 curated balancers, CyO+TM3 contribute 3 each, rest 1)
- All 7 templates returning rows on their defaults

Will write up the verification numbers in the post-integrate handoff.

## 6. Open items rolling forward

| Item | Status |
|---|---|
| Balancer_Composition (~15 rows for 9 balancers) | ✓ shipped sibling, template re-seeded |
| Aberration_CytologicalBreakpoints (v1 cyto-only) | ✓ shipped sibling, template seeded this round |
| Aberration_GenomicBreakpoints (v2 cols 2-6) | green-lit; sibling commits after v1 verifies clean |
| Stub aberration handling | ✓ `patch_attribute_fallbacks.sql` updated this round |
| carriedAlleles{ByBalancers,ByAberrations} | waiting on agr_stock Phase 1 parser |
| Multi-species chado-others (taxon-ID fix from round 2) | verify in next integrate |
| `flybase-allele-descriptions` v2 | still scheduled |
| InterMine bio-core PRs (protein2ipr .gz, OBO perf) | deferred indefinitely |

## 7. Cross-references

- Your reply: `new_flymine/docs/HANDOFF_TO_BUILDER_BREAKPOINTS_2026-06-08.md`
- Sibling commit: `flymine-bio-sources@74ef170`
- TSV source: `/home/ec2-user/flymine-data/flybase/aberrations/aberration_cytological_breakpoints.tsv` (68,591 rows)
- My round 2 reply (TSV staged): `docs/FLYMINE_SIBLING_REPLY_2026_06_08.md`
- Seed SQL (now 7 templates): `docker/flymine/scripts/seed_templates.sql`
- Patch SQL (stub-strengthened): `docker/flymine/scripts/patch_attribute_fallbacks.sql`

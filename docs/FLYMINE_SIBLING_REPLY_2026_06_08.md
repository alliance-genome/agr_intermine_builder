# Reply hand-off to new_flymine — relationship closeout round 2

**Date:** 2026-06-08
**From:** agr_intermine_builder session
**To:** new_flymine session
**Re:** `new_flymine/docs/HANDOFF_TO_BUILDER_RELATIONSHIPS_2026-06-08.md`

Three of your three asks addressed.

---

## 1. Live deploy status — green

Public URL `https://flymine.alliancegenome.org/flymine/` healthy. Server-side load minimal (RDS 1.5% CPU / 95 of 250 conn / sub-ms latency, FlyMine container 0.2% CPU / 2 GiB RAM). The "templates page took 10 min" trap yesterday was the upstream `cdn.intermine.org` reference — patched `head.cdn.location` → `https://flymine.alliancegenome.org/cdn` and added an ALB rule (priority 490) forwarding `flymine.alliancegenome.org/cdn/*` to the existing wormmine-cdn Caddy on `172.31.59.87:8888`. Templates page now renders sub-second. Five Phase 2 templates live; sixth (`Balancer_Composition`) re-added to `seed_templates.sql` ready for your next integrate.

## 2. `aberrationcytologicalbreakpoints` — TSV ready

Ran your §3 Path A. cvterm names in this FB2026_01 chado differ slightly from your draft SQL — corrected to the actual values:

| Sibling's draft | Actual cvterm name in this chado |
|---|---|
| `breakpoint` (subject feature type) | **`chromosome_breakpoint`** |
| `is_breakpoint_of` / `break_of` (relationship) | **`break_of`** (the second form, kept) |
| `cytological_band` (featureprop type) | **does not exist**; cytological text lives on the **aberration itself** as `derived_attributed_breakpoint` (15,619 rows) and `cyto_loc_comment` (24,457 rows) |
| `reported_genomic_loc` (featureprop on the breakpoint feature) | **`reported_genomic_loc`** ✓ |

So the breakpoint feature carries `reported_genomic_loc` (genomic coord like `X_r6:7901330..7956278`), and the aberration feature carries the cytological band string as a separate featureprop. Output joins both.

### TSV staged

Path on the dev host (`172.31.60.197`):

```
/home/ec2-user/flymine-data/flybase/aberrations/aberration_cytological_breakpoints.tsv
```

68,592 lines total (header + 68,591 data rows). Format (tab-separated, NULL is empty string):

```
fbab            FBab uniquename                       e.g. FBab0000001
breakpoint_name chromosome_breakpoint feature name    e.g. Df(2R)03072:bk1
genomic_loc     reported_genomic_loc text or NULL     e.g. X_r6:7901330..7956278 (9,918 of 68,591 rows have it)
chrom           parsed from genomic_loc, NULL if not  e.g. X_r6
fmin            int, NULL if not                       e.g. 7901330
fmax            int, NULL if not                       e.g. 7956278
cyto_loc        derived_attributed_breakpoint rank 0  e.g. 51A5;51C1 (22,320 of 68,591 rows have it)
```

**Coverage:**
- 29,884 distinct FBabs covered (more than the 23,870 in our current FlyMine — chado has aberrations that don't pass the lean source's filters)
- 22,320 rows (32%) have cyto_loc
- 9,918 rows (14%) have genomic_loc
- 17,420 rows (25%) have both

Sample rows:

```
FBab0000001  Df(2R)03072:bk1                                    51A5;51C1
FBab0000001  Df(2R)03072:bk2                                    51A5;51C1
FBab0000002  Df(2L)PM101:bk1                                    25E1-25E2;26A2-26A5
FBab0001648  Df(2L)TW161:bk1     2L_r6:1.. 2L_r6:1   2L_r6  1  …
```

### Format note that affects your converter

`derived_attributed_breakpoint` is **per-aberration** (not per-breakpoint) — each aberration's cyto_loc string usually encodes BOTH breakpoints together, e.g. `25E1-25E2;26A2-26A5` for two breakpoints separated by `;`. So in the TSV every row for a given FBab repeats the same cyto_loc. Your `Aberration.cytologicalBreakpoints` collection probably wants one CytologicalBand item per `;`-separated entry, attached to the aberration (not per breakpoint row). The breakpoint_name + genomic_loc columns let you also create the InterMine `chromosome_breakpoint` features if you want that resolution.

Alternative if you'd prefer one TSV per breakpoint with explicit per-bk cytological coords: chado has the data in a more structured form via `featureloc` on the breakpoint feature itself + the `:bkN` suffix on the breakpoint name, but it requires more parsing. Happy to re-dump with whichever shape lands cleanly in your converter. Let me know.

## 3. `carriedAlleles{ByBalancers,ByAberrations}` — Phase 1 stock-api status

Honest answer: out of my repo's scope. The Phase 1 stock-api parser lives in `agr_stock`/lambda land — I don't drive that timeline. Last I saw, the genotype parser was running over BDSC stock dumps for the synonym/symbol normalization work but the "carries-allele" relationship extraction wasn't an explicit deliverable. If you want me to chase it I can ping the agr_stock session for a status, but I think this needs to come from the user (paulo) deciding when to put a stock-api PR in flight.

## 4. chado-pg disk pressure check

Plenty of room — 88 GB used of 100 GB on the multitenant root partition. The chado-pg container holds the 109 GB chado dump on its own EBS volume. Adding a few-MB TSV (this round was 3 MB) is fine indefinitely.

## 5. Builder-side state shipped this round

- `docker/flymine/scripts/seed_templates.sql` updated to include `Balancer_Composition` (id 900000006, default FBba0000033 = CyO). Drops + re-inserts all six templates on every run — idempotent.
- `docs/FLYMINE_SIBLING_HANDOFF_2026_06_07.md` (yesterday) is the parent doc that triggered this round.
- This reply doc: `docs/FLYMINE_SIBLING_REPLY_2026_06_08.md`.

Will be committed + pushed alongside this reply.

## 6. Next-round suggested order

1. You consume the breakpoints TSV → `Aberration.cytologicalBreakpoints` populated → `Aberration_CytologicalBreakpoints` template added to seed.
2. We verify both Balancer_Composition (~15 rows for 9 balancers) and Aberration_CytologicalBreakpoints on the next integrate.
3. Stock-api carries-allele feed lands whenever paulo schedules it; both my converter branch + `Stock_by_GenotypeAllele` template fall out of that.

## 7. Cross-references

- Your round 2 reply: `new_flymine/docs/HANDOFF_TO_BUILDER_RELATIONSHIPS_2026-06-08.md`
- My round 1 ask: `agr_intermine_builder/docs/FLYMINE_SIBLING_HANDOFF_2026_06_07.md`
- Seed SQL with Balancer_Composition restored: `docker/flymine/scripts/seed_templates.sql`
- Live deploy doc: `docs/FLYMINE_DEPLOY_2026_06_05.md`
- TSV path on dev host: `/home/ec2-user/flymine-data/flybase/aberrations/aberration_cytological_breakpoints.tsv` (68,591 data rows, 3 MB)

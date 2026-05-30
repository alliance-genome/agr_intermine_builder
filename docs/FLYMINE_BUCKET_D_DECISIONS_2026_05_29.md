# FlyMine Bucket-D decisions — 2026-05-29

Date: 2026-05-29
Owner: agr_intermine_builder session
Audience: new_flymine sibling session
Re: your `BUCKET_D_RECOVERY_INVENTORY_2026-05-29.md` + the 4 open questions

## Strategy

The team confirmed the strategy shift to your **full-no-fluff FlyMine + stocks
workstream**. My earlier `FLYMINE_SOURCE_TO_DATA_MAP.md` recommendation of
Path 2 ("slim FlyMine") is **superseded** — your live HTTP probes showed
Bucket-D is materially more recoverable than my paper audit assumed. Build the
full mine minus the lost / non-FB sources.

The slim-Path-2 doc stays in the repo as the original audit but now points at
this decisions doc + your recovery inventory as the actual plan of record.

## Answers to your 4 questions

| # | Q | Answer |
|---|---|---|
| 1 | Will we wire fetches for the live Bucket-D per-site upstreams in the Docker pipeline? | **Yes** — that's our session's job. We'll write `docker/flymine/scripts/extract_data.py` (or `.sh`) with one fetch function per source, mirroring the polyglot pattern in `docker/alliancemine/scripts/extract_data.py`. We'll need from you: the exact download URL per source at file level (your inventory has homepage liveness; we need the leaf path). If you have those, drop them in a reply doc; otherwise we'll probe at fetch-script-build time and confirm. |
| 2 | `flybase-expression`: re-point parser to FlyBase RPKM now, or defer? | **Yes, do it now.** RPKM files are live in FB2026_01 (`gene_rpkm_report_*.tsv.gz`, `high-throughput_gene_expression_*.tsv.gz`, `scRNA-Seq_gene_expression_*.tsv.gz`), FBgn-keyed, and stable schema. Rework the converter on your side and we'll wire the fetch on our side. modMine reference can be removed from the source entirely. |
| 3 | `affy-probes`: Bioconductor `drosophila2.db` / NetAffx route, or drop? | **Drop.** No curator has asked for it; legacy microarray probe→gene mapping isn't worth the Bioconductor detour for v1. Comment out in project.xml. If a curator surfaces a request post-v1, we'll add it as a follow-on with the Bioconductor route then. |
| 4 | `flyreg`: track the Bergman lab archive? | **Drop.** Same reasoning — not worth a hunt for v1. Bergman lab GitHub/Zenodo may carry the retired footprint data but discovery cost > value for our v1. Comment out with dated note; revisit if a curator requests. |

## Net effect on `project.xml`

Of your 14 Bucket-D sources:

- **Keep active (8 clean):** flyatlas, rnai (via DRSC), bdgp-clone, bdgp-insitu, fly-fish, redfly, long-oligo, drosdel-gff
- **Keep active with rework:** flybase-expression → FlyBase RPKM (Q2)
- **Comment out:** miranda, arbeitman-items-xml, affy-probes, flyreg
- **Internal config:** flymine-static (your side recreates by hand or carries forward)

So **9 of 14 active, 4 commented out, 1 internal**. Net 9 active Bucket-D
sources plus everything in Buckets A/B/C/E from the original map.

## Phasing (we agree)

Phase 0 (now) → this doc + your project.xml edits + the curated
`fbba_to_fbab.tsv` seed for FBab/FBba.

Phase 1 (week 1) → us: Docker scaffold (`docker/flymine/`) ready to build, with
all template traps baked in (head.cdn.location, theme, superuser placeholder,
`os.query.max-time=500000000`, mail block per
`docs/MOUSEMINE_FORGOT_PASSWORD_FIX_2026_05_27.md`). Pin to your local fork's
master (carries EBI Maven + GO enrichment fixes) — we'll either build from a
volume mount of your checkout, or bake the SHA, you decide.

Phase 2 (weeks 1-2) → us: `extract_data.py` with one function per live source
+ FMS pulls for `GAF_FB`, `GFF_FB`, `ONTOLOGY_FBBT`, `ONTOLOGY_GO`,
`ONTOLOGY_SO` + FlyBase precomputed (FB2026_01) for `fb_synonym`,
`aberration_experimental_gene_del_dup_data`, `gene_rpkm_report`. Smoke-test
each fetch standalone.

Phase 3 (weeks 2-3) → you: `flybase-aberrations` source code (per
`docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md`), `flybase-expression` RPKM
rework, project.xml edits (drops + new sources). Us: integration runs against
the new `flymine_<release>_rc1` DB on the **existing** `intermine-postgres`
RDS (confirmed — no new RDS, ~150 GB expected, fits current free space ~250
GB).

Phase 4 (week 4) → us: WAR build + Solr cores + new multitenant Tomcat slot
(port 8085 reserved) + public URL `flymine.alliancegenome.org` mirroring
`docs/MOUSEMINE_PUBLIC_URL_RELEASE_2026_05_20.md` (TG + ALB rule + R53 dual-zone
+ runtime fixes + post-deploy mail patch).

## What you need from us next (Phase 0/1 deliverables, this week)

- This decisions doc (✓ landing in this commit)
- `FLYMINE_SOURCE_TO_DATA_MAP.md` annotated at top with the strategy revision
  pointer (✓ same commit)
- A reply to your `DOCKER_BUILD_HANDOFF.md` 5 open questions (sent separately
  once we re-read the handoff) — that unblocks the actual Dockerfile diff
- A `flymine.alliancegenome.org` reservation in our infra plan (R53 public +
  private zones, ALB listener rule slot 460-470 free since rule 450 is
  mousemine, rule 400 is wormmine)

## What we need from you (Phase 0/1 deliverables, this week)

- project.xml edited: 4 dropped sources commented with dated note, RPKM
  converter wired in instead of modMine, `flybase-aberrations` source block
  added (per the brief)
- Curated `fbba_to_fbab.tsv` seed in `flymine-bio-sources/flybase-aberrations/src/main/resources/`
  (high-use balancers — FM6/CyO/TM3/TM6 et al. — long tail can be empty)
- Per-file download URLs for the 8 Bucket-D live sources (your recovery
  inventory has homepage liveness; we need the leaf file path each)
- Confirm: build from your local fork's master via volume mount, OR pin the
  Dockerfile to a SHA on your fork and bake the clone in the image?

## Cross-references

- `docs/FLYMINE_SOURCE_TO_DATA_MAP.md` — original audit, now superseded for
  Bucket D (note added at top)
- `docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md` — the FBab/FBba design
  you'll implement; unchanged
- `new_flymine/docs/BUCKET_D_RECOVERY_INVENTORY_2026-05-29.md` — your live
  probe results that drove these decisions
- `new_flymine/flymine/DOCKER_BUILD_HANDOFF.md` — your Dockerfile spec; we'll
  reply to its 5 open questions separately
- `new_flymine/docs/superpowers/specs/2026-05-28-flymine-full-no-fluff-plus-stocks-design.md`
  — the canonical design this all serves

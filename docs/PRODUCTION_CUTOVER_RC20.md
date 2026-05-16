# AllianceMine 9.0.0-rc20 Production Cutover

Date: 2026-05-13
Operator: pnuin
Outcome: live at `https://alliancemine.alliancegenome.org`

## Summary

Promoted `alliancemine-9.0.0-rc20` to production by swapping the ALB target in
`alliancemine-multitenant` TG from `172.31.59.87:8082` (previous 9.0.0 container,
went unhealthy `Target.Timeout` before cutover) to `172.31.59.87:8086`
(rc20 container with 16 template fixes + postprocess reruns + class_keys
patch). No new TG, no new rule — same swap pattern as
`docs/PRODUCTION_CUTOVER_9_0_0.md` (2026-05-01).

8082 container left running (drained from TG) as fast rollback.

## Why rc20 over previous 9.0.0

| Driver | Detail |
|---|---|
| User-reported template bugs | 14+ template defects across yeast curators (CDC28 17 blank rows, Gene→Alleles, Gene→Expression / Expression→Gene, Gene→Genomic DNA missing systematic name, Gene→UTRs 0 rows, GoSlim impossible AND, etc.) — see `docs/RC20_TEMPLATE_FIX_STATUS_2026_05_12.md` |
| Class_keys.properties typo | `taxonif` instead of `taxonid`; Complex class missing identifier/accession/name |
| Postprocess gaps in 9.0.0 | 5 postprocess steps (`create-intergenic-region-features`, `create-location-overlap-index`, `create-overlap-view`, `create-gene-flanking-features`, `populate-child-features`) had been commented out; uncommented + rerun on rc20 |
| Lost SGD curator templates | 28 hand-edited templates from old `userprofile_alliancemine_local` were restored to `rnash@stanford.edu` (see `docs/RNASH_TEMPLATE_RESTORE_2026_05_12.md`) |
| RDS perf headroom | Scaled `intermine-postgres` `db.t3.xlarge` → `db.r6i.xlarge` (16 GB → 32 GB RAM), tuned `shared_buffers=8GB`, `effective_cache_size=16GB` |
| Solr cores | Created + populated `-rc20` cores from `-9.0.0` via filesystem `cp` (1.2 GB, 14.5M docs / 53K autocomplete) |
| 8082 unhealthy | Pre-cutover health on `alliancemine-multitenant` showed `172.31.59.87:8082` = unhealthy `Target.Timeout`; production effectively degraded already |

## Pre-cutover state

| Component | Value |
|---|---|
| ALB | `alliancemine-lb` (`alliancemine-lb-309443304.us-east-1.elb.amazonaws.com`) |
| Listener | HTTPS:443 (ARN `.../listener/app/alliancemine-lb/836951d93444020c/dcc809bd897b5247`) |
| Rule priority 250 | host-header `alliancemine.alliancegenome.org` → TG `alliancemine-multitenant` |
| Target group | `alliancemine-multitenant` (type=ip, hc `GET /alliancemine/service/version`, code 200, interval 30s, hc port `traffic-port`) |
| Old target | `172.31.59.87:8082` — UNHEALTHY (`Target.Timeout`) |
| New target | `172.31.59.87:8086` — to be registered |

## Pre-flight checks (passed)

```bash
$ curl -sS http://172.31.59.87:8086/alliancemine/service/version
35

$ curl -sS 'http://172.31.59.87:8086/alliancemine/service/template/results?name=Gene_Alleles&constraint1=Gene&op1=LOOKUP&value1=CDC28&format=count'
47
```

47 = expected count after `Gene_Alleles` template fix added AGR allele columns to view. Confirms rc20 userprofile DB has saved-template overrides live and webapp serving correctly.

## Cutover commands

```bash
TG=arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b

# Register rc20
aws elbv2 register-targets --region us-east-1 \
  --target-group-arn $TG \
  --targets Id=172.31.59.87,Port=8086

# Health check confirmed `healthy` within <30 s (rc20 was already warm from pre-flight)

# Deregister 8082 (still drains for 300 s default; container stays alive)
aws elbv2 deregister-targets --region us-east-1 \
  --target-group-arn $TG \
  --targets Id=172.31.59.87,Port=8082
```

## Verification (post-cutover)

```
$ curl -sS https://alliancemine.alliancegenome.org/alliancemine/service/version
35

$ curl -sS 'https://alliancemine.alliancegenome.org/alliancemine/service/template/results?name=Gene_Alleles&constraint1=Gene&op1=LOOKUP&value1=CDC28&format=count'
47

ALB target health:
  172.31.59.87:8086 → healthy
  172.31.59.87:8082 → draining
```

## Rollback

The 8082 container is still running on multitenant. To revert:

```bash
TG=arn:aws:elasticloadbalancing:us-east-1:100225593120:targetgroup/alliancemine-multitenant/9c6cdef38cbc7e6b

aws elbv2 register-targets --target-group-arn $TG --targets Id=172.31.59.87,Port=8082
aws elbv2 deregister-targets --target-group-arn $TG --targets Id=172.31.59.87,Port=8086
```

Caveat: 8082 went `Target.Timeout` before cutover. Likely needs `pg_terminate_backend` per `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` to clear bag-upgrade deadlock + Hikari pool restart, plus webapp restart, before re-registering. Don't blind-rollback — diagnose first.

Keep 8082 container alive ≥1 week per same policy as 9.0.0 cutover (8.3.0 was kept ≥1 week).

## What ships in rc20

### Template fixes (live in `alliancemine_userprofile.savedtemplatequery`, 16 rows)

See `docs/RC20_TEMPLATE_FIX_STATUS_2026_05_12.md` table — Gene_Alleles, Allele_Identifiers, Literature_Complements, Deleted_Merged_Features_Tab, Organism_IntergenicRegions, Gene_Expression, Expression_Gene, Gene_GenomicDNA, Gene_Identifiers, Gene_UTRs, ChromosomeRegion_AllGenes, Chromosome_Gene_FeatureType, gene_overlapping_flanking_regions, Complex_Details_Participant, GoSlimTerm_Gene, GO_Terms_Tab, Organism_Genes, Gene_Variants.

**These are saved-template DB overrides — they live in `alliancemine_userprofile` and ride forward across builds as long as the userprofile DB is reused.** Future rebuilds that share `alliancemine_userprofile` inherit them automatically. Source-XML versions (`default-template-queries.xml`) NOT yet patched — separate task, see `docs/UPSTREAM_CODE_UPDATE_PLAN.md`.

### Infrastructure fixes

- `class_keys.properties`: `Complex = identifier, accession, name`; `taxonif` → `taxonid` typo fixed
- `webconfig-model.xml`: Complex `systematicName` fieldconfig reordered above `properties`
- 5 postprocess steps reactivated + rerun: `create-intergenic-region-features`, `create-location-overlap-index`, `create-overlap-view`, `create-gene-flanking-features`, `populate-child-features`
- Solr cores `-rc20` populated (filesystem copy from `-9.0.0`, 1.2 GB)
- `alliancemine_userprofile.osbag_int` for "Curated Macromolecular Complexes" manually populated (634 rows)

### Restored content

- 28 SGD curator templates attached to `rnash@stanford.edu` (private, `userprofileid=22000001`, IDs 82000016-82000043) — `docs/RNASH_TEMPLATE_RESTORE_2026_05_12.md`

## Known gaps shipped (queued for rc21 rebuild)

| Gap | Why | Fix path |
|---|---|---|
| `intron=0` (Retrieve → All genes with introns) | `Intron` items never emitted by current sgd-gff loader; 8.3.0 had 348 yeast introns from a now-removed source | `docs/INTRON_LOADING_GAP.md` Option A/B/C |
| yeast variants = 0 | `variant` table is 82K ZFIN/RGD-only, no yeast | Add yeast variants source OR extend alliance-variants |
| CDC28-style allele dedup | `alliance-alleles` source loads AGR-shape duplicates of yeast alleles | Dedup in `SgdConverter` / converter level |
| SGD allele field completeness | Pending audit, tasks #37 + #38 | Audit `sgd-allele` converter + FMS payload + model |
| `GOEvidenceCode.annotType` NULL | go-annotation source doesn't populate; workaround dropped the filter | Patch go-annotation converter |
| Yeast UTR sequence text | sgd-gff-utr doesn't link UTR → Sequence Item | Patch sgd-gff-utr converter |
| Ghost taxon 4932 | Two `S. cerevisiae` org rows (559292 + 4932); 4 orphan genes on 4932 | One-shot SQL remap OR loader normalize 4932 → 559292 |
| Source XML lag | All 16 template fixes live in DB only; `default-template-queries.xml` in upstream unchanged | PR3 in `docs/UPSTREAM_CODE_UPDATE_PLAN.md` |

## Snapshot

Snapshot `alliancemine-9.0.0-rc20` container to ECR before any further changes
(per `docs/RUNTIME_CONTAINER_BACKUP.md`). Suggested tag:
`agr_alliancemine:runtime-9.0.0-rc20` + dated alias.

## Open follow-ups

- Build rc21 with source-level fixes (task #44 / `docs/UPSTREAM_CODE_UPDATE_PLAN.md`)
- Tier 1: bake `intermine-tomcat:agr-runtime` (`docs/INTERMINE_TOMCAT_DOCKER.md`)
- Tier 2: JDBC keepalive to eliminate bag-upgrade deadlock at restart
- Audit SGD allele source completeness (tasks #37 + #38)

## Cross-references

- `docs/PRODUCTION_CUTOVER_9_0_0.md` — prior cutover (8.3.0 → 9.0.0, 2026-05-01); pattern reused here
- `docs/RC20_TEMPLATE_FIX_STATUS_2026_05_12.md` — full template fix table
- `docs/SESSION_LOG_2026_05_11.md` — multi-day rc20 fix narrative
- `docs/UPSTREAM_CODE_UPDATE_PLAN.md` — rc21 PR breakdown
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — restart with bag-upgrade kick
- `docs/RUNTIME_CONTAINER_BACKUP.md` — ECR snapshot procedure
- `docs/POST_9_0_0_PLANNING.md` — backlog

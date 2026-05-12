# Intron loading gap — `Retrieve → All genes that have introns` template

Date: 2026-05-12
Status: open, needs rebuild
Task: #29

## Symptom

`Gene_Introns` template (Retrieve → All genes that have introns) returns 0 rows for yeast in rc20. 8.3.0 returned 348 rows. Multiple yeast curators flagged this as a regression in the 9.0.0 build.

## Why it's not fixed by postprocess

The `populate-child-features` postprocess step **only propagates parent↔child references for items that already exist in the objectstore**. If no `Intron` items were emitted by any data converter during the integration phase, postprocess has nothing to wire up — it does not derive introns from MRNA exon gaps or any other source.

Verified state in `alliancemine_9_0_0_rc20` after running all 5 postprocess steps (2026-05-12 ~04:00 UTC):

| Table | Count |
|---|---|
| `intron` | 0 |
| `genesintrons` | 0 |
| `intronstranscripts` | 0 |
| `fiveprimeutrintron` | 0 |
| `senseintronicncrnagene` | 0 |

Every intron-derived table is empty. Confirms data was never loaded, not just unjoined.

## Why it worked in 8.3.0

8.3.0 integration emitted 348 yeast `Intron` items (verified via direct count on `alliancemine_8_3_0.intron` table from 8082 webapp). Whatever loader produced them in 8.3.0 was lost or disabled during the 9.0.0 rebuild. Suspect candidates:

- The 8.3.0 build's `sgd-gff` source may have used an older GFF dump that included explicit `intron` GFF lines. Newer Alliance-distributed SGD GFF may have stripped those rows.
- A separate now-removed source loaded introns from `intron.tab` or similar SGD download. Not present in current `docker/alliancemine/project.xml`.
- Possibly an `agr_intermine_data_extractor` Neo4j pull (same 8.3.0 pre-Alliance tool) — that whole path was retired.

To confirm: grep 8.3.0's `intermine.log` for "Intron" creates, OR query `alliancemine_8_3_0.dataset` for any dataset whose name suggests intron loading.

## Fix options (all require rebuild)

### Option A — Add an intron source to project.xml

If SGD distributes an intron file (e.g. `intron.tab`, `chromosomal_feature.tab` filtered to type=intron), add a new `<source>` entry to `project.xml` that loads it. Need to find the source file first.

```bash
# On the SGD download mirror, search for likely files:
ls /root/data/intermine/ | grep -i intron
# or on S3:
aws s3 ls s3://agr-db-backups/alliancemine/intermine/ | grep -i intron
```

If file exists: write or reuse a converter (e.g. tab → Item with `geneId`, `chromosomeLocation`, `primaryIdentifier`).

### Option B — Derive introns from MRNA exon gaps via custom postprocess

If no SGD-supplied intron file exists, derive introns at postprocess time. Algorithm:

```
for each MRNA:
  exons = MRNA.exons sorted by chromosomeLocation.start
  for i in 1..exons.length-1:
    intron_start = exons[i-1].end + 1
    intron_end   = exons[i].start - 1
    if intron_end > intron_start:
      create Intron item:
        primaryIdentifier = MRNA.primaryIdentifier + "_intron_" + i
        chromosomeLocation = (intron_start, intron_end, exons[i-1].strand)
        gene = MRNA.gene
        transcripts = [MRNA]
```

Implementation lives in `alliancemine-bio-sources/sgd-gff/src/main/java/.../DeriveIntronsPostProcess.java` or similar. Cost: code + rebuild + rerun postprocess.

### Option C — Source GFF that includes introns

Find a GFF file that explicitly carries `intron` feature lines and use that instead of the current SGD Transcriptome v1.0 GFF. Possibly:
- SGD's saccharomyces_cerevisiae.gff3 (direct from SGD downloads, not via Alliance)
- Ensembl Fungi yeast GFF
- RefSeq yeast GFF

Then either swap the source or run a second sgd-gff-like source pointing at the new file. Same rebuild cost.

## What needs to happen before the next build

1. **Audit 8.3.0 to find where introns came from.** SSH to AllianceMineDev → query `alliancemine_8_3_0` for sample intron rows + their `datasetid` → JOIN to `dataset` table → identify the source name. That tells us exactly which loader to restore.
   ```sql
   SELECT i.primaryidentifier, d.name AS dataset
   FROM intron i
   JOIN bioentitiesdatasets bd ON bd.bioentities = i.id
   JOIN dataset d ON d.id = bd.datasets
   LIMIT 10;
   ```
2. **Decide Option A vs B vs C** based on what 8.3.0 used.
3. **Schedule the rebuild** — fits into the same rc21 build that will dedupe alliance-alleles (task #27 follow-on) and possibly fix sgd-gff-utr transcript edges (#34 long-term).

## Workaround for users until rebuild

- `Gene_Introns` template hidden from default UI via `aspect:` tag or removal from public list, with a banner noting "yeast intron annotations temporarily unavailable in 9.0.0; restore planned for next release"
- Document as known regression in release notes
- Curators can still hit intron data via the BioMart or Python client against 8082's `alliancemine_8_3_0` DB (8082 webapp still serves 8.3.0 data)

## Verification after fix

```sql
SELECT count(*) FROM intron;
-- expect ~250-400 for yeast (348 was the 8.3.0 figure)

SELECT count(*) FROM genesintrons;
-- expect similar
```

```bash
curl 'http://172.31.59.87:8086/alliancemine/service/template/results?name=Gene_Introns&constraint1=Gene.organism.name&op1=eq&value1=Saccharomyces+cerevisiae&format=count'
# expect 250+
```

## Related work

- Task #29 — open
- `docs/SESSION_LOG_2026_05_11.md` — broader rc20 fix session record
- `docs/RC20_TEMPLATE_TRIAGE.md` — original audit (Class A postprocess block; intron was assumed to be resolved by `populate-child-features`, this doc corrects that)
- `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — separate multi-MOD discussion

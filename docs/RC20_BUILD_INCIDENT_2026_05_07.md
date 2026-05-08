# RC20 build incident + recovery — 2026-05-07/08

Full timeline of the AllianceMine rc20 build attempt that started with a
gene-loss audit, broke production rc18, and ended with a bunch of
build-pipeline fixes plus a working Gene.tsv synthesiser.

This document is verbose on purpose. The same gotchas are likely to bite
the next person who builds AllianceMine, so write it down.

---

## TL;DR

| Symptom | Real cause | Fix |
|---|---|---|
| 9.0.0 prod missing 60-72% of MOD genes | `alliance-genes` source loaded 0 rows in the original 9.0.0 build because BGI JSON files were placed in `/root/data/genes/` but the converter expects a 14-column TSV. | New `bgi_to_genes_tsv.py` synthesises Gene.tsv from BGI files. |
| Expression annotation = 0 | The `alliance-expression` checkpoint DB was dropped during the disk-full incident on 2026-04-30; integration never re-ran. | Re-run `alliance-expression` integrate. (FMS file glob was a red herring on this snapshot.) |
| First Gene.tsv build still loaded 0 rows | `bgi_to_genes_tsv.py` emitted SO **IDs** (`SO:0001217`); converter switches on SO **names** (`protein_coding_gene`). Every row hit `if (item == null) continue;`. | Translate SO ID → name in the synthesiser using `/root/data/fms/ONTOLOGY_SO.obo`. |
| `gradle builddb` ran against wrong DB → wiped rc18 prod | `/root/alliancemine/alliancemine.properties` (in-project) shadowed `/root/.intermine/alliancemine.properties` (entrypoint-templated). Gradle reads the in-project one first. The in-project copy was a stale rc18 placeholder from upstream. | Symlink the in-project file to the InterMine-convention path. Rolled back prod by pointing the alliancemine-9.0.0 webapp at `alliancemine_8_3_0` DB. |
| `project_build` failed to make checkpoint copies on RDS | Hardcoded `ssh <dump_host> createdb ...`; RDS doesn't accept SSH; `ssh` not even in the image. | Fake `ssh` wrapper at `/usr/local/bin/ssh` and `/usr/bin/ssh` that drops the host arg and execs the rest locally. |
| `project_build -V 9.0.0-rc20` couldn't open properties | It looks for `/root/.intermine/alliancemine.properties.<release>`, not the canonical name. | Symlink the versioned name → canonical: `ln -s /root/.intermine/alliancemine.properties /root/.intermine/alliancemine.properties.9.0.0-rc20`. |

---

## Background

AllianceMine 9.0.0 has been in production since 2026-05-01. On
2026-05-07 a curator filed a bug report listing ~15 broken templates
(Gene → Alleles, Gene → Expression, Gene → UTRs, etc.). The audit
that followed showed:

| Class | 8.3.0 | 9.0.0 prod |
|---|---|---|
| total gene | 459,020 | 286,572 (-37%) |
| Mouse genes | 91,412 | 30,760 (-66%) |
| Worm genes | 48,928 | 13,874 (-72%) |
| expressionannotation | 1,767,809 | 0 |
| Alliance Gene data set rows | 90K+ per MOD | **0 across all MODs** |

The gene loss was a build defect, not a data-source issue. The 9.0.0
build pipeline had never actually loaded the `Alliance Gene data set`
for any MOD other than yeast.

---

## Root cause #1 — BGI JSON vs TSV

The build container's `extract_data.py` downloads `BGI_<MOD>.json`
(per-MOD Basic Gene Information) into `/root/data/genes/`.

The `alliance-genes` source in `project.xml` is wired to read
`/root/data/genes/`:

```xml
<source name="alliance-genes" type="alliance-genes">
    <property name="src.data.dir" location="/root/data/genes"/>
    <property name="src.data.dir.includes" value="Gene.tsv"/>
</source>
```

The Java side `AllianceGenesConverter.java` does:

```java
public void process(Reader reader) throws Exception, ObjectStoreException {
    Iterator<?> lineIter = FormattedTextParser.parseTabDelimitedReader(reader);
    int count = 0;
    System.out.println("Processing Genes...");
    while (lineIter.hasNext()) {
        String[] line = (String[]) lineIter.next();
        if (count == 0) { count++; continue; }   // skip header
        if (line.length < 14) continue;          // need 14 cols
        // ...
    }
}
```

Tab-delimited 14-col reader. BGI is JSON. The `<src.data.dir.includes>`
glob *was* honoured (only Gene.tsv would be passed, JSON files
ignored), but in the historical 9.0.0 build NOBODY had created Gene.tsv
in the first place — the file simply didn't exist. The converter found
no matching files, did nothing, and the build moved on without error.

8.3.0 worked because someone had pre-staged
`/data/genes/Gene.tsv` (193 MB, 14-col, ~470K rows) on the dev host
back in Aug 2025 — produced by the now-defunct
`agr_intermine_data_extractor` Java tool that queried the Alliance
Neo4j backend. That file existed when 8.3.0's mount was
`/data/genes:/root/data/genes` (host path). The new builder mounts
`./data:/root/data` (relative to compose.yml), so the legacy host file
is invisible to the new container.

### Fix: bgi_to_genes_tsv.py

`docker/alliancemine/scripts/bgi_to_genes_tsv.py` reads each
`BGI_<MOD>.json`, extracts the 14 fields the converter wants, emits
`/root/data/genes/Gene.tsv`. Wired into `extract_data.py
build_genes_tsv()` so it runs unconditionally at end of every fetch.

`project.xml` updated to scope the alliance-genes source to `Gene.tsv`
only via `<src.data.dir.includes>`, which keeps the converter from
trying to parse the BGI JSON files as TSV.

### Field mapping

| Col | Field | BGI JSON path |
|---|---|---|
| 1 | Id | `basicGeneticEntity.primaryId` |
| 2 | SecondaryId | `basicGeneticEntity.secondaryIds[0]` |
| 3 | Synonyms | `[a, b, c]` from `basicGeneticEntity.synonyms[]` |
| 4 | CrossRefs | `[a, b, c]` from `basicGeneticEntity.crossReferences[].id` |
| 5 | Name | top-level `name` |
| 6 | Symbol | top-level `symbol` |
| 7 | MOD Description | `geneSynopsis` |
| 8 | Auto Description | empty (BGI doesn't have it) |
| 9 | Species | `basicGeneticEntity.taxonId` |
| 10 | Chromosome | `genomeLocations[0].chromosome` |
| 11 | Start | `genomeLocations[0].startPosition` |
| 12 | End | `genomeLocations[0].endPosition` |
| 13 | Strand | `genomeLocations[0].strand` |
| 14 | SoTerm | **SO term name** (translated from `soTermId` via SO.obo) |

---

## Root cause #2 — SO ID vs SO name

First version of the synthesiser dropped `gene.soTermId` straight into
column 14 — values like `SO:0001217`. The converter's switch
statement matches **names**:

```java
if (feature_type.equalsIgnoreCase("RNase_MRP_RNA_gene")) {
    item = createItem("RNaseMRPRNAGene");
} else if (feature_type.equalsIgnoreCase("protein_coding_gene")) {
    item = createItem("Gene");
} else if (...) {
    ...
}
if (item == null) {
    continue;        // every row hits this when feature_type is an SO ID
}
```

Net effect: every row dropped, items DB only had the `DataSource`
record from the BioFileConverter constructor. Integrate "succeeded"
in 18 seconds writing 0 genes. Only the `DataSource AGR` Item landed
in rc20, which then triggered the InterMine **previous-run guard** on
every retry:

```
ERROR  IntegrationWriterDataTrackingImpl
  There is already an equivalent in the database from this source
  (alliance-genes) from a *previous* run; object from source in this
  run: DataSource[name="AGR", id=3];
  object from database: DataSource[name="AGR", id=44000001]
```

### Diagnosing this without the right log

Critical detail: `System.out.println("Processing Genes...")` and the
post-loop `System.out.println("size of genes:  N")` go to **stdout**,
not to `intermine.log`. They show up in `pbuild.log` only when
`project_build`'s shell pipes the gradle child's stdout there. If
you're running gradle directly the output ends up in the terminal —
ALWAYS pipe through `tee` so you can grep later.

```bash
./gradlew --no-daemon integrate -Psource=alliance-genes 2>&1 \
    | tee manual-alliance-genes.log
grep -E "Processing Genes|size of genes" manual-alliance-genes.log
```

`size of genes: 0` is the canary that this whole class of bug fired.

### Fix: SO ID → name translation

`bgi_to_genes_tsv.py` now loads `/root/data/fms/ONTOLOGY_SO.obo` once
at start-up and builds a dict `{"SO:0001217": "protein_coding_gene", ...}`.
`row_for_gene()` translates each row's `soTermId` through the dict
(falls back to the raw ID if not found, with a warning).

After fix, `/root/data/genes/Gene.tsv` has SO names in column 14.
Top distribution from the 369K-row file:

```
145847 protein_coding_gene
 66062 gene
 43196 pseudogene
 42674 lncRNA_gene
 29164 ncRNA_gene
 15363 piRNA_gene
  4867 miRNA_gene
  4757 snoRNA_gene
  3894 lincRNA_gene
  3096 tRNA_gene
  2947 snRNA_gene
  2801 heritable_phenotypic_marker
   ...
```

All values match the converter's `if (feature_type.equalsIgnoreCase("..."))`
chain.

---

## Root cause #3 — properties file shadowing

The cluster-level damage. Independent of the gene-load bug.

The `alliancemine` upstream repo ships a default
`alliancemine.properties` at the project root (`/root/alliancemine/alliancemine.properties`)
with placeholder credentials and `databaseName=alliancemine_9_0_0_rc18`.

The container's `entrypoint.sh` templates a *different* file at
`/root/.intermine/alliancemine.properties` (the InterMine convention)
with the runtime values (rc20 in this build, etc.).

Gradle reads from the project-local file **first** — webapp/build.gradle
literally hardcodes `/root/alliancemine/alliancemine.properties`.

When `./gradlew builddb` was run inside the container, gradle picked
up the upstream's stale rc18 placeholder, connected to the **live
production rc18 database**, and ran the build-DB DDL there — drop +
recreate of every InterMine class table. Production rc18 went from
60 GB to 4 GB in seconds. AllianceMine prod broke.

### Recovery

Rolled the production webapp back to 8.3.0:

```bash
docker exec alliancemine-9.0.0 bash -c '
  for F in /usr/local/tomcat/webapps/alliancemine/WEB-INF/classes/intermine.properties \
           /usr/local/tomcat/webapps/alliancemine/WEB-INF/web.properties; do
    sed -i \
      -e "s|databaseName=alliancemine_9_0_0_rc18|databaseName=alliancemine_8_3_0|" \
      -e "s|solr/alliancemine-search-9.0.0|solr/alliancemine-search|" \
      -e "s|solr/alliancemine-autocomplete-9.0.0|solr/alliancemine-autocomplete|" \
      -e "s|project.releaseVersion=9.0.0|project.releaseVersion=8.3.0|" \
      $F
  done
'
docker restart alliancemine-9.0.0
```

The 9.0.0 WAR runs against the 8.3.0 schema fine (InterMine schemas
are mostly compatible across one minor release).

`alliancemine_8_3_0` DB on RDS is intact (459K genes, all MODs
populated). Live URL `https://alliancemine.alliancegenome.org/alliancemine/`
returns 200 against the 8.3.0 data.

### Fix in Dockerfile

```dockerfile
RUN rm -f /root/alliancemine/alliancemine.properties && \
    ln -s /root/.intermine/alliancemine.properties /root/alliancemine/alliancemine.properties
```

Symlink — single source of truth, no shadowing. `webapp/build.gradle`
still reads `/root/alliancemine/alliancemine.properties` happily; it
just resolves through the symlink to the entrypoint-templated file.

---

## Root cause #4 — project_build needs ssh

`project_build` (the InterMine perl driver) makes checkpoint dumps via:

```perl
exec "ssh", $dump_host, "createdb", "-T", $main_db, "$main_db:$source", ...
```

When `dump_host` is the RDS endpoint (which it has to be, since
that's where postgres lives in our deployment), this fails: RDS
doesn't accept SSH, and the alpine-based build container doesn't
have ssh installed anyway.

The inner `createdb` already carries `-h <dump_host>` so libpq picks
up the right server regardless of where the command runs.

### Fix

```dockerfile
RUN printf '#!/bin/sh\nshift\nexec "$@"\n' > /usr/local/bin/ssh && \
    chmod +x /usr/local/bin/ssh
```

Drops the leading host arg, exec's the rest locally. `createdb`
runs on the build container, hits RDS via the inner `-h` flag, the
copy proceeds.

Also installed at `/usr/bin/ssh` since perl's PATH lookup may differ
from bash's.

---

## Root cause #5 — versioned properties filename

`project_build -V 9.0.0-rc20` looks for
`/root/.intermine/alliancemine.properties.9.0.0-rc20`, not the canonical
`alliancemine.properties`.

### Fix

Either symlink before invoking:

```bash
ln -sf /root/.intermine/alliancemine.properties \
       /root/.intermine/alliancemine.properties.9.0.0-rc20
```

Or bake the symlink into the entrypoint:

```bash
ln -sf "${PROPERTIES_FILE}" "${PROPERTIES_FILE}.${ALLIANCE_RELEASE}-rc${RC_NUMBER}"
```

(Not yet baked — see "Open work" below.)

---

## Recovery procedure (replay)

If the same chain of issues hits the next build, this is the order
that worked:

### 1. Confirm the patches are in the running image

The current image
`alliancemine-builder:9.0.0-compiled` (sha `136a9c4dcf19` after the
in-place commit chain) contains:

| Inside container | Type | What |
|---|---|---|
| `/root/scripts/bgi_to_genes_tsv.py` | new | BGI JSON → 14-col Gene.tsv with SO name translation |
| `/root/scripts/extract_data.py` | patched | calls `build_genes_tsv()` after FMS download |
| `/root/alliancemine/project.xml` | patched | `alliance-genes` source includes `Gene.tsv` only |
| `/root/alliancemine/alliancemine.properties` | symlink | → `/root/.intermine/alliancemine.properties` |
| `/usr/local/bin/ssh` and `/usr/bin/ssh` | new | fake wrapper for project_build |

Backup tag for rollback: `alliancemine-builder:9.0.0-compiled-prepatched-20260507`.

### 2. Recreate the runtime container

```bash
docker compose run --rm alliancemine-builder bash
# entrypoint runs, properties templated, drops to shell
```

### 3. Verify properties point at the target rc

```bash
grep -E "^db.production.datasource.databaseName|^webapp.deploy.url|^index.solrurl" \
    /root/.intermine/alliancemine.properties
```

Should show `alliancemine_9_0_0_rc<N>`, not rc18 or rc20.

### 4. Pre-stage version-specific symlink

```bash
ln -sf /root/.intermine/alliancemine.properties \
       /root/.intermine/alliancemine.properties.9.0.0-rc<N>
```

### 5. Pre-create the destination DB on RDS

```bash
PGPASSWORD=... psql -h ... -U postgres -d postgres \
    -c "CREATE DATABASE alliancemine_9_0_0_rc<N>;"
```

### 6. Pre-create Solr cores

```bash
ssh ... 'sudo -u solr /opt/solr-8.11.2/bin/solr create_core -c alliancemine-search-9.0.0-rc<N>'
ssh ... 'sudo -u solr /opt/solr-8.11.2/bin/solr create_core -c alliancemine-autocomplete-9.0.0-rc<N>'
```

### 7. Run extract_data

```bash
python3 /root/scripts/extract_data.py
```

This now produces `/root/data/genes/Gene.tsv` with SO names. Verify:

```bash
awk -F'\t' 'NR>1 {print $14}' /root/data/genes/Gene.tsv | sort | uniq -c | sort -rn | head
```

Expect: `protein_coding_gene 145K`, `lncRNA_gene 42K`, etc. (NOT `SO:00012xx`.)

### 8. Run project_build

```bash
cd /root/alliancemine
./project_build -V 9.0.0-rc<N> -b -E UTF8 \
    intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
    alliancemine_9_0_0_rc<N> 2>&1 \
    | tee /root/alliancemine/build-rc<N>-$(date +%Y%m%d-%H%M).log
```

**Pipe through `tee`** every time. Without it, the converter's
"size of genes:" debug line is lost when the terminal scrolls away.

### 9. Verify alliance-genes loaded

When the alliance-genes source completes:

```bash
PGPASSWORD=... psql -h ... -d alliancemine_9_0_0_rc<N> \
    -c "SELECT count(*) FROM gene;"
```

Should be ~370K, **not 95K** (placeholder count from prior sources).

```bash
PGPASSWORD=... psql -h ... -d alliancemine_9_0_0_rc<N> \
    -c "SELECT featuretype, count(*) FROM gene GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
```

Should show ~14 distinct featuretype values, top is `protein_coding_gene`.
If `featuretype` column is all NULL → build still broken.

### 10. Resume on failure

`project_build -l` on the same dump_host + dump_prefix will reload
the latest `<prefix>:<source>` checkpoint and continue. **Always use
`-l`, never `-r`** (per `feedback_project_build_resume.md`).

If you stopped to do alliance-genes manually:

```bash
cd /root/alliancemine
./gradlew --no-daemon integrate -Psource=alliance-genes 2>&1 \
    | tee manual-alliance-genes.log

# Then resume project_build at the next source:
./project_build -V 9.0.0-rc<N> -l -E UTF8 \
    -a 'go-annotation-' \
    intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com \
    alliancemine_9_0_0_rc<N>
```

`-a 'go-annotation-'` (trailing dash) means "start at go-annotation
and continue through the rest of the action plan".

### 11. Watch storage + memory

RDS at this build size grew to 800+ GB. The auto-scale was at 1000 GB.
Keep an eye on:

- `FreeStorageSpace` (CloudWatch) — under 200 GB triggers autoscale
  delays
- `FreeableMemory` — under 500 MB means the planner spills sorts to
  disk; build slows
- `pg_database_size` for each `<prefix>:<source>` checkpoint —
  cumulative checkpoints can hit 100+ GB during a single build

Drop early checkpoints once newer ones supersede them:

```bash
PGPASSWORD=... psql -h ... -d postgres \
    -c 'DROP DATABASE "alliancemine_9_0_0_rc<N>:alliance-mgi-fasta";'
```

Only the **latest** checkpoint matters for `-l` resume.

---

## Files changed in `agr_intermine_builder`

| Path | Change |
|---|---|
| `docker/alliancemine/scripts/bgi_to_genes_tsv.py` | NEW — BGI JSON → 14-col Gene.tsv with SO name translation |
| `docker/alliancemine/scripts/extract_data.py` | patched — calls `build_genes_tsv()` after FMS download (and on `--skip-fms`) |
| `docker/alliancemine/project.xml` | patched — `alliance-genes` source `<src.data.dir.includes>=Gene.tsv` |
| `docker/alliancemine/Dockerfile` | three additions: properties symlink, fake ssh wrapper, no other gradle changes |
| `docs/RC20_BUILD_INCIDENT_2026_05_07.md` | this file |
| `docs/GENES_TSV_REBUILD.md` | written earlier in the same session, covers the BGI→TSV synthesiser design |

---

## Open work

| Item | Why | Where |
|---|---|---|
| Bake versioned-properties symlink into entrypoint | So `project_build -V <release>-rc<N>` works without manual `ln -s` | `docker/alliancemine/entrypoint.sh` |
| File upstream PR for `alliancemine-bio-sources` AllianceGenesConverter | Accept SO IDs natively (cleaner than translating) | `alliance-genome/alliancemine-bio-sources` |
| File upstream PR for `alliancemine` to ship a non-placeholder properties file | Or remove the in-project file entirely | `alliance-genome/alliancemine` |
| Replace fake ssh wrapper with a project_build patch | Less invasive long-term | `legacy/old_bash_scripts/run_data_extractor` doc |
| Switch to API-based gene fetcher | Once `alliancemine-bio-sources` `wire-api-sources` branch lands on master, deprecate `bgi_to_genes_tsv.py` and use `fetch_genes.py` | `docs/GENES_TSV_REBUILD.md` (already noted) |
| Capture `pbuild.log` from the project_build wrapper | Currently only project_build's own perl prints land in `pbuild.log`; gradle stdout is dropped to terminal | wrap `gradlew` calls in `tee` inside project_build |

---

## Lessons

1. **Don't trust task-cache results in InterMine builds.** A
   gradle integrate that exits in 18 seconds with no errors is not
   a successful integration; it's a NO-OP. Always check the
   resulting row count, not just the exit code.

2. **Always `tee` the build output.** The converter's most
   informative debug lines (`Processing Genes...`,
   `size of genes:  N`) only land on stdout. Without `tee`, by the
   time you realise something is wrong the evidence is gone.

3. **Properties file shadowing is the worst kind of bug** because
   gradle is silent about which one it picked. The container
   conventionally has both `/root/alliancemine/alliancemine.properties`
   and `/root/.intermine/alliancemine.properties`; one of them is
   stale and the other is correct, and gradle picks the stale one.
   Symlink them so this can never happen again.

4. **InterMine's previous-run guard is your friend.** It's the
   thing that turned a silent 0-row load into an obvious error on
   retry. Without it, we'd have shipped rc20 with the same broken
   alliance-genes the original build had.

5. **Per-MOD BGI JSON exists in FMS, but the format the converter
   consumes (14-col Gene.tsv) is a synthesised intermediate.** No
   single FMS file matches what `AllianceGenesConverter` reads.
   The build has to do the synthesis itself.

6. **Don't run gradle commands without verifying which DB the
   properties point at.** The 60-GB rc18 production database can be
   wiped in under a minute by a `builddb` aimed at the wrong target.
   Verify `db.production.datasource.databaseName` in
   `/root/alliancemine/alliancemine.properties` before every
   `./gradlew builddb`.

---

## Related

- `docs/GENES_TSV_REBUILD.md` — design + field mapping for the synthesiser
- `docs/INCIDENT_2026_04_30_to_05_01.md` — the earlier incident that
  also dropped the alliance-expression checkpoint
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — bag-upgrade deadlock kick
- `docs/INTERMINE_TOMCAT_DOCKER.md` — tomcat patches every container
  needs (tangentially related — the rolled-back webapp uses these)
- `legacy/old_bash_scripts/run_data_extractor` — historical reference
  for how 8.3.0's Gene.tsv was generated (Neo4j-backed Java tool)

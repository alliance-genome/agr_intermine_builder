# rc20 fix session log — 2026-05-11 / 2026-05-12

Comprehensive record of fixes applied + findings + open work after the rc20 build went live on 8086 (multitenant) and SGD curators reported template issues. Future-self reference; cross-links to TODO.md, RC20_TEMPLATE_TRIAGE.md, and TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md.

## Environment recap

| Host | Role | Notes |
|---|---|---|
| AllianceMineDev (172.31.60.197) | Build container host | Runs `alliancemine-alliancemine-builder-run-c06d6908f14f` (the rc20 builder); ProxyJump=blast |
| multitenant (172.31.59.87) | Webapp host | Runs `alliancemine-9.0.0-rc20` (port 8086), `alliancemine-9.0.0` (8082, rolled back to 8.3.0 DB), `wormmine`, `mousemine`; Solr at :8983 (native, not docker); ssh direct |
| intermine-postgres (RDS) | Production DB host | db.t3.xlarge, PG 15.12, 445 GB free / 1 TB allocated. Hosts `alliancemine_9_0_0_rc20`, `alliancemine_8_3_0`, `alliancemine_userprofile`, plus wormmine/mousemine DBs |
| user-intermine-db (RDS, old) | Historical userprofile DB | db.t3.medium, PG 12.22. Holds 4 pre-8.3.0 userprofile DBs (the canonical SGD curator template store) |

## Credentials reference (operator-local only)

- intermine-postgres master: `$RDS_PASSWORD` env in builder container
- user-intermine-db master: password retrievable from Secrets Manager `IntermineLocalPropertiesFile` — under `db.userprofile-production.datasource.password`. NEVER commit.
- SGD prod DB readonly: in `$SGD_DB_PASSWORD` env in builder

## What got fixed live on 8086

### 1. Complex bag-upgrade (2026-05-11)

Public list "Curated Macromolecular Complexes" showed 0 items even though 634 Complex rows exist in rc20.

Root causes:
- `class_keys.properties` had NO entry for Complex → bag-upgrade couldn't resolve EBI-* identifiers in `bagvalues` to Complex objects in new release DB
- `Organism = name, shortName, taxonif` had typo (should be `taxonid`) — ClassKeyHelper warned every startup

Fix:
- Added `Complex = identifier, accession, name` to class_keys.properties
- Fixed `taxonif` → `taxonid`
- Three layers patched: live container (`/usr/local/tomcat/webapps/alliancemine/WEB-INF/classes/class_keys.properties`), builder source (`/root/alliancemine/dbmodel/resources/class_keys.properties`), Dockerfile RUN block (commit `581d7cb`)
- Also manually populated `osbag_int` with 634 rows via SQL INSERT against `alliancemine_9_0_0_rc20.osbag_int` (bagid=67000001) joining `bagvalues` from `alliancemine_userprofile` to `complex.identifier`. Bag-upgrade for current rc20 webapp wouldn't re-run automatically since `intermine_state=CURRENT`; manual populate as one-time band-aid. Future builds get auto-resolved because class_keys now correct.

Source-repo commit in sibling `alliancemine` repo (wire-api-sources branch, `af455b1`) ready for upstream PR.

### 2. Complex webconfig fieldconfig reorder (2026-05-11)

Complex list default columns hid results until user manually added a column. Root cause: `webconfig-model.xml` Complex class block had `properties` (long-text) ahead of `systematicName`. Default list view picks first attribute fieldconfigs as visible columns; properties first → systematicName off-screen.

Fix:
- Moved `systematicName` above `properties` in builder source + live container + Dockerfile RUN block (commit `581d7cb`)
- Matches the prod 8082 patch that was applied manually but never committed upstream

Source-repo commit `af455b1` ready for upstream PR.

### 3. Gene_Alleles template — AGR cols added (2026-05-12)

CDC28 returned 47 alleles with 17 blank rows; TFC3 returned 4 with 2 blank. ACT1 returned 105 with 38 blank deeper in pagination. Pattern: SGD-source allele records populate `allelesgdid/name/alleleClass`; AGR-source (alliance-alleles) records populate `alleleId/alleleSymbol/alleleType`. Template view selected only SGD fields → AGR rows rendered as blank.

Fix:
- UPDATE `savedtemplatequery` row 32000295 in `alliancemine_userprofile`: extended view from 11 cols to 14 cols by inserting `Gene.alleles.alleleId Gene.alleles.alleleSymbol Gene.alleles.alleleType` after `Gene.alleles.alleleClass`. dataTypes count 11→14.
- Source XML in builder (`/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` line 345) patched with same change.
- Restarted 8086. Verified: 47 rows for CDC28 all populated, 14 cols, AGR rows show their AGR triplet, SGD rows show their SGD triplet.

Note: AGR rows for yeast are mostly duplicates of SGD-source alleles (same allele under both schemas). Dedup planned for next build via alliance-alleles converter fix.

### 4. Allele_Identifiers template — multiplex + LOOKUP (2026-05-12)

Yeast users got 0 results because template constrained `Gene.alleles.alleleSymbol = sa45217` (`=` op, not LOOKUP; ZFIN value; AGR-only field).

Fix:
- Extended `Allele` class key in class_keys.properties from `alleleId, alleleSymbol` → `alleleId, alleleSymbol, name, allelesgdid` so LOOKUP resolves yeast SGD allele names.
- INSERT new `savedtemplatequery` row (id 32000462) with multiplex view (12 cols including both SGD and AGR allele triplets), constraint `Gene.alleles LOOKUP cdc28-4`, default org `S. cerevisiae`.
- Source XML and live container both patched. Webapp restarted.

### 5. Solr cores populated for rc20 (2026-05-12)

8086 webapp configured to use `alliancemine-search-9.0.0-rc20` + `alliancemine-autocomplete-9.0.0-rc20` cores, but both were empty. Keyword search box on 8086 returned 0 results despite rc20 DB having 14.5M indexable docs.

Root cause: 5/8 indexing run wrote 14.5M docs to `alliancemine-search-9.0.0` core (NOT `-rc20`) because alliancemine.properties at index-time had `index.solrurl=...alliancemine-search-9.0.0` (no rc suffix). Build reported "BUILD SUCCESSFUL in 18m 28s" but indexed the wrong core. Silent misconfiguration.

Fix (took ~3 min instead of 18-min full re-index):
1. UNLOAD empty `-rc20` cores via Solr admin API (with `deleteIndex/DataDir/InstanceDir=true`)
2. `cp -r /var/solr/data/alliancemine-search-9.0.0 /var/solr/data/alliancemine-search-9.0.0-rc20` on multitenant (1.2 GB), `chown -R solr:solr`
3. Remove the auto-created `core.properties` from the copied dir (Solr otherwise complains "another core is already defined there")
4. CREATE rc20 cores via Solr admin API pointing at the copied instance dirs
5. Verified: `-rc20` search core has 14,533,301 docs, autocomplete 53,093 docs

Both `-9.0.0` cores preserved (1.2 GB extra disk, +0.05 GB autocomplete).

**Important for future builds**: alliancemine.properties at index-time MUST contain the right rc suffix. Verify before running create-search-index. Better: add a build-pipeline smoke check that queries the target core's numFound after indexing finishes.

## Diagnoses without fixes yet (XML edits queued; restart-batched)

For remaining template fixes that are XML-only edits (no rebuild), batch all edits to userprofile savedtemplatequery rows + ONE restart at the end. Each restart costs ~3-5 min on rc20 (Spring + JSP + ObjectStoreSummary + bag-upgrade). Don't restart per-template.

Templates remaining in XML-only fix track:
- Gene_Variants — hide for yeast OR multiplex (ZFIN-only path)
- Literature_Complements — drop 3 always-blank cols
- Gene_Expression / Expression_Gene — change ZFIN-default LOOKUP + OUTER on location
- Gene_GenomicDNA — delete AGR duplicate at line 105 (or fix its defaults); line 451 SGD already has full cols
- Gene_Identifiers — add `Gene.secondaryIdentifier` + `Gene.crossReferences.source.name` + replace ZFIN defaults
- Gene_UTRs — rewrite path `Gene.transcripts.UTRs.*` → `Gene.UTRs.*`; drop stale `dataSets.name='SGD data set'` constraint
- ChromosomeRegion_AllGenes — fix default org `S. cerevisiae S288C` → `S. cerevisiae` (or delete AGR duplicate at line 15)
- Chromosome_Gene_FeatureType — fix default fly → yeast (or delete AGR duplicate at line 23)
- Organism_Genes — fix `S. cerevisiae S288C` default
- Complex_Details_Participant — AND'd `accession=CPX-599` + `name CONTAINS "U4/U6..."` (different complexes) → switch to OR or drop one default
- GoSlimTerm_Gene — AND'd `annotType=manually curated` + `annotType=high-throughput` (impossible) → switch to OR
- GO_Terms_Tab — empty `ONE OF` namespace list → pick default
- Deleted_Merged_Features_Tab — verify if `Gene.modDescription` exists in model first; if yes XML-only; if not, model addition + rebuild

## Postprocess gaps — uncomment + rerun

5 postprocess steps were commented out in builder's `/root/alliancemine/project.xml`. Now uncommented (in builder + in-repo `docker/alliancemine/project.xml`). Need to rerun against rc20 DB.

| Step | Unlocks | ETA |
|---|---|---|
| create-intergenic-region-features | `intergenicregion` table (currently 0); Retrieve→All intergenic regions; Gene→Upstream intergenic | 5-10 min |
| create-location-overlap-index | Location B-tree indexes for overlap queries | 1-2 min |
| create-overlap-view | overlap-pair materialized view; `*.overlappingFeatures.*` paths | 2-5 min |
| create-gene-flanking-features | `geneflankingregion` table (currently 0); Gene→Flanking features | 5-15 min |
| populate-child-features | parent→child propagation; expected to populate `intron` table (currently 0); Retrieve→All genes with introns | 5-10 min |

Plus re-index (no longer needs to be 18 min if we just need rc20 to be re-pointed — alternative is to swap cores):
- create-search-index ~18 min full re-index (or skip if cores are already correct)
- create-autocomplete-index ~5 min

Pre-flight: pg_dump rc20 to S3 first as restore point. User canceled the running pg_dump earlier (pid 23552 was 1.4 GB into 7-8 GB target). Restart fresh dump piped directly to S3:

```bash
ssh AllianceMineDev
docker exec alliancemine-alliancemine-builder-run-c06d6908f14f bash -lc \
  'PGPASSWORD=$RDS_PASSWORD pg_dump -h $RDS_HOST -U $RDS_USER -F c -d alliancemine_9_0_0_rc20 \
   | aws s3 cp - s3://agr-db-backups/db-backups/alliancemine/alliancemine_9_0_0_rc20_20260512.dump \
     --expected-size 8000000000'
```

## Hidden gotchas discovered this session

### `user-intermine-db` RDS holds historical userprofile DBs

Old RDS instance hidden in plain sight. PG 12.22, db.t3.medium. Holds 4 userprofile DBs from pre-8.3.0 migration:

| DB | Saved templates |
|---|---|
| `userprofile_alliancemine_local` (underscores) | **90** ← canonical SGD curator store |
| `userprofile-alliancemine-stage` (dashes) | 75 |
| `userprofile-alliancemine-prod` | 65 ← matches current `alliancemine_userprofile` count exactly |
| `userprofile-alliancemine-local` | 65 |

When SGD curators say "X used to work" — they may be remembering the 90-template `_local` version. 25 templates exist there but NOT in current prod userprofile. Migration to new RDS pulled the `-prod` set (65), not `_local` (90).

Local dumps saved at `dumps/old_userprofile/` (gitignored). Restore plan in TODO #39.

### Two yeast organism rows

`organism` table has two `shortName='S. cerevisiae'` entries:
- id 25000004, taxon 559292 (S288C reference) — 7964 genes
- id 32000001, taxon 4932 (legacy generic) — **4 ghost genes**

Both share shortName so most template filters `= 'S. cerevisiae'` match both transparently. But: `S. cerevisiae S288C` (the AGR template default) matches NEITHER. And 4 yeast genes are stranded on the wrong taxonid.

Fix: source-loader normalization (collapse 4932 → 559292 in fetcher) OR one-shot SQL remap.

### Properties shadowing trap (recurring danger)

`/root/alliancemine/alliancemine.properties` (in-project, hardcoded) shadows `/root/.intermine/alliancemine.properties` (entrypoint-templated). Gradle reads project-local first. Upstream's project-local file has stale rc18 placeholder. Misaimed `./gradlew builddb` against this destroyed live rc18 prod on 2026-05-07 (see RC20_BUILD_INCIDENT_2026_05_07.md).

Dockerfile symlinks the in-project file to `/root/.intermine/...` so they're the same file. Verified working after rc20 build. **Always sanity-check `db.production.datasource.databaseName` before any `./gradlew builddb`**.

### Solr URL drift in alliancemine.properties at indexing time

The 5/8 indexing run indexed wrong core because alliancemine.properties had `alliancemine-search-9.0.0` (no rc suffix) at runtime. Currently correct (`alliancemine-search-9.0.0-rc20`) but worth verifying before every reindex. Possibly entrypoint.sh has order-of-operations bug where rc suffix isn't applied before postprocess runs.

### Each webapp restart = 3-5 min warm-up

Even fast hits afterwards (sub-second), but the warm-up window blocks all requests:
- WAR unpack
- Spring + Struts init
- JSP precompile
- ObjectStoreSummary load
- Bag-upgrade for all bags (variable; rc20 has 4+ public bags)

Batch all XML edits, ONE restart at end. Don't restart per fix.

### Allele class key needs broader fields

Default `Allele = alleleId, alleleSymbol` (AGR-only). Yeast SGD alleles populate `name`/`allelesgdid` instead. Extended to `Allele = alleleId, alleleSymbol, name, allelesgdid` this session. Update in: live container + builder source. Add to Dockerfile RUN block as part of future commit.

## Key paths / commands

### Builder paths
- `/root/alliancemine/webapp/src/main/resources/default-template-queries.xml` — template definitions
- `/root/alliancemine/dbmodel/resources/class_keys.properties` — class keys
- `/root/alliancemine/webapp/src/main/webapp/WEB-INF/webconfig-model.xml` — UI display config
- `/root/alliancemine/project.xml` — sources + postprocess

### Webapp runtime paths (inside `alliancemine-9.0.0-rc20` container on multitenant)
- `/usr/local/tomcat/webapps/alliancemine/WEB-INF/classes/class_keys.properties` — overrides JAR-internal copy
- `/usr/local/tomcat/webapps/alliancemine/WEB-INF/webconfig-model.xml`
- `/usr/local/tomcat/intermine.log` — runtime log

### Solr cores
- Native install on multitenant, `/var/solr/data/<corename>/`
- 6 alliancemine cores: search/autocomplete × {unversioned, -9.0.0, -9.0.0-rc20}
- API: http://172.31.59.87:8983/solr/admin/cores

### Userprofile DB (savedtemplatequery)
- `alliancemine_userprofile` on intermine-postgres
- Schema: `(id integer pkey, templatequery text, userprofileid integer)`
- 65 saved templates by superuser (userprofile.id=1000001)
- To UPDATE/INSERT use `$mytag$ ... $mytag$` dollar-quoting to avoid escape hell

### Useful one-liners

```bash
# Count templates loaded from saved + WAR XML on webapp
curl -s 'http://172.31.59.87:8086/alliancemine/service/templates?format=json' | python3 -c "import json,sys; print(len(json.load(sys.stdin)['templates']))"

# Run a template via REST with default constraints (returns count)
curl -s "http://172.31.59.87:8086/alliancemine/service/template/results?name=<NAME>&format=count"

# Inspect a template body
PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -U postgres -d alliancemine_userprofile -A -t \
  -c "SELECT templatequery FROM savedtemplatequery WHERE templatequery LIKE '<template name=\"<NAME>\"%';"

# Active RDS queries (excluding mine)
PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -U postgres -d alliancemine_userprofile -c "\
  SELECT pid, age(now(),query_start) AS dur, state, wait_event, application_name, datname, left(query,80) \
  FROM pg_stat_activity \
  WHERE state IN ('active','idle in transaction') AND application_name != 'psql' \
  ORDER BY dur DESC NULLS LAST LIMIT 10;"

# Solr core doc count
curl -s 'http://172.31.59.87:8983/solr/<corename>/select?q=*:*&rows=0&wt=json' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['response']['numFound'])"
```

## Cross-references

- `TODO.md` — current task index (12 open tasks)
- `docs/RC20_TEMPLATE_TRIAGE.md` — original full audit doc
- `docs/RC20_BUILD_INCIDENT_2026_05_07.md` — rc20 build incident timeline
- `docs/TEMPLATE_DESIGN_MULTIMOD_DISCUSSION.md` — multi-MOD allele/expression shape decision
- `docs/POSTPROCESS_BLOCK_REENABLE.md` — postprocess rerun procedure
- `docs/TEMPLATE_FIX_GENE_UTRS.md` — Gene_UTRs path-rewrite plan
- `docs/IAM_POLICIES_PNUIN_RDS.md` — RDS reboot/scale grant (already applied, RDSManageIntermine inline policy)
- `docs/RUNBOOK_ALLIANCEMINE_RESTART.md` — restart procedure + bag-upgrade kick

## Commits made this session (local-only, NOT pushed)

```
agr_intermine_builder development:
  398122a  Dockerfile: bake rc20 webapp + build-host patches
  581d7cb  Dockerfile: bake Complex class_keys + taxonif fix
  6750da8  build: Gene.tsv synthesis + rc20 template triage
  b92ff4e  ops: rc18/rc20 runbooks, multitenant backup/restore, kill-stuck cron
  abbbfc5  docker: intermine-tomcat-1x scaffold + mousemine container
  785d154  docs: backend migration plans, IAM policy, perf + WAF, TODO

alliancemine wire-api-sources:
  af455b1  Fix Complex bag-upgrade + webconfig column order; correct taxonif typo
```

Pending uncommitted local edits (will be next session's commit):
- `docker/alliancemine/project.xml` — 5 postprocess steps uncommented
- `docker/alliancemine/Dockerfile` — should also add Allele class_key extension to RUN block
- Source patches in builder for: Gene_Alleles view, Allele_Identifiers (new template body in DB; should mirror in source XML)
- `dumps/` — operator-local userprofile + rc20 backups (gitignored)

## What I learned for future sessions

1. **Solr cores can silently index to the wrong place.** Always verify `numFound` after `create-search-index` finishes. The build log saying "completed" doesn't mean the right core got the data.
2. **InterMine has TWO template stores** — `default-template-queries.xml` in WAR + `savedtemplatequery` in userprofile DB. Saved wins. Patch both for consistency: live for immediate effect, source XML for next build.
3. **Class keys gate LOOKUP behavior.** When LOOKUP fails for a class, check `class_keys.properties` before assuming data is missing. Adding fields here is cheap and durable.
4. **Bag-upgrade is stateful per-bag.** Once a bag's `intermine_state=CURRENT`, restart won't re-run upgrade. Manual `osbag_int` populate is a band-aid; class_keys fix is the durable answer.
5. **The historical user-intermine-db RDS** is the only place 25 lost SGD curator templates still exist. Don't delete that RDS until templates are extracted.
6. **`pg_stat_activity` distinguishes ClientWrite from RDS-side bottlenecks.** When `wait_event=ClientWrite` and CPU is low, RDS is not the slow part — it's the receiving side (network or local I/O).
7. **Solr core copy needs core.properties removed** or it conflicts with the CREATE call.

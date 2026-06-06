# FlyMine Deploy 2026-06-05

End-to-end record of the first FlyMine deploy on AGR multitenant infrastructure: build container, Solr indexes, Tomcat container, profile DB, and the runtime patches that turned a generic InterMine 5.1.0 / FlyMine fork into a working webapp.

## Final state

| Component | Value |
|---|---|
| Public URL | (pending) `flymine.alliancegenome.org` — needs ALB target group + Route53 |
| Internal URL | `http://172.31.59.87:8085/flymine/begin.do` |
| Webapp container | `flymine` on multitenant (`intermine-tomcat:agr-1x-runtime`, port 8085) |
| Main DB | `flymine_v0-2026-05-31_rc2` on `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com` — **20 GB** |
| Profile DB | `flymine_userprofile_test` — seeded by `CREATE DATABASE … TEMPLATE wormmine_userprofile` |
| Items DB | `flymine_items` (rebuilt each integration) |
| Solr | `flymine-search` (3 727 344 docs) + `flymine-autocomplete` (199 540 docs) on `172.31.59.87:8983` |
| Build container | `flymine-build` (long-running) on AllianceMineDev `172.31.60.197`; image `100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest` |
| Release tag | `v0-2026-05-31`, rc2 |

## Data summary

### Sources active in `project.xml`

71 source entries; 26 carried data into the rc2 build after Phase 2 round 4 (per `FLYMINE_PHASE2_ROUND3_CLOSEOUT_HANDOFF_2026_06_05.md`). The dominant loaders:

- **`chado-db-flybase-dmel`** — FlyBase chado dump (FB2026_01) on local `chado-pg` Postgres; provides genes, transcripts, exons, alleles, FBti insertions, FBab aberrations, FBba balancers, FBtp construct cross-refs, ontologies, publications, GO annotations, stocks.
- **`chado-db-flybase-dpse` / `chado-db-flybase-others`** — non-melanogaster Drosophila species.
- **`flybase-aberrations`**, **`flybase-allele-descriptions`**, **`flybase-allele-stubs`**, **`flybase-transgenic-constructs`** — lean source patches we wrote (or sibling did) for fields chado doesn't carry.
- **`uniprot`** — D. mel proteins.
- **`do`**, **`fly-anatomy-ontology`**, **`fly-development-ontology`**, **`fly-misc-cvterms`**, **`go-annotation`** — ontologies + GO.
- **`drosophila-homology`** — pre-computed orthologs.
- **`flybase-*-fasta`** — gene / CDS / UTR FASTA per species.

### Class counts (from `objectstoresummary.properties`)

`InterMineObject` (catch-all) = **17 600 543** rows.

Top loaded classes:

| Class | Count |
|---|---|
| SequenceFeature | 2 606 748 |
| OntologyRelation | 815 610 |
| TransposableElementInsertionSite | 394 906 |
| PhenotypeAnnotation | 383 050 |
| SequenceCollection | 352 436 |
| Allele | 329 847 |
| Synonym | 303 215 |
| OntologyAnnotation | 182 289 |
| GOAnnotation | 182 289 |
| Gene | 164 765 |
| TransgenicConstruct | 163 626 |
| Publication | 154 254 |
| UTR | 60 549 |
| OntologyTerm | 58 700 |
| RegulatoryRegion | 58 506 |
| Protein | 57 911 |
| ProteinDomain | 51 489 |
| Transcript | 35 118 |
| ThreePrimeUTR | 30 324 |
| Aberration | 23 870 |
| PointMutation | 7 008 |
| TransposableElement | 6 306 |
| SOTerm | 2 312 |

Full per-class breakdown lives in `/usr/local/tomcat/webapps/flymine/WEB-INF/objectstoresummary.properties` (106 entries, generated from DB row counts — see "Runtime patches" below).

### Post-processes that ran

15 post-processes defined; the two that mattered for cutover:

- **`create-search-index`** — populated `flymine-search` core, 4m 44s, 3 727 344 docs.
- **`create-autocomplete-index`** — populated `flymine-autocomplete` core, 24s, 199 540 docs.

The remaining 13 (`create-utr-references`, `make-spanning-locations`, etc.) had already run during Phase 2 round 4 integration.

## Build & deploy sequence

### 1. Build (Phase 2 round 4 — finished before this session)

`project_build` 5h+ run produced rc2 DB at 20 GB. 26 sources active. PROJECT_BUILD_EXIT=0.

### 2. Solr postprocess — `create-search-index`

Hit four traps before it succeeded:

1. **Solr down on multitenant** — `sudo systemctl start solr`.
2. **`SolrServerException: Server refused connection at localhost:8983`** — `dbmodel/resources/keyword_search.properties` ships with `index.solrurl = http://localhost:8983/solr/flymine-search`. The dbmodel classpath copy wins over `~/.intermine/flymine.properties` for the postprocess merge. Patched at Dockerfile build time: `sed` replaces `localhost:8983` with `172.31.59.87:8983` in both `keyword_search.properties` and `objectstoresummary.config.properties`.
3. **`RuntimeException: Indexing failed`** — actual cause hidden behind gradle wrapper; surfaced only in `intermine.log`: `PathException: 'Gene.pathways' not in model 'genomic'`. Removed `pathways` from `index.references.Gene = ...` and commented out `index.facet.multi.Pathway = pathways.name`. `kegg-pathway` / `reactome` sources aren't loaded in the slim build.
4. **HikariCP RDS connection storm** — `db.production` pool size brought down to 10 max / 2 min; `db.common-tgt-items` to 5 / 1; `db.userprofile-production` to 3 / 1. Total cap 18, well under RDS `max_connections=250`.

After patches: 4m 44s, **3 727 344 docs in `flymine-search`**.

### 3. Solr postprocess — `create-autocomplete-index`

Failed with bare "Creating autocomplete index failed" — gradle swallowed the underlying stack. Root cause: `objectstoresummary.config.properties` declares `autocomplete = name` for classes (`Disease`, `Pathway`, `MRNAExpressionTerm`) that aren't in the slim model. AutoCompleter's `Class.forName` misses abort the whole task. Commented those three out at Dockerfile build time.

After patch: 24s, **199 540 docs in `flymine-autocomplete`**.

### 4. WAR build

`./gradlew :webapp:war` — 131 MB WAR written to `webapp/build/libs/webapp.war`. Extracted from container via `docker compose run -v /tmp/flymine-debug:/debug …; cp /root/flymine/webapp/build/libs/*.war /debug/`.

### 5. WAR ship to multitenant

scp via laptop hop (multitenant doesn't accept direct SSH from dev): `dev:/tmp/flymine-debug/flymine.war` → laptop `/tmp/flymine.war` → multitenant `/tmp/flymine.war`.

### 6. Tomcat container launch

```
docker run -d --name flymine --restart unless-stopped -p 8085:8080 \
  -v /tmp/flymine.war:/usr/local/tomcat/webapps/flymine.war:ro \
  --add-host agr.stage.alliancemine.solr.server:172.17.0.1 \
  --add-host agr.stage.flymine.solr.server:172.17.0.1 \
  -e JAVA_OPTS="-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx6g -Xms2g" \
  intermine-tomcat:agr-1x-runtime
```

WAR deployed in 4.5 s, Tomcat 8.5.100 / Java 11. HTTP 302 on `/flymine/`, 503 on `/flymine/begin.do`.

### 7. Profile DB schema

`UnavailableException: userprofileOSW is null` — table `intermine_metadata` missing. Did NOT run `:dbmodel:buildDB -Pos=userprofile-production` (would re-trigger 10-min compile). Instead:

```sql
DROP DATABASE flymine_userprofile_test;
CREATE DATABASE flymine_userprofile_test TEMPLATE wormmine_userprofile;
```

The wormmine template carries 278 user accounts and the full intermine_metadata + bag/list/tag/savedquery schema. `flymine_userprofile` (production) doesn't exist yet — to be created later.

### 8. Superuser account row

Webapp checks `superuser.account = superuser@mail_account` and fails init if absent:

```sql
INSERT INTO userprofile (username, password, superuser, id, localaccount)
VALUES ('superuser@mail_account', 'X', true, 999999999, true);
```

(`X` is a placeholder; password isn't used for OpenID/Google login.)

Restart container → HTTP 200 on `/flymine/begin.do`.

### 9. In-place webconfig patch (broken widgets)

begin.do showed `webconfig-model.xml is not valid` warning enumerating ~9 widgets referencing classes/paths missing from the slim model (`FlyAtlasResult`, `MRNAExpressionResult`, `Pathway`, `miRNAinteractions`, `proteinDomainRegions`, …). Removed the offending widgets from the source at Dockerfile build time via awk-delete on each `<graphdisplayer id="X" …/>` / `<enrichmentwidgetdisplayer id="X" …/>` block.

Widgets removed:
- `flyatlas_for_gene` / `flyatlas_for_probeset` (FlyAtlasResult, ProbeSet)
- `flyfish` / `bdgp` / `bdgp_enrichment` (MRNAExpressionResult, MRNAExpressionTerm)
- `miranda_enrichment` (miRNAinteractions)
- `pathway_enrichment` (pathways)
- `prot_dom_enrichment_for_gene` / `prot_dom_enrichment_for_protein` (proteinDomainRegions)

For the running container we hot-patched the deployed `WEB-INF/webconfig-model.xml` via `docker cp` + restart; future WAR builds bake it in.

### 10. cargoRedeployRemote attempt — failed

Tried `:webapp:cargoRedeployRemote` to push the new WAR via tomcat manager. Failed with `FAIL - Unable to delete [/usr/local/tomcat/webapps/flymine.war]` because the WAR is a read-only bind-mount, not a regular file. The webapp ended up in `stopped` state; brought it back with `curl -u manager:manager …/manager/text/start?path=/flymine`.

### 11. Hand-rolled `objectstoresummary.properties`

`:webapp:summariseObjectStore` runs but doesn't write the file — fails silently on a `ClobAccess` value-type check against `Sequence.residues`, with the underlying stack swallowed. Adding `noSummary = Sequence` to `objectstoresummary.config.properties` didn't help (different property name, or different code path).

Generated the file directly from the DB:

1. Extracted 105 InterMine class names from `genomic_model.xml` inside `dbmodel.jar`.
2. For each, mapped CamelCase → lowercase table name and ran `SELECT count(*)`.
3. Emitted `org.intermine.model.bio.<Class>.classCount=<n>` lines plus a top-level `org.intermine.model.InterMineObject.classCount=17600543`.

File lives at `/usr/local/tomcat/webapps/flymine/WEB-INF/objectstoresummary.properties` (alliancemine uses the same WEB-INF root path, not `WEB-INF/classes/`).

`docker cp` + `manager/text/reload` brought the warnings down to zero.

## Runtime patches baked into the image (`docker/flymine/Dockerfile`)

All applied at image-build time, idempotent:

1. **Bintray strip** (`flymine-bio-sources/build.gradle`) — removes 3 dead JFrog classpath / plugin entries.
2. **Heap** (`flymine/gradle.properties`) — appends `org.gradle.jvmargs=-Xmx48g -XX:+HeapDumpOnOutOfMemoryError`.
3. **Solr URL hardcoded** — `index.solrurl` / `autocomplete.solrurl` patched from `localhost` → `172.31.59.87:8983` in both `keyword_search.properties` and `objectstoresummary.config.properties`.
4. **Gene.pathways drop** — `index.references.Gene = goAnnotation.ontologyTerm` (was `pathways goAnnotation.ontologyTerm`).
5. **Pathway facet skip** — `index.facet.multi.Pathway = pathways.name` commented.
6. **Autocomplete class drop** — `Disease`, `Pathway`, `MRNAExpressionTerm` autocomplete lines commented.
7. **`noSummary = Sequence`** appended (didn't help — kept for future investigation).
8. **Webconfig widget removal** — 9 graphdisplayer / enrichmentwidgetdisplayer blocks awk-deleted by id.
9. **Pre-compile at build time** (added but **not yet pushed**) — the long `RUN cd /root/flymine-bio-sources && ./gradlew install` block that obsoletes `compile_if_needed` and `/root/.needs_compile`. Will land in the next image rebuild.

`scripts/build_and_push.sh` switched to `docker buildx build --platform linux/amd64 --push` so Mac builds produce amd64 manifests.

`docker-compose.yml`, `entrypoint.sh`, `properties/flymine.properties.template`, `.env.example` also updated for Solr env vars + Hikari pool sizing + chado-pg routing — see git diff.

## Day-0 data-fill patches (2026-06-06)

Post-deploy audit showed many user-facing attribute columns were NULL even when the underlying entity was loaded. Two layers of fix:

### Tier 1 — SQL fallbacks (`scripts/patch_*.sql`, run by `finalize_build.sh`)

Idempotent, runs in seconds, baked into the image (copies via Dockerfile, symlinked as `/usr/local/bin/finalize_build`). Apply between `:dbmodel:postprocess` and `:webapp:summariseObjectStore` so the WAR's `objectstoresummary.properties` reflects the patched data.

| Table | Patch |
|---|---|
| chromosome | `name = symbol = primaryidentifier` for the 26 chado-loaded chromosomes |
| aberration | `name = symbol`; `secondaryidentifier = primaryidentifier` |
| balancer | same |
| transgenicconstruct | same |
| transcript | `name = secondaryidentifier` ("CG10129-RA") |
| transposableelement / transposableelementinsertionsite | `name = symbol or secondaryidentifier` |
| gene (90% skeleton entries from chado-db-flybase-{others,dpse}) | `symbol = name = secondaryidentifier = primaryidentifier` so the FBgn renders in cross-class queries instead of an empty cell |
| protein | `name = symbol = primaryaccession` (35K / 58K rows) |
| proteindomain | `symbol = primaryidentifier`; `secondaryidentifier = shortname` |
| stock | `name = secondaryidentifier` (the genotype string); `symbol = primaryidentifier` |
| allele | `name = symbol`; `secondaryidentifier = primaryidentifier` |

Post-patch coverage for the key columns:

- aberration.name: 0% → 100%
- balancer.name: 0% → 99.7% (2 of 644 have no symbol either)
- gene.symbol: 10% → 100%
- gene.name: 7% → 100%
- transgenicconstruct.name: 0% → 100%
- transposableelementinsertionsite.name: 0% → 100%
- protein.name: 0% → 61% (rest have no primaryaccession)
- stock.name: 0% → 100%
- allele.name: 0% → 100%

These don't conjure missing data — they make the existing identifier visible where the chado loader left a NULL.

### Tier 2 — Source-level fixes (next build)

Deep data still missing; needs source-code or project.xml work:

| Gap | Fix |
|---|---|
| `publication.{title,journal,year,firstauthor,doi,…}` all NULL | Re-enable `update-publications` with an NCBI API key (currently disabled in project.xml; eutils rate-limits at 144K pubs without key). Alternative: pre-fetch a FlyBase publications.xml feed and point `src.data.file` at it |
| `protein.{molecularweight,uniprotname,uniprotaccession}` all NULL | Re-run `uniprot` source with `loadFullRecord=true` style attribute pass (current run only kept primaryaccession + sequence) |
| `aberration.description` / `balancer.description` all NULL | Patch sibling's `flybase-aberrations` lean source to emit description from chado `featureprop` (the chado-db loader doesn't pull these for aberration/balancer entity types) |
| `transposableelementinsertionsite` chromosome attached on 18% only | Drop FBti entries without chromosome location at integration time, OR re-run chado-db with insertion-loc enabled — most non-located FBtis are stubs |
| `gene.symbol = FBgn…` for non-D.mel (slim build) | Either keep the fallback (FBgn is at least a valid identifier) OR drop `chado-db-flybase-{others,dpse}` from project.xml for a D.mel-only mine |

These all land as edits to the FlyMine fork in `~/Projects/alliance/new_flymine/` and re-runs of specific `:dbmodel:integrate -Psource=…` steps; coordinate with the sibling session before scheduling.

## Remaining follow-ups

- **ALB target group + Route53 for `flymine.alliancegenome.org`** — internal-only today.
- **Pre-compiled image push** — Dockerfile change is in place locally; needs a `scripts/build_and_push.sh` run. Will eliminate the 10-min `compile_if_needed` startup on every fresh container.
- **`flymine_userprofile` (production profile DB)** — currently using `_test` copy of wormmine. Create real one when ready to cut over.
- **`webapp.baseurl` / `WEBAPP_BASEURL`** — currently baked as `http://localhost:8080`; set `WEBAPP_BASEURL=http://flymine.alliancegenome.org` before cutover WAR build.
- **Investigate `summariseObjectStore` ClobAccess failure properly** — the hand-rolled summary works but doesn't have field-value lists or null-field info, which the webapp's drop-downs/facets use.
- **`flymine_userprofile_test` superuser row** — `superuser@mail_account` inserted as a stub; replace with a real maintainer account before production cutover.
- **Backup the runtime container** — see `docs/RUNTIME_CONTAINER_BACKUP.md` for the ECR snapshot pattern (`runtime-v0-2026-05-31-rc2`).

## References

- Phase 2 round 3/4 hand-offs: `docs/FLYMINE_PHASE2_ROUND3_CLOSEOUT_HANDOFF_2026_06_05.md` and sibling reply in `../new_flymine/docs/HANDOFF_TO_BUILDER_PHASE2_ROUND3_CLOSEOUT_2026-06-05.md`.
- AllianceMine equivalents (same container/runtime pattern): `docs/RC20_BUILD_INCIDENT_2026_05_07.md`, `docs/PRODUCTION_CUTOVER_9_0_0.md`.
- InterMine Solr-config trap memory: `~/.claude/projects/-Users-nuin-Projects-alliance-agr-intermine-builder/memory/feedback_intermine_solr_traps.md`.

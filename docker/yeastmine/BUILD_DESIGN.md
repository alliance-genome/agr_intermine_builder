# YeastMine Build — Design

**Status:** Approved design, pre-implementation. Captures the plan to take the
`docker/yeastmine/` scaffold to a full end-to-end data integration on RDS.

**Goal (this round):** a complete YeastMine integration through `:webapp:war`,
running on the shared RDS, reusing AllianceMine's SGD plumbing and orchestrated
in the FlyMine/WormMine style (no `build_full.py`).

**Out of scope (this round):** deploy to the multitenant Tomcat, ALB target
registration, public URL/CloudFront routing. Those follow once a WAR builds
clean on RDS.

---

## 1. Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| How far this round | Full end-to-end integration on RDS (through `:webapp:war`); deploy deferred |
| Data sourcing | Reuse AllianceMine's SGD plumbing (same SGD Postgres + S3 sync), not an independent fetcher |
| Orchestration style | FlyMine/WormMine pattern: shell + `extract_data.py` + `finalize_build.sh`, manual `project_build`; **no** ported `build_full.py` |
| Source provenance | **Approach A** — local fork COPY'd in (flymine `source/` pattern), `project.xml` edited; build + push to ECR |

---

## 2. What already exists vs. what changes

The scaffold (commit `bdebfa8`) already provides: Dockerfile (git-clone based),
`docker-compose.yml`, `.env.example`, `entrypoint.sh` (DB setup + properties),
`properties/yeastmine.properties.template`, README. Its properties are kept in
sync with the other mines (mail, CDN, `os.query.max-time`, theme).

### Two gaps found in the current scaffold
1. **No `db.sgd` datasource block** in `yeastmine.properties.template`. YeastMine's
   five *database* sources (`sgd`, `sgd-complementation-db`, `go-annotation-db`,
   `disease`, `sgd-complexes`) all read from `db.sgd`. Without it, those sources
   cannot integrate. Copy the block from `docker/alliancemine/properties/
   alliancemine.properties.template` and add `SGD_DB_*` env.
2. **Path mismatch.** Upstream `project.xml` hard-codes `/data/intermine/...`
   file-source paths; AllianceMine's `extract_data.py` stages into
   `/root/data/intermine/...`. Reconciled by editing `project.xml` in the fork
   (Approach A).

---

## 3. Directory layout target (`docker/yeastmine/`)

```
source/yeastmine/                          local fork, rsynced in, gitignored   (NEW)
source/yeastmine-bio-sources/              local fork, rsynced in, gitignored   (NEW)
Dockerfile                                 COPY-from-source/ (was: git clone)    (EDIT)
docker-compose.yml                         + SGD_DB_*, + SOLR_*                  (EDIT)
entrypoint.sh                              + Solr URL block, compile-after-props (EDIT)
.env.example                               + SGD_DB_*, + SOLR_*                  (EDIT)
properties/yeastmine.properties.template   + db.sgd block, + Solr URLs          (EDIT)
scripts/build_and_push.sh                  yeastmine variant of flymine's        (NEW)
scripts/extract_data.py                    adapted from alliancemine             (NEW)
scripts/finalize_build.sh                  + patch_*.sql (yeast fixups, TBD)     (NEW)
data/                                      volume mount -> /root/data            (exists)
```

---

## 4. Source provenance (Approach A)

Fork `yeastgenome/yeastmine` + `yeastgenome/yeastmine-bio-sources` into a local
working dir (e.g. `~/Projects/alliance/new_yeastmine/`). The fork carries edits
that exist nowhere upstream:

- **`project.xml` file-source paths**: `/data/intermine/...` -> `/root/data/intermine/...`.
- **Maven repo URL fixes** if needed (FlyMine required EBI URL patches; verify a
  clean YeastMine `:dbmodel:assemble` first and only patch if it breaks).
- **Branch pin** via `YEASTMINE_BRANCH` (e.g. `R64-5-1`, or master@known-good).

`scripts/build_and_push.sh` (modeled on flymine's): rsync the fork excluding
`.git/.gradle/build/bin/out`, `docker buildx build --platform linux/amd64`,
content-hash tag (`src-<sha12>`) + `latest`, push to ECR repo `yeastmine-builder`.
`--no-push` does a local single-arch `--load` for smoke tests. Consumer
(AllianceMineDev) pulls + `docker compose run`.

---

## 5. Data sourcing — all 24 sources mapped

### 5a. Database sources (no extraction; read live from `db.sgd`)
`sgd`, `sgd-complementation-db`, `go-annotation-db`, `disease`, `sgd-complexes`.
Require: `db.sgd` block in properties + `SGD_DB_*` env + network reachability to
`www-rds-primary.yeastgenome.org` (AllianceMine already connects here).

### 5b. File sources via S3 sync (`s3://agr-db-backups/alliancemine/intermine/`)
The SGD subset AllianceMine already stages:
`sgd-gff` (gff), `sgd-gff-utr` (gff-utr), `sgd-db-utr` (db-utr),
`fungi-homologs`/`cgob-homologs`/`cglabrata-homologs`/`pombe-homologs`/
`homolog-genes`/`diopt-orthologs` (yeast_orthologs/*, incl.
`ORTHOLOGY-ALLIANCE_COMBINED.tsv`), `sgd-protein-properties` (protein-properties),
`sgd-protein-ntermini` (protein-ntermini), `psi-mi-ontology` (psi-mi.obo),
`go-slim` (goslim_yeast.obo).

### 5c. Extra ontology downloads (YeastMine's exact forms, not in the S3 subset)
`go` (go-basic.obo), `do` (doid.obo), `eco` (eco.obo), `so` (so.obo) — from FMS
(AllianceMine already pulls `ONTOLOGY_GO/DOID/ECO/SO`) or OBO Foundry public URLs.

### 5d. Small/static
`update-publications` (publications.xml), `entrez-organism` (organisms.xml) —
InterMine bio defaults / upstream repo content.

`extract_data.py` keeps `--skip-*` flags so file staging and re-runs are
independent halves.

---

## 6. Build flow (manual, FlyMine-style)

1. `scripts/build_and_push.sh` -> image (ECR, or `--no-push` local).
2. **entrypoint**: wait-for-RDS -> resolve release/RC -> construct DB names ->
   configure properties (incl. `db.sgd` + Solr URLs) -> create DBs ->
   compile-on-first-run (**after** properties, per the flymine ordering fix:
   `webapp/build.gradle` reads `webapp.port` as int at config time).
3. `python3 scripts/extract_data.py` -> S3 sync + ontology downloads into `/root/data/...`.
4. `./gradlew buildDB`  — **verify `db.production.datasource.databaseName` first**
   (CLAUDE.md rule; a misaimed builddb once wiped prod).
5. `project_build` integrate, **piped through `tee`** (row-count debug only hits
   stdout). Resume with **`-l`**. **Order `sgd` first** to validate the SGD
   connection + canonical-converter behavior before the long sources.
6. `scripts/finalize_build.sh --sql-only` (yeast patches, if any) — **before**
   postprocess, so `create-attribute-indexes` builds b-trees once from patched data.
7. `./gradlew postprocess`, **with `create-search-index` omitted** (see §9) —
   drop it from the fork's `<post-processing>` list for this round, or run the
   individual postprocess tasks excluding it. No multitenant Solr dependency.
8. `scripts/finalize_build.sh --skip-war` (`summariseObjectStore`) -> `./gradlew :webapp:war`.

---

## 7. Risks & how the plan retires them

| Risk | Mitigation |
|---|---|
| Canonical `yeastgenome` converters vs the reachable SGD schema (AllianceMine uses a *fork* of `SgdConverter`) | Integrate the single `sgd` source first (step 5 ordering) before a full run |
| SGD DB reachability from build host | Confirm `pg_isready`/`psql` to `www-rds-primary.yeastgenome.org` early (M2) |
| `project.xml` `/data/intermine` paths | Edited in the fork (Approach A); verified by `:dbmodel:assemble` |
| **Solr cores for postprocess** — `create-search-index` needs `yeastmine-search` / `yeastmine-autocomplete` on multitenant Solr | **Resolved (§9): skip `create-search-index` this round**; create cores + reindex at deploy. No multitenant dependency this round |
| `superuser.account` / theme / mail placeholders | Already handled in template; only matter at deploy (out of scope) |

---

## 8. Milestones

- **M1** — image builds + `:dbmodel:assemble` passes (fork + Dockerfile COPY + `build_and_push.sh`).
- **M2** — `db.sgd` wired; SGD DB reachable; `sgd` single-source integrate green.
- **M3** — `extract_data.py` stages all file sources; `project.xml` paths resolve.
- **M4** — full `project_build` integrate green (tee'd, ordered, `sgd` first).
- **M5** — postprocess (`create-search-index` skipped, per §9) + `finalize_build.sh` + WAR built on RDS.

---

## 9. Resolved decision: Solr search-index during postprocess

**Decision: skip `create-search-index` this round.** `postprocess` includes
`create-search-index`, which writes to the `yeastmine-search` /
`yeastmine-autocomplete` Solr cores on the multitenant host. To keep this
RDS-only round free of any multitenant dependency, that postprocess is omitted
(dropped from the fork's `<post-processing>` list, or by running the postprocess
tasks individually except that one). The cores are created and the index is
built/reindexed when the webapp is deployed in a later round.

---

## 10. Cross-references

- `docker/flymine/` — the orchestration pattern this mirrors (`build_and_push.sh`,
  `finalize_build.sh`, `extract_data.py`, `source/` COPY pattern).
- `docker/alliancemine/scripts/extract_data.py` — the S3-sync + SGD source the
  YeastMine fetcher is adapted from; `db.sgd` block + `SGD_DB_*` come from its
  properties template and compose.
- `docker/wormmine/` — lighter single-org build-only sibling.
- `docker/yeastmine/README.md` — scaffold status + "Known follow-ups" this design fulfils.

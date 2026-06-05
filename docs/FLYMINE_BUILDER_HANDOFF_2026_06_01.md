# FlyMine builder — handoff for the new_flymine sibling

Status as of 2026-06-01 after first end-to-end smoke build on AllianceMineDev.

## What's done

- **Docker image** `flymine-builder:latest` baked, pushed to ECR (linux/amd64,
  `100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest`).
  Source baked in from your local fork via `scripts/build_and_push.sh` (rsync
  stages `new_flymine/{flymine,flymine-bio-sources}` → COPY into image).
- **Entrypoint** waits for RDS → resolves Alliance release → constructs DB
  names → envsubsts `flymine.properties` → creates DBs → compiles bio-sources
  + flymine (cold ~15 min, warm ~2 min via persisted maven/gradle volumes).
- **Compile order**: `configure_properties` happens **before** `compile_if_needed`.
  Without this the webapp install fails on `${DEPLOY_PORT}` because gradle reads
  it as int at config time. Don't undo that reorder.
- **Schema** built into `flymine_v0-2026-05-31_rc2` (211 tables, `:dbmodel:buildDB`).
- **Smoke integrate**: `so` source → 2404 OntologyTerm + 1 Ontology row.
  End-to-end pipeline verified: items DB → dataLoad → production DB → indexes.

## What's fetched

`~/flymine-deploy/data/` on AllianceMineDev (bind-mounted to `/root/data` in container):

```
fms/   (~1.1 GB, FMS snapshot release 9.1.0)
  ONTOLOGY_GO.obo SO.obo DOID.obo ECO.obo FBBT.obo
  GAF_FB.gaf GFF_FB.gff
  DISEASE/ORTHOLOGY/EXPRESSION/VARIANT-ALLELE_COMBINED.tsv
genes/
  BGI_FB.json
flybase/   (~5 GB, FB2026_01 precomputed)
  fbab-fbba/{fb_synonym, aberration_experimental_gene_del_dup}
  flybase-expression/{gene_rpkm_report, high-throughput, scRNA-Seq}
  fbab-fbba-phase2/cyto-genetic-seq
```

extract_data.py sources you can pull on AllianceMineDev:

| --only flag | What it pulls | State |
|---|---|---|
| `fms` | 12 FMS files via snapshot API | wired ✅ |
| `flybase-precomputed` | 6 FB2026_01 files | wired ✅ |
| `external` | NCBI gene_info, HGNC, Reactome flat files, UniProt keywlist | wired ✅ |
| `uniprot-drosophila` | UniProt XML filtered to taxon 7227 (~50 MB) | wired ✅ |
| `intact` | psimitab zip | wired ✅ |
| `biogrid` | by-organism tab3 zip | wired ✅ |
| `interpro` | names.dat + ParentChildTree + interpro.xml.gz | wired ✅ |
| `flyatlas` `rnai` `bdgp-clone` `bdgp-insitu` `fly-fish` `redfly` `long-oligo` `drosdel-gff` | Bucket-D live sources | **TODO — leaf URLs pending from you** |

## What's owned by you (new_flymine)

1. **project.xml path rewrites** — every `<source>` has a `/micklem/data/...`
   path. The integrate runs that ran here today worked around this with
   symlinks (mkdir `/micklem/data/.../current/` + `ln -sf /root/data/fms/...`).
   That's good for smoke testing 1–2 sources at a time but not for a full
   build. Need bulk rewrites to `/root/data/...` paths matching the
   `extract_data.py` directory layout in the table above.
2. **Bucket-D leaf URLs** — `extract_data.py` has TODO placeholders for the
   8 live sources you confirmed are alive (per
   `docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md`). Once you supply the
   exact file paths, I'll wire them.
3. **FBab/FBba converter** — the synthesized aberration/balancer data wiring
   into the model (per `docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md`).
   Build side ready to consume whatever the converter emits.
4. **flybase-expression rework to RPKM** — RPKM files are on disk
   (`flybase/flybase-expression/gene_rpkm_report_fb_2026_01.tsv`); converter
   side is yours.

## How to fire on AllianceMineDev

Image is on the box already (re-pull when I push a new revision):

```bash
ssh ec2-user@172.31.60.197
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 100225593120.dkr.ecr.us-east-1.amazonaws.com
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest
docker tag 100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest flymine-builder:latest

cd ~/flymine-deploy
# .env is configured; FLYMINE_RELEASE=v0-2026-05-31 / BUILD_TYPE=test / RC_NUMBER=2

# Re-fetch (idempotent — skips files already present):
docker compose run --rm -T flymine-builder python3 /root/scripts/extract_data.py --only fms flybase-precomputed external

# Smoke-integrate a single source (example: do ontology via symlink workaround):
docker compose run --rm -T flymine-builder bash -c "
  mkdir -p /micklem/data/do/current
  ln -sf /root/data/fms/ONTOLOGY_DOID.obo /micklem/data/do/current/doid-non-classified.obo
  cd /root/flymine && ./gradlew :dbmodel:integrate -Psource=do --stacktrace
"

# Inspect rows on RDS:
PGPASSWORD=$(grep ^RDS_PASSWORD ~/agr_intermine_builder/docker/alliancemine/.env | cut -d= -f2) \
  psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -d "flymine_v0-2026-05-31_rc2" -tAc \
  "SELECT (SELECT count(*) FROM ontologyterm) AS terms, (SELECT count(*) FROM ontology) AS ontos"
```

## Known traps

- `bash -c "..."` worked after I fixed the entrypoint `case` block. Older image
  revisions before today's push (sha:89388442) drop the `-c` args and hang.
- `compile_if_needed` re-runs on every container start because `.needs_compile`
  is image-baked. Warm caches make it ~2 min, but to drop to ~5 sec we should
  switch the marker to a volume sentinel (`/root/.m2/.flymine_compiled`).
  Follow-up — not blocking.
- The watcher pattern in my logs polls every 30 s and looks for end markers
  (`INTEGRATE_EXIT=`, `BUILD FAILED`, schema table count). Don't match on
  `BUILD SUCCESSFUL` alone — bio-sources clean prints that early and trips the
  watcher.
- Symlink `/micklem/data/<path>/current/<file>` workaround works for any source
  with absolute `src.data.file` / `src.data.dir`. Bulk-rewrite project.xml when
  you can.

## Files I changed today

- `docker/flymine/Dockerfile` — COPY source/* + bake bintray strip + heap append
- `docker/flymine/entrypoint.sh` — reordered (configure → compile) + bash-args fix
- `docker/flymine/scripts/extract_data.py` — real FMS API fetcher + 4 external
  source fetchers (uniprot-drosophila, intact, biogrid, interpro) + small
  external bundle (NCBI/HGNC/Reactome/keywlist)
- `docker/flymine/scripts/build_and_push.sh` — rsync staging + content-hash tag
  + ECR push helper
- `docker/flymine/docker-compose.yml` — dropped source bind mounts, kept
  `./data:/root/data` + named volumes for maven/gradle

Image content hash: `src-c6d2acd16fbd-amd64` (pinned tag).

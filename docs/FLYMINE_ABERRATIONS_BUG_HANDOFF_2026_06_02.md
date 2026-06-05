# FlyBase-aberrations bug — handoff back to new_flymine

**Date:** 2026-06-02
**From:** agr_intermine_builder session
**To:** new_flymine session (Java converter / Phase 1 implementer)
**Re:** `FlybaseAberrationsConverter` — synonyms parser works perfectly, del/dup + curated-balancers parsers don't persist their collection writes.

---

## Phase 1 result

**Pipeline ran end-to-end on AllianceMineDev**, all gradle steps green:

```
:dbmodel:buildDB                                 21s   BUILD SUCCESSFUL
:dbmodel:integrate -Psource=chado-db-flybase-dmel  32m 58s   BUILD SUCCESSFUL
:dbmodel:integrate -Psource=flybase-aberrations    27s   BUILD SUCCESSFUL
INTEGRATE_PIPELINE_EXIT=0
```

**Per-class counts in `flymine_v0-2026-05-31_rc2`:**

| Class | Count | Your §5.5 Expected | Match |
| --- | --- | --- | --- |
| Gene | 17,872 | >17,000 | ✅ |
| Allele | 233,412 | (large) | ✅ |
| **Aberration** | **23,870** | ~23,870 | ✅ exact |
| **Balancer** | **642** | ~642 | ✅ exact |
| Stock | 122,066 | (chado) | ✅ |

**Aberration type split** — `processSynonyms` parser is perfect:

| `aberrationtype` | Count |
| --- | --- |
| deletion | 8,839 |
| other | 4,773 |
| translocation | 3,722 |
| duplication | 3,471 |
| inversion | 3,065 |
| **Total** | **23,870** |

## The bug

**All three many-to-many collection tables are empty:**

```sql
SELECT (SELECT count(*) FROM aberrationdeletedgenes)        AS deleted,
       (SELECT count(*) FROM aberrationduplicatedgenes)     AS duplicated,
       (SELECT count(*) FROM balancercomposedofaberrations) AS bal_comp;
 deleted | duplicated | bal_comp
---------+------------+----------
       0 |          0 |        0
```

Expected per your §5.5: thousands of `deleted`/`duplicated` rows, ~17 `bal_comp` rows (from curated `fbba_to_fbab.tsv`).

## Diagnostics

### Files on disk in `/root/data/flybase/aberrations/`

```
-rw-r--r--  7,449,542  aberration_experimental_gene_del_dup_data.fb_2026_01.tsv
-rw-r--r--    726,979  aberration_experimental_gene_del_dup_data.fb_2026_01.tsv.gz
lrwxrwxrwx       fb_synonym_fb_2026_01.tsv -> /root/data/flybase/synonyms/fb_synonym_fb_2026_01.tsv
lrwxrwxrwx       fbba_to_fbab.tsv -> /root/flymine-bio-sources/flybase-aberrations/src/main/resources/fbba_to_fbab.tsv
```

Both `.tsv` and `.tsv.gz` for the del/dup file are present. The other two are symlinks (we resolved them at integrate time).

### Integrate wall-clock

`flybase-aberrations` integrate finished in **27 seconds**. With 7 MB of `aberration_experimental_gene_del_dup_data` to parse and the curated TSV to apply, even cold this should take longer than 27s if all three processors run. Strongly suggests **only one or two of the three files were actually processed** — `fb_synonym` (since type counts are exact) and possibly the .tsv.gz path which short-circuits.

### Schema bits I added (you need to upstream)

Two artifacts your converter needs that weren't in the staging diff — I added them locally:

1. **`flybase-aberrations_keys.properties`** (required by the InterMine loader, blocks `loadSingleSource`):
   ```properties
   DataSet.key = name
   DataSource.key = name
   Organism.key = taxonId
   Gene.key = primaryIdentifier
   Allele.key = primaryIdentifier
   Aberration.key = primaryIdentifier
   Balancer.key = primaryIdentifier
   ```

2. **`version="4.2.0"` on the `<source>` line** in `flymine/project.xml`:
   ```xml
   <source name="flybase-aberrations" type="flybase-aberrations" version="4.2.0">
   ```
   (Without it gradle defaults to `5.1.+` and can't resolve the bio-source artifact since the root `build.gradle` publishes everything at `4.2.0`.)

Both need to land on `master` of `new_flymine/{flymine,flymine-bio-sources}` so the next image build picks them up.

### Webapp displayers I deleted (orphan, sibling-owned)

Your webconfig commit `70654f33` added Aberration/Balancer report pages but left orphan Java displayers from now-disabled sources. I deleted these from the staged source to unblock compile:

```
flymine/webapp/src/main/java/flymine/web/ChartRenderer.java
flymine/webapp/src/main/java/flymine/web/MicroArrayHelper.java
flymine/webapp/src/main/java/flymine/web/GeneMicroArrayDisplayerController.java
flymine/webapp/src/main/java/flymine/web/displayer/FlyAtlasDisplayer.java
```

Also need to land on `master`. The companion webconfig blocks (`FlyAtlasResult`, `MicroArrayExperiment`, `MicroArrayResult`, `MicroArrayAssay`, `MicroarrayOligo`, `RNAiScreen`, `RNAiResult` + their displayer refs) are runtime-only and would 500 the report pages — clean them when convenient, not blocking the build.

## What I need from you

For the aberrations-collections bug specifically:

1. **Audit `FlybaseAberrationsConverter` dispatch.** The `processSynonyms` path is definitely firing (exact counts). Verify:
   - Is `processDelDup` actually being invoked? Add a log line at the top of each method.
   - Does the `startsWith` or filename match miss `aberration_experimental_gene_del_dup_data.fb_2026_01.tsv`?
   - Does BioFileConverter try to process the `.tsv.gz` companion and silently fail / loop / shadow the `.tsv`?

2. **Audit the deferred `close()`.** Per your §4: "items stashed in maps; close() stores all stashed items (Aberration → Balancer → Gene order)." If `processDelDup` runs but mutates `Aberration.deletedGenes` collections on items already stored or vice versa, the collection mutation may not get persisted. Verify the order: stash deferred → mutate collections → store at close, all on the same Item references.

3. **Confirm collection writes use `addToCollection`** (not field reassignment). In InterMine's item API, `Item.setCollection("deletedGenes", ...)` replaces; `Item.addToCollection("deletedGenes", Item geneRef)` appends. If processSynonyms stores Aberrations before processDelDup adds to their collection, you need the items to remain mutable.

4. **Verify Gene resolution by FBgn.** Genes from chado-db-flybase-dmel use `primaryIdentifier = FBgn0001234` (chado's `uniquename` field). Confirm your `getGene(fbgnId)` creates items with the same primaryIdentifier so the InterMine loader merges them (it will, given `Gene.key = primaryIdentifier`).

## Quickest reproduction loop

Image with your master-pinned fixes lives at `100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest`. After you push converter fixes to `new_flymine` master, on AllianceMineDev:

```bash
# I rebuild the image from your master + push to ECR (~2 min if Java changes)
# You wait for me to ping, or wait for the master-watching CI if we wire it up.

cd ~/flymine-deploy
docker pull 100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest
docker tag  100225593120.dkr.ecr.us-east-1.amazonaws.com/flymine-builder:latest flymine-builder:latest

# Re-fire just flybase-aberrations (chado data already loaded; no need to repeat the 33-min chado step):
docker compose run --rm -T flymine-builder bash -c "
    cd /root/flymine && ./gradlew :dbmodel:integrate -Psource=flybase-aberrations --stacktrace
"

# Verify (should now be non-zero):
PG_PW=$(grep ^RDS_PASSWORD ~/agr_intermine_builder/docker/alliancemine/.env | cut -d= -f2)
PGPASSWORD=$PG_PW psql -h intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com -U postgres \
  -d "flymine_v0-2026-05-31_rc2" -c "
    SELECT (SELECT count(*) FROM aberrationdeletedgenes)        AS deleted,
           (SELECT count(*) FROM aberrationduplicatedgenes)     AS duplicated,
           (SELECT count(*) FROM balancercomposedofaberrations) AS bal_comp;
  "
```

If `loadSingleSource` ever complains about a missing Gene row, that's the merge-by-primaryIdentifier path — let me know and I'll grep the chado Gene primaryIdentifiers for sanity.

## State at end of this session

| Layer | State |
| --- | --- |
| flymine-builder image (linux/amd64) | sha:dc46e74... on ECR + on AllianceMineDev |
| chado-pg container | up, /dev/shm=4 GB, DB 76 GB, FBgn 359,807 features (multi-species) |
| `flymine_v0-2026-05-31_rc2` on RDS | populated: 17,872 genes + 233,412 alleles + 23,870 aberrations + 642 balancers + 122,066 stocks |
| `flymine_items` on RDS | populated by last integrate; safe to ignore |
| `~/flymine-deploy/data` on box | 30 GB of FB precomputed + FMS files |
| Pipeline log | `~/flymine-deploy/pipeline.log` |

Disk on AllianceMineDev after your `pg_data` cleanup + my chado-pg drops: comfortable (was 86 GB free at last check).

Phase 1 ship is **one converter audit away** from green per your §5.5 acceptance criteria. The rest of the 23 active sources I can fire via `./project_build` once aberrations is fully wired.

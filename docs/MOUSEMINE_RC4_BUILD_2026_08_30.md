# MouseMine rc4 build — interpro/protein2ipr/update-publications re-enabled

**Date:** 2026-08-30 (build 2026-08-27→28, deployed 2026-08-30)
**Release:** `mousemine_rc4`, project version `1.8-2026-08` (MGI ETL 2026-08-24)
**Supersedes:** `mousemine_rc3` (`1.8-2026-06`) — **rc2 + rc3 were dropped from RDS before the build** (operator request; MouseMine was down for the rebuild duration).
**Live:** `https://mousemine.alliancegenome.org/mousemine/`

rc4 re-enables the three sources rc3 skipped (`interpro`, `protein2ipr`,
`update-publications`) after the maintainer added a UTF-8 filter to the interpro
download. mgi-base ran **dupe-free** this build. update-publications had **two**
distinct failures that took real debugging — both root-caused and fixed here.

---

## Maintainer's four items — outcomes

| Item | Outcome |
|---|---|
| **interpro** (UTF-8 filter added to download) | ✅ Ran clean. `iconv -f UTF-8` confirmed `interpro.xml` (259 MB) is valid UTF-8 — the filter works. |
| **protein2ipr** (depends on interpro) | ✅ Ran clean once interpro was in. |
| **mgi-base duplicates** ("should not happen") | ✅ **Zero duplicates** — integrate log: *"There were no duplicate objects"* (×2). Did not recur with the new ETL. |
| **update-publications** ("else pubs are empty") | ✅ **Integrated — publications enriched.** Two root causes found + fixed (below). 450,302 / 450,313 publications now have titles (was 0). |

Final DB: 1.56M genes, **450,313 publications (450,302 with title, 449,872 with journal)**, **705,820 authors**. 251 GB.

---

## Build procedure

Standard MouseMine Ant build (see `MOUSEMINE_RUNBOOK.md`) in the `mousemine`
container on AllianceMineDev, ETL already staged in `/data/etl_output` (2026-08-24).
The rc3 patches persist in this container (writeLargeUTF UTF-8 patch in all 3
`intermine-objectstore.jar` copies, `BioEntity.name = mgi-base, *`), verified before start.

1. **Re-enabled the 3 sources** in `project.xml` — removed the `<!-- SKIPPED rc3: … -->`
   comment wrappers around `interpro` (488), `protein2ipr` (494), `update-publications` (569).
2. **FMS ontology gap**: MouseMine's own FMS fetch returns empty JSON, so the
   ontology/GAF files (`ONTOLOGY_GO/DOID/SO.obo`, `GAF_FB.gaf`) were **copied from the
   AllianceMine 9.1.0 build's `data/fms/`** (same Alliance-wide files). (Same borrow as FlyMine.)
3. `CREATE DATABASE mousemine_rc4 ENCODING 'UTF8' TEMPLATE template0`; point
   `/root/.intermine/mousemine.properties` at rc4; `project.releaseVersion=MGI update: 2026-08-24`.
4. `ant build-db` (dbmodel, **no** `-Drelease`) → `project_build -b -E UTF8 localhost /data/dump/mousemine_rc4`
   (~14 h; mgi-base is the long pole).
5. project_build failed on the **last** source (`update-publications`) — see below.
6. After fixing update-publications, ran postprocess (`project_build -E UTF8 -a do-sources-`,
   ~6 h incl. the Lucene `create-search-index`) → cutover.

---

## update-publications — the two root causes (the hard part)

update-publications was skipped in rc3 ("ProxyReference id not in ID map"). Retrying
in rc4 reproduced it, and fixing it exposed a second issue. Both are in the data the
Entrez retriever generates (`.../integrate/build/publication.xml`, 400 MB, 441,763
Publications + 703,528 Authors), not in the loader.

### 1. ProxyReference / forward-reference — "Given a ProxyReference, but id not in ID Map"

**Cause:** `EntrezPublicationsRetriever` writes **all publications first, then all authors**
(publications stream out as each Entrez batch is fetched; `authorMap.values()` is written
once at the end). So every Publication forward-references an Author defined millions of lines
later. InterMine's `ObjectStoreDataLoader` reads items in file/insertion order (no `ORDER BY`)
and, for a many-to-many collection member delivered as a bare untyped `ProxyReference` via the
plain `ObjectStoreTranslatingImpl`, `getEquivalentObjects` cannot skeleton it — it throws.
Deterministic (identical in rc3), systemic (nearly every publication).

**Fix (interim):** reorder `publication.xml` to **authors-first** (contiguous blocks: authors
were lines 4,803,608–6,914,191, publications 2–4,803,597 → header + authors + publications +
footer), then re-run **only the load** — neutralize the source's `-pre-retrieve` (comment out
the `<retrieve-publications …/>` task in `update-publications/build.xml`) so the Entrez fetch
doesn't regenerate the file, and `ant -Dsource=update-publications`. Authors then land in the
ID map before any publication references them.

**Permanent fix (maintainer):** patch `EntrezPublicationsRetriever` to emit Author (and MeshTerm)
items **before** Publications — buffer publications to a temp file during the fetch loop, then write
`authorMap.values()`/`meshTerms.values()` first and append the buffered publications.

### 2. Duplicate authors — "Duplicate objects found for pk Author.key_name"

Reordering fixed #1 but exposed this. Author's primary key is `key_name` (the name string).

**Cause: encoding mojibake.** 33,656 author names contain `?` — accented characters replaced
with `?` (e.g. Vársányi→"Vars?nyi M", Hernández-Ochoa→"Hern?ndez-Ochoa EO", Zákány→"Z?k?ny J").
Distinct accented names collapse to the same `?`-string, so **393 names collide** (412 excess
Author items). The collision throws in the parallel `BatchingFetcher.doPk` **before**
`ignore.duplicates` is consulted — so `ignore.duplicates=true` on the source did **not** fix it
(confirmed empirically; production had 0 duplicate authors, so the dup is purely in the source XML).

**Fix (interim):** deduplicate the 393 colliding author groups in `publication.xml` — keep one
item per name, remap the 412 dropped author IDs, and rewrite the 3,436 affected publication
author references (`scripts/dedup_authors.py`, applied on the dev host). Result: 703,116 unique
author names, 0 collisions; publications reference the surviving author. Then the load ran clean
to completion (1,144,879 objects, 103 min, 0 errors).

**Permanent fix (maintainer):** correct the UTF-8 handling of author names in the retriever so
accented characters survive and distinct names stay distinct (same theme as the interpro filter).
The interim dedup merges 412 genuinely-distinct-but-indistinguishable authors — negligible
(0.06% of 703K) and superseded once the encoding is fixed.

> Both interim fixes act on the **generated** `publication.xml`; the retriever source is
> unchanged. The authors-last original is backed up as `publication.xml.authors-last.bak`,
> the reordered-with-dups as `publication.xml.reordered-with-dups.bak`. `update-publications/build.xml`
> was restored after the load (the `-pre-retrieve` neutralization is reverted).

---

## Cutover (rc3 was already dropped)

Model unchanged (the re-enabled sources use existing classes: ProteinDomain, Author, Publication),
so a properties-repoint + restart — no WAR rebuild — per `MOUSEMINE_RUNBOOK.md`:

1. Backed up `mousemine_userprofile` (83 MB, pg15 client — RDS is 15.x) to
   `/home/ec2-user/mousemine_userprofile_pre-rc4-cutover_2026-08-30.dump`.
2. In `mousemine-1x` (multitenant), repointed `WEB-INF/classes/intermine.properties`
   `db.production … mousemine_rc3 → mousemine_rc4`, `project.releaseVersion=1.8-2026-08`
   (also web.properties banner). `docker restart mousemine-1x`.
3. Lucene keyword index re-extracts from rc4 on first search (~37 min, self-clearing);
   saved lists lazily bag-upgrade.

**Verify (all pass):** `service/version` 200; `db.production=mousemine_rc4`; `begin.do` no
internal error; release `1.8-2026-08`; gene query returns rows; **publication query returns
enriched titles/journals** (the fix, end to end).

**Backups retained:** `intermine.properties.bak.rc3` in the container; userprofile dump.
(No rollback to rc3 possible — rc3 DB was dropped.)

---

## Follow-ups

1. **Retriever permanent fixes** (maintainer): (a) emit authors before publications;
   (b) UTF-8-correct author names. Both remove the need for the interim reorder + dedup next build.
2. **Reclaim RDS**: drop rc4 checkpoint DBs (`mousemine_rc4:mgi-base` ~180 GB,
   `mousemine_rc4:mus_spretus-gff` ~144 GB) now the build is done and verified (~300 GB).
3. **FMS ontology fetch**: MouseMine's `--only fms` returns empty JSON — fix the resolver or
   make the AllianceMine-build borrow explicit.
4. Warm the Lucene search post-restart (a few queries); confirm bag upgrade completes.

## Related
- `MOUSEMINE_RUNBOOK.md` — build/manage/update reference (update prod DB → rc4)
- `MOUSEMINE_RC3_BUILD_2026_06_16.md` — the prior build (writeLargeUTF fix, why the 3 sources were skipped)
- `docker/mousemine/scripts/dedup_authors.py` — the author-dedup used here (kept for reference / next build until the retriever is patched)

# MouseMine rc3 Build — 2026-06-16 → 06-19

Full record of the MouseMine `rc3` build: triggered by new June-10 MGI source data, it surfaced a long-standing InterMine `0x00`/UTF-8 COPY bug plus several data-integration config gaps, and an RDS storage-full incident mid-postprocess. This doc captures the patches, the failure rounds, and the recovery so the next build (or a Docker-image bake of these fixes) is a known quantity.

## Outcome

| Item | Value |
|---|---|
| Main DB | `mousemine_rc3` on `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com` — **259 GB** (rc2 was 252 GB) |
| Genes | 1,560,351 (incl. all strains + homologs) |
| Proteins | 94,562 |
| WAR | **87 MB** at `mousemine:/intermine/mousemine/webapp/dist/mousemine-webapp.war` (rc2 was 84 MB) |
| Sources integrated | 16 of 18 (skipped `interpro`, `protein2ipr`, `update-publications` — see below) |
| Postprocess | all 10 ran (create-search-index 71 min, summarise-objectstore 14 min) |
| **Deploy status** | **NOT cut over** — rc2 still serving production on multitenant `mousemine-1x`. Cutover deferred. |
| Build host | `mousemine` container on AllianceMineDev (172.31.60.197) — Ant-based InterMine 1.x, Java 8/11, local Postgres unused (RDS via properties) |

## Trigger + data

SGD/MGI shipped fresh source files. The new ETL output was already extracted on the dev host:
- `~/agr_mousemine/mousemine_data/update.tar.gz` (603 MB, Jun 10) — the dumped MGI item-XML + ontologies
- Unpacked into `/data/etl_output/{mgi-base,mgi-geneids,emapa,biogrid,entrez,go,intact,interpro,mp,do,cl,uberon,reactome,panther,psi-mi,strain-genomes,uniprot*,so}/2026.06.10.*/`
- `project.xml` entity `&mm_data;` = `/data/etl_output`

No fresh ETL run needed — the Jun-10 dirs were used as-is.

## Build sequence (what actually worked)

MouseMine is **Ant-based InterMine 1.x**, not Gradle. Key commands (all inside the `mousemine` container):

```bash
# 1. create DB on RDS
psql ... -c "CREATE DATABASE mousemine_rc3 ENCODING 'UTF8' TEMPLATE template0"

# 2. point properties at rc3
sed -i 's/mousemine_rc2/mousemine_rc3/g' /root/.intermine/mousemine.properties
#    (backup kept at mousemine.properties.bak.pre-rc3)

# 3. build schema — from dbmodel/, NO -Drelease flag
#    (-Drelease=1.8 makes it look for mousemine.properties.1.8 which doesn't exist)
cd /intermine/mousemine/dbmodel && ant build-db          # 227 tables

# 4. integrate — project_build lives at /intermine/bio/scripts/project_build
cd /intermine/mousemine
/intermine/bio/scripts/project_build -b -E UTF8 localhost /data/dump/mousemine_rc3
#    -b = build-db first (fresh).  -E UTF8 REQUIRED for RDS (default SQL_ASCII breaks createdb)
#    Resume after a failure:  -l = reload last checkpoint, continue
#    Start at a named source:  -a <source>-     (dash suffix = "and everything after")

# 5. postprocess (after all sources):  -a do-sources-  runs all 10 postprocesses
/intermine/bio/scripts/project_build -E UTF8 -a do-sources- localhost /data/dump/mousemine_rc3

# 6. WAR — the `war` target doesn't exist; run the webapp project default
cd /intermine/mousemine/webapp && ant default            # -> webapp/dist/mousemine-webapp.war
```

### project_build checkpoints + the storage trap

Without `-T`, `project_build` makes a server-side `CREATE DATABASE … TEMPLATE` checkpoint after every `dump="true"` source. Each checkpoint is a **full copy of the in-progress DB** (140–250 GB here). These pile up fast and were a major driver of the RDS storage-full incident. `-l` restores from the latest checkpoint; if you DROP the checkpoint to reclaim space you lose the resume point and `-l` falls back to "no backup file found" → restarts from source 1 (it does NOT wipe the integrated data in `mousemine_rc3`, but you must resume with `-a <next-source>-`, not `-l`).

## The `0x00` / UTF-8 COPY bug (the headline issue)

**Symptom (recurred on `so`, `interpro`, `mgi-base`):**
```
org.postgresql.util.PSQLException: ERROR: invalid byte sequence for encoding "UTF8": 0x00
  Where: COPY attribute, line N, column intermine_value
```

**What it is NOT:** the source files were clean (0 null bytes, valid XML/OBO). Stripping non-ASCII from the source files with `iconv`/python "fixed" `so` but **corrupted XML** (cut multi-byte UTF-8 sequences mid-character → `not well-formed` SAX errors on `HTIndex.xml` etc.). Dead end — don't pre-process source files.

**Root cause:** `org.intermine.sql.writebatch.PostgresDataOutputStream.writeLargeUTF(Collection<String>)` — the method that serializes attribute values into the binary COPY stream — had two bugs:
1. It pre-computed the UTF-8 byte length with a hand-rolled (modified-UTF-8) loop, then wrote bytes with `str.getBytes()` (**platform default charset**, not UTF-8). When the two diverged, the COPY stream desynced and Postgres read junk (incl. `0x00`) as the next field.
2. It never stripped `0x00` chars, which Postgres COPY rejects outright.

Patching `Item.setAttribute` and `fulldata.Attribute.setValue` did NOT help (the 0x00 enters below them, via the writer). The fix is in the writer itself:

```java
// PostgresDataOutputStream.java — writeLargeUTF(Collection<String>)
protected int writeLargeUTF(Collection<String> strs) throws IOException {
    java.util.List<byte[]> encoded = new java.util.ArrayList<byte[]>(strs.size());
    int totalLen = 0;
    for (String str : strs) {
        if (str.indexOf(0) >= 0) {                     // strip nulls
            StringBuilder sb = new StringBuilder(str.length());
            for (int i = 0; i < str.length(); i++) { char c = str.charAt(i); if (c != 0) sb.append(c); }
            str = sb.toString();
        }
        byte[] b = str.getBytes(java.nio.charset.StandardCharsets.UTF_8);  // correct charset
        encoded.add(b);
        totalLen += b.length;
    }
    writeInt(totalLen);
    for (byte[] b : encoded) write(b);
    return totalLen + 4;
}
```

**CRITICAL gotcha — there are THREE copies of `intermine-objectstore.jar`** in the build tree; the integrate classpath picks up a webapp-build copy, not just `dist/`. All three must be patched or the fix appears to do nothing:
```
/intermine/intermine/objectstore/main/dist/intermine-objectstore.jar
/intermine/bio/webapp/build/webapp/WEB-INF/lib/intermine-objectstore.jar
/intermine/intermine/webapp/main/build/webapp/WEB-INF/lib/intermine-objectstore.jar
```
Recompile + `jar uf` each:
```bash
cd /intermine/intermine/objectstore/main
CP=$(find /intermine -name "*.jar" | tr "\n" ":")
javac -cp $CP -d build/classes src/org/intermine/sql/writebatch/PostgresDataOutputStream.java
for J in <the three jars>; do jar uf $J -C build/classes org/intermine/sql/writebatch/PostgresDataOutputStream.class; done
```

Patched source archived at `mousemine:/root/rc3_patches/PostgresDataOutputStream.java.patched`. **This is the one fix worth upstreaming / baking into the mousemine Docker image** — it would have saved ~2 days.

## Other integration fixes (in order hit)

1. **`interpro` + `protein2ipr` — skipped.** The InterProConverter emits the same `0x00`; even after the writer patch, interpro's XML had a deeper SAX issue and protein2ipr depends on interpro. Commented both out of `project.xml` (`<!-- SKIPPED rc3 … -->`). They were in rc2 — effect is users keep rc2-era InterPro domain data. Revisit upstream.

2. **`mgi-base` duplicate items** — `IllegalArgumentException: There are duplicate objects … multiple items exist with the same item.identifier` (18 `AlleleMolecularMutation` items with the same osbid resolution). Fix: add to the mgi-base source in `project.xml`:
   ```xml
   <property name="ignore.duplicates" value="true"/>
   ```

3. **`mgi-base` field-priority conflict** — `Conflicting values for field Chromosome,Gene.name … needs configuring in genomic_priorities.properties`. Fix: add ONE rule to all 3 copies of `genomic_priorities.properties` (resources + build/model + build/classes):
   ```properties
   BioEntity.name = mgi-base, *
   ```
   ⚠️ Do NOT also add `Gene.name` / `Chromosome.name` — InterMine throws `multiple priorities configured for Gene.name (found a match on Gene.name and BioEntity.name)`. The parent `BioEntity.name` covers the subclasses.

4. **`update-publications` — skipped.** `ProxyReference … id not in ID Map` (looks up a publication id not pre-loaded). Commented out of `project.xml`. Minor — publication metadata enrichment only.

`project.xml` + `genomic_priorities.properties` patched copies archived at `mousemine:/root/rc3_patches/`.

mgi-base is the heavy source: **~12.5 hours** to integrate on the final clean run (1.5M+ items), then a ~10-min checkpoint copy.

## RDS storage-full incident (2026-06-18 → 06-19)

During the `create-autocomplete-index` postprocess, its `createdb -T` checkpoint (~194 GB copy) ran the RDS instance to **0 bytes free**. Postgres entered `storage-full` and refused ALL connections → **every mine (alliancemine/flymine/wormmine/yeastmine) went down**, not just the build.

- RDS `intermine-postgres` was at allocated 1000 GB / **max-allocated 1000 GB (no autoscale headroom)**.
- Recovery requires growing allocated storage — there is **no self-heal**. The dev-host + multitenant instance roles (`S3DataAccess`) lack `rds:ModifyDBInstance`; it had to be run with admin creds:
  ```bash
  aws rds modify-db-instance --db-instance-identifier intermine-postgres \
    --allocated-storage 1500 --max-allocated-storage 2000 --apply-immediately
  # NOTE: must raise max-allocated at the same time, else
  #   InvalidParameterCombination: Max storage size must be greater than storage size
  ```
- Provisioning took ~5 min; instance went `storage-full` → `modifying` → `available`; all mines recovered automatically once free space returned (~528 GB free after).

**Storage hygiene that helped:** dropped obsolete build artifacts to claw back ~165 GB (`mousemine_db` 3.5 GB stale, `mousemine_rc3:mus_spretus-gff` checkpoint 144 GB, `flymine_…:entrez-organism` 17 GB, old flymine rc1/rc2). **Lesson:** before a MouseMine build, ensure RDS free ≥ 2× the final DB size (checkpoints transiently double it), and confirm `MaxAllocatedStorage` has headroom so autoscale can save you.

## Failure timeline (for reference)

| Round | Died on | Cause | Fix |
|---|---|---|---|
| 1–2 | `so` | 0x00 (source-strip dead end) | — |
| 3 | — | (build-db OK, schema 227 tables) | — |
| 4–6 | `mgi-base` | 0x00 via writer | patch `writeLargeUTF` (all 3 jars) |
| 7 | `mgi-base` HTIndex.xml | iconv corrupted source XML | restore source from `.bak` |
| 8 | `mgi-base` | duplicate AlleleMolecularMutation | `ignore.duplicates=true` |
| 9 | `mgi-base` | Conflicting Gene/Chromosome name | `BioEntity.name = mgi-base, *` |
| 10 | `uniprot` | 2 priority rules for Gene.name | drop Gene.name/Chromosome.name, keep BioEntity.name |
| 11 | `update-publications` | ProxyReference id not in map | skip source |
| 11.5 | — | all 16 sources done | run postprocess `-a do-sources-` |
| pp | `summarise-objectstore` | **RDS storage-full** | grow RDS 1000→1500 GB |
| pp2 | — | summarise + create-search-index OK | — |
| war | — | **WAR built, 87 MB** | done |

## Remaining work

1. **Cutover** (deferred): copy WAR to multitenant `/home/ec2-user/mine-wars/mousemine.war`, point `mousemine-1x` properties at `mousemine_rc3`, restart. ⚠️ First restart triggers a ~30-min legacy Lucene keyword-search re-extract (MouseMine uses Lucene, not Solr — see `project_mousemine_keyword_search` memory). Warm a search after restart.
2. **Re-add `interpro` / `protein2ipr` / `update-publications`** once the converters are fixed upstream.
3. **Bake the `writeLargeUTF` patch into the mousemine Docker image** so future builds don't rediscover it.
4. **Drop `mousemine_rc2`** (252 GB) only AFTER rc3 cutover is verified — it's the rollback.

## Related

- `JOB_AID_MOUSEMINE.md` / `MOUSEMINE_BUILD_GUIDE.md` — container access + base build steps
- `project_mousemine_keyword_search` memory — Lucene (not Solr); warm after restart
- `INCIDENT_MULTITENANT_REBOOT_2026_06_23.md` — the reboot that followed this incident (Solr DNAT + WAR persistence)

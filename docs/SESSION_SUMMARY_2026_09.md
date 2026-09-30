# Session summary — September 2026

One long working session, from about 2026-09-10 to 2026-09-30, across the AGR InterMine hosts:
three production releases, the MouseMine move to InterMine 5.1, several production incidents
found and fixed, a host upgrade, automation, and a full backup. This page is the overview; each
item links to its detailed document.

Hosts: build host **AllianceMineDev** `172.31.60.197`; production **multitenant** `172.31.59.87`
(public IP `98.94.35.110` since the resize); shared RDS `intermine-postgres`.

## At a glance

| Area | Outcome |
|---|---|
| Releases | AllianceMine 9.1.0, YeastMine rc3, FlyMine rc3 (crossReference clean reload) live |
| Mail | SES forgot-password fix on all 5 mines, and baked into builds |
| MouseMine 5.1 | Port built, validated against 1.8, running on multitenant :8088 with a copy of production users/lists |
| MouseMine 1.8 | 6-day outage found and fixed; stale model-browser counts fixed; 2.5-hour restart outage patched away |
| FlyMine | Keyword search (broken since the rc2/rc3 switch) reindexed and fixed |
| YeastMine | Weekly Friday build with automatic deploy; build date + GO version in the header; logo fixed |
| WormMine | WormBase logo in BlueGenes |
| Infrastructure | Multitenant 32 → 64 GB; new Tomcat 5.x image; 297 GB of RDS checkpoints dropped; full S3 backup |
| Tooling | Resize runbook, 1.8-vs-5.1 comparison tool, FlyMine reindex script, MouseMine 5.1 build runner |

## Timeline

| When | What |
|---|---|
| ~09-03 to 09-10 | Three-mine release: **AllianceMine 9.1.0**, **YeastMine R64-5-1 rc3**, **FlyMine rc2 → rc3** with a clean reload of gene crossReferences (key `subject, identifier, source`; stub genes stripped). STOCK re-verified. MouseMine userprofile work. |
| ~09-18 | **Mail on all mines**: the SES forgot-password fix re-applied to MouseMine, FlyMine and YeastMine (all 5 mines working). Made permanent with `scripts/bake_mail_into_war.sh` (525289b), wired into FlyMine's build. |
| 09-18 → 09-21 | **Unified builder** design proposal and review decisions (69c29ac, 438a243; `docs/UNIFIED_BUILDER_DESIGN.md`). Left as a proposal. |
| ~09-22 | Dropped 8 `alliancemine_9_1_0_rc1:*` checkpoint DBs (**297 GB**; RDS used 892 → 604 GB). The live DB was untouched. |
| 09-24 → 09-26 | **MouseMine 5.1 port**: gap inventory, build wiring, then a full test build (58 sources, 10 post-processes) with a string of 5.1 fixes and InterMine 5.1.0 patches. A single-JVM post-process leaked RDS connections and briefly locked production mines out (09-26 ~07:15–07:50 UTC); fixed by running one JVM per step. |
| 09-26 | 1.8 vs 5.1 validated: 118/129 classes identical; differences explained (report artifact). Repos pushed to private GitHub. |
| 09-27 | **`intermine-tomcat:agr-5x-runtime`** image built and tested on multitenant. |
| 09-28 | Found **MouseMine 1.8 dead since 09-22** (heap OOM, container still "Up"); restarted. Found `alliancemine-9.0.0-rc20` is the live AllianceMine 9.1.0 (stale name). **MouseMine 5.1 deployed** on :8088 with its own Solr cores and a copy of the production profile DB. Advised MGI on `www.mousemine.org` (redirect, since the ALB has no fixed IP). **YeastMine weekly build** designed and built. Stale 1.8 model-browser counts traced to a May summary and regenerated. |
| 09-29 | Restarting 1.8 to load the new counts caused a **2.5-hour outage** (the index reloads on every restart). Diagnosed, patched and deployed; restarts now take seconds. YeastMine header gets build date + GO version; YeastMine logo fixed. |
| 09-30 | **Multitenant resize** to r7i.2xlarge (64 GB), about 15 minutes of downtime; MouseMine 5.1 back up. **FlyMine search** reindexed and fixed. YeastMine deploy agent installed. WormMine logo. Full **S3 backup**. **1.8 vs 5.1 comparison** report. |

## By system

### MouseMine 5.1 (InterMine 5.1 port)
- Code: `nuin/mousemine-im5` and `nuin/mousemine-bio-sources-im5` (private GitHub, pushed).
  Scope and gaps are in `docs/IM5_PORT_GAP_INVENTORY.md`.
- Test DB `mousemine_im5_test`, built on AllianceMineDev with `scripts/im5_test_build.sh`
  (stages: prep, builddb, patches, integrate, postprocess (one JVM per step), war).
- InterMine 5.1.0 patches: NUL-safe `PostgresDataOutputStream`; re-executed load batches;
  chromosome-locations commit and lock fix; NCBIfam IDs in protein2ipr.
- Deployed at `http://172.31.59.87:8088/mousemine/` (internal): profile DB
  `mousemine_im5_userprofile` (copy of production, one renamed path migrated), Solr cores
  `mousemine-im5-test-*`.
- Compared with 1.8: 61/65 templates identical, 152/166 class counts identical. Differences:
  - fewer Panther homologues;
  - accented author names kept (a fix);
  - ontology cross-reference terms;
  - 5.1 misses term **synonym LOOKUP** (1.8's `bag-queries.xml` has an `OntologyTerm` section; to add);
  - one extra-ancestor case.
- Report: <https://claude.ai/artifact/MpEmxJdr9tQDs98tQVSchi>; tool: `scripts/compare_mines.py`.

### MouseMine 1.8 (production)
- **6-day outage** (09-22 to 09-28): heap OOM, and nothing restarted it. Now runs a 6 GB heap in an
  8 GB container with `ExitOnOutOfMemoryError`.
- **Stale counts**: the model browser showed May's numbers (for example 808,036 alleles against a
  real 823,414). The summary was regenerated for rc4.
- **Restart outage**: every restart re-extracted the 6.5 GB keyword index from the DB and blocked
  all Tomcat threads (1–2.5 hours down). Patched `KeywordSearch` to reuse the on-disk index
  (`patches/mousemine-1x/`, `docs/MOUSEMINE_1X_KEYWORD_INDEX_FIX.md`).
- `www.mousemine.org`: MGI redirects from their Apache server to `https://mousemine.alliancegenome.org/…`.

### YeastMine
- Weekly build: Fri 22:00 PT on the build host, with checks against the live build, then deploy
  via S3 on multitenant (Solr core swap, WAR swap, verify, automatic rollback). Keeps 4 builds.
  First run Fri 2026-10-02. Runbook: `docs/YEASTMINE_WEEKLY_BUILD.md`.
- Header shows `R64-5-1 (built <date>, GO <release>)`. Logo served from our host (the SGD host is dead).
- Found and fixed along the way:
  - a June-era Solr index (rebuilt weekly now);
  - WARs shipping empty mail settings;
  - `os.query.max-time` hand-set below InterMine's default.

### FlyMine
- Search failed on every query: the Solr index dated from rc1, but the DB was switched to rc3.
  Reindexed into standby cores and swapped (`docker/flymine/scripts/reindex_search.sh`).
  **Any future DB switch must include a reindex.**

### WormMine, AllianceMine
- WormMine: BlueGenes logo is now the WormBase worm mark (the generic logo came from the retired
  rawgit CDN).
- AllianceMine: 9.1.0 live, served by the container named `alliancemine-9.0.0-rc20` on :8086.
  Never retire it by name.

### Infrastructure
- Multitenant resize (`scripts/resize_multitenant.sh`): c7i.4xlarge → r7i.2xlarge (8 vCPU / 64 GB).
  Pre-resize snapshots `snap-0e342f558a6dea8f8` and `snap-0ceb298481f66b4d5`. All containers set to
  restart `unless-stopped`.
- `intermine-tomcat:agr-5x-runtime` (Tomcat 9.0.122 / JDK 11), `docs/INTERMINE_TOMCAT_DOCKER.md` §11.
- **Backup**: `s3://agr-db-backups/intermine-ops/2026-09-30/` (4.3 GB, README inside). It holds git
  bundles, all userprofile dumps, images, WARs, container and host config, and build-host scripts.

## Lessons (also saved as working notes)
- Check what a container actually serves (`service/version/release`, ALB target groups), not its name.
- A DB repoint also needs a **Solr reindex** and a **regenerated object-store summary**. Otherwise
  search breaks and counts go stale.
- Hand edits inside running containers are lost on the next WAR deploy. Put them in the build
  templates (mail, logos, release label).
- InterMine 5.x: run post-processing one JVM per step; Solr URLs live in resource files; the old 1.x
  paths `bioEntities` and `Strain.genome` are renamed.
- MouseMine 1.x must never be restarted casually without the index-reuse patch in place.
- Mines can OOM silently. `ExitOnOutOfMemoryError`, an `unless-stopped` restart policy, and an ALB
  `UnHealthyHostCount` alarm (still to add) are the defences.

## Open items
1. MouseMine 5.1: add the `OntologyTerm` synonym LOOKUP (`bag-queries.xml`); decide on Panther and
   the junk ontology terms; webapp work (JBrowse panel, JSP overrides, mail, CDN); public URL and
   BlueGenes.
2. Alerting on ALB `UnHealthyHostCount` for all mines; bot rate-limiting.
3. Watch the first YeastMine weekly build and deploy (Fri 2026-10-02 22:00 PT); the dead
   BlueGenes link in YeastMine's classic header.
4. `www.mousemine.org` CNAME: needs an ACM certificate (someone with ACM rights).
5. Push branch `unified-mine-builder` (agr_intermine_builder); it holds this session's commits.
6. Unified builder: still a proposal (`docs/UNIFIED_BUILDER_DESIGN.md`).

## Documents
- `docs/OPS_LOG_2026_09_25_TO_09_30.md`: detailed log of the second half
- `docs/YEASTMINE_WEEKLY_BUILD.md`: weekly build and deploy runbook
- `docs/MOUSEMINE_1X_KEYWORD_INDEX_FIX.md`: 1.8 restart-outage fix
- `docs/INTERMINE_TOMCAT_DOCKER.md` §11: Tomcat 5.x image
- `docs/UNIFIED_BUILDER_DESIGN.md`: unified builder proposal
- `mousemine-im5`: `docs/IM5_PORT_GAP_INVENTORY.md` (5.1 port scope)
- Reports: 1.8 vs 5.1 port differences <https://claude.ai/artifact/QBjchBuQV8nFx4W8q5LCzP>;
  side-by-side comparison <https://claude.ai/artifact/MpEmxJdr9tQDs98tQVSchi>

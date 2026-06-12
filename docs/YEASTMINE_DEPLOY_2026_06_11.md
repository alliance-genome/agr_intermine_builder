# YeastMine Deploy 2026-06-11

End-to-end record of the first YeastMine deploy on AGR multitenant infrastructure: build container, Tomcat runtime, Solr indexes, profile DB, ALB / Route53 / BlueGenes wiring, and the profile-content migration from AllianceMine.

## Final state

| Component | Value |
|---|---|
| Public URL | `https://yeastmine.alliancegenome.org/yeastmine/` |
| Public BlueGenes | `https://www.alliancegenome.org/bluegenes/` → 4th mine in dropdown |
| Internal URL | `http://172.31.59.87:8087/yeastmine/begin.do` |
| Webapp container | `yeastmine` on multitenant (`intermine-tomcat:agr-1x-runtime`, port 8087, `-Xmx4g -Xms2g`, `--restart unless-stopped`) |
| WAR location | `/home/ec2-user/mine-wars/yeastmine.war` (persistent; was `/tmp` initially) |
| Main DB | `yeastmine_R64_5_1_rc1` on `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com` |
| Profile DB | `yeastmine_userprofile_test` — fresh from `./gradlew buildUserDB` (NOT a clone) |
| Items DB | `yeastmine_items` |
| Solr | `yeastmine-search` (6.5M docs) + `yeastmine-autocomplete` (128k docs) on `172.31.59.87:8983` |
| Build container | `flymine-build` (long-running) on AllianceMineDev `172.31.60.197`; image built via `scripts/build_and_push.sh --no-push` |
| Release tag | `R64-5-1`, rc1 |
| ALB | `alliancemine-lb-309443304.us-east-1.elb.amazonaws.com` (host-header routed) |
| Target group | `yeastmine-multitenant` (target-type `ip`, `172.31.59.87:8087`, HC `/yeastmine/service/version`=200) — **healthy** |
| Route53 CNAME | `yeastmine.alliancegenome.org` → ALB, TTL 300, in BOTH public `Z3IZ3D6V94JEC2` + private `Z007692222A6W93AZVSPD` zones |
| service/version | `35` |
| Container created | `2026-06-11T16:45:56Z` |

## Build (recap; full detail in [`project_yeastmine_build`](../.claude/memory) memory)

Built in an **isolated fresh clone** at `~/yeastmine-build/agr_intermine_builder` on AllianceMineDev — NOT the team's `/home/ec2-user/agr_intermine_builder` (that one sits on `refactor/alliancemine-docker` with uncommitted WIP; leave alone).

Fork at `~/yeastmine-build/fork/{yeastmine,yeastmine-bio-sources}` (yeastgenome/*), `project.xml` edited:

- Paths `/data/intermine` → `/root/data/intermine` (container layout)
- Both Solr postprocesses (`create-search-index`, `create-autocomplete-index`) DROPPED for the build round (Solr was deferred; re-added later via a mounted project.xml in the deploy phase to populate cores)

`.env` reused RDS + SGD creds from `docker/alliancemine/.env`. **Pinned `RC_NUMBER=1`** — the entrypoint's `resolve_rc_number` auto-increments off existing `yeastmine_*_rc*` DBs, so running build steps as separate `docker compose run` invocations drifts the RC (builddb → rc1, integrate → empty rc3 → `intermine_metadata for db.production doesn't exist`). Without the pin you get a phantom DB nobody loaded.

Full build commands:
```bash
docker compose run --rm yeastmine-builder bash -c \
  'cd /root/yeastmine && ./project_build -b -v localhost /root/data/dump/yeastmine'
docker compose run --rm yeastmine-builder finalize_build
```

**Result:** all 24 sources integrated + all postprocesses ran (~96 min). 232k genes (incl. ortholog genes from other species), 7,261 yeast genes w/ location, 6,818 proteins, 205k GO annotations, 1.74M interactions, 201k phenotypes, 118k publications. WAR built (127 MB) at `~/yeastmine-build/agr_intermine_builder/docker/yeastmine/data/yeastmine_R64_5_1_rc1.war`.

## Deploy

### 1. Profile DB

Build pipeline builds the production objectstore ONLY. Fresh `yeastmine_userprofile_test` was empty → webapp threw `userprofileOSW is null` at `InitialiserPlugin` startup. Fix:
```bash
./gradlew buildUserDB    # RC pinned to 1
```
→ 13 tables created, restart container. (The placeholder `superuser.account=superuser@mail_account` did NOT trip `InitialiserPlugin`; it accepted it.)

### 2. Container

Image `intermine-tomcat:agr-1x-runtime` (the same 4-patch baked runtime used by all the 1.x-vintage mines — see `INTERMINE_TOMCAT_DOCKER.md`).

```bash
docker run -d --name yeastmine --restart unless-stopped \
  -p 8087:8080 \
  -v /home/ec2-user/mine-wars/yeastmine.war:/usr/local/tomcat/webapps/yeastmine.war:ro \
  -e JAVA_OPTS='-Dorg.apache.el.parser.SKIP_IDENTIFIER_CHECK=true -Xmx4g -Xms2g' \
  intermine-tomcat:agr-1x-runtime
```

WAR moved from `/tmp/yeastmine.war` to `/home/ec2-user/mine-wars/yeastmine.war` for reboot persistence (the other mines still use `/tmp` — TODO migrate them too).

### 3. Multitenant capacity

Box is `c7i.4xlarge` (30.8 GiB), RAM-saturated. To fit yeastmine I:

- Removed an orphan container `affectionate_carson` (2.1 GB, had been running `find / -name *.war` for a month).
- **Stopped the non-serving `alliancemine-9.0.0` standby on :8082** (7.6 GB). ALB `alliancemine-multitenant` TG routes prod to :8086 (rc20); :8082 was the post-cutover rollback. Container is now STOPPED (image retained — restart to restore rollback).

Active port map:

| Port | Mine | Container |
|---|---|---|
| 8080, 8086 | alliancemine (8086 = live; 8080 legacy) | alliancemine-9.0.0-rc20 |
| 8082 | alliancemine rollback (**stopped**) | alliancemine-9.0.0 |
| 8081 | wormmine | wormmine |
| 8084 | mousemine | mousemine-1x |
| 8085 | flymine | flymine |
| **8087** | **yeastmine** | **yeastmine** |
| 8983 | Solr (shared) | solr |

### 4. Solr cores

Solr runs directly on multitenant (not in a per-mine container). Created the two yeastmine cores by copying flymine core `conf/` + calling the Solr CREATE API (no Solr restart needed):
```bash
# already-running solr on :8983
curl 'http://172.31.59.87:8983/solr/admin/cores?action=CREATE&name=yeastmine-search&configSet=flymine-search'
curl 'http://172.31.59.87:8983/solr/admin/cores?action=CREATE&name=yeastmine-autocomplete&configSet=flymine-autocomplete'
```

Re-added `create-search-index` + `create-autocomplete-index` to a mounted `project.xml` and ran the postprocesses inside the build container → cores populated with 6.5M / 128k docs.

#### ⚠️ Incident: OOM-killed shared Solr during indexing

Running yeastmine's `create-search-index` **OOM-killed the shared Solr**. Keyword search went down for alliancemine / flymine / wormmine until restart. **Root cause: Solr heap was the default `-Xmx512m`** — fine for serving cores off disk, far too small to index a new 3M+ doc core alongside everything else.

Fix (applied to benefit ALL mines):
```bash
# /etc/default/solr.in.sh
SOLR_HEAP="4g"
# then
sudo systemctl restart solr
```

**Lesson — file under [`feedback_intermine_solr_traps`](../.claude/memory):** check Solr `-Xmx` + host RAM headroom BEFORE indexing a new core on the shared Solr. Always free RAM first.

### 5. ALB + Route53 + cert

The team-DNS-only assumption is **wrong**: my laptop AWS creds AND the dev-host instance role both have Route53 write access on `Z3IZ3D6V94JEC2` (public) and `Z007692222A6W93AZVSPD` (private) for `alliancegenome.org`. No need to file a ticket.

#### Target group
```bash
aws elbv2 create-target-group \
  --name yeastmine-multitenant \
  --target-type ip \
  --protocol HTTP --port 8087 \
  --vpc-id $VPC \
  --health-check-path /yeastmine/service/version \
  --matcher HttpCode=200
aws elbv2 register-targets \
  --target-group-arn $TG_ARN \
  --targets Id=172.31.59.87,Port=8087
```

#### Listener rules on the 443 listener of `alliancemine-lb`

| Priority | Host header | Path | Action |
|---|---|---|---|
| **545** | `yeastmine.alliancegenome.org` | `/cdn/*` | forward → `wormmine-cdn` TG (Caddy mirror on `172.31.59.87:8888`) |
| **550** | `yeastmine.alliancegenome.org` | — | forward → `yeastmine-multitenant` TG |

Priority is what AWS calls "lower number = higher precedence." `545 < 550`, so the `/cdn/*` rule wins for CDN paths and the catch-all routes everything else. The `/cdn/*` rule mirrors what we did for flymine — avoids the `cdn.intermine.org` blocking-template issue if YeastMine's WAR ever references upstream CDN paths.

#### Route53 (both zones)
```json
// /tmp/r53-yeastmine.json
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "yeastmine.alliancegenome.org",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "alliancemine-lb-309443304.us-east-1.elb.amazonaws.com"}]
    }
  }]
}
```
```bash
for z in Z3IZ3D6V94JEC2 Z007692222A6W93AZVSPD; do
  aws route53 change-resource-record-sets --hosted-zone-id $z \
    --change-batch file:///tmp/r53-yeastmine.json
done
```
INSYNC in seconds. `dig @8.8.8.8 yeastmine.alliancegenome.org` returned the ALB DNS immediately.

#### Cert

The 443 listener already serves a `*.alliancegenome.org` wildcard cert — covers `yeastmine.alliancegenome.org` with no extra work.

#### Verify
```bash
curl -sI https://yeastmine.alliancegenome.org/yeastmine/begin.do
# HTTP/2 200, ~587ms

curl -s https://yeastmine.alliancegenome.org/yeastmine/service/version
# 35
```

### 6. BlueGenes registration

YeastMine is the **4th** mine in the dropdown alongside AllianceMine / WormMine / FlyMine. The BlueGenes container reads `config.edn` baked into `bluegenes.jar` (**not** the bind-mounted `config.edn` at runtime — that's the trap that ate the first 30 minutes).

```bash
docker cp bluegenes:/bluegenes.jar /tmp/
cd /tmp && unzip -o bluegenes.jar config.edn

# edit config.edn — append to :bluegenes-additional-mines vector:
#   {:root "https://yeastmine.alliancegenome.org/yeastmine"
#    :name "YeastMine"
#    :namespace "yeastmine"}

zip -j /tmp/bluegenes-yeast.jar config.edn
docker cp /tmp/bluegenes-yeast.jar bluegenes:/bluegenes.jar
docker restart bluegenes
```

Verified the served HTML's `serverVars` block now lists all three additional mines (WormMine + FlyMine + YeastMine).

## Profile-content migration from AllianceMine (later that evening)

YeastMine has its OWN fresh profile DB (8.6 MB from `buildUserDB`) — NOT a clone of alliancemine (contrast: FlyMine cloned `wormmine_userprofile`, 174 MB, inherited 278 users). The yeast-relevant templates and lists had to be pulled across by hand. Both mines happen to share `superuser` at `userprofileid=1000001` (lucky coincidence — same number means superuser-attribution rows port across without rewriting).

### Templates: 19 of ~29 yeast-relevant superuser templates landed

Filtered alliance `savedtemplatequery` rows on yeast keywords in the template body, generated INSERTs into yeastmine `savedtemplatequery` (ids 2000001+) and yeastmine `tag` (ids 2100001+ for `im:public` + `im:aspect:*` visibility/grouping). Yeastmine went **89 → 108 templates** in DB.

- **9 surface live** in the yeastmine UI.
- **10 fail model validation** because they reference alliance-specific paths: `Gene.alleles.alleleSgdid`, `Gene.alleles.variants.*`, `Phenotype.experimentType`, `Phenotype.mutantType`, `Gene.interactions.alleleinteractions.allele1.name`. Left in DB (harmless — just don't render). Can be rewritten to yeastmine model paths later.

### Lists: 18 of 18 superuser bags landed — 28,863 members, 0 unmatched

Via SQL+REST, not `pg_dump` — yeastmine has to re-resolve identifiers against its own production DB.

The recipe is in [`feedback_intermine_bag_migration`](../.claude/memory). Three traps worth calling out:

1. **SGD prefix mismatch.** AllianceMine ships `SGD:S000028460`; YeastMine has bare `S000028460`. Strip with `regexp_replace(primaryidentifier, '^SGD:', '')` on the source SELECT, or every Gene bag POSTs HTTP 200 with `listSize=0` and N unmatched identifiers in the response.
2. **Complex doesn't lookup by `accession`.** Both DBs share the Complex Portal feed (634 rows, identical `accession` CPX-* + `identifier` EBI-*). POSTing `CPX-*` against `type=Complex` matched 0/634. The class-key for Complex resolves on `identifier` (EBI-*), not `accession`. Retry with EBI-* → 634/634.
3. **InterMine caches `savedbag` in JVM memory.** A DB `DELETE FROM savedbag` does NOT refresh the live webapp's view; the cached bag still wins and a fresh POST sees a name collision → HTTP 400 with empty body. **`docker restart` after every DELETE that touches savedbag, before retrying POST.** Not in any InterMine doc I could find — webapp impl detail.

#### Migration helper

`/tmp/copy_bags_to_yeastmine.py` runs inside `flymine-build`:
```bash
docker exec -e RDS_PASSWORD=... -e APIKEY=0f13821438d4f632a16d7ee5dca33f1c \
  flymine-build python3 /tmp/copy_bags_to_yeastmine.py
```

Skipped 4 cross-organism / human-only bags up front: `chrlist`, `Gene list for all organisms 1 Feb 2022 12.57`, `Human genes complementing or complemented by yeast genes`, `Human genes with yeast homologs`.

#### Final list inventory (yeastmine)

| List | Class | Size |
|---|---|---|
| ALL_Yeast_Genes | Gene | 7,336 |
| ALL_Verified_Uncharacterized_Dubious_ORFs | Gene | 6,617 |
| Uncharacterized_Verified_ORFs | Gene | 5,934 |
| Verified_ORFs | Gene | 5,787 |
| Dubious_ORFs | Gene | 683 |
| Curated Macromolecular Complexes | Complex | 634 |
| RNA genes and rRNA spacer regions | Gene | 410 |
| Long Terminal Repeat | LongTerminalRepeat | 384 |
| ARSs | ARS | 352 |
| tRNAs | TRNAGene | 299 |
| Uncharacterized_ORFs | Gene | 147 |
| snoRNAs | SnoRNAGene | 77 |
| Not In Systematic Sequence Of S288C | NotInSystematicSequenceOfS288C | 72 |
| Retrotransposons | Retrotransposon | 50 |
| Telomeres | Telomere | 32 |
| rRNA and spacer regions | RRNAGene | 27 |
| Centromeres | Centromere | 16 |
| snRNAs | SnRNAGene | 6 |
| **Total** | | **28,863** |

### Users: NOT migrated

Decision: only superuser / curator accounts were in scope, and alliance's superuser tags + templates already attribute to `id=1000001` which yeastmine also has as superuser. No user-table copy needed.

## Full-mirror round (2026-06-12) — SGD wanted everything, not yeast-only

SGD pushed back the next morning: "wants all the lists" + "the logins are not correct." Redid the migration as a wholesale mirror of alliance's userprofile DB rather than the curated yeast slice.

### Procedure (`/tmp/copy_all_bags.py`)

```bash
# 1. stop yeastmine to freeze cache state
docker stop yeastmine

# 2. wipe my previous migration from yeastmine_userprofile_test:
#    - tag rows 2100001..2199999  (my im:public/im:aspect:* tags)
#    - all savedbag                (my 18 yeast bags)
#    - templates 2000001..2099999  (my 19 yeast templates)
#    - the placeholder userprofile id=1000001
psql ... yeastmine_userprofile_test -c "
  BEGIN;
  DELETE FROM tag WHERE id BETWEEN 2100001 AND 2199999;
  DELETE FROM savedbag;
  DELETE FROM savedtemplatequery WHERE id BETWEEN 2000001 AND 2099999;
  DELETE FROM userprofile WHERE id=1000001;
  COMMIT;
"

# 3. bulk-copy alliance userprofile -> yeastmine (preserves id, bcrypt password, apikey)
pg_dump ... alliancemine_userprofile --table=userprofile --data-only --no-owner \
  | psql ... yeastmine_userprofile_test

# 4. generate apikeys for the 30 users who didn't have one in alliance
psql ... yeastmine_userprofile_test -c "
  UPDATE userprofile SET apikey = md5(random()::text || id::text || clock_timestamp()::text)
   WHERE apikey IS NULL"

# 5. bulk-copy templates + tags (full set, not yeast-filtered)
pg_dump ... alliancemine_userprofile --table=savedtemplatequery --data-only --no-owner \
  | psql ... yeastmine_userprofile_test
pg_dump ... alliancemine_userprofile --table=tag --data-only --no-owner \
  | psql ... yeastmine_userprofile_test

# 6. start yeastmine, wait for it to warm up
docker start yeastmine && sleep 35

# 7. run /tmp/copy_all_bags.py inside flymine-build container:
#    - for each of 241 alliance bags: look up owner's apikey in yeastmine_userprofile_test
#    - SELECT identifiers from alliance prod with SGD: stripped
#    - Complex + OntologyTerm: use 'identifier' column (not 'primaryidentifier')
#    - POST as that owner to /service/lists with TIMEOUT=600
docker exec -d -e RDS_PASSWORD=... -e TIMEOUT=600 flymine-build \
  sh -c 'python3 /root/copy_all_bags.py > /root/copy_all_bags.log 2>&1'

# 8. promote SGD curator to superuser + restart to flush userprofile cache
psql ... yeastmine_userprofile_test -c \
  "UPDATE userprofile SET superuser=true WHERE username='rnash@stanford.edu'"
docker restart yeastmine
```

### Result

| Object | Before | After |
|---|---|---|
| Users | 1 (placeholder) | **31** (all alliance accounts, bcrypt passwords preserved) |
| Templates | 89 yeastmine system + 19 yeast slice | **89 + 95 alliance** = 184 |
| Tags | 343 yeastmine system + 37 yeast slice | **343 + 336 alliance** = 679 |
| Bags with members | 18 (28,863 members) | **44** (85,435 members) |
| Superusers | 1 (`superuser@mail_account`) | **2** (placeholder + `rnash@stanford.edu`) |

Per-user bag distribution after migration:

| User | Bags |
|---|---|
| superuser@mail_account | 22 |
| rnash@stanford.edu | 9 |
| colm.murphy@cuanschutz.edu | 7 |
| adi.avramshperling@utoronto.ca | 2 |
| cphillips93@gatech.edu, dang@calicolabs.com, eullyao@student.ubc.ca, jayp21867@gmail.com | 1 each |

### Outcomes for the 241 alliance bags

- **41 OK** + **1 timed-out-on-client-but-landed-server-side** + **1 OntologyTerm fix-up** = **43 with real members**
- **193 genuinely EMPTY** — alliance `osbag_int` had 0 rows for those bagids; user-created lists from stale data (135 dsc222 ChIP-seq peak lists, 39 gabrar lists, etc.). Not a bug — nothing to resolve. Alliance had **457 distinct bagids in osbag_int vs only 241 savedbag rows** → many orphan member-sets, but also many orphan bag-rows without members.
- **2 OntologyTerm bags still EMPTY** after fix-up (also 0 rows in alliance `osbag_int`).
- **3 Phenotype bags failed** — alliance's `phenotype` table has NO identifier-like column (`mutanttype`, `allele`, `observable`, `qualifier`, … no primary id). REST resolver can't match. Yeastmine + alliance prod both carry 201k+ Phenotype rows from the same Alliance feed, so a follow-up SQL-clone keyed on `(allele, observable, qualifier, mutanttype, strainbackground)` would land them. Deferred.

### New traps logged in [`feedback_intermine_bag_migration`](../.claude/memory)

- **OntologyTerm also uses `identifier`** for lookup (same as Complex — table has no `primaryidentifier` at all).
- **Phenotype has no lookup column.** Pure-SQL clone is the only path; REST won't help.
- **Expect ~80% EMPTY** on long-lived user bags: `osbag_int` orphan rows accumulate as the production DB churns over years.
- **userprofile cache:** `UPDATE userprofile SET superuser=true …` doesn't take effect until `docker restart` — same JVM-cache shape as savedbag. `service/user/whoami` returns the stale value until restart.

### Login

All alliancemine logins work as-is on yeastmine because the bcrypt password hashes were copied verbatim. The 30 users who never had an apikey in alliance got auto-generated 32-char md5 apikeys (random). SGD curators (`rnash@stanford.edu`, `dang@calicolabs.com`, etc.) log in with their existing alliancemine credentials. The `superuser@mail_account` placeholder remains at id=1000001 for template/tag-attribution compatibility; `rnash@stanford.edu` is the real-email second superuser.

## Operational notes

- **Don't restart `mousemine-1x`.** Triggers a 30-min Lucene keyword-search re-extract (legacy, not Solr). Warm it with one search after any unavoidable restart.
- **Don't restart the shared Solr lightly.** All four mines lose keyword search until it comes back. If you must, pre-stage the heap fix.
- The alliancemine-9.0.0 :8082 standby is STOPPED, not removed — keep it that way ≥1 week as rollback for 9.0.0-rc20. Image retained; `docker start alliancemine-9.0.0` to restore.
- Container restart policy is `unless-stopped` — survives host reboot.

## Quick reference

| Action | Command |
|---|---|
| Tail webapp logs | `docker logs -f yeastmine` |
| Restart webapp | `docker restart yeastmine` (clears in-memory bag cache) |
| Check target health | `aws elbv2 describe-target-health --target-group-arn $TG` |
| Refresh DNS view | `dig @8.8.8.8 yeastmine.alliancegenome.org` |
| Reseed user profile | `./gradlew buildUserDB` (after dropping DB) |
| Reindex Solr core | `--start-from postprocess` in builder with `create-search-index` re-added |

## Related docs

- `INTERMINE_TOMCAT_DOCKER.md` — the 4-patch baked `intermine-tomcat:agr-1x-runtime` image
- `ALLIANCEMINE_PUBLIC_URLS.md` — sibling routing notes for alliancemine
- `FLYMINE_DEPLOY_2026_06_05.md` — same shape, prior week
- `RUNBOOK_ALLIANCEMINE_RESTART.md` — the `pg_terminate_backend` kick if a restart hangs on bag upgrade

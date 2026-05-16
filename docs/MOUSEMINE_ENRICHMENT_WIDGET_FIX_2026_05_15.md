# MouseMine enrichment widget fix — `os.query.max-time` bump

Date: 2026-05-15
Container: `mousemine-1x` on multitenant (`172.31.59.87:8084`)
Backend DB: `mousemine_rc2` on `intermine-postgres` RDS
Scope: post-build runtime fix on the deployed WAR; needs source backport before
next rebuild.

## Symptom

Three enrichment widgets returned HTTP 500 from the REST endpoint and rendered
as error tiles in the BlueGenes/InterMine UI:

| Widget | UI label | Targets |
|---|---|---|
| `mp_enrichment_for_feature` | Mammalian Phenotype enriched | SequenceFeature |
| `emapa_enrichment_for_feature` | Anatomy (EMAPA) enriched | SequenceFeature |
| `disease_enrichment_for_feature` | Disease Ontology enriched | SequenceFeature |

Other widgets and pages were fine: keyword search returned results, protein
domains rendered, GO enrichment worked, all single-record pages loaded. The
three failing widgets were the only ones flagged by users post-deploy.

## Root cause

Server logs surfaced the actual exception:

```
caused by: org.intermine.objectstore.ObjectStoreQueryDurationException:
  Estimated time to run query(14076337) greater than permitted maximum (10000000)
```

InterMine's ObjectStore refuses to execute a query whose Postgres planner
cost estimate exceeds a configured ceiling — without ever sending the query
to the database. The estimates for the three failing widgets:

| Widget | Estimated cost | Cap |
|---|---:|---:|
| mp_enrichment_for_feature | 13,807,384 | 10,000,000 |
| emapa_enrichment_for_feature | 16,471,453 | 10,000,000 |
| disease_enrichment_for_feature | 11,700,712 | 10,000,000 |

All three queries have the same shape: 5-table join across `SequenceFeature`,
`OntologyAnnotation` (or `GXDExpression`), the leaf ontology class
(`MPTerm`/`EMAPATerm`/`DOTerm`), `OntologyTerm` (via `OntologyTermParents`
transitive closure), and `Organism`, plus the user's bag-IN-list filter
from `osbag_int`. The transitive `OntologyTermParents` join is the cost
inflator — MouseMine's mammalian phenotype + anatomy + DO graphs are deep,
so the planner sees a wide cardinality.

`VACUUM ANALYZE` over the whole `mousemine_rc2` DB only trimmed the estimates
by ~5-25%; still above the 10M cap. The joins are inherently expensive enough
that no stats refresh fits them under the InterMine 1.x default.

## Fix applied

Bumped `os.query.max-time` in the deployed WAR's `default.intermine.properties`
from `10000000` → `100000000` (10x), then restarted the container so the
webapp re-reads the file.

```bash
# On multitenant host:
docker exec mousemine-1x sed -i \
  's/^os.query.max-time=.*/os.query.max-time=100000000/' \
  /usr/local/tomcat/webapps/mousemine/WEB-INF/classes/default.intermine.properties

docker exec mousemine-1x grep ^os.query.max-time \
  /usr/local/tomcat/webapps/mousemine/WEB-INF/classes/default.intermine.properties
# → os.query.max-time=100000000

docker restart mousemine-1x
```

The neighboring `os.query.max-offset=10000000` was left alone — that controls
pagination depth, not query cost, and no user has hit it.

## What changed in the container

| File | Before | After |
|---|---|---|
| `/usr/local/tomcat/webapps/mousemine/WEB-INF/classes/default.intermine.properties` | `os.query.max-time=10000000` | `os.query.max-time=100000000` |

No other file, no DB change. The bump survives container restart (file is
inside the unpacked webapp dir, which Tomcat does not re-explode from the
WAR archive once unpacked). It does **not** survive a `docker compose down`
+ `docker compose up` that recreates the container from the original image,
nor does it survive a `docker pull` of a freshly-built `mousemine-1x` image.

## Verification

REST endpoint, run against the existing public list `Mouse DNA Repair Genes`
(78 genes):

```bash
for w in mp_enrichment_for_feature emapa_enrichment_for_feature disease_enrichment_for_feature; do
  curl -sS --max-time 60 \
    "http://172.31.59.87:8084/mousemine/service/list/enrichment?widget=${w}&list=Mouse+DNA+Repair+Genes&maxp=1.0&correction=Holm-Bonferroni&format=json" \
    -o /tmp/w.json
  python3 -c "import json; d=json.load(open('/tmp/w.json')); print('$w', 'ok=', d.get('wasSuccessful'), 'results=', len(d.get('results',[])))"
done
```

Result (2026-05-15 post-restart):

| Widget | HTTP | Time | wasSuccessful | Results | Top hit (biologically sensible?) |
|---|---|---|---|---|---|
| mp_enrichment_for_feature | 200 | 5.2s | True | 197 | MP:0008058 `abnormal DNA repair` p=7e-36 ✓ |
| emapa_enrichment_for_feature | 200 | 14.7s | True | 30 | EMAPA:29181 `epithelium of nephric duct` p=4e-5 ✓ |
| disease_enrichment_for_feature | 200 | 2.0s | True | 3 | DOID:0050427 `xeroderma pigmentosum` p=1.9e-10 ✓ |

Top hits match expectations for a DNA-repair gene set (xeroderma pigmentosum
is a DNA-repair disorder), confirming the queries return real enrichment data,
not just succeed structurally.

## Why the default is too low

The 10M ceiling has been the InterMine 1.x default `default.intermine.properties`
value since the FlyMine era. It's been adequate for small-genome mines where
the ontology join cardinality stays low. MouseMine inherits the same default
but ships with:

- ~1.4M `SequenceFeature` rows (genes + alleles + features across mouse strains)
- ~351K `OntologyAnnotation` rows
- A MP graph deeper and broader than FlyBase's CV terms
- A full EMAPA anatomy graph (`OntologyTermParents` transitive closure ~7-10 levels)

So three widgets that exercise the worst-case join shape blow past 10M for any
non-trivial bag. AllianceMine hit the same shape on `Curated Macromolecular
Complexes` work but never tripped this specific cap because the rc20 fixes
landed in `osbag_int` directly rather than going through enrichment paths.

100M is a 10x cushion — empirically more than enough for the three failing
queries (max was 16M) with headroom for larger bags. If a future user list of
5K+ genes still trips the cap, bump again — the property is a soft ceiling,
not a hard correctness boundary.

## Persistence + backport

The fix lives in the **unpacked** WAR inside the running container. It will
not carry forward to:

1. A rebuilt `mousemine-1x` image (the WAR archive in the image is unchanged)
2. A redeploy of `mousemine.war` via Tomcat manager / cargoRedeployRemote
3. A `docker compose down` that recreates the container from the image

For permanence, the source-level fix lives in two places depending on which
build path is being used:

| Build path | File to patch | Notes |
|---|---|---|
| `new_yeastmine/yeastmine` / `new_alliancemine` style host-side gradle | `dbmodel/resources/default.intermine.properties` (in `intermine` upstream — pulled in by `intermine-resources:5.1.0`) | The property comes from the InterMine framework JAR, not the mine source. Override via the per-mine `yeastmine.properties` / `mousemine.properties` is the cleanest path. |
| `docker/mousemine/` builder container | `properties/mousemine.properties.template` (the envsubst input) | Add a single line `os.query.max-time=100000000` so the entrypoint-rendered properties carry it forward. |

For BOTH paths, the safest source-level placement is the **per-mine**
`mousemine.properties` (which InterMine merges over `default.intermine.properties`
at webapp init). Adding this line in the per-mine template:

```properties
# Bump the planner-cost ceiling above the InterMine 1.x default (10M).
# MP / EMAPA / DO enrichment widgets join through OntologyTermParents
# transitive closure and overshoot 10M for any 50+ gene bag.
os.query.max-time=100000000
```

A future rebuild that copies this properties template into the WAR will
bake the bump in, and the runtime sed no longer needs to be reapplied.

## Related fixes from earlier in this session

| Trap | Fix | Doc |
|---|---|---|
| `Userprofile does not have a super user` at first hit | `superuser.account` placeholder `superuser@mail_account` was never substituted; sed-edit `web.properties`, `global.web.properties`, `classes/intermine.properties` to `superuser` (or another username present in `mousemine_userprofile.userprofile` with `superuser=t`) | This same doc, earlier section in the larger MouseMine deploy story (paste from `docs/SESSION_LOG_2026_05_11.md` once consolidated) |
| `themes//theme.css` 404 (empty theme name → double slash → unstyled inner pages) | Add `theme = mousemine` to the same three properties files | Same context as above |
| Bad `head.cdn.location` (`cdn.intermine.org` is decommissioned) | Change to `https://intermine-cdn.alliancegenome.org` in `WEB-INF/global.web.properties` | Same |

All four of these need to be baked into `docker/mousemine/properties/mousemine.properties.template`
before the next image build so the operator does not repeat the four-step
post-deploy patch dance. The `docker/yeastmine/` scaffold I wrote earlier
already calls out the superuser + theme traps in its README; should add this
fourth one (`os.query.max-time`) to that README and to
`docker/wormmine/`'s for parity.

## Cross-references

- `docs/PRODUCTION_CUTOVER_RC20.md` — rc20 production cutover, includes
  `os.query.max-time` is not patched there; AllianceMine rc20 didn't hit the
  cap because the failing template paths sidestepped enrichment widgets
- `docs/AMPLIFY_AND_NGINX_CLEANUP_2026_05_14.md` — concurrent cleanup work
- `docs/cleanup_amplify_nginx/README.md` — same
- `docker/mousemine/README.md` — should grow a "known traps" section listing
  superuser, theme, CDN, and `os.query.max-time` patches needed at deploy
- `docker/yeastmine/README.md` — same, fourth bullet

# InterMine Python Backend — Migration Plan

> Self-contained plan for porting the InterMine 1.x Java backend to a
> Python + FastAPI service that BlueGenes consumes. JSP webapp is retired;
> the existing Java build pipeline (`project_build`, ~50 source converters)
> stays untouched and continues writing into the same PostgreSQL schema.
>
> Audience: a fresh Claude Code session opened against this repo, paired
> with the human operator (Paulo / `@nuin`). Read this top to bottom before
> writing code.

## 1. Context

### 1.1 Current state (May 2026)

- **AllianceMine 9.0.0 in production** since 2026-05-01 at
  `https://alliancemine.alliancegenome.org`. Deployed as a Java WAR in
  Tomcat 9 on multitenant (`172.31.59.87`), port `8082`. ALB target group
  `alliancemine-multitenant`.
- **Database** on shared RDS instance `intermine-postgres`
  (`db.t3.large`, 8 GB, PG 15.12). Param group
  `intermine-postgres15`. Same instance hosts mousemine, wormmine, flymine
  profile DBs.
- **Build pipeline** is Docker-based (`docker/alliancemine/`), 6-stage
  (buildDB → extract_data → project_build → postprocess → war → deploy).
  Runs on `AllianceMineDev` (`172.31.60.197`). Builds the WAR + writes
  the integrated DB to RDS.
- **BlueGenes** (ClojureScript frontend) talks to the Java webservice
  REST endpoints. Today it points at the Java WAR; after migration it
  points at the Python service.
- **Solr** runs natively on multitenant, port `8983`. Cores per release:
  `alliancemine-search-{version}`, `alliancemine-autocomplete-{version}`.
- **Profile DB** (`alliancemine_userprofile`) is shared across releases
  and persists user state (saved bags, queries, templates).

### 1.2 Pain points the migration solves

These are the bugs that drove the rewrite decision; the new backend
must structurally prevent them:

1. **Bag-upgrade deadlock** (2026-05-01 incident) — `PrecomputedTableManager`
   HashMap lock + JDBC zombie socket + per-bag serial init thread.
   See `docs/INCIDENT_2026_04_30_to_05_01.md`.
2. **JDBC connection-pool fragility** — Hikari `maxLifetime=1800000` forced
   conn rotation, fresh `connect()` timed out, postprocess died at 1h40m.
   No `tcpKeepAlive`, no `socketTimeout` in JDBC URL.
3. **WAR property baking** — `webapp.baseurl=http://localhost:8090`,
   `superuser.account`, profile DB name baked at build time. Each deploy
   needs a manual property patcher.
4. **Container backup gap** — `docker system prune -a -f` deleted
   alliancemine + wormmine on 2026-04-30 because no ECR snapshot existed.
   Now snapshotted (`docs/RUNTIME_CONTAINER_BACKUP.md`,
   `docs/MULTITENANT_BACKUP_RESTORE.md`).
5. **Postprocess work_mem blowup** — RDS `work_mem=512MB` × parallel
   workers × shared 8 GB instance = OOM on transfer-sequences.
6. **6-8 hour build cycles** — most of which is `project_build`. This
   does NOT change with the backend rewrite. Build pipeline stays Java.

### 1.3 What stays in Java

- `project_build` and the ~50 bio source converters (FlyMine,
  AllianceMine, MouseMine, WormMine specifics).
- Postprocess steps (transfer-sequences, summary tables, search index).
- The PostgreSQL schema produced by these — the Python backend reads
  this schema; it does not regenerate it.

The Python backend replaces only the **runtime** Java code that serves
HTTP requests from BlueGenes and from external API clients.

## 2. Goal

Single deliverable: a Python + FastAPI service named `intermine-py` (working
title) that:

1. Speaks the same JSON wire format as InterMine 1.x webservice, byte-for-byte
   on the endpoints BlueGenes depends on.
2. Loads the InterMine genomic model from the same XML schema files the Java
   build emits (`genomic_model.xml`).
3. Executes PathQuery DSL against the integrated PostgreSQL DB
   (`alliancemine_9_0_0_rc18` and successors).
4. Manages user profile state (lists, queries, templates, tags) via the
   same `alliancemine_userprofile` schema currently used by the Java webapp.
5. Talks to the existing Solr cores for keyword search and autocomplete.
6. Deploys as a single Docker image, all config from env vars (no WAR baking,
   no post-deploy property patcher).

Non-goals:

- Re-implementing the build pipeline.
- Replacing BlueGenes.
- Changing the database schema or the model XML format.
- Multi-mine federation (Phase 4+).

## 3. Stack

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Operator fluency, AI codegen quality, ecosystem |
| Web framework | FastAPI | OpenAPI auto-gen for BlueGenes client, async, mature |
| ASGI server | uvicorn + uvloop, `--workers N` | Multi-process to bypass GIL |
| PG driver | asyncpg | Fastest Python PG, native async, good keepalive |
| Query layer | SQLAlchemy 2.0 Core (NOT ORM) | Type-safe SQL builder, no ORM magic; we have our own model |
| Validation | Pydantic v2 | JSON wire format guarantees, Rust-backed perf |
| XML | `lxml` | Genomic model parsing |
| Solr client | `httpx` (async) | Direct HTTP, no abstractions |
| Auth | `python-jose` (JWT) + bcrypt | Same token format BlueGenes already speaks |
| Logging | `structlog` | JSON output, structured fields |
| Tests | `pytest` + `pytest-asyncio` + `httpx` test client | Snapshot tests against current Java |
| Type checking | `mypy --strict` + `ruff` | Catches 80% of class-of-bugs early |
| Build | `uv` for deps, multistage Dockerfile | uv > pip + pip-tools, 10× faster |
| CI | GitHub Actions self-hosted runner | Already exists for build pipeline |

Avoid: SQLAlchemy ORM (too magical for InterMine's dynamic schema), Django
(too heavyweight), Flask (not async-native), Celery (overkill).

## 4. Repository layout

The Python backend lives in this same repo, under a new directory:

```
agr_intermine_builder/
├── docker/                         # existing build container
├── src/                            # existing host-side CLI tools
├── intermine-py/                   # NEW — Python backend
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── README.md
│   ├── Dockerfile
│   ├── docker-compose.yml          # local dev: backend + PG + Solr
│   ├── .env.example
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app factory
│   │   ├── config.py               # pydantic-settings, env vars
│   │   ├── deps.py                 # dependency injection (DB pool, etc.)
│   │   ├── model/                  # InterMine genomic model loader
│   │   │   ├── __init__.py
│   │   │   ├── loader.py           # parse genomic_model.xml
│   │   │   └── classes.py          # runtime model representation
│   │   ├── pathquery/              # PathQuery DSL
│   │   │   ├── __init__.py
│   │   │   ├── parser.py           # XML/JSON → AST
│   │   │   ├── ast.py              # AST types (Pydantic)
│   │   │   ├── compiler.py         # AST → SQLAlchemy Core query
│   │   │   └── executor.py         # run query, stream results
│   │   ├── objectstore/            # SQL result materialization
│   │   │   ├── __init__.py
│   │   │   ├── pool.py             # asyncpg pool wrapper
│   │   │   ├── results.py          # ResultRow/ResultBatch types
│   │   │   └── precompute.py       # precomputed-table awareness
│   │   ├── profile/                # userprofile DB ops
│   │   │   ├── __init__.py
│   │   │   ├── users.py
│   │   │   ├── lists.py            # SavedBag CRUD + upgrade
│   │   │   ├── templates.py
│   │   │   └── tags.py
│   │   ├── solr/                   # search + autocomplete
│   │   │   ├── __init__.py
│   │   │   └── client.py
│   │   ├── auth/                   # JWT + token issue
│   │   │   ├── __init__.py
│   │   │   └── tokens.py
│   │   ├── routes/                 # FastAPI routers per /service/* group
│   │   │   ├── __init__.py
│   │   │   ├── version.py          # /service/version, /service/release
│   │   │   ├── model.py            # /service/model
│   │   │   ├── query.py            # /service/query, /service/query/results
│   │   │   ├── template.py         # /service/templates
│   │   │   ├── list.py             # /service/lists
│   │   │   ├── search.py           # /service/search
│   │   │   ├── widget.py           # /service/widgets
│   │   │   ├── path.py             # /service/path/values
│   │   │   ├── classkeys.py        # /service/classkeys
│   │   │   ├── data_sources.py     # /service/data-sources
│   │   │   ├── user.py             # /service/user
│   │   │   └── branding.py         # /service/branding
│   │   └── wire/                   # JSON shape compatibility
│   │       ├── __init__.py
│   │       └── java_compat.py      # match Java webservice JSON exactly
│   └── tests/
│       ├── conftest.py
│       ├── snapshots/              # captured Java JSON for diff tests
│       ├── test_version.py
│       ├── test_model.py
│       ├── test_pathquery.py
│       ├── test_results.py
│       ├── test_lists.py
│       └── ...
└── docs/
    └── INTERMINE_PYTHON_BACKEND_MIGRATION.md   # this file
```

## 5. API surface to port

BlueGenes drives the prioritization. These endpoints **must** work for
BlueGenes to function. Order = roughly Phase order.

### Phase 1 — Read-only (4 weeks of operator time)

| Endpoint | Method | Used by BlueGenes for | Wire format gotcha |
|---|---|---|---|
| `/service/version` | GET | Version check | Plain integer in body, e.g. `35` |
| `/service/release` | GET | Release version string | Plain text |
| `/service/model` | GET | Class/attribute browser | Big nested JSON; class hierarchy + references |
| `/service/classkeys` | GET | Identifier lookup | `{"classes": {"Gene": ["primaryIdentifier"]}}` |
| `/service/branding` | GET | UI theming | `{"properties": {"branding.colors.header.main": "..."}}` |
| `/service/data-sources` | GET | Data source list | Array of `{name, url, version, description}` |
| `/service/query/results` | GET, POST | Run a PathQuery | Most complex endpoint — see §6 |
| `/service/query/results/count` | GET, POST | Count rows | Plain integer |
| `/service/path/values` | GET, POST | Distinct values for a path | Used for filter dropdowns |
| `/service/templates` | GET | Public templates | Big array of templates with constraints |
| `/service/templates/{name}/results` | GET, POST | Run a template | Same shape as `/service/query/results` |
| `/service/widgets` | GET | Widget definitions | Categorized list |

### Phase 2 — User state writes (4-6 weeks)

| Endpoint | Method | Notes |
|---|---|---|
| `/service/user/token` | POST | Token-based auth |
| `/service/user/whoami` | GET | Current user profile |
| `/service/lists` | GET, POST, PUT, DELETE | Saved bags |
| `/service/lists/append` | POST | Add to existing list |
| `/service/lists/intersect` `/union` `/subtract` | POST | Set ops |
| `/service/list/upgrade` | POST | **The bag upgrade — get this right** |
| `/service/lists/tags` | GET, POST, DELETE | List tags (incl. `im:public`, `im:frontpage`) |
| `/service/queries` | GET, POST, DELETE | Saved queries |
| `/service/templates` | POST, PUT, DELETE | Private templates |

### Phase 3 — Search + tools (3-4 weeks)

| Endpoint | Method | Notes |
|---|---|---|
| `/service/search` | GET, POST | Solr keyword search |
| `/service/search/autocomplete` | GET | Solr autocomplete |
| `/service/regions/genomic` | POST | Region search |
| `/service/widgets/{name}/results` | POST | Widget execution (enrichment, chart) |

### Phase 4 — Federated + admin (later)

- `/service/intermines` — registry of federated mines
- `/service/admin/*` — operator endpoints
- BLAST integration (if used)

### Skipped (not in BlueGenes critical path)

- `/aspects/*`, `/portal.do`, `/genomicRegionSearch.do` — Java JSP UI legacy.
- `/feed/news` — RSS, low priority.
- `/api/*` deprecated SOAP/XML endpoints.

## 6. PathQuery — the heart of the backend

PathQuery is InterMine's user-facing query DSL. BlueGenes builds queries
graphically and submits them as XML or JSON. Example:

```xml
<query model="genomic" view="Gene.symbol Gene.organism.name Gene.chromosome.primaryIdentifier">
  <constraint path="Gene.symbol" op="=" value="zen" />
</query>
```

This compiles to roughly:

```sql
SELECT g.symbol, o.name, c.primaryIdentifier
FROM gene g
LEFT OUTER JOIN organism o ON g.organismid = o.id
LEFT OUTER JOIN chromosome c ON g.chromosomeid = c.id
WHERE g.symbol = $1
```

Things that make PathQuery non-trivial:

1. **Outer-join semantics by default.** Adding a path doesn't filter rows.
2. **Reference traversal.** `Gene.organism.name` walks foreign keys.
3. **Collection traversal.** `Gene.exons.length` produces multiple rows
   per gene (one per exon).
4. **Constraint logic.** `(A and B) or C` constraint trees.
5. **Subclass narrowing.** `<constraint path="Gene" type="Pseudogene" />`.
6. **Bag constraints.** `Gene IN ALL_Yeast_Genes` joins via savedbag table.
7. **LOOKUP constraints.** `Gene LOOKUP "zen"` — ID resolution magic.
8. **Sort + limit + paging.**
9. **Outer-join groups (`<join>`)** — control whether a path branch is
   inner or outer joined.
10. **Precomputed table rewriting.** InterMine ObjectStore detects when a
    subtree of the query matches a precomputed (materialized) table and
    rewrites the query to read from that instead. **5-100× speedup.**
    Without this, big queries are unusably slow.

### Implementation strategy

**Phase 1a:** Parser + AST + naïve compiler (no precompute). Handles:
- Single-class queries
- Reference traversal
- AND-only constraints
- Sort + limit
- JSON output matching Java wire format

**Phase 1b:** Add OR/NOT constraint trees, collection traversal,
subclass narrowing.

**Phase 1c:** Add bag constraints, LOOKUP constraints.

**Phase 2 (mandatory before retiring Java):** Precomputed-table awareness.
Read `precompute_index` table, match query subtrees, rewrite. Without
this, gene pages and template results are 10× slower than Java.

### Wire format compatibility

The Java webservice emits JSON like:

```json
{
  "modelName": "genomic",
  "results": [
    ["zen", "Drosophila melanogaster", "2L"],
    ["en",  "Drosophila melanogaster", "2R"]
  ],
  "wasSuccessful": true,
  "executionTime": "2026-05-02 12:34:56",
  "rootClass": "Gene",
  "viewTypes": {"Gene.symbol": "java.lang.String", ...},
  "iTotalRecords": 2,
  "iTotalDisplayRecords": 2
}
```

BlueGenes parses this exactly. Our output must match — case, key order
(JSON spec says irrelevant but BlueGenes' `cljs.reader` may not care, but
JS clients do), nested shape.

**Strategy:** capture real Java responses with `curl` against the running
9.0.0 instance. Save under `tests/snapshots/`. Snapshot test every endpoint:
canonicalize JSON (sort keys), diff. Any drift fails CI.

## 7. Data model loading

InterMine's genomic model is in `genomic_model.xml`, generated by the build
pipeline. ~100+ classes with inheritance, references, and collections.

```xml
<class name="Gene" extends="SequenceFeature" is-interface="true">
  <attribute name="symbol" type="java.lang.String"/>
  <attribute name="primaryIdentifier" type="java.lang.String"/>
  <reference name="organism" referenced-type="Organism"/>
  <collection name="exons" referenced-type="Exon"/>
</class>
```

**Loading:**
1. On startup, parse `genomic_model.xml` with `lxml`.
2. Resolve inheritance (multiple inheritance flatten).
3. Build runtime model: `dict[class_name, ClassDescriptor]`.
4. Build attribute/reference index for path resolution.
5. Cache in app state.

**Pydantic generation:** consider generating Pydantic classes from the
model at startup (or build time) so result rows can be validated against
the model. Tradeoff: dynamic mode is simpler but loses static checks.

## 8. Authentication

Two modes today:

1. **Anonymous** — public queries, public lists. No token.
2. **Token auth** — `Authorization: Token <token>` header. Token is
   stored in `userprofile.api_key`. User-supplied lists, private templates.

Java behavior:
- Token issued by `/service/user/token` (POST username/password)
- Token never expires until rotated
- Stored in PG userprofile schema

Python implementation:
- Same token table read for auth
- `Depends(get_current_user)` on protected routes
- Optional: also support short-lived JWT for new clients (BlueGenes can
  switch over time)

## 9. Profile DB compatibility

`alliancemine_userprofile` is shared between Java and Python during the
transition. Schema is fixed by Java code today. Important tables:

| Table | Used for | Java column types we mirror |
|---|---|---|
| `userprofile` | User accounts | id, username, password (bcrypt), apiKey, superuser bool |
| `savedbag` | Lists | id, name, type (class), description, dateCreated, intermine_state, userprofileid |
| `savedbagstable` | Bag rows | bagid, value (id of object) |
| `savedquery` | Queries | id, name, query (xml), userprofileid |
| `savedtemplatequery` | Templates | id, name, templateQuery (xml), userprofileid |
| `tag` | List/template tags | id, tagName, objectIdentifier, type, userprofileid |
| `permanenttoken` | API tokens | id, token, userprofileid, type, dateCreated |

The Python service writes through the same schema. **Do not migrate the
schema.** Schema migrations would break the still-deployed Java webapp
during the transition.

## 10. Bag upgrade — DON'T REPEAT 2026-05-01

The bug:
1. Tomcat startup runs `UpgradeBagList` for all superuser bags serially.
2. Each bag upgrade holds a global `PrecomputedTableManager` HashMap lock.
3. JDBC zombie socket caused indefinite hang inside one bag upgrade.
4. All Tomcat request threads queued behind the lock. Webapp dead.

Python re-implementation rules:

1. **No on-startup upgrade.** Bags are upgraded **lazily on first access** OR
   in a background task that processes one bag at a time without blocking
   the request thread.
2. **Per-bag isolation.** Upgrade one bag = one transaction, one query, one
   timeout. No shared mutable state across bags.
3. **State machine made explicit:**
   - `NOT_CURRENT` → `UPGRADING` (start) → `CURRENT` (done) or `NOT_CURRENT`
     (failed, retryable).
4. **Idempotent upgrade query.** Re-running a partially completed upgrade
   must be safe.
5. **Postgres `statement_timeout`** set per upgrade query (e.g. 60s). On
   timeout, mark bag `NOT_CURRENT`, log, move on.
6. **No global lock.** If two upgrades for different bags happen in
   parallel, they don't contend.

This is a Phase 2 deliverable but design it from day 1.

## 11. JDBC pool settings (do these right)

Today's Java config (logged during the failure):

```
maxLifetime=1800000    (30 min — caused the connect timeout)
idleTimeout=600000     (10 min)
connectionTimeout=30000 (30 s)
maxConnections=20
minimumIdle=10
```

Python with asyncpg pool config:

```python
pool = await asyncpg.create_pool(
    dsn=settings.database_url,
    min_size=4,
    max_size=20,
    max_inactive_connection_lifetime=300,   # 5 min — faster turnover, no zombies
    command_timeout=120,                    # per-query timeout
    server_settings={
        "tcp_keepalives_idle": "30",
        "tcp_keepalives_interval": "10",
        "tcp_keepalives_count": "3",
        "application_name": "intermine-py",
    },
)
```

Plus on the connection: `await conn.execute("SET statement_timeout = 60000")`
for the lazy bag upgrade path.

These settings would have prevented both the bag-upgrade deadlock and the
mousemine `transfer-sequences` connect timeout.

## 12. Configuration

All via environment variables (no property files baked at build time):

```
# DB
DATABASE_URL=postgresql://postgres:***@intermine-postgres.../alliancemine_9_0_0_rc18
USERPROFILE_DATABASE_URL=postgresql://postgres:***@intermine-postgres.../alliancemine_userprofile

# Solr
SOLR_BASE_URL=http://172.31.59.87:8983/solr
SOLR_SEARCH_CORE=alliancemine-search-9.0.0
SOLR_AUTOCOMPLETE_CORE=alliancemine-autocomplete-9.0.0

# Service
WEBAPP_BASEURL=https://alliancemine.alliancegenome.org
SERVICE_PREFIX=/alliancemine/service
RELEASE_VERSION=9.0.0
SUPERUSER_ACCOUNT=superuser@alliancegenome.org

# Auth
JWT_SIGNING_KEY=***
TOKEN_TTL_DAYS=365

# Logging
LOG_LEVEL=info
LOG_FORMAT=json
```

Pydantic-settings loads + validates these on startup. App refuses to start
if any required var is missing. **No more `localhost:8090` baked in.**

## 13. Deployment

Dockerfile (multistage):

```
FROM python:3.12-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv pip sync --system --no-cache uv.lock

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY app/ app/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop"]
```

Build: `docker build -t intermine-py:9.0.0 .`
Run: `docker run -p 8083:8000 --env-file .env intermine-py:9.0.0`

ALB rollout: same as 9.0.0 cutover playbook (`PRODUCTION_CUTOVER_9_0_0.md`).
Add Python service as new ALB target on a different port (8083), test in
parallel with Java (8082), swap rule when ready.

## 14. Testing

### 14.1 Snapshot tests against current Java

```python
# tests/snapshots/version.json captured from running Java
# tests/test_version.py
@pytest.mark.asyncio
async def test_version_matches_java(client):
    r = await client.get("/service/version")
    assert r.text == load_snapshot("version.txt")
```

Capture script:

```bash
# Run once against the live Java instance, save to tests/snapshots/
for endpoint in version model templates classkeys data-sources; do
  curl -sS "https://alliancemine.alliancegenome.org/alliancemine/service/$endpoint" \
    > "intermine-py/tests/snapshots/$endpoint.json"
done
```

### 14.2 Integration tests

- Spin up PG with a known fixture DB
- Spin up minimal Solr
- Run end-to-end PathQuery → result
- Compare wire format

### 14.3 Property-based tests

`hypothesis` for PathQuery: generate random valid queries, ensure they
parse + compile to valid SQL + don't crash on execution.

### 14.4 Load test

`locust` or `vegeta` against the Python service vs Java service. Goal:
- Same p50, better p99 (no JVM GC pauses).
- Lower memory baseline.
- Faster cold start.

## 15. Phasing

### Phase 0 — Setup (week 1)

- [ ] Scaffold `intermine-py/` directory
- [ ] `pyproject.toml` with locked deps
- [ ] FastAPI app skeleton with `/health`
- [ ] Dockerfile + docker-compose for local dev
- [ ] CI: `mypy --strict`, `ruff`, `pytest` on PRs
- [ ] Capture Java webservice snapshots for all Phase 1 endpoints

### Phase 1 — Read-only API (months 1-2)

Goal: BlueGenes can browse the model, run simple queries, view results
against the Python service. Java webapp still serves writes.

- [ ] Genomic model loader
- [ ] `/service/version`, `/service/release`, `/service/model`
- [ ] `/service/classkeys`, `/service/branding`, `/service/data-sources`
- [ ] PathQuery parser + AST + naïve compiler
- [ ] `/service/query/results` (basic single-class, AND constraints, sort, limit)
- [ ] `/service/query/results/count`
- [ ] `/service/templates` (read-only public templates)
- [ ] `/service/templates/{name}/results`
- [ ] `/service/path/values`
- [ ] Snapshot diff tests passing for all endpoints
- [ ] Deploy as side-by-side ALB target on multitenant
- [ ] Configure BlueGenes test instance to use Python backend

### Phase 1.5 — PathQuery completeness (month 2-3)

- [ ] OR/NOT constraint trees
- [ ] Collection traversal
- [ ] Subclass narrowing
- [ ] Bag constraints (read-only)
- [ ] LOOKUP constraints
- [ ] Outer-join group control
- [ ] **Precomputed-table awareness** (mandatory before retiring Java)

### Phase 2 — User writes (months 3-4)

- [ ] Auth: token endpoint, `whoami`, dependency injection
- [ ] `/service/lists` CRUD
- [ ] `/service/lists/{append,intersect,union,subtract}`
- [ ] **Bag upgrade** — lazy on first access, per-bag isolation
- [ ] List tags
- [ ] Saved queries CRUD
- [ ] Private templates CRUD
- [ ] Snapshot tests for all write endpoints
- [ ] Production cutover for AllianceMine (retire Java webapp)

### Phase 3 — Search + tools (months 4-6)

- [ ] Solr keyword search proxy
- [ ] Autocomplete
- [ ] Region search
- [ ] Widget framework (enrichment, chart, list, table widgets)

### Phase 4 — Multi-mine + admin (months 6+)

- [ ] Replicate the AllianceMine cutover for MouseMine, WormMine, FlyMine
- [ ] `/service/intermines` registry (federated query support)
- [ ] Admin endpoints (rebuild precomputes, vacuum, list active queries)
- [ ] BlueGenes tools API

## 16. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PathQuery semantics drift from Java (subtle outer-join differences) | High | High | Snapshot tests against Java; diff every endpoint |
| Precomputed-table rewriter is harder than expected | Medium | High | Keep Java webapp running until rewriter handles top-N templates |
| Bag upgrade race conditions in async Python | Medium | Medium | Per-bag advisory locks via `pg_try_advisory_xact_lock` |
| BlueGenes JSON shape changes between InterMine versions | Low | Medium | Pin BlueGenes version, capture snapshots from a single Java release |
| Profile DB schema churn from Java side | Low | High | Don't run Java webapp + Python in write-mode simultaneously after Phase 2 |
| Async Python perf surprises (GIL workers, event loop lag) | Low | Medium | Load test before each phase cutover; uvloop is mandatory |
| asyncpg/SQLAlchemy version mismatch breakage | Low | Low | Lock versions in `uv.lock`; renovate weekly |
| Solr breaking changes during InterMine release upgrades | Low | Medium | Keep Solr URLs in env, not code; test against snapshotted Solr core |

## 17. Open questions for the next session to resolve

These are decisions deliberately deferred to the implementation session:

1. **Pydantic-from-XML vs runtime model dict.** Compile-time class
   generation gives type safety but adds build complexity. Pure runtime
   dict is simpler. Decide before Phase 1.
2. **SQL builder choice within each query.** SQLAlchemy 2.0 Core (preferred)
   vs raw asyncpg with f-string templates (faster but unsafe) vs `pypika`
   (third option). Recommendation: SQLAlchemy Core.
3. **Sync vs async profile DB writes.** asyncpg supports transactions but
   nested savepoints are awkward. Consider `psycopg3` if write-heavy ops
   need easier transaction management.
4. **Where to host BlueGenes during transition.** Today it's separate;
   Python service can serve static BlueGenes assets if convenient.
5. **OpenAPI spec as source of truth?** FastAPI generates one. BlueGenes
   could consume it for client codegen. But that's a deviation from how
   BlueGenes calls Java today (no OpenAPI). Defer.
6. **Migration of existing Java tests.** Java has `acceptance-test/`
   directory with curl-based suite. Port these to pytest? Probably yes.
7. **Telemetry stack.** OpenTelemetry → CloudWatch? Prometheus? Decide
   when first endpoint hits production.
8. **Should we package the binary AOT?** PyOxidizer or just Docker?
   Docker is simpler; AOT only if cold-start matters.

## 18. Out-of-scope (explicit)

These are not in the rewrite. Do not let scope creep pull them in:

- Replacing PostgreSQL.
- Replacing Solr.
- Replacing BlueGenes.
- Replacing the build pipeline (`docker/alliancemine/`).
- Adding new InterMine features that don't exist in the Java version.
- Multi-language UI (BlueGenes handles i18n).
- GraphQL API (REST only, matching Java).
- gRPC (REST only).
- Schema migrations on the integrated DB.
- Schema migrations on the userprofile DB beyond what's needed for
  bag-upgrade state.

## 19. References

Existing repo docs to read before starting:

- `CLAUDE.md` — project overview, build pipeline, RDS layout
- `docs/INFRASTRUCTURE_REFERENCE.md` — SSH hosts, IPs, machine specs
  (operator-only, has credentials)
- `docs/RELEASE_PROCESS.md` — how the Java side ships today
- `docs/RELEASE_PROMOTION_PROTOCOL.md` — production cutover playbook
- `docs/PRODUCTION_CUTOVER_9_0_0.md` — concrete example of the cutover
- `docs/INCIDENT_2026_04_30_to_05_01.md` — what we're trying not to repeat
- `docs/POST_9_0_0_PLANNING.md` — open follow-ups, some of which this plan
  resolves (Tier 1 property patcher, Tier 2 JDBC keepalive)
- `docs/RUNTIME_CONTAINER_BACKUP.md` — manual snapshot procedure
- `docs/MULTITENANT_BACKUP_RESTORE.md` — automated snapshot scripts

External:

- InterMine docs: `https://intermine.readthedocs.io/`
- BlueGenes repo: `https://github.com/intermine/bluegenes`
- PathQuery DSL spec: `https://intermine.readthedocs.io/en/latest/api/pathquery/`
- InterMine REST API: `https://intermine.readthedocs.io/en/latest/api/`

## 20. First commit checklist

When the next Claude Code session starts, the first commit should:

1. Create `intermine-py/` with the layout from §4.
2. `pyproject.toml` with these initial deps:
   ```toml
   [project]
   name = "intermine-py"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
     "fastapi>=0.110",
     "uvicorn[standard]>=0.27",
     "uvloop>=0.19",
     "asyncpg>=0.29",
     "sqlalchemy>=2.0",
     "pydantic>=2.6",
     "pydantic-settings>=2.2",
     "lxml>=5.1",
     "httpx>=0.27",
     "structlog>=24.1",
     "python-jose[cryptography]>=3.3",
     "bcrypt>=4.1",
   ]
   [tool.uv]
   dev-dependencies = [
     "mypy>=1.9",
     "ruff>=0.3",
     "pytest>=8",
     "pytest-asyncio>=0.23",
     "hypothesis>=6.99",
   ]
   ```
3. `app/main.py` with FastAPI app + `/health` returning `{"status": "ok"}`.
4. `app/config.py` with pydantic-settings.
5. `app/deps.py` with asyncpg pool factory.
6. `Dockerfile` (multistage, uv-based).
7. `docker-compose.yml` with PG + Solr for local dev.
8. `.env.example` with all required vars (no real secrets).
9. CI workflow: ruff + mypy + pytest on PR.
10. `intermine-py/README.md` linking back to this migration doc.

Ship that as PR 1. Don't write any business logic in PR 1.

PR 2 onward: one endpoint per PR, with snapshot test.

---

End of plan. Hand this file to the next session and say:
**"Read `docs/INTERMINE_PYTHON_BACKEND_MIGRATION.md` and execute Phase 0
section §20 first commit checklist."**

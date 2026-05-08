# InterMine Go Backend — Migration Plan

> Self-contained plan for porting the InterMine 1.x Java backend to a
> Go service that BlueGenes consumes. JSP webapp is retired; the existing
> Java build pipeline (`project_build`, ~50 source converters) stays
> untouched and continues writing into the same PostgreSQL schema.
>
> Audience: a fresh Claude Code session opened against this repo, paired
> with the human operator (Paulo / `@nuin`). Read this top to bottom before
> writing code.
>
> **Companion doc:** `docs/INTERMINE_PYTHON_BACKEND_MIGRATION.md` — same
> plan, Python+FastAPI stack. Pick one before starting.

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
  Runs on `AllianceMineDev` (`172.31.60.197`).
- **BlueGenes** (ClojureScript frontend) talks to the Java webservice REST
  endpoints. Today it points at the Java WAR; after migration it points
  at the Go service.
- **Solr** runs natively on multitenant, port `8983`. Cores per release:
  `alliancemine-search-{version}`, `alliancemine-autocomplete-{version}`.
- **Profile DB** (`alliancemine_userprofile`) is shared across releases.

### 1.2 Pain points the migration solves

These are bugs that drove the rewrite decision; the new backend must
structurally prevent them:

1. **Bag-upgrade deadlock** (2026-05-01) — `PrecomputedTableManager`
   HashMap lock + JDBC zombie socket + per-bag serial init thread.
   See `docs/INCIDENT_2026_04_30_to_05_01.md`.
2. **JDBC connection-pool fragility** — Hikari `maxLifetime=1800000`
   forced conn rotation; fresh `connect()` timed out; postprocess died
   at 1h40m. No `tcpKeepAlive`, no `socketTimeout`.
3. **WAR property baking** — `webapp.baseurl=http://localhost:8090`,
   `superuser.account`, profile DB name baked at build time. Each deploy
   needs a manual property patcher.
4. **Container backup gap** — `docker system prune -a -f` deleted
   alliancemine + wormmine on 2026-04-30 because no ECR snapshot existed.
   Now snapshotted (`docs/RUNTIME_CONTAINER_BACKUP.md`,
   `docs/MULTITENANT_BACKUP_RESTORE.md`).
5. **Postprocess work_mem blowup** — RDS `work_mem=512MB` × parallel
   workers × shared 8 GB instance = OOM.
6. **6-8 hour build cycles** — does NOT change with this rewrite. Build
   pipeline stays Java.

### 1.3 What stays in Java

- `project_build` and the ~50 bio source converters.
- Postprocess steps (transfer-sequences, summary tables, search index).
- The PostgreSQL schema produced by these — Go backend reads it; does
  not regenerate it.

## 2. Goal

Single deliverable: a Go service named `intermine-go` (working title)
that:

1. Speaks the same JSON wire format as InterMine 1.x webservice,
   byte-for-byte on endpoints BlueGenes depends on.
2. Loads the InterMine genomic model from the same XML schema files
   (`genomic_model.xml`).
3. Executes PathQuery DSL against the integrated PostgreSQL DB
   (`alliancemine_9_0_0_rc18` and successors).
4. Manages user profile state (lists, queries, templates, tags) via the
   same `alliancemine_userprofile` schema.
5. Talks to existing Solr cores for keyword search and autocomplete.
6. Deploys as a single static binary OR a small Docker image. All config
   from env vars (no WAR baking).

Non-goals:

- Re-implementing the build pipeline.
- Replacing BlueGenes.
- Changing the database schema.
- Multi-mine federation (Phase 4+).

## 3. Stack

| Component | Choice | Why |
|---|---|---|
| Language | Go 1.22+ | Fast compile, single binary, native async, AI fluency |
| Web framework | `chi` (`go-chi/chi/v5`) | Idiomatic, stdlib `net/http` compatible, no magic |
| PG driver | `pgx/v5` (`jackc/pgx`) + `pgxpool` | Best-in-class PG, native binary protocol, builtin keepalive |
| Query layer | `sqlc` (`sqlc-dev/sqlc`) | Generates type-safe Go from `.sql` files, compile-time SQL check |
| JSON | `encoding/json` (stdlib); `goccy/go-json` if hot path needs it | Stdlib first, swap if profiler says so |
| Validation | `go-playground/validator/v10` | Struct-tag-based, fast |
| XML | `encoding/xml` (stdlib) | Genomic model parsing |
| HTTP client | stdlib `net/http` for Solr, `resty` if convenience matters | Stdlib first |
| Auth | `golang-jwt/jwt/v5` + `bcrypt` (`x/crypto/bcrypt`) | JWT for new clients, bcrypt for password hash compat with Java |
| Logging | `log/slog` (stdlib, Go 1.21+) | JSON output, structured fields, no extra deps |
| Tests | `testing` (stdlib) + `testify/require` + `httptest` | Snapshot tests against current Java |
| Linting | `golangci-lint` (~30 linters bundled) | Catches 80% of issues pre-review |
| Build | Single `go build`, multistage Dockerfile for distroless | Static binary, ~30 MB image |
| CI | GitHub Actions self-hosted runner | Same runner as build pipeline |

Avoid: gorm (ORM magic, slow), gin (opinionated middleware mess), echo
(fine but chi is more stdlib-aligned), database/sql native (you'll cry —
use pgx).

## 4. Repository layout

The Go backend lives in this same repo, under a new directory:

```
agr_intermine_builder/
├── docker/                         # existing build container
├── src/                            # existing host-side CLI tools
├── intermine-go/                   # NEW — Go backend
│   ├── go.mod
│   ├── go.sum
│   ├── README.md
│   ├── Dockerfile
│   ├── docker-compose.yml          # local dev: backend + PG + Solr
│   ├── .env.example
│   ├── Makefile                    # build, test, lint, run targets
│   ├── cmd/
│   │   └── intermine-go/
│   │       └── main.go             # entrypoint, wires everything
│   ├── internal/
│   │   ├── config/
│   │   │   └── config.go           # env var parsing (envconfig)
│   │   ├── db/
│   │   │   ├── pool.go             # pgxpool factory
│   │   │   └── migrations/         # bag-upgrade-state additions only
│   │   ├── model/                  # InterMine genomic model loader
│   │   │   ├── loader.go           # parse genomic_model.xml
│   │   │   ├── descriptor.go       # ClassDescriptor, AttributeDescriptor
│   │   │   └── path.go             # path resolution Gene.organism.name
│   │   ├── pathquery/              # PathQuery DSL
│   │   │   ├── parser.go           # XML/JSON → AST
│   │   │   ├── ast.go              # AST node types
│   │   │   ├── compiler.go         # AST → SQL string + args
│   │   │   ├── executor.go         # exec, stream rows
│   │   │   └── precompute.go       # precomputed-table rewriter
│   │   ├── objectstore/            # SQL result materialization
│   │   │   ├── results.go          # ResultRow, ResultBatch
│   │   │   └── stream.go           # row streaming for big results
│   │   ├── profile/                # userprofile DB ops
│   │   │   ├── users.go
│   │   │   ├── lists.go            # SavedBag CRUD + upgrade
│   │   │   ├── templates.go
│   │   │   ├── tags.go
│   │   │   └── queries/            # sqlc-generated code targets
│   │   ├── solr/                   # search + autocomplete
│   │   │   └── client.go
│   │   ├── auth/                   # JWT + token issue
│   │   │   ├── tokens.go
│   │   │   └── middleware.go       # chi middleware for `Authorization:`
│   │   ├── server/                 # chi routes + handlers
│   │   │   ├── server.go           # router setup
│   │   │   ├── version.go          # /service/version, /service/release
│   │   │   ├── model.go            # /service/model
│   │   │   ├── query.go            # /service/query, /service/query/results
│   │   │   ├── template.go         # /service/templates
│   │   │   ├── list.go             # /service/lists
│   │   │   ├── search.go           # /service/search
│   │   │   ├── widget.go           # /service/widgets
│   │   │   ├── path.go             # /service/path/values
│   │   │   ├── classkeys.go        # /service/classkeys
│   │   │   ├── data_sources.go     # /service/data-sources
│   │   │   ├── user.go             # /service/user
│   │   │   └── branding.go         # /service/branding
│   │   └── wire/                   # JSON shape compatibility
│   │       └── java_compat.go      # match Java webservice JSON exactly
│   ├── sqlc/
│   │   ├── sqlc.yaml               # codegen config
│   │   └── queries/                # *.sql files, one per domain
│   │       ├── users.sql
│   │       ├── lists.sql
│   │       ├── templates.sql
│   │       └── tags.sql
│   └── tests/
│       ├── snapshots/              # captured Java JSON for diff tests
│       ├── integration/            # full-stack tests
│       ├── version_test.go
│       ├── model_test.go
│       ├── pathquery_test.go
│       ├── results_test.go
│       └── lists_test.go
└── docs/
    └── INTERMINE_GO_BACKEND_MIGRATION.md   # this file
```

Note: standard Go `internal/` directory means anything inside cannot be
imported by other modules. Forces a clean public API surface (only
`cmd/intermine-go` is public).

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
| `/service/widgets/{name}/results` | POST | Widget execution |

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

Compiles to roughly:

```sql
SELECT g.symbol, o.name, c.primaryIdentifier
FROM gene g
LEFT OUTER JOIN organism o ON g.organismid = o.id
LEFT OUTER JOIN chromosome c ON g.chromosomeid = c.id
WHERE g.symbol = $1
```

### Hard parts

1. **Outer-join semantics by default.** Adding a path doesn't filter rows.
2. **Reference traversal.** `Gene.organism.name` walks foreign keys.
3. **Collection traversal.** `Gene.exons.length` produces multiple rows
   per gene (one per exon).
4. **Constraint logic.** `(A and B) or C` constraint trees.
5. **Subclass narrowing.** `<constraint path="Gene" type="Pseudogene" />`.
6. **Bag constraints.** `Gene IN ALL_Yeast_Genes` joins via savedbag table.
7. **LOOKUP constraints.** `Gene LOOKUP "zen"` — ID resolution magic.
8. **Sort + limit + paging.**
9. **Outer-join groups** (`<join>`) — control inner vs outer per branch.
10. **Precomputed-table rewriting.** ObjectStore detects when a query
    subtree matches a precomputed (materialized) table and rewrites the
    query to read from that. **5-100× speedup.** Without this, big
    queries are unusably slow.

### Implementation strategy

**Phase 1a:** Parser + AST + naïve compiler (no precompute):
- Single-class queries
- Reference traversal
- AND-only constraints
- Sort + limit
- JSON output matching Java wire format

**Phase 1b:** OR/NOT constraint trees, collection traversal, subclass
narrowing.

**Phase 1c:** Bag constraints, LOOKUP constraints.

**Phase 2 (mandatory before retiring Java):** Precomputed-table awareness.
Read `precompute_index` table, match query subtrees, rewrite. Without
this, gene pages and template results are 10× slower than Java.

### Go-specific concerns

- **No sum types.** AST nodes via interface + type switch. Verbose but
  works. Consider `go-sumtype` linter to enforce exhaustive switches.
- **No generics-heavy AST.** Go 1.22 generics workable but limited; avoid
  building a recursive parametric AST. Prefer interface{Node} + type
  assertion in the compiler walker.
- **SQL building:** prefer `squirrel` (Masterminds) for compositional
  builders OR raw string concatenation with `pgx.NamedArgs`. **Do not**
  use sqlc here — sqlc is for fixed queries, PathQuery is dynamic.
  Reserve sqlc for profile DB CRUD where queries are known at compile time.

### Wire format compatibility

The Java webservice emits:

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

BlueGenes parses this exactly. Our output must match. **Strategy:** capture
real Java responses with `curl` against the running 9.0.0 instance. Save
under `tests/snapshots/`. Snapshot test every endpoint: canonicalize JSON
(sort keys), diff. Any drift fails CI.

Go specifics: `json.Marshal` produces deterministic key order via struct
tags. For dynamic maps, sort keys explicitly via custom marshaler.

## 7. Data model loading

InterMine's genomic model lives in `genomic_model.xml`, generated by the
build pipeline. ~100+ classes with inheritance, references, collections.

```xml
<class name="Gene" extends="SequenceFeature" is-interface="true">
  <attribute name="symbol" type="java.lang.String"/>
  <attribute name="primaryIdentifier" type="java.lang.String"/>
  <reference name="organism" referenced-type="Organism"/>
  <collection name="exons" referenced-type="Exon"/>
</class>
```

**Loading:**
1. On startup, parse `genomic_model.xml` with `encoding/xml`.
2. Resolve inheritance.
3. Build `map[string]*ClassDescriptor`.
4. Build attribute/reference index for path resolution.
5. Cache in app state (struct field, no globals).

**Type translation:**

| Java type | Go type |
|---|---|
| `java.lang.String` | `string` |
| `java.lang.Integer` | `int32` |
| `java.lang.Long` | `int64` |
| `java.lang.Boolean` | `bool` |
| `java.lang.Float`/`Double` | `float64` |
| `java.util.Date` | `time.Time` |
| (collection) | `[]T` |
| (reference) | `*T` (pointer for nullable) |

No Pydantic equivalent. Validation done via `validator` struct tags or
explicit checks.

## 8. Authentication

Two modes:

1. **Anonymous** — public queries, public lists. No token.
2. **Token auth** — `Authorization: Token <token>` header. Token in
   `userprofile.api_key`. Required for user-supplied lists, private
   templates.

Java behavior:
- Token issued by `/service/user/token` (POST username/password)
- Token never expires until rotated
- Stored in PG userprofile schema

Go implementation:
- chi middleware reads `Authorization` header
- Looks up token in `userprofile.permanenttoken` table
- Sets `*User` in request context
- `mustAuth` middleware for protected routes
- Optional: also issue short-lived JWT for new clients

## 9. Profile DB compatibility

`alliancemine_userprofile` is shared between Java and Go during
transition. Tables:

| Table | Used for | Columns we mirror |
|---|---|---|
| `userprofile` | User accounts | id, username, password (bcrypt), apiKey, superuser bool |
| `savedbag` | Lists | id, name, type (class), description, dateCreated, intermine_state, userprofileid |
| `savedbagstable` | Bag rows | bagid, value (id of object) |
| `savedquery` | Queries | id, name, query (xml), userprofileid |
| `savedtemplatequery` | Templates | id, name, templateQuery (xml), userprofileid |
| `tag` | List/template tags | id, tagName, objectIdentifier, type, userprofileid |
| `permanenttoken` | API tokens | id, token, userprofileid, type, dateCreated |

Go service writes through the same schema. **Do not migrate the schema.**
Schema migrations would break the still-deployed Java webapp during
transition.

`sqlc` generates Go types directly from PG schema introspection, so the
struct types stay in sync with the DB automatically.

## 10. Bag upgrade — DON'T REPEAT 2026-05-01

The bug:
1. Tomcat startup runs `UpgradeBagList` for all superuser bags serially.
2. Each holds a global `PrecomputedTableManager` HashMap lock.
3. JDBC zombie socket caused indefinite hang inside one bag upgrade.
4. All Tomcat request threads queued behind the lock. Webapp dead.

Go re-implementation rules:

1. **No on-startup upgrade.** Bags upgraded **lazily on first access** OR
   in a background goroutine that processes one bag at a time without
   blocking handlers.
2. **Per-bag isolation.** Upgrade one bag = one transaction, one query,
   one timeout. No shared mutable state across bags.
3. **State machine explicit:**
   ```go
   type BagState int
   const (
     NotCurrent BagState = iota
     Upgrading
     Current
   )
   ```
4. **Idempotent upgrade query.** Re-running a partially completed upgrade
   must be safe.
5. **Postgres `statement_timeout`** per upgrade query (e.g. 60s). On
   timeout, mark `NotCurrent`, log, move on.
6. **No global lock.** Two upgrades for different bags should not
   contend. Use `pg_try_advisory_xact_lock(bag_id)` for per-bag locking.
7. **Background queue:** buffered channel, single worker goroutine.
   Handlers enqueue upgrade requests, return immediately. State checked
   on next access.

Phase 2 deliverable. Design from day 1.

## 11. PG pool settings (do these right)

Today's Java config (caused the failure):

```
maxLifetime=1800000     (30 min — caused the connect timeout)
idleTimeout=600000      (10 min)
connectionTimeout=30000 (30 s)
maxConnections=20
minimumIdle=10
```

Go with `pgxpool` config:

```go
cfg, err := pgxpool.ParseConfig(databaseURL)
if err != nil {
    return nil, err
}
cfg.MinConns = 4
cfg.MaxConns = 20
cfg.MaxConnLifetime = 30 * time.Minute
cfg.MaxConnIdleTime = 5 * time.Minute       // shorter — kill zombies fast
cfg.HealthCheckPeriod = 1 * time.Minute     // pgx pings idle conns
cfg.ConnConfig.ConnectTimeout = 10 * time.Second

// Connection-level keepalive (replaces JDBC tcpKeepAlive)
cfg.ConnConfig.RuntimeParams["application_name"] = "intermine-go"
cfg.ConnConfig.RuntimeParams["statement_timeout"] = "120000"
cfg.ConnConfig.RuntimeParams["tcp_keepalives_idle"] = "30"
cfg.ConnConfig.RuntimeParams["tcp_keepalives_interval"] = "10"
cfg.ConnConfig.RuntimeParams["tcp_keepalives_count"] = "3"

pool, err := pgxpool.NewWithConfig(ctx, cfg)
```

`pgxpool` has builtin health checks — every `HealthCheckPeriod`, idle
conns get pinged. Dead conns are reaped + replaced **before** a handler
asks for them. This is the structural fix to the connect-timeout bug.

## 12. Configuration

All via env vars, parsed via `kelseyhightower/envconfig` or `caarlos0/env`:

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

`envconfig.Process("", &cfg)` populates a struct on startup. Required
fields use struct tags `envconfig:"DATABASE_URL,required"`. App refuses
to start if any required var is missing. **No more `localhost:8090` baked
in.**

## 13. Deployment

Multistage Dockerfile producing distroless image:

```dockerfile
# builder
FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags="-s -w -X main.version=${VERSION}" \
    -o /out/intermine-go ./cmd/intermine-go

# runtime
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/intermine-go /usr/local/bin/intermine-go
EXPOSE 8000
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/intermine-go"]
```

Final image: ~30 MB. Static binary. No shell, no apt, no glibc.

Build: `docker build -t intermine-go:9.0.0 .`
Run: `docker run -p 8083:8000 --env-file .env intermine-go:9.0.0`

Or skip Docker entirely:
```bash
GOOS=linux go build -o intermine-go ./cmd/intermine-go
scp intermine-go multitenant:/usr/local/bin/
ssh multitenant "systemd start intermine-go"
```

ALB rollout: same playbook as 9.0.0 cutover
(`PRODUCTION_CUTOVER_9_0_0.md`). Add Go service as new ALB target on a
different port (8083), test in parallel with Java (8082), swap rule when
ready.

## 14. Testing

### 14.1 Snapshot tests against current Java

```go
func TestVersionMatchesJava(t *testing.T) {
    expected, err := os.ReadFile("snapshots/version.txt")
    require.NoError(t, err)
    resp := httptest.NewRecorder()
    req := httptest.NewRequest("GET", "/service/version", nil)
    server.ServeHTTP(resp, req)
    require.Equal(t, string(expected), resp.Body.String())
}
```

Capture script:

```bash
for endpoint in version model templates classkeys data-sources; do
  curl -sS "https://alliancemine.alliancegenome.org/alliancemine/service/$endpoint" \
    > "intermine-go/tests/snapshots/$endpoint.json"
done
```

For JSON, use `jsondiff` or hand-roll a sort-keys-then-diff helper. Match
must be byte-perfect after canonicalization.

### 14.2 Integration tests

`internal/testutil/` with fixtures:
- `dockertest`-managed Postgres container with seeded fixture DB
- Minimal Solr container
- End-to-end PathQuery → result
- Wire format diff

### 14.3 Property-based tests

`testing/quick` (stdlib) or `gopter` for PathQuery: generate random valid
queries, ensure they parse + compile to valid SQL + don't crash.

### 14.4 Load test

`vegeta` against the Go service vs Java service. Goal:
- Same p50, better p99 (no JVM GC pauses, sub-ms goroutine scheduling).
- Lower memory baseline (~30 MB Go vs ~2 GB Java).
- Faster cold start (~50 ms Go vs ~30 s Tomcat).

### 14.5 Race detector

Run all tests with `-race` flag in CI. Catches concurrency bugs in
goroutine code paths (bag upgrade queue, request handling).

## 15. Phasing

### Phase 0 — Setup (week 1)

- [ ] Scaffold `intermine-go/` directory
- [ ] `go.mod` with locked deps
- [ ] chi server skeleton with `/health`
- [ ] Dockerfile + docker-compose for local dev
- [ ] CI: `golangci-lint`, `go test -race`, `go vet`
- [ ] Capture Java webservice snapshots for all Phase 1 endpoints
- [ ] sqlc setup with one fixture query

### Phase 1 — Read-only API (months 1-2)

Goal: BlueGenes can browse the model, run simple queries, view results
against the Go service. Java webapp still serves writes.

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
- [ ] Configure BlueGenes test instance to use Go backend

### Phase 1.5 — PathQuery completeness (month 2-3)

- [ ] OR/NOT constraint trees
- [ ] Collection traversal
- [ ] Subclass narrowing
- [ ] Bag constraints (read-only)
- [ ] LOOKUP constraints
- [ ] Outer-join group control
- [ ] **Precomputed-table awareness** (mandatory before retiring Java)

### Phase 2 — User writes (months 3-4)

- [ ] Auth: token endpoint, `whoami`, chi middleware
- [ ] `/service/lists` CRUD via sqlc-generated profile DB code
- [ ] `/service/lists/{append,intersect,union,subtract}`
- [ ] **Bag upgrade** — lazy on first access, per-bag isolation, advisory locks
- [ ] List tags
- [ ] Saved queries CRUD
- [ ] Private templates CRUD
- [ ] Snapshot tests for all write endpoints
- [ ] Production cutover for AllianceMine (retire Java webapp)

### Phase 3 — Search + tools (months 4-6)

- [ ] Solr keyword search proxy
- [ ] Autocomplete
- [ ] Region search
- [ ] Widget framework

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
| Bag upgrade race conditions in goroutine code | Medium | Medium | Per-bag advisory locks via `pg_try_advisory_xact_lock`; `-race` in CI |
| BlueGenes JSON shape changes between InterMine versions | Low | Medium | Pin BlueGenes version, capture snapshots from a single Java release |
| Profile DB schema churn from Java side | Low | High | Don't run Java webapp + Go in write-mode simultaneously after Phase 2 |
| pgx version churn (fast-moving lib) | Low | Low | Pin major version; renovate weekly |
| Solr breaking changes during InterMine release upgrades | Low | Medium | Keep Solr URLs in env, not code; test against snapshotted Solr core |
| Go generics limitations forcing interface{} + type assertion | Medium | Low | Accept Go's idioms; don't fight the language |

## 17. Open questions for the next session to resolve

These decisions deliberately deferred to the implementation session:

1. **chi vs echo vs gin.** Recommended chi for stdlib alignment but echo
   has nicer middleware ergonomics. Pick before scaffolding.
2. **sqlc vs squirrel vs raw pgx.** sqlc for static profile DB queries,
   squirrel or raw for dynamic PathQuery SQL. Consider whether to mix.
3. **slog vs zerolog.** stdlib `slog` (Go 1.21+) preferred for zero-deps;
   `zerolog` faster but third-party. Decide.
4. **Go workspace (go.work) or single module.** If `intermine-go/` shares
   types with future Go CLI tools, use workspace. Otherwise single module.
5. **Where to host BlueGenes during transition.** Today separate; Go
   service can serve static BlueGenes assets via `embed.FS`.
6. **OpenAPI generation.** Go has `swaggo/swag` (annotation-driven) or
   `ogen`. Defer; BlueGenes doesn't currently use OpenAPI.
7. **Migration of existing Java tests.** Java has `acceptance-test/`
   directory with curl-based suite. Port these to Go test framework?
8. **Telemetry stack.** OpenTelemetry → CloudWatch? Prometheus
   `/metrics`? Decide when first endpoint hits production.
9. **Error type hierarchy.** Go's error wrapping (`fmt.Errorf("...%w...")`)
   vs `cockroachdb/errors` (richer). Decide pattern early.

## 18. Out-of-scope (explicit)

Not in the rewrite. Do not let scope creep pull them in:

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
- `docs/INTERMINE_PYTHON_BACKEND_MIGRATION.md` — sibling plan, Python stack
- `docs/INFRASTRUCTURE_REFERENCE.md` — SSH hosts, IPs, machine specs
  (operator-only, has credentials)
- `docs/RELEASE_PROCESS.md` — how the Java side ships today
- `docs/RELEASE_PROMOTION_PROTOCOL.md` — production cutover playbook
- `docs/PRODUCTION_CUTOVER_9_0_0.md` — concrete example of the cutover
- `docs/INCIDENT_2026_04_30_to_05_01.md` — what we're trying not to repeat
- `docs/POST_9_0_0_PLANNING.md` — open follow-ups, some resolved by this plan
- `docs/RUNTIME_CONTAINER_BACKUP.md` — manual snapshot procedure
- `docs/MULTITENANT_BACKUP_RESTORE.md` — automated snapshot scripts

External:

- InterMine docs: `https://intermine.readthedocs.io/`
- BlueGenes repo: `https://github.com/intermine/bluegenes`
- PathQuery DSL spec: `https://intermine.readthedocs.io/en/latest/api/pathquery/`
- InterMine REST API: `https://intermine.readthedocs.io/en/latest/api/`
- pgx docs: `https://github.com/jackc/pgx`
- chi docs: `https://github.com/go-chi/chi`
- sqlc docs: `https://docs.sqlc.dev/`

## 20. First commit checklist

When the next Claude Code session starts, the first commit should:

1. Create `intermine-go/` with the layout from §4.
2. `go.mod` with these initial deps:
   ```
   module github.com/alliance-genome/agr_intermine_builder/intermine-go

   go 1.22

   require (
     github.com/go-chi/chi/v5 v5.0.12
     github.com/go-chi/cors v1.2.1
     github.com/jackc/pgx/v5 v5.5.5
     github.com/kelseyhightower/envconfig v1.4.0
     github.com/golang-jwt/jwt/v5 v5.2.1
     golang.org/x/crypto v0.22.0
     github.com/stretchr/testify v1.9.0
   )
   ```
3. `cmd/intermine-go/main.go` with chi app + `/health` returning
   `{"status": "ok"}`.
4. `internal/config/config.go` with envconfig struct.
5. `internal/db/pool.go` with pgxpool factory.
6. `Dockerfile` (multistage, distroless final image).
7. `docker-compose.yml` with PG + Solr for local dev.
8. `.env.example` with all required vars (no real secrets).
9. `Makefile`: `build`, `test`, `lint`, `run`, `docker-build`.
10. CI workflow: `golangci-lint`, `go test -race ./...`, `go vet ./...`.
11. `intermine-go/README.md` linking back to this migration doc.
12. `sqlc/sqlc.yaml` with one trivial query as a smoke test.

Ship that as PR 1. **Don't write any business logic in PR 1.**

PR 2 onward: one endpoint per PR, with snapshot test.

## 21. Why Go vs Python — quick reference for the decision

If you're reading this trying to decide between this plan and the
Python sibling plan:

| Dimension | Go | Python |
|---|---|---|
| Solo+AI dev velocity | Fast (boring, AI rarely wrong) | Fastest (operator's daily lang) |
| Runtime perf | 5-10× Python | "Good enough" — query-bound anyway |
| Memory footprint | ~30 MB idle | ~200 MB per worker × N workers |
| Deploy artifact | Single static binary | Docker image |
| Cold start | ~50 ms | ~1 s |
| Compile feedback loop | ~2 s | (interpreter) |
| Type safety | Compile-time | mypy --strict (catches ~80%) |
| Bioinformatics ecosystem fit | Weak | Strong |
| Ops debugging at 3am | Easy | Easy |
| sqlc compile-time SQL check | Yes | No (closest: SQLAlchemy 2.0 typed) |
| Async story | Goroutines (best in class) | asyncio + asyncpg |
| Bus factor | Low (boring lang) | Low (operator's main lang) |

**Pick Go if:** runtime perf or deploy footprint matters. Or you want
the JDBC pool-bug class structurally killed by `pgxpool` health checks.

**Pick Python if:** prototyping speed dominates, you want consistency
with the existing `src/` CLI tools, or Pydantic v2 type safety beats
Go's runtime checks for your taste.

Both plans are isomorphic in scope. Pick one, start, don't switch
mid-stream.

---

End of plan. Hand this file to the next session and say:
**"Read `docs/INTERMINE_GO_BACKEND_MIGRATION.md` and execute Phase 0
section §20 first commit checklist."**

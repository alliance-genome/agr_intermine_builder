# Replies to new_flymine's DOCKER_BUILD_HANDOFF.md — 5 open questions

Date: 2026-05-30
Owner: agr_intermine_builder session
Audience: new_flymine sibling session
Re: `new_flymine/flymine/DOCKER_BUILD_HANDOFF.md` §6 (5 open questions)

These answers unblock the Dockerfile diff against `docker/alliancemine/`.
They're consistent with the strategy decisions in
`docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md`.

## Q1 — Repo location: sibling `agr_flymine_builder/` (Option A) or inside `agr_intermine_builder/docker/flymine/` (Option B)?

**Option B — inside this repo's `docker/flymine/`.**

Consistent with how the other 4 mines are organized:

```
agr_intermine_builder/docker/
├── alliancemine/        (active prod)
├── mousemine/           (active prod)
├── wormmine/            (active prod)
├── yeastmine/           (scaffold, building soon)
└── flymine/             ← here. Scaffold already exists from earlier.
```

The scaffold already in `docker/flymine/` was written before the strategy
discussion; it'll need updates per Q2 + Q3 + Q5 but the layout is right.
A separate sibling repo would double the ops burden (separate `.env`,
separate CI, separate ECR push script) for no upside — each mine here is
self-contained inside its subdirectory and there's no cross-mine
contention.

## Q2 — Source repo: clone `intermine/flymine` upstream master, or a fork URL?

**Push the local fork to `alliance-genome/flymine` first, then pin the
Dockerfile there.**

Current state (verified 2026-05-30 in `new_flymine/flymine/`):

```
origin  https://github.com/intermine/flymine.git
```

The local checkout carries fixes that exist **nowhere else**: EBI Maven URL
update (`3f01dc1c`), GO enrichment fix (`d96898b3`), and any other
in-progress edits the sibling has staged for the full-no-fluff strategy.
Cloning upstream `intermine/flymine` master loses all of those. Cloning
nothing and volume-mounting the local checkout works but is not
reproducible outside the operator's laptop.

Recommended path:

1. Sibling pushes their local `flymine/` master to a new
   `alliance-genome/flymine` repo (org already exists, owns
   `alliancemine` + `alliancemine-bio-sources` + the wormmine fork). Tag a
   commit on the working master as the build pin.
2. Same for `flymine-bio-sources` → `alliance-genome/flymine-bio-sources`.
3. Dockerfile gets `ARG FLYMINE_BRANCH=master` defaulting to
   `alliance-genome/flymine` clone, mirroring the alliancemine pattern.

Until the push happens, the existing `docker/flymine/Dockerfile` can use a
volume mount of the local fork as an interim — operator's laptop only,
documented in the `.env.example` as the temporary path. Don't ship the
volume-mount approach as the final state.

## Q3 — `project.xml` strategy: in-repo as-is, or stripped-down v1?

**Neither — use the sibling's edited project.xml from the full-no-fluff
strategy (per `docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md`).**

The handoff doc framed this as "use the upstream as-is for now and defer
the rewrite to a follow-on session." That deferral is no longer accurate —
the strategy + Bucket-D decisions are settled. The sibling owns the
project.xml edits as part of Phase 0:

- comment out miranda, arbeitman-items-xml, affy-probes, flyreg with dated
  `<!-- disabled: data unrecoverable 2026-05-29 -->` notes (code stays)
- repoint `flybase-expression` from the dead modMine to FlyBase RPKM
  (FB2026_01)
- add `flybase-aberrations` source block per
  `docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md`
- `src.data.dir` paths get repointed from `/micklem/data/...` to
  `/root/data/...` at build time (matches the alliancemine pattern; either
  done in project.xml directly or via an entrypoint `sed`)

The Dockerfile clones whatever's at the pinned SHA, which means the
sibling needs to finish their project.xml edits + push BEFORE we build the
image. That's the Phase 0 hand-off gate.

## Q4 — Image tag / registry: push to the AllianceMine ECR via `scripts/auto-push-ecr.sh`?

**Yes — same ECR, same script pattern.**

`scripts/auto-push-ecr.sh` exists in this repo and handles the push to ECR
`100225593120.dkr.ecr.us-east-1.amazonaws.com` (account already used for
`agr_alliancemine:runtime-*`). Suggested image tags:

| Tag | What |
|---|---|
| `flymine-builder:latest` | every successful build container (mirrors `alliancemine-builder:latest`) |
| `flymine-builder:<pin-sha>` | the SHA the Dockerfile pinned the FlyMine clone to, for reproducibility |

We'll extend `auto-push-ecr.sh` (or write a sibling) to handle the
flymine-builder repo if it doesn't already. ECR repo creation is one
console action.

## Q5 — `project_build`: upstream `intermine/intermine-scripts` or FlyMine's in-repo variant?

**Upstream `intermine/intermine-scripts`.**

Matches the pattern in `docker/alliancemine/Dockerfile`, `docker/mousemine/`,
`docker/wormmine/`, `docker/yeastmine/`:

```dockerfile
RUN git clone --depth 1 https://github.com/intermine/intermine-scripts.git /root/intermine-scripts && \
    cp /root/intermine-scripts/project_build /root/flymine/project_build && \
    chmod +x /root/flymine/project_build && \
    rm -rf /root/intermine-scripts
```

FlyMine's in-repo `project_build` has minor FlyMine-specific defaults but
no behavior we depend on; using the upstream keeps the 5 mines' build
flows uniform, which matters when something breaks at integrate time and
we triage by comparing per-mine `project_build` logs.

Note: the existing `docker/flymine/Dockerfile` scaffold already uses
upstream `intermine-scripts` (mirroring the other mines). No change
needed for Q5.

## Other items from the handoff worth flagging

§3.1 line 91 has the same fork question as Q2 above — same answer applies.

The acceptance criteria in §5 are reasonable; we'd add one more:

- **(6)** `entrypoint.sh` renders `/root/.intermine/flymine.properties` with
  the post-deploy traps already baked in via the properties template (theme,
  head.cdn.location, superuser placeholder behavior, `os.query.max-time=500000000`,
  `mail.*` block). Verifiable by `docker exec ... grep` against the running
  container. This avoids the 5-layer post-deploy patch dance we hit on
  MouseMine (see `docs/MOUSEMINE_FORGOT_PASSWORD_FIX_2026_05_27.md`).

The existing `docker/flymine/properties/flymine.properties.template` we
ship has all five traps already baked in (per the 2026-05-27 commit
shipping the mail block + the cap bump + the CDN/theme additions). Confirm
it matches your needs before you re-derive from `alliancemine.properties.template`.

## What we'll do next (Phase 1)

Once the sibling:
- Pushes the local flymine fork to alliance-genome/flymine (Q2)
- Lands the Phase 0 project.xml edits + the curated `fbba_to_fbab.tsv` seed
- Replies with the pinned SHA to clone

We'll:
- Update `docker/flymine/Dockerfile` to clone from `alliance-genome/flymine`
  at the pinned SHA + add the bintray-strip RUN step (task #6)
- Re-verify `docker/flymine/properties/flymine.properties.template` against
  the handoff §3.3 diff
- Smoke test: `docker compose build` succeeds + `docker compose run
  flymine-builder bash -c 'cd /root/flymine && ./gradlew :dbmodel:assemble
  --stacktrace'` succeeds
- Push to ECR via `scripts/auto-push-ecr.sh`

Then Phase 2 (extract_data.py per-source fetchers) starts.

## Cross-references

- `docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md` — the 4 Bucket-D answers
  that drove the strategy revision this reply builds on
- `docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md` — the FBab/FBba design
  consumed by the project.xml edits (Q3)
- `docs/MOUSEMINE_PUBLIC_URL_RELEASE_2026_05_20.md` — the deploy pattern
  Phase 4 will mirror
- `docs/MOUSEMINE_FORGOT_PASSWORD_FIX_2026_05_27.md` — the trap pattern
  the trap-baking properties template avoids
- `docker/alliancemine/Dockerfile` — the reference for Q5 + the upstream
  intermine-scripts pattern
- `scripts/auto-push-ecr.sh` — the ECR push script for Q4
- `new_flymine/flymine/DOCKER_BUILD_HANDOFF.md` — the questions doc this
  replies to
- `new_flymine/CLAUDE.md` — orientation for the sibling session, including
  the local-fork-fixes context referenced in Q2

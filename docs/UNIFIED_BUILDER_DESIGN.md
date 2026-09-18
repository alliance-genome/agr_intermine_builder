# Unified InterMine build — design proposal

Status: **draft for review** (branch `unified-mine-builder`, 2026-09-18)
Method: ultracode workflow (6 build maps → 4-angle design panel → synthesis) + independent codex cross-review.

## TL;DR

The right target is **not one universal builder**. It is a **shared build substrate +
a validated per-mine config registry + two thin build fronts** (gradle for the four
InterMine-5.x mines; Ant for the live MouseMine). Standardize everything *below* the
"invoke the build tool" line — where 4 of the 5 mines are the *same* gradle/Alpine/JDK8
skeleton copy-pasted and drifting — and keep the Ant/gradle line as a deliberate
boundary, not a wart to sand off.

Why not literally "one builder": forcing InterMine-1.x (Ant/JDK11/Ubuntu, off-repo,
its own MGI ETL, **just went live as rc4**) and InterMine-5.x (gradle/JDK8/Alpine) into
one artifact means either rewriting a live ETL pipeline (months, real regression risk,
zero data payoff) or a universal stage abstraction serving exactly one Ant consumer
(accidental complexity). The honest win is deduping the ~90% shared plumbing.

## Current state (mapped)

| Mine | Front | In-repo build | Notes |
|---|---|---|---|
| alliancemine | gradle/5.x | yes (reference: `build_full.py` 6-stage) | LIVE rc20 prod; strictest guards; **requires** existing persistent profile DB |
| flymine | gradle/5.x | yes | file-swap deploy (RO bind-mount), not cargo; bakes WAR patches post-`:webapp:war` |
| yeastmine | gradle/5.x | yes | staged local fork (COPY), fragile un-versioned project.xml edits |
| wormmine | gradle/5.x | yes (build-only) | no fake-ssh wrapper; extra Perl deps; no live pipeline to break |
| mousemine | Ant/1.x | **no** — `docker/mousemine/` is a gradle skeleton its own README says "cannot run a full integration" | real build is off-repo Ant/JDK11/Ubuntu + `/mousemine_etl`; LIVE rc4 |

The four gradle Dockerfiles share a near-identical ~50-line prefix (Alpine 3.20,
openjdk8, a ~15-module cpanm block, `project_build` from intermine-scripts, `.needs_compile`,
java-version HEALTHCHECK); their entrypoints are ~90% identical, differing by a mine-name
string and FMS-vs-manual release resolution. That duplication is the high-value, low-risk
target.

## Recommended architecture

One **shared base image** (not one mega-Dockerfile) + thin overlays + a config registry:

```
docker/base-builder/Dockerfile     -> intermine-build-base:jdk8-gradle (ECR)
                                       shared deps ONLY (Alpine+openjdk8, cpanm block,
                                       project_build, HEALTHCHECK). NOT the fake-ssh
                                       wrapper and NOT source-dependent heap patches —
                                       those are not universal (see codex corrections).
docker/base-builder-ant/Dockerfile -> DEFERRED (only if the live MouseMine comes in-tree)
docker/lib/entrypoint-common.sh    -> sourced library of the shared entrypoint functions
docker/<mine>/Dockerfile           -> ~30-line overlay: FROM base@<digest> + source
                                       acquisition (clone ARG vs COPY fork) + per-mine
                                       Perl (wormmine) + fake-ssh (only mines that need it)
                                       + ordered mine-specific patch scripts
docker/<mine>/entrypoint.sh        -> ~15 lines: export MINE_NAME/DB_PREFIX/RELEASE_SOURCE,
                                       source entrypoint-common.sh
mines/<mine>.yaml                  -> config registry (DATA, schema-validated): versions,
                                       ports, db_prefix, solr-core scheme, deploy mechanism,
                                       release-source, source strategy, patch manifest,
                                       AND the profile-DB policy (create-copy vs require)
scripts/build_pipeline.py          -> generalized gradle stage-runner (--mine), giving
                                       flymine/yeastmine/wormmine the orchestrator they lack;
                                       MANDATORY tee of project_build output
scripts/finalize_build.sh          -> generalized WAR-finalize (<mine> + patch dir); must
                                       preserve per-mine stage ORDER (flymine: SQL patches
                                       BEFORE postprocess), not just a single tail stage
patches/intermine/{MailUtils.java, bake_mail_into_war.sh} -> single canonical mail fix
docker/intermine-tomcat-1x/        -> UNCHANGED shared runtime image (the model we copy)
```

**Config = DATA, logic = code.** Per-mine *facts* (ports, core names, prefixes, profile
policy) live in schema-validated YAML because a wrong port or core name silently
misdeploys. Per-mine *surgery* (SgdConverter dedup, class_keys fixes, slim-model trims,
dedup_authors) stays as ordered patch scripts the manifest *references* — not encoded as
config values (avoids the inner-platform trap).

## What standardizes vs stays mine-specific

**Standardizes:** base image; entrypoint function library; the config registry; the gradle
stage-runner; the finalize/mail/patch/Solr-core toolset; DB/Solr naming convention; the
persistent-userprofile handling (factored to ONE place).

**Stays mine-specific (irreducible):** each `project.xml`/source list (the mine's biology);
imperative source-tree patches; data provenance + extractors (FMS/API/S3, FlyBase chado,
MGI ETL, SGD external Postgres); extra infra (flymine chado-pg sidecar, SGD datasource,
wormmine Perl); source-acquisition mode (COPY staged fork vs git-clone); the Ant/1.x front
for the live MouseMine; deploy mechanism (cargo vs file-swap vs build-only) behind a
pluggable contract.

## Migration plan (revised safety-first, per codex review)

The original plan led with base extraction. Codex's central correction — **establish and
test DB-lifecycle safety before touching shared plumbing** — reorders it:

0. Branch off `unified-mine-builder`. Every step independently valuable + revertible; each
   gated by a per-mine build + smoke test. Each mine keeps its old Dockerfile until its new
   image diffs clean.
1. **Inventory effective config + DB-safety tests FIRST.** Reconcile the contradiction:
   alliancemine *requires* an existing profile DB and aborts; wormmine/flymine/yeastmine
   *create/copy* profiles and terminate connections to the prod profile. The registry must
   carry a per-mine `profile_db_policy` (require | create-copy) — you cannot impose one
   guard on all. Write executable tests that REJECT a production DB target, a missing
   required profile, and inconsistent props (there is today no real `verify-db-target`
   guard — `build_full.py` invokes `buildDB` directly; a misaimed builddb once wiped rc18
   prod). Parity of rendered files is necessary but NOT sufficient.
2. **Fence the stale src/ orchestration.** `src/intermine_builder/mine_config.py` has wrong
   versions/ports and no YeastMine, BUT `build-mines` is a declared CLI entry point with
   callers + tests and `buildUserDB` is implemented (using the stale profile name) — it is
   *reachable*, not dead. Fix or fence it (guard against stale DB names reaching buildDB)
   before anything reads it; decide delete-vs-reduce-to-host-duties.
3. **Extract the dependency-only base** (`docker/base-builder`) — shared deps only,
   content-equivalent to today, nothing consumes it yet. Note the deltas that must NOT be
   normalized away: alliancemine *replaces* the gradle heap while others *append*;
   wormmine has **no** fake-ssh wrapper; source-dependent heap patches go *after* source
   acquisition; compile timing differs (first-run vs image-build install).
4. **Pilot on WORMMINE** (build-only, no live pipeline). Then validate the *actual* shared
   workflow on **YEASTMINE + FLYMINE** (byte-diff rendered `.intermine/<mine>.properties`,
   `.pgpass`, constructed DB names vs a pre-migration container; throwaway test-RC builds
   only). Extract `entrypoint-common.sh` here.
5. **De-duplicate the mail/patch toolset** to one canonical copy; generalize
   `finalize_build.sh <mine>` preserving per-mine stage ORDER.
6. **Introduce `mines/<mine>.yaml`** descriptively (match current behavior, change nothing),
   wire entrypoint-common/finalize/build_pipeline to read it, and reconcile-or-delete src/
   so there is exactly ONE source of truth.
7. **Generalize `build_pipeline.py` / `create_solr_cores.py`** (`--mine`).
8. **Rebase ALLIANCEMINE LAST** (live prod, subtlest guards) — but test its safety contract
   from step 1, not at the end. Byte-diff parity + keep old Dockerfile as rollback.
9. **DEFERRED / optional:** archive (don't delete) the dead `docker/mousemine` skeleton
   after recording its provenance; bring the live Ant/ETL MouseMine in-tree as the second
   front (JDK11/Ant base) consuming the shared config/patch/deploy/runtime layers, wrap-only.
   Declinable without blocking the gradle win.

## Risks

- **Blast-radius inversion:** a base/lib bug breaks all gradle mines at once. Mitigate: pin
  base by digest per overlay, roll one mine at a time, CI matrix rebuilds every mine on any
  base/lib change.
- **Silent normalization of a load-bearing quirk** (heap replace-vs-append, wormmine no
  fake-ssh, compile timing, extra Perl). Preserve deltas explicitly; parity-test each mine.
- **alliancemine is live prod** with the highest-stakes guards — migrates last, safety
  contract tested from the start, old Dockerfile as rollback.
- **Registry as new single point of failure:** a wrong port (real flymine=8085) or core
  name silently misdeploys. Schema-validate; keep it DATA; never let generated names reach
  buildDB without the (to-be-written) verify-db-target guard.
- **Source provenance untouched by layering:** flymine/yeastmine COPY un-versioned forks
  with fixes that exist nowhere upstream — source acquisition can't converge on git-clone
  until those forks are published; per-mine source strategy is permanent for now.
- **Two-fronts is "one builder with a fuzzier seam":** every cross-cutting patch must be
  validated against both fronts. Rebuttal: the substrate is already shared, so Front B can
  collapse into Front A later *if* an upstream MouseMine→gradle migration ever lands.

## Open questions (need a human decision)

- Is an upstream MouseMine Ant→gradle migration coming? If imminent, unify fully now and
  skip two-front scaffolding; if not (likely — rc4 just shipped), two fronts is correct.
- Delete src/ orchestration entirely, or reduce to host-only duties reading `mines/*.yaml`?
  (Recommend delete unless the `build-mines` CLI is actively used — codex confirmed it's
  wired, so confirm real usage before deleting.)
- Will alliance-genome publish the flymine/yeastmine forks so source acquisition can
  converge on pinned git-clone?
- Converge deploy on file-swap for the gradle mines (migrate alliancemine off
  cargoRedeployRemote), or keep cargo as a per-mine exception behind the deploy contract?
- Standardize the Solr-URL patch timing (runtime vs image-build-bake) across mines?
- Ratify deleting/archiving the dead `docker/mousemine` gradle skeleton before any base-ant
  work.

## Effort

Gradle-side standardization (steps 1–8): ~3–4 weeks part-time, front-loaded with low-risk
high-value extraction. MouseMine second front (step 9): a separate ~1.5–2 weeks, isolated
and declinable. A genuinely single gradle builder would instead be blocked on rewriting +
revalidating the live MGI ETL+Ant pipeline — months, real regression risk, zero
data-quality upside.

---
*Generated from an ultracode design workflow (`wf_a7990dfe-c32`, 11 agents) synthesizing
6 build maps and 4 unification approaches, then cross-reviewed by codex-cli 0.153.2
(verdict: endorse-with-changes; its corrections on DB-lifecycle safety, the reachable
src/ CLI, and the base-extraction deltas are folded into the plan above).*

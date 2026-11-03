# Compose Launcher Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks in order. Steps use checkbox syntax for tracking.

**Goal:** Replace duplicate host-side build orchestration with a small launcher on a separate branch.

**Architecture:** Docker Compose owns images, containers, mounts, and environment settings. Existing mine-specific scripts own build stages. A standard-library Python launcher selects the mine, invokes those commands, and preserves their exit status and output.

**Tech Stack:** Python 3.9+, Docker Compose, Bash, tee; existing mine pipelines.

**Spec:** The user approved the Compose-first design in this conversation and requested implementation on a different branch, with a possible fork later.

## Global Constraints

- Work on `simplify-compose-launcher`, based on `829d28b`.
- Preserve the existing `AGENTS.md` and unrelated untracked files.
- Keep database protection, extraction validation, deployment rollback, and operational tools.
- No live builds, deployments, infrastructure changes, merge, or push for this refactor.
- Launcher runs without installing Python dependencies; Compose remains the configuration authority.
- Keep mine-specific differences explicit; do not invent missing full-build pipelines.

## Review Focus

- Paths containing spaces and shell metacharacters must survive unchanged.
- Failed commands and logging failures must remain failures; stdout/stderr must be retained.
- Status/log inspection must not start containers, provision databases, or clean resources.
- Invocation from another directory must select the intended Compose project and `.env`.
- Host build scripts must use the selected directory; YeastMine's build command must not publish.

## Task 1: Launcher and operational boundary tests

**Files:** Create `mine`, `src/cli/mine.py`, `tests/test_mine_cli.py` and a fake executable helper under `tests/helpers/`. Modify FlyMine's build script to accept an explicit working directory while retaining its existing default.

**Interface:** `./mine [--directory DIR] [--dry-run] MINE ACTION [ARGS...]`; `./mine list`. Actions: `image`, `build`, `run`, `shell`, `status`, `logs`, `compose`. `--directory` selects an existing mine Compose directory. Arguments after the action belong to the underlying command.

- [x] Write subprocess tests with a fake Docker executable and controlled host-script fixtures; test actual CLI output, argument boundaries, directory selection, logs, and exit codes.
- [x] Run focused tests and confirm failure because the launcher is absent.
- [x] Implement the launcher. Use Compose for image/run/shell/status and an explicit Compose passthrough. Use Bash pipefail plus tee for persistent command logs; no Docker SDK or parallel scheduler.
- [x] Route AllianceMine builds to its container command, FlyMine to its existing host script, and YeastMine to its existing weekly script with `--no-publish`. Reject full builds for MouseMine/WormMine with instructions for `run`.
- [x] Verify failed commands, malformed invocations, and Ctrl-C do not report success. Dry runs create no log files or subprocesses.

## Task 2: Remove the second build system

**Files:** Remove `mine_builder.py`, `docker_manager.py`, `build_executor.py`, `mine_config.py`, `config.py`, their obsolete unit tests/fixtures, and `examples/quick_start.py`. Simplify the package initializer and `src/cli/build_mines.py`. Modify `pyproject.toml`, `uv.lock`, and packaging tests.

**Interface:** `mine` is the primary installed entry point; `build-mines` and `python -m src.cli.build_mines` are aliases using the new syntax. RDS, release, and database administration commands remain independent.

- [x] Add installed-wheel tests for the launcher and alias, including execution outside the checkout with an explicit directory and no optional imports.
- [x] Run tests to observe the missing entry point, then remove obsolete orchestration and configuration dependencies.
- [x] Keep all extraction, promotion, and deployment regression tests; run the whole remaining suite.
- [x] Verify the lockfile, Python 3.9 syntax, and isolated launcher execution with `python -S`.

## Task 3: Documentation and final verification

**Files:** Add root `README.md` and `examples/README.md`; update `src/README.md`, `docs/BUILD_SYSTEM.md`, `docs/QUICKSTART.md`, the overview's alternative-path section, and applicable navigation/agent notes (except protected `AGENTS.md`).

- [x] Document setup, all five mines, resume/environment handling, log locations, host-script prerequisites, and old-to-new command migration.
- [x] Mark historical design documents as historical rather than treating them as another supported build path.
- [x] Run full pytest, focused Ruff/Black, shell syntax, lockfile, diff checks, and aislop; resolve errors and fixable warnings.
- [x] Obtain a fresh read-only review and address substantive findings with regression tests.
- [x] Record validation and report the branch, reduction, supported commands, and remaining limitations.

## Execution notes

- Ruling: Use the requested new branch in the existing checkout; tracked files were clean and the two unrelated untracked files remain untouched.
- Ruling: Preserve the existing `AGENTS.md` as explicitly requested earlier; keep its `build_mines list` invocation working through the compatibility alias.
- Ruling: Persist launcher output with the already-required Bash/tee tools instead of implementing another Python stream/signal abstraction.
- Ruling: Keep host build-script prerequisites intact. MouseMine and WormMine have no full pipeline to delegate to; reject that action instead of pretending it exists.
- Ruling: Updating the RDS CLI's next-step command exposed an existing unused provisioner and ignored AWS profile in status. Reuse its selected-profile client; a regression test failed before the fix and passed afterward. Existing mutation commands were not redesigned.
- Final review: A fresh read-only reviewer found one P2 cancellation defect: a PID-targeted signal could stop the logging shell while leaving its command running. Direct-PID SIGINT/SIGTERM/SIGHUP tests reproduced it. A small wait/forward helper now owns the logging process group; all 33 launcher tests pass.
- Final review scope: Real Docker/container cancellation and live builds were not exercised. Existing host-script retention, `.env` sourcing, deployment behavior, installed prerequisites, and other RDS mutation-profile behavior remain under their existing runbooks; no live operations were performed.

## Validation

- Full suite: **69 passed in 17.03s**, including real launcher subprocess tests and installed-wheel checks.
- Launcher: 155 lines, replacing the 2,050-line host build/configuration path; the former build module is a seven-line alias.
- Ruff and Black: clean for changed Python code and launcher tests.
- Python 3.9 syntax: all nine changed/new Python files parse successfully.
- Shell syntax, offline lockfile check, and `git diff --check`: passed.
- Aislop changed-file scan: **100/100, zero diagnostics**.
- Mypy: **12 existing errors in three operational-tool files**, reduced from 21 by removing obsolete orchestration. No launcher type errors.
- Coverage percentages are not comparable with the previous suite: removed classes no longer count, and dependency-free launcher subprocesses intentionally run with `python -S` outside coverage injection. Behavior is checked at the command boundary.
- `AGENTS.md` matches the base commit byte-for-byte; unrelated `gene` and `yeastmine-home.png` remain untouched.
- All builds, external services, and cancellation checks used test doubles; no live Docker/RDS/AWS/Solr operations.

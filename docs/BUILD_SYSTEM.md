# Compose build system

The host launcher selects an existing mine directory and delegates commands:

```text
./mine <mine> <action>
  ├── Docker Compose: image, run, shell, status, compose
  ├── Existing mine pipeline: build
  └── Persistent host output: logs
```

There is one authoritative configuration for each builder:
`docker/<mine>/docker-compose.yml` plus its `.env` and properties templates.
The launcher adds no stage model, Docker object cache, resource registry, or
database provisioning. See the [command reference](../README.md#commands).

## Pipeline ownership

| Mine | Pipeline owner | Resume control |
|---|---|---|
| AllianceMine | `docker/alliancemine/scripts/build_full.py`, invoked by the container entrypoint | `RC_NUMBER=N`, `build --start-from STAGE --resume` |
| FlyMine | `docker/flymine/scripts/build_release.sh` on the host | `RESUME_AT=STEP` and the prepared `.env` |
| YeastMine | `docker/yeastmine/weekly/weekly_build.sh` on the host | `RESUME_RC=N` |
| MouseMine, WormMine | Individual commands documented in their Compose directories | Operator-selected commands |

FlyMine's existing release prerequisites still apply, including its per-release
integration script and completed Chado restore. The launcher passes the selected
directory through `FLYMINE_DIR`; direct script use keeps the existing default.

YeastMine builds use `--no-publish` and the selected directory as `YM_DIR`.
`WEEKLY`, `AMFMS`, installed check scripts, S3 status, and retention behavior remain
owned by that pipeline. Configure them according to the
[weekly-build runbook](../docker/yeastmine/weekly/README.md).

Image builds for FlyMine and YeastMine require the staged local sources used by
their Dockerfiles. Their existing `scripts/build_and_push.sh --no-push` helpers
stage and build those sources; the launcher does not copy or replace source trees.

## Logs and failure behavior

`image`, `build`, and `run` append both output streams to
`<selected-directory>/logs/commands.log`. `./mine <mine> logs` prints the last
100 lines; `logs -f` follows the file. Underlying pipeline log files stay intact.

Bash `pipefail` and `tee` preserve command failures and logging failures. For
logged commands, the launcher forwards SIGINT, SIGTERM, and SIGHUP to the whole
command process group and waits for the command wrapper. Other actions replace
the launcher process directly. Use `tmux` or the existing systemd timers for
builds that must survive disconnects.

`status` calls Compose `ps --all`; it reports containers rather than an inferred
pipeline stage. `logs` reads a host file without contacting Docker. Inspection
does not start containers or remove them. Container cleanup is explicit through
the `compose` action; inspect resources before removing anything.

## Migration from the Python orchestrator

| Previous command/API | Replacement |
|---|---|
| `build-mines list` | `./mine list` |
| `build-mines build --mine alliancemine` | `./mine alliancemine build` |
| `build-mines build --mine alliancemine --rebuild` | `./mine alliancemine image --no-cache`, then `build` |
| `build-mines status --mine alliancemine` | `./mine alliancemine status` |
| `build-mines stage --mine alliancemine --stage extract_data` | `./mine alliancemine run python3 /root/scripts/extract_data.py` |
| `build-all` | Explicitly invoke the supported mine pipelines in your automation, checking each exit status |
| `cleanup` | Inspect with `status`, then use explicit Compose removal commands |
| `MineBuilder`, `DockerManager`, `BuildExecutor`, `Config`, `MineConfig` imports | Call the launcher or Compose as a subprocess |

The installed `build-mines` name and `src.cli.build_mines` module remain aliases
for the **new syntax**. The generic Python orchestration API and its redundant
configuration classes have been removed. RDS management, release tooling,
database administration, container pipelines, and deployment scripts remain.

## Development checks

```bash
uv pip install -e '.[dev]'
python -m pytest
ruff check src/cli/mine.py src/cli/build_mines.py tests/
black --check src/cli/mine.py src/cli/build_mines.py tests/test_mine_cli.py tests/test_packaging.py
```

Launcher tests use real subprocesses and fake external executables to check
argument boundaries, directory selection, output, exit codes, and interruption.
Packaging tests execute the installed commands outside the checkout. Regression
tests retain extraction, production-database protection, and deployment rollback
coverage without contacting live services.

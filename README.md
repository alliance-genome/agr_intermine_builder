# InterMine build tools

For a detailed before-and-after comparison, read the [workflow review and operator guide](docs/compose-workflow-review.html). The standalone HTML includes a print layout for saving as PDF.

Run the existing mine builds with Docker Compose from the build machine. The
`mine` launcher selects a Compose directory and runs its commands; each mine's
scripts remain responsible for its build pipeline.

## Start here

Requirements: Python 3.9+, Docker with Compose, Bash, `tee`, and `tail` on a
Linux or macOS host. The launcher needs no Python package installation.

```bash
ssh build-host
cd agr_intermine_builder
cp docker/alliancemine/.env.example docker/alliancemine/.env
# Configure credentials and release settings in that .env file.
./mine list
./mine alliancemine image
./mine alliancemine build --skip-stages deploy
```

Builds require the configured databases, data sources, and substantial memory.
Use `tmux` for long interactive sessions. See [release preparation](docs/RELEASE_PROCESS.md)
before running a full integration.

## Commands

```bash
./mine alliancemine image --no-cache     # Compose image build
./mine alliancemine build               # Existing full pipeline
./mine alliancemine shell               # Interactive configured container
./mine alliancemine run python3 /root/scripts/extract_data.py
./mine alliancemine status              # Compose containers, including stopped runs
./mine alliancemine logs -f             # Follow persistent launcher output
./mine flymine compose exec -T chado-pg psql --version
./mine --dry-run alliancemine build     # Preview without starting anything
```

Options after the action are passed to the underlying command. Shell and run
commands execute the existing entrypoint, including its configuration and database
setup. Status and logs only inspect existing state. `image`, `build`, and `run`
append stdout/stderr to `docker/<mine>/logs/commands.log`; pipeline-specific logs
remain in their existing locations. Failures propagate to the calling shell.

To use a deployed Compose directory outside this checkout:

```bash
./mine --directory /home/ec2-user/flymine-deploy flymine build
```

The selected directory owns the Compose file, `.env`, mounts, and scripts. Direct
`docker compose` commands remain supported. FlyMine and YeastMine image builds
require their local source trees to be staged first; their existing
`scripts/build_and_push.sh --no-push` helpers perform that preparation.

## Mine pipelines

| Mine | `build` action |
|---|---|
| AllianceMine | Container's `build` command, with its existing resume/stage options |
| FlyMine | `scripts/build_release.sh`; requires the prepared Chado restore, build database, source tree, and release scripts |
| YeastMine | `weekly/weekly_build.sh --no-publish`; requires the installed weekly-build checks, standby cores, and existing data paths |
| MouseMine, WormMine | No full pipeline in these Compose directories; use `run` for the commands in each mine's README |

YeastMine's scheduled publishing and deploy agent remain separate. Its manual build
still runs the existing checks, status updates, and retention policy. AllianceMine
retains its optional deployment stage; pass `--skip-stages deploy` for a build only.
Production promotion and rollback remain in their existing operational scripts.

Pin the release candidate in the **environment before container startup**, so
entrypoint configuration and the pipeline target the same database:

```bash
RC_NUMBER=21 ./mine alliancemine build --start-from project_build --resume --skip-stages deploy
RESUME_AT=postprocess ./mine --directory /home/ec2-user/flymine-deploy flymine build
RESUME_RC=21 ./mine yeastmine build
```

Set the release in the selected `.env` or environment. Do not use pipeline-only
`--rc`/`--release` flags to change the target after the entrypoint has configured it.

## Repository and development

- `docker/<mine>/`: Dockerfiles, Compose settings, properties, and pipelines.
- `src/cli/mine.py`: launcher; `src/cli/` also contains independent operational tools.
- `scripts/` and `patches/`: deployment, maintenance, and upstream fixes.
- `tests/`: launcher, packaging, extraction, promotion, and rollback checks.
- `docs/`: runbooks; start with [the build system](docs/BUILD_SYSTEM.md).

```bash
uv pip install -e '.[dev]'
python -m pytest
```

Package installation provides `mine`, its `build-mines` alias, and `rds-manager`.
An installed launcher used outside this checkout needs `--directory` to locate the
mine's Compose assets. See [migration notes](docs/BUILD_SYSTEM.md#migration-from-the-python-orchestrator)
for the removed Python build API and old CLI syntax.

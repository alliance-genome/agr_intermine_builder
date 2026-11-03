# Quickstart

Run commands on the build machine with Python 3.9+, Docker Compose, Bash, `tee`,
and `tail` available. No Python package installation is needed for `./mine`.

```bash
cd agr_intermine_builder
cp docker/alliancemine/.env.example docker/alliancemine/.env
# Edit .env with RDS, SGD, release, and Solr settings.
./mine list
./mine --dry-run alliancemine image
./mine alliancemine image
./mine alliancemine build --skip-stages deploy
```

Full builds use substantial resources and take hours. Review the
[release prerequisites](RELEASE_PROCESS.md) and use `tmux` before starting one.

```bash
./mine alliancemine status
./mine alliancemine logs -f
RC_NUMBER=21 ./mine alliancemine build --start-from project_build --resume --skip-stages deploy
```

Pin `RC_NUMBER` in the environment before container startup when resuming. The
selected `.env` sets the release. Container entrypoints still perform their
existing database setup, including when you request a shell.

For another mine or an existing deployment directory, see the
[command guide](../README.md) and [pipeline support table](BUILD_SYSTEM.md#pipeline-ownership).
MouseMine and WormMine currently expose individual commands through `run`;
their Compose directories have no full build script.

RDS administration, production promotion, deployment, and rollback remain
separate operational tasks. See [host tools](../src/README.md) and the
[release promotion protocol](RELEASE_PROMOTION_PROTOCOL.md).

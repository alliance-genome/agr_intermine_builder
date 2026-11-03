# Host commands

`src/cli/mine.py` is the standard-library Compose launcher used by `./mine`.
It delegates image and container management to Docker Compose and full builds to
the existing mine scripts. It reads no database credentials or release registry.

```bash
./mine list
./mine alliancemine image
./mine alliancemine build --skip-stages deploy
```

The installed `mine` and `build-mines` entry points use the same syntax.
`python -m src.cli.build_mines list` remains supported as an alias.
Installed commands require `--directory /path/to/mine` outside this checkout.
See [migration and architecture](../docs/BUILD_SYSTEM.md).

## Independent operational tools

Install their dependencies with `uv pip install -e .` when needed:

```bash
python -m src.cli.rds_manager status
python -m src.cli.set_release show
python -m src.cli.db_admin --help
```

`src/intermine_builder/rds_provisioner.py` remains the implementation for RDS
administration. Provisioning, release editing, and database maintenance are
separate from routine build commands. Their existing configuration conventions
remain unchanged; the launcher's build configuration belongs in `docker/<mine>/.env`.

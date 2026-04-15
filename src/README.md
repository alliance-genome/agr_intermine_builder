# Host-Side Orchestration Layer

Python modules that run on the host machine (not inside Docker containers). These manage infrastructure, configuration, and multi-mine orchestration via the Docker Python SDK.

## Relationship to `docker/alliancemine/`

This `src/` layer and `docker/alliancemine/scripts/` serve different purposes:

- **`src/`** runs on the host — manages Docker containers, provisions RDS, sets release versions
- **`docker/alliancemine/scripts/`** runs inside containers — executes Gradle builds, downloads data, integrates sources

The 9.0.0 build used `docker/alliancemine/` directly via `docker compose`. The `src/` CLI tools are still useful for RDS management and release versioning.

## CLI Tools

```bash
# RDS management
python -m src.cli.rds_manager create
python -m src.cli.rds_manager status
python -m src.cli.rds_manager stop
python -m src.cli.rds_manager start

# Alliance release versioning
python -m src.cli.set_release show
python -m src.cli.set_release current
python -m src.cli.set_release 9.0.0

# Multi-mine build orchestration
python -m src.cli.build_mines build --mine alliancemine
python -m src.cli.build_mines list
```

## Modules

- `mine_builder.py` — Top-level orchestrator (Docker networks, images, containers)
- `docker_manager.py` — Docker container lifecycle via Python SDK
- `build_executor.py` — Runs build stages inside containers
- `config.py` — Aggregates configuration from environment variables
- `mine_config.py` — Mine and stage definitions (MineType, BuildStage enums)
- `rds_provisioner.py` — RDS instance provisioning
- `aws/` — Advanced RDS management (stub)

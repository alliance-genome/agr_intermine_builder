# Repository Guidelines

## Project Structure & Module Organization

- `src/intermine_builder/` contains host-side configuration, Docker orchestration, build execution, and RDS provisioning; `src/cli/` exposes command-line tools.
- `docker/<mine>/` contains mine-specific Dockerfiles, Compose configurations, build scripts, and properties templates. `docker/alliancemine/` is the primary AllianceMine build pipeline; `docker/intermine-tomcat-*` provides runtime images.
- `tests/` covers Python orchestration; shared fixtures live in `tests/conftest.py`.
- `scripts/` holds operational utilities, `patches/` upstream fixes, and `docs/` runbooks. Treat `legacy/` as reference material.

## Build, Test, and Development Commands

Run from the repository root in an activated Python 3.9+ virtual environment:

```bash
uv pip install -e '.[dev]'              # Install package and development tools
python -m src.cli.build_mines list      # List configured mines
pytest                                # Run tests with coverage reporting
black src/ tests/                      # Format Python
ruff check src/ tests/                 # Lint Python
mypy src/                             # Check types
```

For AllianceMine, enter `docker/alliancemine/`, copy `.env.example` to `.env`, and configure credentials:

```bash
docker compose build                                  # Build the image
docker compose run --rm alliancemine-builder build     # Run the full pipeline
```

Full builds require configured external services, substantial resources, and several hours. See `docs/RELEASE_PROCESS.md`.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Black and Ruff use 100-character lines; preserve Python 3.9 compatibility. Follow existing dataclass configuration patterns and keep host orchestration separate from container build logic.

## Testing Guidelines

Use pytest and pytest-cov. Name files `test_*.py` and functions `test_*`; reuse fixtures and mock Docker, AWS, and database interactions. Add regression tests for behavioral fixes. Run focused checks with `pytest tests/test_config.py`. Coverage of `src/` is reported automatically; no minimum percentage is configured.

## Commit & Pull Request Guidelines

Recent commits use descriptive, scope-prefixed subjects such as `docs: ...`, `scripts: ...`, and `builds: ...`. Keep commits focused. PRs should explain the problem, affected mines, validation performed, and any deployment or rollback steps. Link relevant issues and update affected runbooks.

## Configuration & Agent Checks

Keep credentials in untracked `.env` files; never commit secrets or database dumps. Verify the target database before schema builds and preserve persistent user-profile databases. Capture `project_build` and `gradlew integrate` output through `tee`.

Resolve aislop errors and fixable warnings; report remaining nonfixable warnings. Do not weaken rules or edit `.aislop/config.yaml` without consent.

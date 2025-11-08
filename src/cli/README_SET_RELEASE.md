# Alliance Release Version Manager

Set the AllianceMine release version from the Alliance FMS API or manually.

## Quick Start

```bash
# Set to current production release (recommended)
uv run python -m src.cli.set_release current

# Set to next upcoming release
uv run python -m src.cli.set_release next

# Set to specific version
uv run python -m src.cli.set_release 8.3.0

# Show current setting and available versions
uv run python -m src.cli.set_release show
```

## What It Does

This tool:
1. Fetches release version from Alliance FMS API (`https://fms.alliancegenome.org/api/releaseversion/`)
2. Updates `ALLIANCE_RELEASE` in the project root `.env` file
3. Provides clear feedback about what changed

The `ALLIANCE_RELEASE` value is then used by:
- Docker build process (baked into image)
- InterMine properties (`project.releaseVersion`)
- Web interface display
- Documentation and metadata

## Alliance FMS API Endpoints

### Current Release
```bash
curl https://fms.alliancegenome.org/api/releaseversion/current
```
Returns the current production release (e.g., 8.2.0).

### Next Release
```bash
curl https://fms.alliancegenome.org/api/releaseversion/next
```
Returns the next upcoming release (e.g., 8.3.0).

## Usage Examples

### Example 1: Update to Current Release

```bash
$ uv run python -m src.cli.set_release current

Current ALLIANCE_RELEASE: 8.1.0
New ALLIANCE_RELEASE:     8.2.0 (from Alliance API (current))

✅ Updated .env file: ALLIANCE_RELEASE=8.2.0

Next steps:
  cd docker/alliancemine-unified
  docker-compose build --build-arg ALLIANCE_RELEASE=8.2.0
  docker-compose up -d
```

### Example 2: Preview Changes (Dry Run)

```bash
$ uv run python -m src.cli.set_release next --dry-run

Current ALLIANCE_RELEASE: 8.2.0
New ALLIANCE_RELEASE:     8.3.0 (from Alliance API (next))

🔍 DRY RUN: Would update .env file (use without --dry-run to apply)
```

### Example 3: Show Current Settings

```bash
$ uv run python -m src.cli.set_release show

Current ALLIANCE_RELEASE: 8.2.0

Available from Alliance API:
  Current: 8.2.0
  Next:    8.3.0
```

### Example 4: Set Specific Version

```bash
$ uv run python -m src.cli.set_release 8.3.0

Current ALLIANCE_RELEASE: 8.2.0
New ALLIANCE_RELEASE:     8.3.0 (from manual input)

✅ Updated .env file: ALLIANCE_RELEASE=8.3.0

Next steps:
  cd docker/alliancemine-unified
  docker-compose build --build-arg ALLIANCE_RELEASE=8.3.0
  docker-compose up -d
```

## Options

### `--dry-run`

Preview what would be changed without modifying the `.env` file.

```bash
uv run python -m src.cli.set_release current --dry-run
```

## Version Format

Manual versions must follow the pattern: `X.Y.Z` (e.g., `8.2.0`, `8.3.0`)

Invalid examples:
- `8.2` (missing patch version)
- `v8.2.0` (no 'v' prefix)
- `8.2.0-beta` (no suffixes)

## Integration with Build Process

### Workflow

```bash
# 1. Set release version
uv run python -m src.cli.set_release current

# 2. Build Docker image (picks up version automatically)
cd docker/alliancemine-unified
docker-compose build

# 3. Run container
docker-compose up -d
```

The version is:
- Read from root `.env` during Docker build
- Passed as build argument to Dockerfile
- Set as environment variable in container
- Used in InterMine properties file

### Automated Builds

For CI/CD pipelines:

```bash
#!/bin/bash
set -e

# Always use latest current release
uv run python -m src.cli.set_release current

# Build and deploy
cd docker/alliancemine-unified
docker-compose build
docker-compose up -d
```

## Error Handling

### API Connection Failure

If the Alliance API is unreachable:
```
Error: Failed to fetch current release from https://fms.alliancegenome.org/api/releaseversion/current: Connection timeout
```

**Solution**: Use manual version or retry when network is available.

### Invalid Version Format

If providing a manual version in wrong format:
```
Error: Invalid version format '8.2'. Expected format: X.Y.Z (e.g., 8.3.0)
```

**Solution**: Use proper semantic version format (major.minor.patch).

### Missing .env File

If the root `.env` file doesn't exist:
```
Error updating .env: .env file not found at /path/to/agr_intermine_builder/.env
```

**Solution**: Create the `.env` file or run from correct directory.

## Implementation Details

### File Modified

- **Path**: `/path/to/agr_intermine_builder/.env`
- **Pattern**: `ALLIANCE_RELEASE=X.Y.Z`
- **Method**: Regex replacement preserving file structure

### API Response Format

```json
{
  "id": 325252,
  "releaseVersion": "8.2.0",
  "releaseDate": "2025-08-28T10:00:00.000+00:00",
  "defaultSchemaVersion": {
    "id": 236240,
    "schema": "1.0.2.5"
  }
}
```

Only the `releaseVersion` field is used.

## See Also

- [Alliance FMS API Documentation](https://fms.alliancegenome.org/)
- [Docker Build Guide](../../docker/alliancemine-unified/BUILD_GUIDE.md)
- [RDS Setup](../../RDS_SETUP.md)

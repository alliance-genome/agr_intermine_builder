# AllianceMine Database Versioning

This document describes the database versioning system for AllianceMine builds.

## Overview

AllianceMine uses versioned database names to allow multiple versions and iterations to coexist on the same RDS instance. This enables:

- Multiple release versions (8.2.0, 8.3.0, etc.)
- Patch/iteration builds within a release (8.3.0-1, 8.3.0-2)
- Test builds (8.3.0-test)
- Parallel development without database conflicts

## Database Naming Convention

Database names follow this pattern:
```
alliancemine_<RELEASE><SUFFIX>
alliancemine_profiles_<RELEASE><SUFFIX>
```

Where:
- `<RELEASE>` is the Alliance release version (e.g., `8.3.0`)
- `<SUFFIX>` is an optional version suffix (e.g., `-1`, `-patch1`, `-test`)

**Note**: Dots in version numbers are automatically converted to underscores in the actual PostgreSQL database names (e.g., `8.3.0` becomes `8_3_0`).

## Examples

| Configuration | Main Database | Profile Database |
|--------------|---------------|------------------|
| Release 8.3.0 (base) | `alliancemine_8_3_0` | `alliancemine_profiles_8_3_0` |
| Release 8.3.0, iteration 1 | `alliancemine_8_3_0-1` | `alliancemine_profiles_8_3_0-1` |
| Release 8.3.0, patch 1 | `alliancemine_8_3_0-patch1` | `alliancemine_profiles_8_3_0-patch1` |
| Release 8.3.0, test build | `alliancemine_8_3_0-test` | `alliancemine_profiles_8_3_0-test` |

## Configuration

### Using the Helper Script (Recommended)

The `set_db_version.py` script updates the `.env` file with the desired version suffix:

```bash
# Base version (no suffix)
python3 set_db_version.py

# First iteration
python3 set_db_version.py -1

# Second iteration
python3 set_db_version.py -2

# Patch version
python3 set_db_version.py -patch1

# Test build
python3 set_db_version.py -test
```

### Manual Configuration

Edit the `.env` file directly:

```bash
# Alliance release version
ALLIANCE_RELEASE=8.3.0

# Database version suffix (optional: -1, -2, -patch1, etc.)
# Leave empty for base version, or add suffix for iterations/patches
DB_VERSION_SUFFIX=-1
```

## Workflow Examples

### Initial Release Build

```bash
# Set up for base version
python3 set_db_version.py

# Rebuild container if needed
docker-compose build

# Start container and run build
docker-compose up -d
docker-compose exec alliancemine bash -c "cd /opt/intermine/alliancemine && ./gradlew clean buildDB"
```

This creates databases:
- `alliancemine_8_3_0`
- `alliancemine_profiles_8_3_0`

### Patch/Iteration Build

```bash
# Set suffix for first iteration
python3 set_db_version.py -1

# Restart container to pick up new database names
docker-compose down
docker-compose up -d

# Run build (will create new databases)
docker-compose exec alliancemine bash -c "cd /opt/intermine/alliancemine && ./gradlew clean buildDB"
```

This creates NEW databases:
- `alliancemine_8_3_0-1`
- `alliancemine_profiles_8_3_0-1`

The original `alliancemine_8_3_0` databases remain untouched.

### Test Build

```bash
# Set suffix for test
python3 set_db_version.py -test

# Restart and build
docker-compose down
docker-compose up -d
docker-compose exec alliancemine bash -c "cd /opt/intermine/alliancemine && ./gradlew clean buildDB"
```

This creates test databases:
- `alliancemine_8_3_0-test`
- `alliancemine_profiles_8_3_0-test`

## Database Management

### Listing Databases

```bash
docker-compose exec alliancemine psql -h $RDS_HOST -U $RDS_USER -d postgres -c "\l" | grep alliancemine
```

### Switching Between Versions

1. Update `.env` with desired version suffix
2. Restart container: `docker-compose down && docker-compose up -d`
3. The container will automatically connect to the specified database version

### Dropping Old Versions

```bash
# Connect to PostgreSQL
docker-compose exec alliancemine psql -h $RDS_HOST -U $RDS_USER -d postgres

# Drop old database version
DROP DATABASE "alliancemine_8_3_0-test";
DROP DATABASE "alliancemine_profiles_8_3_0-test";
```

## Best Practices

1. **Use Suffixes for Iterations**: When rebuilding the same release, use `-1`, `-2`, etc. to preserve the previous build

2. **Test Builds**: Use `-test` suffix for experimental builds that may be thrown away

3. **Patch Versions**: Use `-patch1`, `-patch2` for minor data fixes within a release

4. **Production Builds**: Use base version (no suffix) for official production releases

5. **Cleanup**: Regularly drop old test/iteration databases to save space

## RDS Storage Considerations

Each AllianceMine database can be quite large (30-100+ GB depending on data). Monitor RDS storage:

```bash
# Check database sizes
docker-compose exec alliancemine psql -h $RDS_HOST -U $RDS_USER -d postgres \
  -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database WHERE datname LIKE 'alliancemine%' ORDER BY datname;"
```

Increase RDS storage allocation if needed to accommodate multiple versions.

# Legacy Files

This folder contains deprecated code and configurations from the previous bash-based build system.

## ⚠️ Deprecated - Do Not Use

These files are **no longer maintained** and have been replaced by the Python-based build system in `src/intermine_builder/`.

## Contents

### old_bash_scripts/
Legacy bash scripts for building InterMines:
- `run_intermine_builder` - Old builder script
- `run_intermine_builder_bash` - Bash version
- `build_intermine_builder` - Build script
- `pull_images` - Image pulling script
- `docker_auth` - Docker authentication
- `start_services` - Service startup
- `mkdatadirs.sh` - Data directory creation
- `compare_templates_for_releases.py` - Template comparison

### old_docker_configs/
Previous Docker configurations:
- `intermine_all_in_one/` - Monolithic Docker setup
- `intermine_all_in_one_rds/` - All-in-one with RDS
- `intermine_builder_rds/` - Old builder with RDS
- `mines/` - Individual mine configs
- `local.docker-compose.yml` - Local compose file
- `dockerhub.docker-compose.yml` - DockerHub compose file
- `Makefile` - Old Makefile

### old_intermine_builder/
Previous InterMine builder implementation:
- `intermine_builder/` - Old builder directory
- `intermine_cdn/` - CDN configurations

### Service Directories
Old service configurations:
- `tomcat/` - Tomcat configs
- `solr/` - Solr configs
- `postgres/` - PostgreSQL configs
- `logs/` - Old log files

## Migration Path

If you need functionality from these legacy files:

1. **For building InterMines**: Use the new Python system
   ```bash
   python -m src.cli.build_mines build --mine alliancemine
   ```

2. **For Docker configurations**: See `docker/multi_mine_rds/`

3. **For documentation**: Read `QUICKSTART.md` and `BUILD_SYSTEM.md`

## Why These Were Replaced

The bash-based system had several limitations:
- ❌ Difficult to maintain and extend
- ❌ No progress tracking
- ❌ Limited error handling
- ❌ No status monitoring
- ❌ Hard to test
- ❌ Monolithic design

The new Python system provides:
- ✅ Modular, object-oriented architecture
- ✅ Real-time progress tracking
- ✅ Comprehensive error handling
- ✅ Status monitoring
- ✅ Type safety
- ✅ Testable components
- ✅ CLI and Python API

## Kept for Reference

These files are kept for:
- Historical reference
- Migration documentation
- Understanding previous architecture
- Potential data recovery

## When to Delete

This folder can be safely deleted after:
1. All mines successfully built with new system
2. All production deployments migrated
3. No dependencies on legacy configs
4. Team confirms no need for reference

---

**Recommendation**: Use the new Python build system documented in the root README and QUICKSTART.md

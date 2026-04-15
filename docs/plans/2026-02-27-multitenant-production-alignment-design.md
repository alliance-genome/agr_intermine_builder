# Design: Multi-Tenant Production Alignment

**Date**: 2026-02-27
**Branch**: `refactor/alliancemine-docker`
**Approach**: Clean & Ship (Approach A)

## Context

The multi-tenant Docker setup (Caddy proxy -> per-mine Tomcat containers on EC2) is now production. AllianceMineDev is the permanent dev instance. The codebase needs to be aligned with this reality.

The Python orchestration layer and Docker build container already target the correct architecture. The main gaps are: stale documentation, uncommitted work, hardcoded infrastructure values, no deployment automation, and legacy code cluttering the repo.

## Decisions

| Decision | Choice |
|----------|--------|
| Approach | Clean & Ship — no new abstractions, make existing code production-ready |
| Legacy code | Archive to git tag, remove from working tree |
| Unified Docker dirs | Keep but mark as deprecated |
| Documentation | Consolidate 12+ docs into 4 operational files + 1 reference |
| Deployment | New Python script for all mines (AllianceMine, WormMine, extensible) |
| Credentials | Preserved in docs/INFRASTRUCTURE_REFERENCE.md before any cleanup |

## Section 1: Codebase Cleanup

### Commit pending work
- `docker/alliancemine/scripts/extract_data.py` — FMS Snapshot API rewrite, ready to commit

### Archive legacy code
- Create git tag `archive/legacy-code` at current HEAD
- Remove `legacy/` directory from working tree
- Tag preserves access: `git show archive/legacy-code:legacy/`
- Contents being archived:
  - `legacy/multi_mine_rds/` — old multi-mine bash-based build
  - `legacy/old_bash_scripts/` — historical bash scripts
  - `legacy/old_docker_configs/` — old Docker setups (all-in-one, builder-rds, mines)
  - `legacy/old_intermine_builder/` — original builder code
  - `legacy/postgres/`, `legacy/solr/`, `legacy/tomcat/`, `legacy/config/`, `legacy/docs/`, `legacy/logs/`

### Mark unified dirs as deprecated
- Add deprecation notice to `docker/alliancemine-unified/README.md`
- Add deprecation notice to `docker/wormmine-unified/README.md`
- Note: "Superseded by docker/alliancemine/ (build-only) + multi-tenant deployment"

## Section 2: Deployment Script

### New file: `scripts/deploy.py`

**Usage:**
```bash
python3 scripts/deploy.py alliancemine           # Deploy one mine
python3 scripts/deploy.py wormmine               # Deploy another mine
python3 scripts/deploy.py --all                   # Deploy all mines
python3 scripts/deploy.py alliancemine --dry-run  # Preview actions
```

**Behavior:**
1. SSH into multi-tenant EC2 (`DEPLOY_HOST` env var or `--host` flag)
2. Pull latest Docker image for the specified mine from ECR
3. Restart the mine's container via docker-compose
4. Wait for health check (HTTP 200 on `/{mine}/service/version`)
5. Report success/failure with timing

**Configuration:**
- `DEPLOY_HOST` — EC2 address (required, no default — no hardcoded IPs)
- `DEPLOY_SSH_KEY` — SSH key path (default: `~/.ssh/AGR-ssl3.pem`)
- `AWS_ACCOUNT_ID` — for ECR registry URL construction
- `AWS_REGION` — defaults to `us-east-1`

**Dependencies:** Uses subprocess `ssh` — no paramiko dependency.

**Mine registry:** Built-in mapping of mine name -> port, image name, health check path. Extensible for future mines.

## Section 3: Documentation Consolidation

### Target structure (4 docs + 1 reference)

| File | Content | Source |
|------|---------|--------|
| `docs/QUICKSTART.md` | Getting started | Keep as-is |
| `docs/ARCHITECTURE.md` | System architecture, Docker setup, RDS topology | Merge: DOCKER_ARCHITECTURE, DEPLOYMENT_STRATEGY, architecture/ |
| `docs/DEPLOYMENT.md` | Deploy, update, manage mines on multi-tenant EC2 | Merge: MULTITENANT_DEPLOYMENT, BLUEGENES_MIGRATION, WORMMINE_MULTITENANT_SETUP, HTTPS_SETUP |
| `docs/RDS.md` | RDS provisioning, management, backup | Merge: RDS_INTEGRATION_NOTES, RDS_SETUP |
| `docs/INFRASTRUCTURE_REFERENCE.md` | All credentials, IPs, resource IDs | Already created |

### Archived to `docs/archive/`
- BLUEGENES_MIGRATION.md
- MULTITENANT_DEPLOYMENT.md
- WORMMINE_MULTITENANT_SETUP.md
- ALLIANCEMINE_HTTPS_SETUP.md
- TODO_HTTPS_SETUP.md
- RDS_INTEGRATION_NOTES.md
- RDS_SETUP.md
- DOCKER_ARCHITECTURE.md
- DEPLOYMENT_STRATEGY.md
- S3_DATA_TRANSFER.md
- Any other stale docs

### Ticket docs
- `tickets/` directory — keep as-is (operational history)

## Section 4: Config Parameterization

### Docker compose files
- Replace hardcoded `intermine-postgres.cmnnhlso7wdi.us-east-1.rds.amazonaws.com` with `${RDS_HOST}` in:
  - `docker/alliancemine/docker-compose.yml`
  - `docker/alliancemine-unified/docker-compose.yml`
  - `docker/wormmine-unified/docker-compose.yml`

### .env.example files
- Update all `.env.example` files to include complete env var list with placeholder values
- No real credentials in example files

### Scripts
- Audit `scripts/` for hardcoded IPs/credentials
- Replace with env var references where found

## Section 5: CLAUDE.md Update

Update project CLAUDE.md to reflect:
- Multi-tenant is production
- AllianceMineDev is permanent dev
- New deployment workflow
- Consolidated documentation structure
- Legacy code archived

## Out of Scope

- CI/CD pipeline (GitHub Actions) — future work
- Python orchestration layer refactoring — already targets correct architecture
- New mine onboarding — current extensibility is sufficient
- AllianceMine 8.3.1 build issues (broken project.xml, SGD source) — separate task

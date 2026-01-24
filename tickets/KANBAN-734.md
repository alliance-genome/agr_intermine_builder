# KANBAN-734: More Frequent Scheduled, Automated Rebuilds of AllianceMine

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-734

## Request

> Users are used to YeastMine data being more current, and since AllianceMine rebuilding is independent of Alliance production releases, we would like to have automated, more frequent regular builds of AllianceMine. We are requesting weekly rebuilds if that can be automated. Automated regeneration of Lists should also be part of this rebuild pipeline.

## Assessment

**Complexity:** Medium

**Related Tickets:** KANBAN-735 (Add checks to AllianceMine)

### Current State

- AllianceMine builds are triggered manually
- Build process takes 3-6 hours
- Lists are regenerated as part of the build process
- New multi-tenant architecture on EC2 (172.31.59.87) supports automated builds

### Implementation Plan

#### Option 1: Cron-based Weekly Build (Recommended)

Add a cron job on the multi-tenant EC2 instance:

```bash
# /etc/cron.d/alliancemine-weekly-build
# Run every Sunday at 2 AM EST
0 2 * * 0 root /opt/alliancemine/scripts/weekly_build.sh >> /var/log/alliancemine-build.log 2>&1
```

**Build script (`weekly_build.sh`):**
```bash
#!/bin/bash
set -e

LOG_DIR="/var/log/alliancemine"
BUILD_DATE=$(date +%Y%m%d)

echo "=== AllianceMine Weekly Build Started: $(date) ==="

# 1. Pull latest data from FMS
cd /opt/alliancemine
python3 download_data.py

# 2. Run full build
docker-compose -f docker-compose.build.yml run --rm alliancemine build

# 3. Regenerate lists
docker-compose exec alliancemine python3 /opt/scripts/regenerate_lists.py

# 4. Health check
curl -f http://localhost:9001/alliancemine/service/version || exit 1

# 5. Notify on completion
echo "Build completed: $(date)" | mail -s "AllianceMine Build $BUILD_DATE Complete" alliancemine-alerts@alliancegenome.org

echo "=== AllianceMine Weekly Build Completed: $(date) ==="
```

#### Option 2: GitHub Actions Scheduled Workflow

```yaml
# .github/workflows/weekly-build.yml
name: Weekly AllianceMine Build

on:
  schedule:
    - cron: '0 7 * * 0'  # Sunday 7 AM UTC (2 AM EST)
  workflow_dispatch:  # Manual trigger

jobs:
  build:
    runs-on: self-hosted
    steps:
      - name: Trigger build
        run: |
          ssh alliancemine@172.31.59.87 '/opt/alliancemine/scripts/weekly_build.sh'
```

### Components

1. **Data Download**: `download_data.py` fetches latest from FMS API
2. **Database Build**: Full InterMine build (~3-4 hours)
3. **List Regeneration**: Python script to populate predefined gene lists
4. **Health Check**: Verify webapp responds correctly
5. **Notifications**: Email/Slack on success/failure

### Risks

- Build failures during automated runs require monitoring
- Resource contention if other processes running
- Data inconsistency if FMS data not ready

### Mitigation

- Implement health checks (KANBAN-735)
- Add failure notifications
- Run during low-traffic window (Sunday 2 AM)
- Implement rollback capability

## Recommendation

Implement Option 1 (cron-based) as part of the multi-tenant deployment. This aligns with the existing infrastructure and doesn't require external CI/CD.

**Prerequisites:**
1. Complete KANBAN-735 (health checks) first
2. Test build script manually
3. Set up monitoring/alerting

## Ticket Response

Weekly automated builds can be implemented using a cron job on the multi-tenant EC2 instance. The build script will:

1. Download latest data from FMS
2. Run full InterMine build
3. Regenerate gene lists
4. Perform health checks
5. Send notifications

**Dependency:** KANBAN-735 (health checks) should be completed first to ensure automated builds can detect and report failures.

I can implement this once the multi-tenant architecture is stable and health checks are in place.

## Status

- [x] Document requirements
- [ ] Implement KANBAN-735 first (health checks)
- [ ] Create build script
- [ ] Test manual execution
- [ ] Add cron job
- [ ] Set up monitoring

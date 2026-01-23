# KANBAN-660: PostgreSQL 12 RDS Instance (user-intermine-db) EOL

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-660

## Request

> We apparently still have one PostgreSQL 12 RDS instance (user-intermine-db) that we should look into upgrading before it goes EOL and we start getting charged for Extended Support. I'd imagine that doing the upgrade itself would be relatively easy, but testing the changes to make sure nothing breaks on the Intermine side would be trickier.

## Current State

### RDS Instances Inventory

| Instance | PostgreSQL | Size | Storage | Purpose |
|----------|------------|------|---------|---------|
| `user-intermine-db` | **12.22** | db.t3.medium | 20 GB | Legacy user profiles (OLD) |
| `intermine-postgres` | 15.12 | db.t3.large | 500 GB | Multi-tenant (NEW) |

### What's on Each Instance

**user-intermine-db (PG 12):**
- Legacy user profile database for old EB-based AllianceMine
- Likely contains: `alliancemine_userprofile` or similar
- Used by: Old Elastic Beanstalk AllianceMine deployment

**intermine-postgres (PG 15):**
- Multi-tenant deployment (current production)
- Contains: `alliancemine_8_3_0`, `wormmine_final`, profile DBs
- Used by: Multi-tenant EC2 instance (172.31.59.87)

## Assessment

**Complexity:** Low

The `user-intermine-db` instance appears to be a **legacy artifact** from the old deployment architecture. The new multi-tenant system on `intermine-postgres` already has integrated user profile databases.

## Options

### Option 1: Shutdown (Recommended)

If the old EB-based AllianceMine is being decommissioned:

1. Verify no active connections to `user-intermine-db`
2. Take a final snapshot for archival
3. Stop/delete the instance
4. **Cost savings:** ~$25-50/month + avoided Extended Support charges

**Pros:**
- No upgrade work needed
- Reduces infrastructure complexity
- Cost savings

**Cons:**
- Need to confirm nothing else uses it

### Option 2: Upgrade to PG 15

If the instance is still needed:

1. Take snapshot of `user-intermine-db`
2. Upgrade via RDS console: 12 → 13 → 14 → 15 (or direct 12 → 15)
3. Test webapp connectivity
4. ~30-60 min downtime

**InterMine Compatibility:**
- InterMine 5.x supports PostgreSQL 12-16
- No code changes required
- HikariCP connection pooling works with all versions

**Testing Required:**
- Verify webapp starts and connects
- Test user login/saved queries/lists
- Check template queries work

### Option 3: Migrate Data to intermine-postgres

If user data needs to be preserved but old instance retired:

1. Dump user profile DB from `user-intermine-db`
2. Restore to `intermine-postgres` as `alliancemine_userprofile_legacy`
3. Update old EB config to point to new instance (if EB stays)
4. Shutdown `user-intermine-db`

## Recommendation

**Go with Option 1 (Shutdown)** if:
- Old EB AllianceMine is being rebuilt/retired
- User data can be migrated or is already on new instance

**Go with Option 2 (Upgrade)** if:
- Old EB must stay running with its own profile DB
- Quick fix needed before EOL deadline

## Timeline

- PostgreSQL 12 EOL: ~1 month (per ticket)
- Extended Support charges begin after EOL
- Upgrade/shutdown can be done in <1 day

## Ticket Response

The `user-intermine-db` (PG 12) is the legacy user profile database for the old EB-based AllianceMine. The new multi-tenant architecture already has integrated profile databases on `intermine-postgres` (PG 15).

**Recommendation: Shutdown instead of upgrade** if old EB is being decommissioned.

If upgrade is needed, InterMine is compatible with PG 12-16, so the upgrade is straightforward with minimal testing (verify webapp connects, user login works).

I can handle the upgrade/shutdown. Need confirmation on whether old EB AllianceMine is staying or going.

## Status

- [x] Identify instance and purpose
- [x] Document options
- [ ] Confirm old EB AllianceMine status
- [ ] Execute shutdown or upgrade

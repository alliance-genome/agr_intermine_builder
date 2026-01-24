# KANBAN-603: AllianceMine Lists All Empty

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-603

## Request

> The preloaded lists in AllianceMine are all empty - 0 genes for all of them. Please repopulate.

## Assessment

**Status:** Done

**Root Cause:** Predefined gene lists were not regenerated after a build, or list generation failed silently during the build process.

### Resolution

Lists were manually repopulated. This issue highlighted the need for:
1. Automated list regeneration as part of builds (KANBAN-734)
2. Health checks to detect empty lists (KANBAN-735)

### Related Tickets

- KANBAN-734: Automated rebuilds (includes list regeneration)
- KANBAN-735: Health checks (detects empty lists)

### Prevention

The new multi-tenant architecture includes:
1. List regeneration as part of the build pipeline
2. Health check scripts to verify list populations
3. Automated alerts if lists are empty

## Can Be Closed?

**YES** - Already marked as Done. Lists were repopulated and the underlying issue is addressed by KANBAN-734/735.

## Suggested Closure Comment

```
Lists have been repopulated. To prevent this issue from recurring:

1. KANBAN-734 will implement automated weekly rebuilds with list regeneration
2. KANBAN-735 will add health checks to detect empty lists early

These improvements are part of the new multi-tenant deployment architecture.
```

## Status

- [x] Lists repopulated
- [x] Root cause identified (missing list regeneration step)
- [ ] Permanent fix via KANBAN-734/735

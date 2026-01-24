# KANBAN-636: AllianceMine List Error

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-636

## Request

> From a user: Me and lab fellows are getting this error when trying to load the page, which prevents us to have access to specific organisms as S. cerevisiae. The tool is thus unusable, and the situation is very frustrating.
>
> https://www.alliancegenome.org/bluegenes/alliancemine/upload/input
>
> The pulldown does not show any organisms to select.

## Assessment

**Status:** Done

**Root Cause:** BlueGenes UI bug - the organism dropdown was making API calls that expected YeastMine-specific endpoints, causing failures on AllianceMine.

### Resolution

Fixed in BlueGenes version 7.5.0. The Alliance's custom BlueGenes Docker image includes this fix.

### Timeline

- **2024-11-18:** Issue reported
- **2024-12-03:** Test version with fix available
- **2024-12-24:** Fix released in production (BlueGenes 7.5.0)
- **2026-01-23:** Ticket marked as Done

### Comments from Ticket

> "Code change was implemented on version 7.5.0, and Alliance's BlueGene docker image doesn't have these issues."

### Related Tickets

- KANBAN-628: Same issue (organism toggle fails)

## Can Be Closed?

**YES** - Already marked as Done. The fix is deployed in production.

## Suggested Closure Comment

```
Fixed in BlueGenes version 7.5.0. The organism dropdown now correctly displays
all organisms available in AllianceMine. Users can select specific organisms
when uploading gene lists.

The fix is part of the Alliance's custom BlueGenes Docker image and has been
in production since December 2024.
```

## Status

- [x] Issue identified (BlueGenes UI bug)
- [x] Fix developed
- [x] Deployed to production (v7.5.0)
- [x] Verified working

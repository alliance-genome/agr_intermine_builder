# KANBAN-628: AllianceMine Organism Toggle Fails

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-628

## Request

> On https://www.alliancegenome.org/bluegenes/alliancemine/upload/input the Organism toggle fails to find any species.

## Assessment

**Status:** Done

**Root Cause:** Same as KANBAN-636 - BlueGenes UI bug where the organism dropdown was making API calls that expected YeastMine-specific endpoints.

### Resolution

Fixed in BlueGenes version 7.5.0. The Alliance's custom BlueGenes Docker image includes this fix.

### Timeline

- **2024-09-27:** Issue reported by David Shaw
- **2024-12-03:** Test version with fix available
- **2024-12-24:** Fix released in production (BlueGenes 7.5.0)
- **2026-01-23:** Ticket marked as Done

### Comments from Ticket

> "The fix was released on 7.4 and it's live on 7.5. One thing that needs more attention is when the EB re-starts it needs to get our Bluegenes container and not InterMine's, as the most updated is currently run by hand."

> "Code change was implemented in version 7.5.0"

### Related Tickets

- KANBAN-636: Same issue (list error with organism dropdown)

## Can Be Closed?

**YES** - Already marked as Done. The fix is deployed in production.

## Suggested Closure Comment

```
Fixed in BlueGenes version 7.5.0. The organism toggle now correctly displays
all available species when uploading gene lists.

This was the same underlying issue as KANBAN-636 and was resolved together.
```

## Status

- [x] Issue identified (BlueGenes UI bug)
- [x] Fix developed
- [x] Deployed to production (v7.5.0)
- [x] Verified working

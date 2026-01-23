# KANBAN-546: Display GO Version in AllianceMine

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-546

## Request

The AllianceMine should prominently display at least the version of GO loaded, and should ideally have the data upload date for other sources too, like YeastMine does.

Requirements:
1. Display GO version on homepage/data sources page
2. Attach GO version to enrichment widget results
3. Show version in tables and download headers

## Assessment

**Complexity:** Medium-High

The `GoConverter.java` (`alliancemine-bio-sources/go-annotation/src/main/java/org/intermine/bio/dataconversion/GoConverter.java`) doesn't capture GO version - it skips comment lines (line 252) which contain version info like:
```
!date-generated: 2024-03-28
!generated-by: GOC
```

### Implementation Phases

**Phase 1 - Capture GO Version (bio-sources change):**
```java
// In GoConverter.process(), extract version from header:
while ((line = br.readLine()) != null) {
    if (line.startsWith("!date-generated:")) {
        String goVersion = line.substring(17).trim();
        // Store in DataSet.version field
    }
    // ... existing code
}
```
Estimate: 1-2 days

**Phase 2 - Display in webapp:**
- Modify `begin.jsp` or header template to query and display DataSet version
- YeastMine likely stores this in `project.properties` or queries DataSet

Estimate: 1 day

**Phase 3 - Enrichment widget:**
- Modify widget JavaScript to include version in results header
- Requires changes to `intermine/webapp/src/main/webapp/js/enrichment/`

Estimate: 2-3 days

## Ticket Response

The GO annotation loader (`GoConverter.java` in alliancemine-bio-sources) currently skips the header lines that contain version info. Implementation requires:

1. **Modify GoConverter** to parse `!date-generated:` header and store in DataSet.version
2. **Webapp changes** to display version on homepage (similar to YeastMine)
3. **Widget changes** for enrichment results (more complex, JS modifications)

Estimate: Phase 1 (1-2 days), Phase 2 (1 day), Phase 3 (2-3 days)

Can implement in next release cycle. Should we prioritize Phase 1 first to at least capture the data?

## Status

- [ ] Phase 1: Capture GO version in bio-sources
- [ ] Phase 2: Display on webapp homepage
- [ ] Phase 3: Enrichment widget modifications

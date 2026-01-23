# KANBAN-663: Neo4j Retirement - AllianceMine Impact Assessment

**URL:** https://agr-jira.atlassian.net/browse/KANBAN-663

## Request

> With the upcoming move from Neo4j to CKG permanent store, need to determine how AllianceMine interacts with Neo4j and create a plan for moving those interactions to the persistent store.

## Assessment

**Complexity:** Low (for AllianceMine specifically)

### Current Data Flow Analysis

AllianceMine **does NOT have any direct dependencies on Neo4j**. The current architecture uses the FMS (File Management System) API as a data intermediary:

```
Neo4j → agr_java_software → FMS (S3 storage) → AllianceMine
                                    ↑
                            download_data.py
```

### Evidence

1. **Current Data Extraction (`download_data.py`)**
   - Uses FMS API at `https://fms.alliancegenome.org/api`
   - Downloads pre-built files from S3 storage
   - No Neo4j connection strings or queries in the codebase
   - Files downloaded: TSV, GAF, OBO, FASTA formats

2. **Bio-sources Code (`alliancemine-bio-sources/`)**
   - Grep for `neo4j`, `graphql`, `cypher`: **No matches**
   - All data converters read flat files (TSV, GAF, JSON, GFF)
   - Example: `AllianceGenesConverter.java` uses `FormattedTextParser.parseTabDelimitedReader()` - reads TSV files
   - No HTTP client code, no REST API calls, no graph database connections
   - `build.gradle` has no Neo4j dependencies

3. **AllianceMine project.xml Data Sources**
   All 30+ data sources fall into two categories:
   - **File-based**: Read from `/root/data/fms/` (FMS downloads) or `/root/data/intermine/` (local files)
   - **PostgreSQL**: SGD sources connect to `sgd` PostgreSQL database (not Neo4j)

   Examples:
   ```xml
   <!-- File-based from FMS -->
   <source name="alliance-genes" type="alliance-genes">
     <property name="src.data.dir" location="/root/data/genes"/>
   </source>

   <!-- PostgreSQL database (SGD) -->
   <source name="sgd" type="sgd">
     <property name="source.db.name" value="sgd"/>
   </source>
   ```

4. **AllianceMine Repository (`alliancemine/`)**
   - Grep for `neo4j`, `graphql`: **No matches** (only pygments lexer mappings in pip packages)
   - No Neo4j drivers or client libraries

5. **Legacy System (historical reference)**
   - `legacy/old_bash_scripts/run_data_extractor` shows historical Neo4j usage:
     ```bash
     -e NEO4J_HOST=stage.alliancegenome.org
     ```
   - This was used by `agr_java_software` container's `GeneExtractor`
   - **This code path is deprecated** - replaced by FMS API downloads

### Data Sources Inventory (from project.xml)

| Source Name | Type | Data Location | Format | Neo4j? |
|-------------|------|---------------|--------|--------|
| alliance-*-fasta | fasta | /root/data/fms/ | FASTA | No |
| do, go, eco, so | ontology | /root/data/fms/ | OBO | No |
| mmo, emapa, zfa, wbbt, fbbt | ontology | /root/data/fms/ | OBO | No |
| alliance-genes | alliance-genes | /root/data/genes/ | TSV | No |
| go-annotation | go-annotation | /root/data/fms/*.gaf | GAF | No |
| alliance-disease | alliance-disease | /root/data/fms/ | TSV | No |
| alliance-orthologs | alliance-orthologs | /root/data/fms/ | TSV | No |
| alliance-alleles | alliance-alleles | /root/data/fms/ | TSV | No |
| alliance-expression | alliance-expression | /root/data/fms/ | TSV | No |
| sgd | sgd | PostgreSQL DB | SQL | No |
| sgd-gff | sgd-gff | /root/data/intermine/gff | GFF3 | No |
| sgd-complexes | sgd-complexes | PostgreSQL DB | SQL | No |
| sgd-complementation-db | sgd-complementation-db | PostgreSQL DB | SQL | No |
| fungi/cgob/pombe-homologs | homologs | /root/data/intermine/ | TSV | No |

**Total: 0 Neo4j dependencies**

### Impact of Neo4j Retirement

**For AllianceMine: Zero direct impact**

The critical dependency is **upstream** - the `agr_java_software` extractors that generate files for FMS:
- `GeneExtractor` - queries Neo4j for gene data
- `FMSExtractor` - processes data for FMS storage

When Neo4j is retired:
1. The upstream file generation process will change
2. Files will come from the new CKG permanent store instead
3. **AllianceMine will continue to work unchanged** as long as:
   - FMS API continues to serve files in the same format
   - File naming conventions remain consistent
   - Data schema within files remains compatible

### Potential Concerns

1. **File Format Changes**: If the new CKG store produces files with different schemas or formats, the bio-sources converters may need updates.

2. **FMS API Changes**: If FMS endpoints change, `download_data.py` would need updates.

3. **Data Quality/Content**: Different data content from CKG vs Neo4j could affect downstream queries or templates.

## Recommendations

### No Action Required (for AllianceMine code)

AllianceMine is already insulated from the Neo4j → CKG migration through the FMS abstraction layer.

### Monitoring During Transition

1. **Validate File Formats**: When first CKG-sourced files are available, compare with current Neo4j-sourced files for schema compatibility.

2. **Test Build**: Run a full AllianceMine build with CKG-sourced data to verify all loaders work correctly.

3. **Verify Data Content**: Compare query results between builds using Neo4j vs CKG source data.

### Questions for Alliance Team

1. Will FMS API endpoints remain stable during the transition?
2. Are there any planned changes to the file formats stored in FMS?
3. Timeline for when CKG-sourced files will be available in FMS?

## Ticket Response

AllianceMine has **no direct Neo4j dependencies**. All data is consumed via the FMS API, which provides pre-generated flat files (TSV, GAF, OBO, etc.).

The historical `agr_java_software` extractors that connect to Neo4j are upstream of AllianceMine - they generate files that are stored in FMS, which AllianceMine then downloads.

**Impact: None** for AllianceMine code/infrastructure.

**Risk: Low** - As long as FMS continues serving files in compatible formats, the transition will be transparent to AllianceMine.

**Recommended Action**: Monitor file format compatibility during the transition period. No code changes anticipated.

## Status

- [x] Investigate Neo4j references in codebase
- [x] Analyze current data flow
- [x] Document file sources and dependencies
- [x] Assess impact and recommendations
- [ ] (Future) Validate build with CKG-sourced data when available

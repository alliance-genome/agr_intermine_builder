# AllianceMine Complete Build Process

## Overview

AllianceMine is an InterMine instance that integrates genomic data from multiple Model Organism Databases (MODs):
- WormBase (C. elegans)
- FlyBase (D. melanogaster)
- MGI (M. musculus)
- RGD (R. norvegicus)
- SGD (S. cerevisiae)
- ZFIN (D. rerio)
- Human data (Homo sapiens)

---

## Build Stages

### Stage 1: Environment Setup (5 minutes)

**What Happens:**
1. EC2 instance launches (r6i.2xlarge, 64GB RAM)
2. Environment variables configured:
   ```bash
   GRADLE_OPTS="-Xmx32g -Xms16g"
   JAVA_HOME="/usr/lib/jvm/java-1.8.0"
   MINE_NAME="alliancemine"
   ALLIANCE_RELEASE="8.2.0"
   ```
3. PostgreSQL connection established (RDS or local)
4. Solr endpoint verified
5. Tomcat availability checked

**Outputs:**
- Build environment ready
- Logging configured
- Directories created: `/root/build/`, `/root/data/`

---

### Stage 2: Repository Cloning (10 minutes)

**What Happens:**

#### 2.1: Clone InterMine Core (Optional)
```bash
git clone https://github.com/intermine/intermine \
  --branch master --depth 1
```
- Only if custom InterMine build needed
- Default: Use published InterMine JARs from Maven Central

#### 2.2: Clone AllianceMine
```bash
git clone https://github.com/alliance-genome/alliancemine \
  --branch master --depth 1
```

**Key Files:**
- `project.xml` - Defines data sources and integration order
- `project.properties` - Mine-specific settings
- `dbmodel/` - Data model definitions
- `webapp/` - Web application customization

#### 2.3: Clone AGR Bio-sources
```bash
git clone https://github.com/alliance-genome/agr_bio_sources \
  --branch master --depth 1
```

**Contains:**
- AGR-specific data parsers
- File format converters (VCF, GFF3, etc.)
- Integration adapters

**Outputs:**
- `/root/intermine/` (if custom build)
- `/root/alliancemine/`
- `/root/alliancemine-bio-sources/`

---

### Stage 3: Build InterMine Core (45 minutes) [Optional]

**What Happens:**

Build order (critical - dependencies matter):

```bash
cd /root/intermine

# 1. Plugin system
cd plugin
./gradlew clean install  # ~3 min

# 2. Core InterMine
cd ../intermine
./gradlew clean install  # ~15 min

# 3. Bio model extensions
cd ../bio
./gradlew clean install  # ~10 min

# 4. Bio data sources
cd sources
./gradlew clean install  # ~10 min

# 5. Post-processing modules
cd ../postprocess
./gradlew clean install  # ~7 min
```

**What Gets Built:**
- InterMine core libraries → `~/.m2/repository/org/intermine/`
- Bio model classes
- Source data parsers
- Post-processing tools

**Outputs:**
- Local Maven repository populated
- InterMine version: e.g., `5.0.0-SNAPSHOT`
- Bio version: e.g., `5.0.0-SNAPSHOT`

---

### Stage 4: Build Bio-sources (30 minutes)

**What Happens:**

```bash
cd /root/alliancemine-bio-sources
./gradlew clean install
```

**What Gets Built:**
- AGR gene source parser
- AGR allele source parser
- AGR disease annotation parser
- AGR phenotype parser
- Orthology data integrator
- Expression data parser
- GO annotation integrator

**Outputs:**
- Custom bio-sources installed to local Maven
- Ready for integration in Stage 6

---

### Stage 5: Configure AllianceMine (5 minutes)

**What Happens:**

#### 5.1: Update Solr Hostnames
```bash
# In keyword_search.properties
sed -i 's/localhost/stage-intermine-solr.alliancegenome.org/g' \
  alliancemine/dbmodel/resources/keyword_search.properties
```

#### 5.2: Update InterMine Versions (if custom build)
```bash
# In gradle.properties
sed -i 's/systemProp.imVersion=.*/systemProp.imVersion=5.0.0-SNAPSHOT/' \
  alliancemine/gradle.properties
```

#### 5.3: Create Mine Properties File
```bash
# ~/.intermine/alliancemine.properties
cat > ~/.intermine/alliancemine.properties <<EOF
# Database connections
db.production.datasource.serverName=postgres:5432
db.production.datasource.databaseName=alliancemine_db
db.production.datasource.user=postgres
db.production.datasource.password=***

db.userprofile-production.datasource.databaseName=alliancemine_profiles_db

# Tomcat deployment
webapp.deploy.url=http://tomcat:8080
webapp.manager=tomcat
webapp.password=tomcat

# Release version
project.releaseVersion=8.2.0
EOF
```

**Outputs:**
- Mine configured for target environment
- Properties file ready
- Database connections defined

---

### Stage 6: Data Integration (3-4 hours) ⚠️ **LONGEST STAGE**

**What Happens:**

This is the heart of the build. The `project_build` script orchestrates:

#### 6.1: Create Database Schema
```bash
./gradlew buildDB
```
- Creates `alliancemine_db` database
- Generates tables from data model
- Creates indexes and constraints
- **Duration:** ~15 minutes

#### 6.2: Load Data Sources (Sequential)

Based on `project.xml`, data sources are loaded in order:

```xml
<sources>
  <!-- 1. Core Gene Data -->
  <source name="agr-gene" type="agr-gene">
    <property name="src.data.dir" location="/data/agr/genes/"/>
  </source>

  <!-- 2. Alleles -->
  <source name="agr-allele" type="agr-allele">
    <property name="src.data.dir" location="/data/agr/alleles/"/>
  </source>

  <!-- 3. Disease Annotations -->
  <source name="agr-disease" type="agr-disease">
    <property name="src.data.dir" location="/data/agr/disease/"/>
  </source>

  <!-- 4. Phenotype Data -->
  <source name="agr-phenotype" type="agr-phenotype">
    <property name="src.data.dir" location="/data/agr/phenotype/"/>
  </source>

  <!-- 5. GO Annotations -->
  <source name="go-annotation" type="go-annotation">
    <property name="src.data.dir" location="/data/go/annotations/"/>
  </source>

  <!-- 6. Orthology -->
  <source name="orthology" type="orthology">
    <property name="src.data.dir" location="/data/orthology/"/>
  </source>

  <!-- 7. Expression Data -->
  <source name="expression" type="expression">
    <property name="src.data.dir" location="/data/expression/"/>
  </source>

  <!-- 8. Variants -->
  <source name="variants" type="vcf">
    <property name="src.data.dir" location="/data/variants/"/>
  </source>

  <!-- + More sources... -->
</sources>
```

**For Each Source:**
```bash
# 1. Download data (if not cached)
aws s3 cp s3://agr-data/8.2.0/genes/ /data/agr/genes/ --recursive

# 2. Parse and integrate
./gradlew integrate -Psource=agr-gene

# What this does:
#   - Parses JSON/TSV/VCF files
#   - Creates Java objects
#   - Stores in intermediate items database
#   - Merges duplicates
#   - Creates relationships
```

**Typical Source Timing:**
- `agr-gene`: 45 min (millions of genes × 7 organisms)
- `agr-allele`: 30 min
- `go-annotation`: 60 min (massive dataset)
- `orthology`: 40 min (cross-species comparisons)
- `variants`: 90 min (VCF files are huge)

**Memory Usage:**
- Peak: ~45GB RAM
- PostgreSQL: ~12GB shared_buffers
- JVM: ~28GB heap
- File cache: ~8GB

**Outputs:**
- `alliancemine_db` populated with data
- Intermediate items database created and merged
- Relationships established

---

### Stage 7: Post-processing (60 minutes)

**What Happens:**

After data loading, post-processing creates derived data:

```bash
./gradlew postprocess
```

**Post-processors Run:**

1. **create-references** (5 min)
   - Creates publication references
   - Links papers to genes/diseases

2. **do-sources** (10 min)
   - Populates data source metadata
   - Tracks data provenance

3. **create-location-overlap-index** (15 min)
   - Spatial index for genome positions
   - Enables fast region queries

4. **create-chromosome-locations-and-lengths** (5 min)
   - Chromosome metadata
   - Coordinate system setup

5. **transfer-sequences** (10 min)
   - DNA/protein sequences
   - FASTA data integration

6. **create-overlap-view** (5 min)
   - Materialized view for overlaps

7. **create-gene-flanking-features** (5 min)
   - Upstream/downstream regions

8. **populate-child-features** (5 min)
   - Gene → transcript → exon hierarchy

**Outputs:**
- Materialized views created
- Spatial indexes built
- Derived relationships populated

---

### Stage 8: Build Search Index (20 minutes)

**What Happens:**

```bash
./gradlew postprocess -Pprocess=create-search-index
```

**Process:**
1. Extract searchable fields from database
2. Generate Solr documents
3. POST to Solr endpoint
4. Solr indexes:
   - Gene symbols
   - Descriptions
   - Synonyms
   - Disease names
   - GO terms

**Outputs:**
- Solr core populated
- Autocomplete ready
- Full-text search enabled

---

### Stage 9: Build Webapp (15 minutes)

**What Happens:**

```bash
cd /root/alliancemine
./gradlew cargoRedeployRemote
```

**What Gets Built:**
1. **Compile webapp**
   - JSP templates
   - JavaScript/CSS assets
   - Java servlets

2. **Package WAR file**
   - `alliancemine.war` (~200MB)

3. **Deploy to Tomcat**
   - Upload to Tomcat manager
   - Tomcat unpacks WAR
   - Webapp starts

4. **Warm-up queries**
   - Execute sample queries
   - Pre-populate caches

**Outputs:**
- Webapp running at `http://tomcat:8080/alliancemine`
- API available at `/service/*`
- List pages functional

---

### Stage 10: Build User Profile Database (5 minutes)

**What Happens:**

```bash
./gradlew buildUserDB
```

**Creates:**
- `alliancemine_profiles_db` database
- User accounts table
- Saved queries table
- Lists (gene lists, etc.)
- Templates metadata

**Outputs:**
- User profile system ready
- Login/register functional

---

## Total Build Time Breakdown

| Stage | Duration | % of Total | Critical Path |
|-------|----------|------------|---------------|
| 1. Environment Setup | 5 min | 1% | ✓ |
| 2. Repository Cloning | 10 min | 2% | ✓ |
| 3. Build InterMine Core | 45 min | 10% | Optional |
| 4. Build Bio-sources | 30 min | 7% | ✓ |
| 5. Configure Mine | 5 min | 1% | ✓ |
| 6. **Data Integration** | **240 min** | **53%** | ✓ **BOTTLENECK** |
| 7. Post-processing | 60 min | 13% | ✓ |
| 8. Build Search Index | 20 min | 4% | ✓ |
| 9. Build Webapp | 15 min | 3% | ✓ |
| 10. Build User DB | 5 min | 1% | ✓ |
| **TOTAL** | **~7 hours** | **100%** | |

---

## Data Sources Details

### Alliance Data Sources

1. **AGR Gene Basic**
   - Source: `https://fms.alliancegenome.org/api/data/gene-basic/`
   - Format: JSON
   - Size: ~500MB
   - Records: ~500K genes

2. **AGR Alleles**
   - Source: `https://fms.alliancegenome.org/api/data/allele/`
   - Format: JSON
   - Size: ~2GB
   - Records: ~2M alleles

3. **AGR Disease Annotations**
   - Source: `https://fms.alliancegenome.org/api/data/disease/`
   - Format: JSON
   - Size: ~1GB
   - Records: ~500K associations

4. **GO Annotations**
   - Source: `http://geneontology.org/gene-associations/`
   - Format: GAF
   - Size: ~800MB
   - Records: ~5M annotations

5. **Orthology**
   - Source: `https://fms.alliancegenome.org/api/data/orthology/`
   - Format: JSON
   - Size: ~3GB
   - Records: ~10M ortholog pairs

6. **Expression Data**
   - Source: Multiple MODs
   - Format: Custom
   - Size: ~1.5GB

7. **Variants (VCF)**
   - Source: MOD-specific
   - Format: VCF
   - Size: ~20GB compressed
   - Records: ~100M variants

---

## Optimization Opportunities

### Current Bottlenecks

1. **Data Integration (53% of time)**
   - Sequential source loading
   - Single-threaded parsers
   - Large VCF processing

2. **Database Operations**
   - Frequent commits
   - Index building during load
   - Constraint checking

3. **Network I/O**
   - Downloading large files
   - No caching between builds

### Potential Improvements

1. **Parallel Source Loading**
   - Load independent sources concurrently
   - Could reduce Stage 6 from 4h → 2h

2. **Bulk Loading**
   - Use PostgreSQL COPY instead of INSERT
   - Disable indexes during load
   - Could save 30-45 minutes

3. **Data Caching**
   - Cache downloaded files in S3
   - Reuse unchanged data sources
   - Could save 15-30 minutes

4. **Memory Optimization**
   - Increase to 128GB instance for large datasets
   - Reduce GC pauses
   - Could save 10-20 minutes

---

## Other MOD Mines

### Similar Build Process

All MOD mines follow the same InterMine build pattern:

| Mine | Organism | Data Sources | Est. Build Time |
|------|----------|--------------|-----------------|
| **AllianceMine** | 7 species | 15+ sources | 7 hours |
| **WormMine** | C. elegans | 12 sources | 4 hours |
| **FlyMine** | D. melanogaster | 20+ sources | 6 hours |
| **MouseMine** | M. musculus | 15 sources | 5 hours |
| **RatMine** | R. norvegicus | 10 sources | 4 hours |
| **YeastMine** | S. cerevisiae | 12 sources | 3 hours |
| **ZebrafishMine** | D. rerio | 10 sources | 4 hours |

### Key Differences

1. **Data Volume**
   - Mouse/Human have more variants
   - Fly has more expression data

2. **Source Complexity**
   - Some MODs have custom formats
   - Different API structures

3. **Post-processing**
   - MOD-specific calculations
   - Custom reports

---

## Dependencies

### External Services

1. **Alliance FMS (File Management System)**
   - `https://fms.alliancegenome.org/`
   - Provides downloadable data files

2. **GO Consortium**
   - `http://geneontology.org/`
   - GO terms and annotations

3. **UniProt**
   - `https://www.uniprot.org/`
   - Protein sequences

4. **Solr**
   - Required for search functionality
   - Must be running during indexing

5. **Tomcat**
   - Target deployment server
   - Must accept manager deploy

### Database Requirements

- PostgreSQL 13+
- Minimum 100GB storage
- Recommended: 16GB shared_buffers
- Full ACID compliance needed

---

## Next Steps for Multi-MOD Support

To build **all MOD mines**, we need:

1. **Mine-specific configurations** for each MOD
2. **Parallel build capability** (build multiple mines concurrently)
3. **Shared database server** (multi-tenant setup)
4. **Tomcat multi-instance** (one port per mine)
5. **Build scheduling** (which mines to rebuild when)

Would you like me to design the multi-MOD architecture based on your vision diagram?

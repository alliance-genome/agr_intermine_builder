# AllianceMine Data Directory

This directory contains all data files needed for building AllianceMine.

## Download Script

Use the unified `download_data.py` script to download ALL required data:

```bash
# Download all data (current release)
python3 download_data.py

# Download next/upcoming release
python3 download_data.py --release-type next

# Dry run
python3 download_data.py --dry-run
```

**Downloads:**

1. **Alliance FMS API Data:**
   - Ontologies (GO, DO, ECO, MMO, anatomies, SO)
   - Disease associations (`DISEASE-ALLIANCE_COMBINED`)
   - Orthology data (`ORTHOLOGY-ALLIANCE_COMBINED`)
   - Allele data (`ALLELE_COMBINED`)
   - Expression data (`EXPRESSION_COMBINED`)
   - GO annotation (GAF) files for all organisms

2. **Genome FASTA Files from MOD sources:**
   - **WB** (C. elegans) - WormBase FTP
   - **FB** (Drosophila) - FlyBase FTP
   - **SGD** (S. cerevisiae) - SGD Downloads
   - **ZFIN** (Zebrafish) - Ensembl FTP
   - **MGI** (Mouse) - Ensembl FTP
   - **RGD** (Rat) - Ensembl FTP
   - **XB** (Xenopus) - Ensembl FTP

## Directory Structure

```
data/
├── fms/                          # Alliance FMS data files
│   ├── FASTA_*.fa*              # Genome sequences
│   ├── ONTOLOGY_*.obo.gz        # Ontology files (GO, DO, ECO, etc.)
│   ├── GAF_*.gaf.gz             # GO annotation files
│   ├── DISEASE-ALLIANCE_COMBINED.tsv.gz
│   ├── ORTHOLOGY-ALLIANCE_COMBINED.tsv.gz
│   ├── ALLELE_COMBINED.tsv.gz
│   ├── EXPRESSION_COMBINED.tsv.gz
│   └── ...
├── genes/                        # Gene data files (if needed)
└── intermine/                    # Additional InterMine data
    ├── ontology/
    ├── gff/
    ├── gff-utr/
    ├── db-utr/
    ├── yeast_orthologs/
    │   ├── fungidb/
    │   ├── CGOB/
    │   ├── C.glabrata/
    │   ├── pombe/
    │   └── homolog_genes/
    ├── protein-properties/
    └── protein-ntermini/
```

## Data Sources

### Alliance FMS API
- **Base URL:** https://fms.alliancegenome.org/api
- **Release info:** `/api/releaseversion/{current|next}`
- **File download:** `/api/datafile/by/{version}/{subtype}/{type}`

Files are retrieved via S3 URLs provided by the API.

### Model Organism Databases (MODs)

Direct downloads from authoritative sources:
- **WormBase:** Latest WormBase release (WS292+)
- **FlyBase:** Latest FlyBase release (r6.55+)
- **SGD:** S. cerevisiae reference genome (R64-4-1)
- **Ensembl:** Latest Ensembl release (111+) for vertebrates

## File Naming Conventions

### FASTA Files
- Format: `FASTA_{ORGANISM}.fa[.gz]`
- Examples: `FASTA_WB.fa.gz`, `FASTA_GRCm39.fa.gz`

### Ontology Files
- Format: `ONTOLOGY_{TYPE}_{VERSION}.obo.gz`
- Examples: `ONTOLOGY_GO_1.obo.gz`, `ONTOLOGY_DOID_1.obo.gz`

### GAF Files
- Format: `GAF_{ORGANISM}_{VERSION}.gaf.gz`
- Examples: `GAF_WB_1.gaf.gz`, `GAF_FB_1.gaf.gz`

### Alliance Combined Files
- Format: `{TYPE}-ALLIANCE_COMBINED_{VERSION}.tsv.gz`
- Examples: `DISEASE-ALLIANCE_COMBINED_7.tsv.gz`

## Docker Mount

This directory is mounted read-only into the AllianceMine container:

```yaml
volumes:
  - ./data:/root/data:ro
```

InterMine's `project.xml` references files at `/root/data/fms/` and `/root/data/intermine/`.

## Storage Requirements

- **Ontologies & Annotations:** ~500MB-1GB
- **Genome FASTA files:** ~4-8GB (varies by organism)
- **Total:** ~5-10GB depending on release

## Troubleshooting

### Files Not Found in FMS API

Some data types may not be available in all releases:
- FASTA files: Only C. elegans available via FMS (use `download_genomes.py` for others)
- ALLELE/EXPRESSION: May not exist for older releases

### Download Failures

If downloads fail:
1. Check internet connectivity
2. Verify FTP/HTTPS access (some networks block FTP)
3. Check disk space
4. Try again - transient network errors are common

### Skipped Files

Files are automatically skipped if they already exist. To re-download:
```bash
rm data/fms/FILENAME
python3 download_data.py
```

## See Also

- `QUICKSTART.md` - Complete setup instructions
- `download_data.py --help` - FMS downloader help
- `download_genomes.py --help` - Genome downloader help

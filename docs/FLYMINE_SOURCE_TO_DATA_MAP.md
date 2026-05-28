# FlyMine source → data correlation

Date: 2026-05-28
Status: audit complete; build-strategy decision pending (see bottom)
Task: #9

`intermine/flymine` `project.xml` (master, last upstream push 2022-08-26)
declares **67 sources**. Every one points at Cambridge's `/micklem/data/`
filesystem, which we do not have. This doc maps each source to where the
data can actually be obtained today: Alliance FMS, FlyBase FTP, an external
provider, or "FlyMine-curated / at-risk."

## Alliance FMS inventory (what we already have)

On AllianceMineDev `/root/data/fms/` (40 files). FlyBase-relevant:

| FMS file | Feeds FlyMine source |
|---|---|
| `GFF_FB.gff` | (genome features — but FlyMine uses chado-db, not GFF; see note) |
| `GAF_FB.gaf` | `go-annotation` |
| `ONTOLOGY_FBBT.obo` | `fly-anatomy-ontology` |
| `ONTOLOGY_GO.obo` | `go` |
| `ONTOLOGY_SO.obo` | `so` |
| `ONTOLOGY_DOID.obo` | `do` |
| `ONTOLOGY_ECO.obo` | (evidence codes, used by go-annotation) |
| `ORTHOLOGY-ALLIANCE_COMBINED.tsv` | `drosophila-homology` / orthology sources (Alliance-shape) |
| `DISEASE-ALLIANCE_COMBINED.tsv` | (no direct FlyMine source; AGR addition) |
| `EXPRESSION-ALLIANCE_COMBINED.tsv` | (maps loosely to `flybase-expression`) |
| `VARIANT-ALLELE_COMBINED.tsv` | (maps loosely to `flybase-alleles`) |

FMS does NOT have: FlyBase chado dumps, any fly FASTA, or any of the
FlyMine-curated datasets.

## Per-source correlation

### Bucket A — Alliance FMS covers it (≈7 sources)

| Source | Type | FMS file | Notes |
|---|---|---|---|
| `go` | go | `ONTOLOGY_GO.obo` | direct |
| `so` | so | `ONTOLOGY_SO.obo` | direct |
| `do` | do | `ONTOLOGY_DOID.obo` | direct |
| `fly-anatomy-ontology` | fly-anatomy-ontology | `ONTOLOGY_FBBT.obo` | direct |
| `go-annotation` | go-annotation | `GAF_FB.gaf` | flybase-scoped GAF |
| `psi-mi-ontology` | psi-mi-ontology | (fetch psi-mi.obo from OBO library) | small, stable URL |
| `fly-development-ontology` | fly-development-ontology | FBdv — not in FMS; fetch from OBO library | small |

### Bucket B — FlyBase FTP (`ftp.flybase.net/releases/`) (≈22 sources)

The 16 FASTA sources + alleles + homology + chado all come from FlyBase.
Confirm current release tag at build time (FTP was slow/timing out during
this audit; recent releases follow `FB20YY_NN`).

| Source | Type | FlyBase path (current release) |
|---|---|---|
| `chado-db-flybase-dmel` | chado-db | chado dump → load into local pg `flybase` DB (see chado note) |
| `chado-db-flybase-dpse` | chado-db | same chado DB |
| `chado-db-flybase-others` | chado-db | same chado DB |
| `flybase-dmel-gene-fasta` | fasta | `fasta/dmel-all-gene-*.fasta.gz` |
| `flybase-dmel-cds-fasta` | fasta | `fasta/dmel-all-CDS-*.fasta.gz` |
| `flybase-dmel-5prime-utr-fasta` | fasta | `fasta/dmel-all-five_prime_UTR-*` |
| `flybase-dmel-3prime-utr-fasta` | fasta | `fasta/dmel-all-three_prime_UTR-*` |
| `flybase-dpse-gene-fasta` / `-cds-` / `-5prime-` / `-3prime-` | fasta | dpse equivalents |
| `flybase-dana-gene-fasta` / `-cds-` | fasta | dana equivalents |
| `flybase-dsim-gene-fasta` / `-cds-` / `-5prime-` | fasta | dsim equivalents |
| `flybase-dvir-gene-fasta` / `-cds-` | fasta | dvir equivalents |
| `flybase-alleles` | flybase-alleles | `precomputed_files/alleles/...` |
| `drosophila-homology` | drosophila-homology | `precomputed_files/orthologs/dmel_orthologs_*` OR Alliance ORTHOLOGY file |

### Bucket C — External providers, still fetchable (≈18 sources)

| Source | Provider | Note |
|---|---|---|
| `uniprot` / `uniprot-fasta` / `uniprot-keywords` | UniProt (EBI) | large; per-proteome download |
| `interpro` / `protein2ipr` / `interpro-go` | InterPro (EBI) | protein2ipr `match_complete` is huge (>100 GB) |
| `reactome` | Reactome | pathway TSVs |
| `kegg-pathway` | KEGG | **license required** — KEGG FTP is subscription-only since 2011 |
| `omim` | OMIM | **license required** — registration + download key |
| `pdb` | RCSB PDB | per-organism structures |
| `psi-intact` | IntAct (EBI) | PSI-MI XML |
| `biogrid` | BioGRID | tab2 download |
| `treefam` | TreeFam | static, project effectively frozen |
| `orthodb` | OrthoDB | per-release flat files |
| `panther` | PANTHER | ftp; AGR also has panther via alliancemine-bio-sources |
| `homologene` | NCBI HomoloGene | **retired by NCBI in 2019** — last build data only |
| `ncbi-gene` | NCBI Gene | gene_info |
| `pubmed-gene` | NCBI | gene2pubmed |
| `hgnc` | HGNC | identifier set |
| `mgi-identifiers` | MGI | also via Alliance |
| `rgd-identifiers` | RGD | also via Alliance |
| `wormbase-identifiers` | WormBase | also via Alliance |

### Bucket D — FlyMine-curated / at-risk (≈12 sources)

These live ONLY under `/micklem/data/flymine/` — Cambridge-curated datasets
that may exist nowhere else now. Highest risk of being unrecoverable.

| Source | What it is | Risk |
|---|---|---|
| `arbeitman-items-xml` | Arbeitman developmental timecourse, pre-built InterMine items XML | high — pre-built items, format frozen |
| `bdgp-clone` | BDGP clone mappings | medium |
| `bdgp-insitu` | BDGP in-situ expression | medium |
| `long-oligo` | long oligo microarray design | high |
| `flyatlas` | FlyAtlas tissue expression | medium — original site may have data |
| `flyreg` | DNase footprint TFBS (REDfly) | medium — REDfly still online |
| `redfly` | REDfly CRMs | medium — REDfly still online |
| `fly-fish` | Fly-FISH subcellular localization | high |
| `drosdel-gff` | DrosDel deletion constructs (2008 snapshot) | high — dated 2008-03-19 |
| `miranda` | miRanda miRNA target predictions | medium |
| `affy-probes` | Affymetrix probe→gene mappings | medium |
| `flybase-expression` | modMine fly RNA-seq | high — modMine decommissioned |
| `flymine-static` | hand-curated static datasets + datasource metadata | high — FlyMine-internal |

### Bucket E — Framework sources, no external data (≈5 sources)

`entrez-organism`, `update-data-sources`, `update-publications`,
`fly-misc-cvterms`, (and `flymine-static` overlaps). These run off
already-loaded data or the NCBI eutils API; no data file to source.

## The chado-db problem

FlyMine's genome model (genes, transcripts, exons, chromosomes, locations)
comes from **3 `chado-db` sources** that read a live FlyBase **Chado
PostgreSQL** database, NOT from GFF. This is fundamentally different from
how AllianceMine/MouseMine load genome features (GFF converters).

Options:
1. Download the FlyBase chado dump (ftp.flybase.net `.../psql/`), restore
   into a local postgres `flybase` DB, point `source.db.name=flybase` at it.
   The chado dump is tens of GB.
2. Abandon chado-db; reload genome features from `GFF_FB.gff` (which FMS
   already has) using the Alliance GFF converter pattern. Requires writing
   a flybase-gff source like alliancemine's sgd-gff. Diverges from upstream
   FlyMine but aligns with how AGR loads every other MOD.

## Build-strategy decision (for the team)

Two realistic paths:

### Path 1 — Faithful FlyMine revival
Reproduce the full 67-source Cambridge build: stand up FlyBase chado pg,
fetch every FlyBase FTP + external dataset, recover or drop the at-risk
Bucket-D curated sets, refresh all the dead `/micklem/data/` URLs, and
likely bump the InterMine framework version. Estimate: weeks-to-months,
with several Bucket-D sources probably permanently lost.

### Path 2 — AGR-style slim FlyMine (recommended)
Build a FlyMine that mirrors how AllianceMine already ingests fly data:
- genome features from `GFF_FB.gff` (FMS)
- GO from `GAF_FB.gaf` + `ONTOLOGY_GO.obo` (FMS)
- anatomy from `ONTOLOGY_FBBT.obo` (FMS)
- orthology / disease / expression / alleles from the
  `*-ALLIANCE_COMBINED` FMS files
- proteins from UniProt, domains from InterPro (external, same as other mines)
- drop the Bucket-D curated FlyMine-specific datasets (or add later if a
  curator wants a specific one back)

This is ~12-15 working sources instead of 67, all from data we already
have or can fetch reliably, using converter patterns already proven in
alliancemine-bio-sources. Estimate: days, not months. Trade-off: not a
1:1 reproduction of historic FlyMine — loses the curated expression/probe
datasets — but produces a current, maintainable fly mine.

**Recommendation: Path 2.** Confirm with the team whether any Bucket-D
dataset is a hard requirement before committing.

## Next steps once a path is chosen

- Path 2: trim `docker/flymine/` project.xml to the slim source list, write
  `extract_data.sh` that pulls the FMS files (mirror
  `docker/alliancemine/scripts/extract_data.py`), wire UniProt/InterPro
  fetch, run the build (tasks #6 #7 #8).
- Path 1: stand up FlyBase chado pg first, then the full fetch matrix above.

## Cross-references

- `docs/SIBLING_SESSION_DOCKER_BUILD.md` — JCenter bintray trap (#6) + general build flow
- `docker/alliancemine/scripts/extract_data.py` — the FMS+S3 fetch pattern to mirror for Path 2
- `docker/flymine/` — the scaffold (image-build skeleton, project.xml unmodified)
- `intermine/flymine` project.xml — source of this audit (67 sources)

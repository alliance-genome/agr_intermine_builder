#!/usr/bin/env python3
"""
extract_data.py — FlyMine source data fetcher.

Mirrors the polyglot pattern from docker/alliancemine/scripts/extract_data.py:
   - Alliance FMS snapshot for cross-MOD ontologies + FlyBase-tagged feeds
   - FlyBase precomputed files from FB2026_01 (s3ftp.flybase.org)
   - Per-site bespoke downloads for the live Bucket-D sources

Per-source fetchers are gated by --only / --skip-source so the operator can
re-run a single source after fixing a parser without blowing away everything.

See:
   docs/FLYMINE_SOURCE_TO_DATA_MAP.md
   docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md
   docs/FBAB_FBBA_FLYMINE_IMPLEMENTATION_BRIEF.md

Default data root: /root/data/  (matches docker-compose.yml ./data:/root/data
bind-mount). Sources land in /root/data/<source>/ to match the project.xml
src.data.dir entries the sibling will rewrite on their side.

Run inside the flymine-builder container:
    python3 /root/scripts/extract_data.py --all
    python3 /root/scripts/extract_data.py --only flyatlas
    python3 /root/scripts/extract_data.py --skip-source fly-fish redfly
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA_ROOT = Path(os.environ.get("FLYMINE_DATA_ROOT", "/root/data"))
FB_RELEASE = os.environ.get("FB_RELEASE", "FB2026_01")
FB_BASE = f"https://s3ftp.flybase.org/releases/{FB_RELEASE}/precomputed_files"
FMS_API_BASE = os.environ.get("FMS_API_BASE", "https://fms.alliancegenome.org/api")
ALLIANCE_RELEASE_TYPE = os.environ.get("ALLIANCE_RELEASE_TYPE", "next")
# Browser-style UA — several Bucket-D sites 403 bare curl/python UA but serve
# anything that looks like a browser.
UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg):
    sys.stdout.write(f"[extract_data] {msg}\n")
    sys.stdout.flush()


def fetch_url(url, dest: Path, retries=3, backoff=5):
    """Download a URL to dest, retrying with backoff. Atomic via .part rename."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  skip (exists): {dest.name}")
        return dest
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(part, "wb") as out:
                    shutil.copyfileobj(resp, out, length=1 << 20)
            part.rename(dest)
            log(f"  ok: {dest.name} ({dest.stat().st_size:,} bytes)")
            return dest
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            log(f"  attempt {attempt}/{retries} failed: {e}")
            time.sleep(backoff * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


def ungz(gz_path: Path, dest: Path = None):
    """Decompress .gz alongside, leaving the original. Returns dest path."""
    dest = dest or gz_path.with_suffix("")
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  skip ungz (exists): {dest.name}")
        return dest
    with gzip.open(gz_path, "rb") as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out, length=1 << 20)
    log(f"  ungz: {dest.name}")
    return dest


# ---------------------------------------------------------------------------
# Alliance FMS sources
# ---------------------------------------------------------------------------


# (dataType, dataSubType, target_dir_relative, target_filename)
# Mirrors the alliancemine FILE_MAP but pruned to FB + cross-MOD files FlyMine
# actually consumes (per project.xml + flymine bio-source modules). Files are
# resolved through the FMS snapshot API and downloaded from the s3Url it
# returns. GZ files are unwrapped on the fly to match what InterMine loaders
# expect.
FMS_FILE_MAP = [
    # Cross-MOD combined TSVs (consumed by alliance-* sources)
    ("DISEASE-ALLIANCE", "COMBINED", "fms", "DISEASE-ALLIANCE_COMBINED.tsv"),
    ("ORTHOLOGY-ALLIANCE", "COMBINED", "fms", "ORTHOLOGY-ALLIANCE_COMBINED.tsv"),
    ("EXPRESSION-ALLIANCE", "COMBINED", "fms", "EXPRESSION-ALLIANCE_COMBINED.tsv"),
    ("VARIANT-ALLELE", "COMBINED", "fms", "VARIANT-ALLELE_COMBINED.tsv"),
    # Ontologies FlyMine integrates
    ("ONTOLOGY", "GO", "fms", "ONTOLOGY_GO.obo"),
    ("ONTOLOGY", "SO", "fms", "ONTOLOGY_SO.obo"),
    ("ONTOLOGY", "DOID", "fms", "ONTOLOGY_DOID.obo"),
    ("ONTOLOGY", "ECO", "fms", "ONTOLOGY_ECO.obo"),
    ("ONTOLOGY", "FBBT", "fms", "ONTOLOGY_FBBT.obo"),
    # FlyBase-tagged feeds (GFF_FB replaces chado-db per docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md)
    ("GAF", "FB", "fms", "GAF_FB.gaf"),
    ("GFF", "FB", "fms", "GFF_FB.gff"),
    # BGI for cross-MOD gene seed (consumed by alliance-genes via bgi_to_genes_tsv)
    ("BGI", "FB", "genes", "BGI_FB.json"),
]


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _fms_resolve_release():
    """Resolve the current Alliance release tag via the FMS API."""
    url = f"{FMS_API_BASE}/releaseversion/{ALLIANCE_RELEASE_TYPE}"
    log(f"  resolving release ({ALLIANCE_RELEASE_TYPE})...")
    data = _http_json(url)
    version = data.get("releaseVersion")
    if not version:
        raise RuntimeError(f"no releaseVersion in FMS reply: {data}")
    log(f"  Alliance release: {version}")
    return version


def _fms_load_snapshot(release):
    """Fetch the snapshot manifest and index by (dataType, dataSubType)."""
    url = f"{FMS_API_BASE}/snapshot/release/{release}"
    log(f"  loading snapshot manifest...")
    data = _http_json(url)
    if data.get("status") != "success":
        raise RuntimeError(f"snapshot API status: {data.get('status')}")
    files = data.get("snapShot", {}).get("dataFiles", [])
    log(f"  snapshot has {len(files)} files")
    index = {}
    for f in files:
        dt = f.get("dataType", {}).get("name", "")
        ds = f.get("dataSubType", {}).get("name", "")
        if dt and ds:
            index[(dt, ds)] = f
    return index


def fetch_fms_files():
    """Resolve Alliance release + download FMS snapshot files FlyMine needs.

    Order matches alliancemine's pattern (alliancemine/extract_data.py
    AllianceDataExtractor) — release_type defaults to "next" so dev builds
    pick up the latest pre-prod release. Override with ALLIANCE_RELEASE_TYPE
    or pin ALLIANCE_RELEASE for reproducible builds.
    """
    log("=== Alliance FMS snapshot ===")
    release_override = os.environ.get("ALLIANCE_RELEASE")
    try:
        release = release_override or _fms_resolve_release()
        index = _fms_load_snapshot(release)
    except (urllib.error.URLError, RuntimeError, ValueError) as e:
        log(f"  ERROR resolving FMS snapshot: {e}")
        return

    success, miss, fail = 0, 0, 0
    for dt, ds, target_dir, target_name in FMS_FILE_MAP:
        out_path = DATA_ROOT / target_dir / target_name
        if out_path.exists() and out_path.stat().st_size > 0:
            log(f"  skip (exists): {target_dir}/{target_name}")
            success += 1
            continue
        finfo = index.get((dt, ds))
        if not finfo:
            log(f"  MISS: {dt}/{ds} not in snapshot")
            miss += 1
            continue
        s3_url = finfo.get("s3Url", "")
        if not s3_url:
            log(f"  MISS: {dt}/{ds} has no s3Url")
            miss += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"  {dt}/{ds} -> {target_dir}/{target_name}")
        try:
            if s3_url.endswith(".gz"):
                tmp = out_path.with_suffix(out_path.suffix + ".gz")
                _download_to(s3_url, tmp)
                with gzip.open(tmp, "rb") as inp, open(out_path, "wb") as outp:
                    shutil.copyfileobj(inp, outp, length=1 << 20)
                tmp.unlink()
            else:
                _download_to(s3_url, out_path)
            mb = out_path.stat().st_size / (1024 * 1024)
            log(f"    OK ({mb:.1f} MB)")
            success += 1
        except (urllib.error.URLError, OSError) as e:
            log(f"    FAILED: {e}")
            fail += 1
    log(f"  FMS summary: {success} ok, {miss} miss, {fail} fail")


def _download_to(url, dest: Path):
    """Atomic-ish download via .part rename."""
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as resp:
        with open(part, "wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)
    part.rename(dest)


# ---------------------------------------------------------------------------
# FlyBase FB2026_01 precomputed files (FBab/FBba data + expression RPKM)
# ---------------------------------------------------------------------------


def fetch_flybase_precomputed():
    """Comprehensive FB precomputed_files fetcher.

    Strategy: pivot to FlyBase-as-canonical. Drops the Bucket-D dependency
    chain that needed leaf URLs from per-lab sites (REDfly, BDGP-insitu,
    fly-fish, etc.) and uses what FlyBase itself ships in
    `s3ftp.flybase.org/releases/<FB_RELEASE>/precomputed_files/`.

    Files are laid out under `data/flybase/<subdir>/` matching the source
    they feed. Unwraps .gz alongside so converters can read either form.
    """
    log(f"=== FlyBase precomputed ({FB_RELEASE}) ===")
    rel_suffix = FB_RELEASE.lower().replace("fb", "fb_")  # FB2026_01 -> fb_2026_01

    # (subdir on FB, [filenames], local sink under data/flybase/)
    # Filenames either fixed or with {rel} placeholder.
    FB_DIR_MAP = [
        # ---- aberrations (FBab) ----
        ("aberrations", ["aberration_experimental_gene_del_dup_data.{rel}.tsv.gz"], "aberrations"),
        # ---- alleles (FBal) ----
        ("alleles", [
            "allele_genetic_interactions_{rel}.tsv.gz",
            "dmel_classical_and_insertion_allele_descriptions_{rel}.tsv.gz",
            "fbal_to_fbgn_{rel}.tsv.gz",
            "genotype_phenotype_data_{rel}.tsv.gz",
            "split_system_combinations_{rel}.tsv.gz",
        ], "alleles"),
        # ---- chemicals (FBch) ----
        ("chemicals", ["chemicals_{rel}.tsv.gz", "chem_synonyms_{rel}.tsv.gz"], "chemicals"),
        # ---- collaborators (xrefs) ----
        ("collaborators", [
            "fbgn_uniprot_{rel}.tsv.gz",
            "gp_information.fb.gz",
            "pmid_fbgn_uniprot_{rel}.tsv.gz",
        ], "collaborators"),
        # ---- experimental tools ----
        ("experimental_tools", ["experimental_tool_data_{rel}.tsv.gz"], "experimental-tools"),
        # ---- genes (FBgn) — broad pull ----
        ("genes", [
            "automated_gene_summaries_{rel}.tsv.gz",
            "best_gene_summary_{rel}.tsv.gz",
            "curated_expression_{rel}.tsv.gz",
            "Dmel_enzyme_data_{rel}.tsv.gz",
            "dmel_gene_sequence_ontology_annotations_{rel}.tsv.gz",
            "dmel_unique_protein_isoforms_{rel}.tsv.gz",
            "fbgn_annotation_ID_{rel}.tsv.gz",
            "fbgn_exons2affy1_overlaps.tsv.gz",          # affy-probes equivalent
            "fbgn_exons2affy2_overlaps.tsv.gz",
            "fbgn_fbtr_fbpp_expanded_{rel}.tsv.gz",
            "gene_rpkm_report_{rel}.tsv.gz",              # flybase-expression
            "high-throughput_gene_expression_{rel}.tsv.gz",
            "scRNA-Seq_gene_expression_{rel}.tsv.gz",
        ], "genes"),
        # ---- GO ----
        ("go", ["gene_association.fb.gz"], "go"),
        # ---- human disease (FBhh) ----
        ("human_disease", [
            "disease_implicated_variants_{rel}.tsv.gz",
            "disease_model_annotations_{rel}.tsv.gz",
            "human_disease_models_{rel}.tsv.gz",
        ], "human-disease"),
        # ---- insertions (FBti) ----
        ("insertions", [
            "construct_maps.zip",
            "fu_gal4_table_{rel}.json.gz",
            "insertion_mapping_{rel}.tsv.gz",
        ], "insertions"),
        # ---- map conversion ----
        ("map_conversion", [
            "cyto-genetic-seq.tsv.gz",
            "cytotable.txt.gz",
            "genome-cyto-seq.txt.gz",
        ], "map-conversion"),
        # ---- metadata ----
        ("metadata", [
            "dataset_metadata_{rel}.tsv.gz",
            "scRNAseq_metadata_{rel}.json.gz",
        ], "metadata"),
        # ---- ontologies (FB-shipped) ----
        ("ontologies", [
            "chebi_{rel}.obo.gz",
            "doid.obo.gz",
            "fly_anatomy.obo.gz",
            "fly_development.obo.gz",
            "flybase_controlled_vocabulary.obo.gz",
            "flybase_stock_vocabulary.obo.gz",
            "gene_group_{REL}.obo.gz",                    # FB2026_01 uppercase variant
            "go-basic.obo.gz",
            "image.obo.gz",
        ], "ontologies"),
        # ---- orthologs ----
        ("orthologs", [
            "dmel_human_orthologs_disease_{rel}.tsv.gz",
            "dmel_paralogs_{rel}.tsv.gz",
        ], "orthologs"),
        # ---- reagents ----
        ("reagents", [
            "antibody_information.{rel}.tsv.gz",
            "cDNA_clone_data_{rel}.tsv.gz",              # replaces bdgp-clone
            "genomic_clone_data_{rel}.tsv.gz",
        ], "reagents"),
        # ---- references (PMIDs) ----
        ("references", [
            "entity_publication_{rel}.tsv.gz",
            "fbrf_pmid_pmcid_doi_{rel}.tsv.gz",
            "representative_publications_{rel}.tsv.gz",
        ], "references"),
        # ---- species ----
        ("species", ["organism_list_{rel}.tsv.gz"], "species"),
        # ---- stocks ----
        ("stocks", ["stocks_{REL}.tsv.gz"], "stocks"),
        # ---- synonyms ----
        ("synonyms", ["fb_synonym_{rel}.tsv.gz"], "synonyms"),
        # ---- transposons ----
        ("transposons", [
            "transgenic_construct_descriptions_{rel}.tsv.gz",
            "transposon_sequence_set.fa.gz",
            "transposon_sequence_set.gff.gz",
        ], "transposons"),
    ]

    rel_upper = FB_RELEASE  # FB2026_01
    success, miss, fail = 0, 0, 0
    for subdir, filenames, sink in FB_DIR_MAP:
        for fn_tpl in filenames:
            fn = fn_tpl.format(rel=rel_suffix, REL=rel_upper)
            url = f"{FB_BASE}/{subdir}/{fn}"
            dest = DATA_ROOT / "flybase" / sink / fn
            try:
                fetch_url(url, dest)
                success += 1
            except RuntimeError as e:
                log(f"  WARN {subdir}/{fn}: {e}")
                fail += 1
                continue
            if dest.suffix == ".gz":
                try:
                    ungz(dest)
                except OSError as e:
                    log(f"  WARN ungz {dest.name}: {e}")
    log(f"  FB precomputed summary: {success} ok, {fail} fail")


def fetch_flybase_chado_xml():
    """FlyBase Chado XML dumps — the canonical structured-data export.

    These bypass the live Chado DB connection entirely and feed the chado-db
    sources via XML rather than JDBC. Big files (genes alone is multi-GB)
    so fetched only on demand via --only flybase-chado-xml.
    """
    log(f"=== FlyBase chado-xml ({FB_RELEASE}) ===")
    base = f"https://s3ftp.flybase.org/releases/{FB_RELEASE}/chado-xml"
    # Subset to FlyMine-relevant Chado entities — skip the truly huge ones
    # (FBgn is ~1 GB compressed) unless the operator passes --include-fbgn.
    files = [
        "chado_FBab.xml.gz",  # aberrations
        "chado_FBal.xml.gz",  # alleles
        "chado_FBba.xml.gz",  # balancers
        "chado_FBch.xml.gz",  # chromosomes
        "chado_FBcl.xml.gz",  # clones
        "chado_FBgg.xml.gz",  # gene groups
        "chado_FBhh.xml.gz",  # human disease
        # FBgn is HUGE — pull on demand via fetch_flybase_chado_fbgn
    ]
    for fn in files:
        url = f"{base}/{fn}"
        dest = DATA_ROOT / "flybase" / "chado-xml" / fn
        try:
            fetch_url(url, dest)
        except RuntimeError as e:
            log(f"  WARN {fn}: {e}")


def fetch_flybase_chado_fbgn():
    """FBgn Chado XML — the huge gene dump (~1 GB compressed).

    Separated so the default chado-xml fetch doesn't always pull it.
    """
    log(f"=== FlyBase chado-xml FBgn (large) ===")
    url = f"https://s3ftp.flybase.org/releases/{FB_RELEASE}/chado-xml/chado_FBgn.xml.gz"
    dest = DATA_ROOT / "flybase" / "chado-xml" / "chado_FBgn.xml.gz"
    try:
        fetch_url(url, dest)
    except RuntimeError as e:
        log(f"  WARN: {e}")


# ---------------------------------------------------------------------------
# Bucket-D sources — DEPRECATED, replaced by FlyBase precomputed.
#
# Original plan (per docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md) was to pull
# per-lab live sites for flyatlas / DRSC RNAi / BDGP / fly-fish / REDfly /
# INDAC / DrosDel. Pivoted 2026-06-01: FlyBase is now the single source of
# truth, since per-lab sites had unstable URLs and required external
# coordination. Sources that have FB equivalents are reachable via
# fetch_flybase_precomputed(); the rest are dropped from the project.xml.
#
# Stubs kept so existing --only flags don't break; they log + no-op.
# ---------------------------------------------------------------------------


def _deprecated_bucket_d(name, replaced_by):
    log(f"=== {name} (deprecated) ===")
    log(f"  Replaced by FlyBase precomputed: {replaced_by}")
    log(f"  Run `--only flybase-precomputed` instead.")


def fetch_flyatlas():
    _deprecated_bucket_d("flyatlas", "no FB equivalent — drop the flyatlas source from project.xml")


def fetch_drsc_rnai():
    _deprecated_bucket_d("rnai", "no FB equivalent — drop the rnai source from project.xml")


def fetch_bdgp_clone():
    _deprecated_bucket_d("bdgp-clone", "flybase/reagents/{cDNA,genomic}_clone_data — replace bdgp-clone with new flybase-clones source")


def fetch_bdgp_insitu():
    _deprecated_bucket_d("bdgp-insitu", "flybase/genes/curated_expression — partial coverage")


def fetch_fly_fish():
    _deprecated_bucket_d("fly-fish", "no FB equivalent — drop the fly-fish source from project.xml")


def fetch_redfly():
    _deprecated_bucket_d("redfly", "no FB equivalent — drop the redfly source from project.xml")


def fetch_long_oligo():
    _deprecated_bucket_d("long-oligo", "no FB equivalent — drop the long-oligo source from project.xml")


def fetch_drosdel_gff():
    _deprecated_bucket_d("drosdel-gff", "no FB equivalent — drop the drosdel-gff source from project.xml")


# ---------------------------------------------------------------------------
# External providers (UniProt / InterPro / Reactome / NCBI / BioGRID / IntAct / HGNC)
# ---------------------------------------------------------------------------


def fetch_external_providers():
    """Light-weight external dataset fetchers.

    Strategy:
      - Start with the small / always-public TSVs (NCBI gene_info, HGNC, Reactome
        flat files) so the source modules that consume them can be exercised
        without waiting on the heavy stuff.
      - The big ones (UniProt full XML, IntAct psimitab.zip, BioGRID by-organism
        tab3, InterPro names) live in dedicated fetchers below and are gated
        through --only so the operator can pull them on demand.
    """
    log("=== external providers (small / always-public) ===")
    targets = [
        # (url, dest relative to DATA_ROOT, ungz)
        ("https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene_info.gz",
         "ncbi/current/gene_info.gz", True),
        ("https://ftp.ebi.ac.uk/pub/databases/genenames/hgnc/tsv/hgnc_complete_set.txt",
         "human/hgnc/current/hgnc_complete_set.txt", False),
        ("https://reactome.org/download/current/ReactomePathways.txt",
         "reactome/current/ReactomePathways.txt", False),
        ("https://reactome.org/download/current/ReactomePathwaysRelation.txt",
         "reactome/current/ReactomePathwaysRelation.txt", False),
        ("https://reactome.org/download/current/Ensembl2Reactome_All_Levels.txt",
         "reactome/current/Ensembl2Reactome_All_Levels.txt", False),
        ("https://reactome.org/download/current/UniProt2Reactome_All_Levels.txt",
         "reactome/current/UniProt2Reactome_All_Levels.txt", False),
        ("https://www.uniprot.org/docs/keywlist.xml",
         "uniprot/current/keywlist.xml", False),
        # NCBI gene2pubmed — consumed by the pubmed-gene InterMine source.
        # Sibling's project.xml points src.data.dir at /root/data/ncbi/pubmed/current/
        # (per FLYMINE_BUILDER_HANDOFF_2026_06_02 verification step).
        ("https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2pubmed.gz",
         "ncbi/pubmed/current/gene2pubmed.gz", True),
    ]
    for url, rel, gz in targets:
        dest = DATA_ROOT / rel
        try:
            fetch_url(url, dest)
            if gz and dest.exists():
                ungz(dest)
        except (RuntimeError, OSError) as e:
            log(f"  WARN {rel}: {e}")


def fetch_uniprot_drosophila():
    """Fetch UniProt swissprot+trembl XML filtered to Drosophila taxon (7227).

    Full Swiss-Prot is ~700 MB compressed; we don't need most of it. The
    InterMine uniprot source happily parses the filtered XML stream from
    rest.uniprot.org. Cache key in the URL keeps reruns idempotent.
    """
    log("=== uniprot (drosophila taxon filter) ===")
    base = "https://rest.uniprot.org/uniprotkb/stream"
    for review_flag, name in (("true", "uniprot_sprot_drosophila.xml.gz"),
                               ("false", "uniprot_trembl_drosophila.xml.gz")):
        url = f"{base}?compressed=true&format=xml&query=organism_id:7227+AND+reviewed:{review_flag}"
        dest = DATA_ROOT / "uniprot" / "current" / name
        try:
            fetch_url(url, dest)
            ungz(dest)
        except (RuntimeError, OSError) as e:
            log(f"  WARN {name}: {e}")


def fetch_uniprot_full():
    """Full UniProt swissprot (sprot) XML, plus the keyword list file.

    Covers all 13 organisms FlyMine's `uniprot.organisms` filter consumes
    (7227, 6239, 9606, 10090, 10116, 46245, 7230, 7244, 7217, 7220, 7222,
    7238, 559292). Skipping trembl by default — full trembl is multi-hundred
    GB; sprot at ~900 MB compressed is what curators care about.
    """
    log("=== uniprot full sprot + keywords ===")
    targets = [
        # url, dest relative, ungz
        ("https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/uniprot_sprot.xml.gz",
         "uniprot/current/uniprot_sprot.xml.gz", True),
        ("https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/keywlist.xml",
         "uniprot/current/keywlist.xml", False),
    ]
    for url, rel, gz in targets:
        dest = DATA_ROOT / rel
        try:
            fetch_url(url, dest)
            if gz:
                ungz(dest)
        except (RuntimeError, OSError) as e:
            log(f"  WARN {rel}: {e}")


def fetch_protein2ipr():
    """Fetch InterPro protein2ipr.dat from EBI.

    The .dat.gz is ~12 GB compressed; uncompressed is ~150 GB which would
    blow most filesystems. We deliberately leave it compressed and let
    the InterMine protein2ipr source handle decompression if it can — many
    bio-source readers gracefully accept .gz inputs.

    If the source needs uncompressed, the operator will see the integrate
    fail with a parse error; comment the source out of project.xml and
    re-fire project_build.
    """
    log("=== interpro protein2ipr (large, kept compressed) ===")
    url = "https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/protein2ipr.dat.gz"
    dest = DATA_ROOT / "interpro" / "match_complete" / "current" / "protein2ipr.dat.gz"
    try:
        fetch_url(url, dest)
        size_gb = dest.stat().st_size / (1024 ** 3)
        log(f"  staged at {dest} ({size_gb:.1f} GB compressed)")
    except (RuntimeError, OSError) as e:
        log(f"  WARN: {e}")


def fetch_intact():
    """IntAct psimitab dump. ~500 MB zip — extract to data/psi/intact/current/."""
    log("=== intact (psi-mitab) ===")
    url = "https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/intact.zip"
    dest = DATA_ROOT / "psi" / "intact" / "current" / "intact.zip"
    try:
        fetch_url(url, dest)
        # InterMine psi source reads the .txt inside; unzip in place.
        out_dir = dest.parent
        try:
            subprocess.run(["unzip", "-o", str(dest), "-d", str(out_dir)],
                           check=True, capture_output=True, text=True)
            log(f"  unzipped intact.zip into {out_dir}")
        except subprocess.CalledProcessError as e:
            log(f"  WARN unzip intact: {e.stderr.strip()[:200]}")
    except (RuntimeError, OSError) as e:
        log(f"  WARN: {e}")


def fetch_biogrid():
    """BioGRID per-organism tab3 archive — pin to a release or use Latest folder.

    The Drosophila file is what FlyMine reads; the by-organism archive ships
    all species in one zip but we only need a couple of files.
    """
    log("=== biogrid (latest tab3) ===")
    url = "https://downloads.thebiogrid.org/BioGRID/Release-Archive/LATEST/BIOGRID-ORGANISM-LATEST.tab3.zip"
    dest = DATA_ROOT / "biogrid" / "current" / "BIOGRID-ORGANISM-LATEST.tab3.zip"
    try:
        fetch_url(url, dest)
        out_dir = dest.parent
        try:
            subprocess.run(["unzip", "-o", str(dest), "-d", str(out_dir)],
                           check=True, capture_output=True, text=True)
            log(f"  unzipped biogrid archive")
        except subprocess.CalledProcessError as e:
            log(f"  WARN unzip biogrid: {e.stderr.strip()[:200]}")
    except (RuntimeError, OSError) as e:
        log(f"  WARN: {e}")


def fetch_interpro():
    """InterPro names + protein2ipr."""
    log("=== interpro ===")
    targets = [
        ("https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/names.dat",
         "interpro/current/names.dat", False),
        ("https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/ParentChildTreeFile.txt",
         "interpro/current/ParentChildTreeFile.txt", False),
        ("https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/interpro.xml.gz",
         "interpro/current/interpro.xml.gz", True),
        # protein2ipr is huge (~10 GB); fetched on demand only via --only interpro-protein2ipr
    ]
    for url, rel, gz in targets:
        dest = DATA_ROOT / rel
        try:
            fetch_url(url, dest)
            if gz:
                ungz(dest)
        except (RuntimeError, OSError) as e:
            log(f"  WARN {rel}: {e}")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


SOURCES = {
    "fms": fetch_fms_files,
    "flybase-precomputed": fetch_flybase_precomputed,
    "flybase-chado-xml": fetch_flybase_chado_xml,
    "flybase-chado-fbgn": fetch_flybase_chado_fbgn,
    "external": fetch_external_providers,
    "uniprot-drosophila": fetch_uniprot_drosophila,
    "uniprot-full": fetch_uniprot_full,
    "protein2ipr": fetch_protein2ipr,
    "intact": fetch_intact,
    "biogrid": fetch_biogrid,
    "interpro": fetch_interpro,
    # Deprecated Bucket-D stubs (replaced by FlyBase precomputed) — kept so
    # operator runs with --only flag don't crash; they log + no-op.
    "flyatlas": fetch_flyatlas,
    "rnai": fetch_drsc_rnai,
    "bdgp-clone": fetch_bdgp_clone,
    "bdgp-insitu": fetch_bdgp_insitu,
    "fly-fish": fetch_fly_fish,
    "redfly": fetch_redfly,
    "long-oligo": fetch_long_oligo,
    "drosdel-gff": fetch_drosdel_gff,
}


def main():
    global DATA_ROOT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="run every source")
    g.add_argument("--only", nargs="+", help=f"run only listed sources (choices: {sorted(SOURCES)})")
    ap.add_argument("--skip-source", nargs="+", default=[], help="skip listed sources")
    ap.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = ap.parse_args()

    DATA_ROOT = args.data_root
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    log(f"data root: {DATA_ROOT}")

    if args.only:
        sources_to_run = args.only
    else:
        sources_to_run = list(SOURCES.keys())
    sources_to_run = [s for s in sources_to_run if s not in args.skip_source]

    unknown = [s for s in sources_to_run if s not in SOURCES]
    if unknown:
        log(f"ERROR: unknown sources: {unknown}")
        sys.exit(2)

    for s in sources_to_run:
        log(f"\n>>> {s}")
        try:
            SOURCES[s]()
        except Exception as e:
            log(f"ERROR fetching {s}: {e}")
            # Continue with the others — partial success is useful
            continue

    log("\ndone.")


if __name__ == "__main__":
    main()

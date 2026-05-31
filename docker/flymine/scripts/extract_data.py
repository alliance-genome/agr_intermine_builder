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
FMS_API = os.environ.get("FMS_API_BASE", "https://fms.alliancegenome.org/api/snapshot")
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


def fetch_fms_files():
    """Cross-MOD ontologies + FlyBase-tagged FMS files (GO, GAF_FB, GFF_FB, FBBT, SO, DOID, ECO).
    These are the files the alliancemine build already pulls; reuse the existing
    AllianceMine S3 cache if present, else fetch via FMS API.
    """
    log("=== FMS files (ontologies + FlyBase) ===")
    fms_files = [
        "ONTOLOGY_GO.obo",
        "ONTOLOGY_SO.obo",
        "ONTOLOGY_DOID.obo",
        "ONTOLOGY_ECO.obo",
        "ONTOLOGY_FBBT.obo",
        "GAF_FB.gaf",
        "GFF_FB.gff",
        "ORTHOLOGY-ALLIANCE_COMBINED.tsv",
        "DISEASE-ALLIANCE_COMBINED.tsv",
        "EXPRESSION-ALLIANCE_COMBINED.tsv",
        "VARIANT-ALLELE_COMBINED.tsv",
    ]
    s3_cache = Path("/root/data/fms")  # AllianceMine sibling cache if present
    out_dir = DATA_ROOT / "fms"
    out_dir.mkdir(parents=True, exist_ok=True)
    for fn in fms_files:
        dest = out_dir / fn
        if dest.exists() and dest.stat().st_size > 0:
            log(f"  skip (exists): {fn}")
            continue
        cached = s3_cache / fn
        if cached.exists() and cached.is_file():
            shutil.copy2(cached, dest)
            log(f"  ok from cache: {fn} ({dest.stat().st_size:,} bytes)")
            continue
        # FMS API resolution would happen here; leave as TODO since the cache
        # is the typical path on AllianceMineDev. Operator can pre-sync.
        log(f"  MISS: {fn} — not in cache, FMS API fetch not yet implemented")


# ---------------------------------------------------------------------------
# FlyBase FB2026_01 precomputed files (FBab/FBba data + expression RPKM)
# ---------------------------------------------------------------------------


def fetch_flybase_precomputed():
    log(f"=== FlyBase precomputed ({FB_RELEASE}) ===")
    rel_suffix = FB_RELEASE.lower().replace("fb", "fb_")  # FB2026_01 -> fb_2026_01
    files = [
        # FBab/FBba — identity + relationships, per the implementation brief
        ("synonyms/fb_synonym_{rel}.tsv.gz", "fbab-fbba"),
        ("aberrations/aberration_experimental_gene_del_dup_data.{rel}.tsv.gz", "fbab-fbba"),
        # Expression RPKM — replaces dead modMine for the flybase-expression source
        ("genes/gene_rpkm_report_{rel}.tsv.gz", "flybase-expression"),
        ("genes/high-throughput_gene_expression_{rel}.tsv.gz", "flybase-expression"),
        ("genes/scRNA-Seq_gene_expression_{rel}.tsv.gz", "flybase-expression"),
        # Cytogenetic / map conversion (Phase 2 — aberration breakpoints)
        ("map_conversion/cyto-genetic-seq.tsv.gz", "fbab-fbba-phase2"),
    ]
    for path_tpl, sink in files:
        path = path_tpl.format(rel=rel_suffix)
        url = f"{FB_BASE}/{path}"
        dest = DATA_ROOT / "flybase" / sink / Path(path).name
        try:
            fetch_url(url, dest)
        except RuntimeError as e:
            log(f"  WARN: {e}")
            continue
        if dest.suffix == ".gz":
            try:
                ungz(dest)
            except OSError as e:
                log(f"  WARN ungz {dest.name}: {e}")


# ---------------------------------------------------------------------------
# Bucket-D live sources (per docs/FLYMINE_BUCKET_D_DECISIONS_2026_05_29.md)
# Per-site downloads. Homepages verified live on 2026-05-29 by sibling;
# exact file leaf paths to be confirmed at fetch time — placeholder URLs
# below; sibling supplies the leaf paths via reply.
# ---------------------------------------------------------------------------


def fetch_flyatlas():
    log("=== flyatlas (flyatlas.org) ===")
    # TODO sibling-confirm: exact download URL on flyatlas.org for the tissue
    # expression flat file. FlyMine's converter reads a per-tissue TSV.
    log("  TODO: per-tissue expression TSV — leaf URL pending sibling reply")


def fetch_drsc_rnai():
    log("=== rnai (DRSC / fgr.hms.harvard.edu) ===")
    # TODO sibling-confirm: DRSC download path for the screen results table.
    # FlyMine's converter reads `all_screens.tsv` (GenomeRNAi format historically);
    # DRSC has its own current format. See repo test fixture
    # flymine-bio-sources/rnai/src/test/resources/all_screens_genomeRNAi.txt
    log("  TODO: DRSC all-screens TSV — leaf URL + format pending sibling reply")


def fetch_bdgp_clone():
    log("=== bdgp-clone (fruitfly.org) ===")
    # TODO sibling-confirm: BDGP clone mappings file
    log("  TODO: BDGP clone TSV — leaf URL pending sibling reply")


def fetch_bdgp_insitu():
    log("=== bdgp-insitu (insitu.fruitfly.org CGI) ===")
    # TODO sibling-confirm: BDGP in-situ expression file. CGI-backed —
    # may need a parameterized download URL not a static file
    log("  TODO: BDGP in-situ data — endpoint pending sibling reply")


def fetch_fly_fish():
    log("=== fly-fish (fly-fish.ccbr.utoronto.ca) ===")
    # TODO sibling-confirm
    log("  TODO: fly-fish subcellular localization TSV — leaf URL pending")


def fetch_redfly():
    log("=== redfly (redfly.ccr.buffalo.edu) ===")
    # TODO sibling-confirm: REDfly CRM + TFBS downloads
    log("  TODO: REDfly CRM/TFBS TSV — leaf URL pending sibling reply")


def fetch_long_oligo():
    log("=== long-oligo (flychip.org.uk INDAC) ===")
    # TODO sibling-confirm: INDAC long-oligo design file
    log("  TODO: INDAC design TSV — leaf URL pending sibling reply")


def fetch_drosdel_gff():
    log("=== drosdel-gff (drosdel.org.uk, frozen 2008) ===")
    # TODO sibling-confirm: DrosDel GFF of deletion constructs
    log("  TODO: DrosDel GFF — leaf URL pending sibling reply")


# ---------------------------------------------------------------------------
# External providers (UniProt / InterPro / Reactome / NCBI / BioGRID / IntAct / HGNC)
# ---------------------------------------------------------------------------


def fetch_external_providers():
    log("=== external providers ===")
    # Placeholder — these are large + per-mine path conventions vary.
    # Pattern these per the alliancemine extract_data.py organization once the
    # FlyMine project.xml drops are finalized.
    log("  TODO: UniProt / InterPro / Reactome / IntAct / BioGRID / NCBI / HGNC — wire in Phase 2 finalize")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


SOURCES = {
    "fms": fetch_fms_files,
    "flybase-precomputed": fetch_flybase_precomputed,
    "flyatlas": fetch_flyatlas,
    "rnai": fetch_drsc_rnai,
    "bdgp-clone": fetch_bdgp_clone,
    "bdgp-insitu": fetch_bdgp_insitu,
    "fly-fish": fetch_fly_fish,
    "redfly": fetch_redfly,
    "long-oligo": fetch_long_oligo,
    "drosdel-gff": fetch_drosdel_gff,
    "external": fetch_external_providers,
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

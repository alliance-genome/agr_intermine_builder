#!/usr/bin/env python3
"""
AllianceMine Data Extraction Script

Downloads data files for InterMine integration in four passes:
  1. S3 sync of SGD/external data into /root/data/intermine/
  2. FMS snapshot download of 49 MOD files into /root/data/fms/ and /root/data/genes/
  3. Alliance API fetch via alliancemine-bio-sources/scripts/fetch_all.py
     into /root/data/api/ (SQLite cache in /root/data/api-cache/)
  4. Flat-file downloads for the InterMine-core protein + pathway sources
     added in Phase 6a/6b (UniProt, InterPro, KEGG, Reactome).
     Lands in /root/data/{uniprot,interpro,kegg,reactome}/current/.

The API fetch step requires /root/alliancemine-bio-sources/ to be present
(cloned by the Dockerfile via the BIO_SOURCES_BRANCH build arg) and
project.xml to reference /root/data/api/*.tsv from the new bio-source modules.

Usage:
    python3 extract_data.py                           # auto-resolve next release
    python3 extract_data.py --release-type current    # use current release
    python3 extract_data.py --release 9.0.0           # pin a specific version
    python3 extract_data.py --skip-fms                # rerun only API + flatfiles
    python3 extract_data.py --skip-api                # legacy FMS-only behaviour
    python3 extract_data.py --skip-flatfiles          # skip Phase-6a/6b downloads
"""

import gzip
import os
import shutil
import subprocess
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import urlopen, urlretrieve, Request
from urllib.error import HTTPError, URLError

FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("/root/data")

# SGD and external data stored in S3 (not available on FMS)
# Downloaded from s3://agr-db-backups/alliancemine/intermine/
S3_DATA_BUCKET = "agr-db-backups"
S3_DATA_PREFIX = "alliancemine/intermine/"

# ---------------------------------------------------------------------------
# Phase 6a/6b: flat-file download sources for InterMine-core bio-sources.
#
# Each entry is (url, target_dir_relative, target_filename). target_dir is
# relative to data_dir (e.g. "uniprot/current" -> /root/data/uniprot/current/).
# The InterMine bio-source loaders expect specific filenames at specific paths
# - changing these requires matching changes in alliancemine/project.xml.
# ---------------------------------------------------------------------------

# UniProt flat-file release. The uniprot bio-source reads the XML; the
# uniprot-keywords bio-source reads keywlist.xml; the fasta source reads
# uniprot_sprot_varsplic.fasta.
# TODO-verify: the InterMine uniprot loader version may want trembl too;
# if so, add a fourth tuple.
UNIPROT_RELEASE_BASE = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete"
UNIPROT_FILES: List[tuple] = [
    (f"{UNIPROT_RELEASE_BASE}/uniprot_sprot.xml.gz",
     "uniprot/current", "uniprot_sprot.xml.gz"),
    (f"{UNIPROT_RELEASE_BASE}/uniprot_sprot_varsplic.fasta.gz",
     "uniprot/current", "uniprot_sprot_varsplic.fasta.gz"),
    (f"{UNIPROT_RELEASE_BASE}/docs/keywlist.xml",
     "uniprot/current", "keywlist.xml"),
]

# InterPro release files. The interpro source reads interpro.xml; protein2ipr
# reads protein2ipr.dat (which lives in a separate match_complete subdirectory).
INTERPRO_RELEASE_BASE = "https://ftp.ebi.ac.uk/pub/databases/interpro/current_release"
INTERPRO_FILES: List[tuple] = [
    (f"{INTERPRO_RELEASE_BASE}/interpro.xml.gz",
     "interpro/current", "interpro.xml.gz"),
    # protein2ipr.dat is huge (~30 GB uncompressed); the loader can read .gz directly.
    (f"{INTERPRO_RELEASE_BASE}/protein2ipr.dat.gz",
     "interpro/match_complete/current", "protein2ipr.dat.gz"),
]

# KEGG pathway data is per-organism. The InterMine kegg-pathway loader expects
# both a {org}_gene_map.tab and a map_title.tab in the same directory.
# TODO-verify: KEGG's licensing may require a registered FTP account for some
# files - check that these public URLs still resolve before deploying.
KEGG_RELEASE_BASE = "https://rest.kegg.jp"
KEGG_ORGANISMS = ["sce", "hsa", "mmu", "rno", "cel", "dme", "dre"]  # taxa we ingest
KEGG_FILES: List[tuple] = [
    (f"{KEGG_RELEASE_BASE}/list/pathway", "kegg/current", "map_title.tab"),
] + [
    (f"{KEGG_RELEASE_BASE}/link/pathway/{org}", "kegg/current", f"{org}_gene_map.tab")
    for org in KEGG_ORGANISMS
]

# Reactome pathway data. The reactome bio-source reads the species-stratified
# Ensembl-to-Reactome TSV plus the pathways listing.
REACTOME_RELEASE_BASE = "https://reactome.org/download/current"
REACTOME_FILES: List[tuple] = [
    (f"{REACTOME_RELEASE_BASE}/Ensembl2Reactome_All_Levels.txt",
     "reactome/current", "Ensembl2Reactome_All_Levels.txt"),
    (f"{REACTOME_RELEASE_BASE}/ReactomePathways.txt",
     "reactome/current", "ReactomePathways.txt"),
    (f"{REACTOME_RELEASE_BASE}/ReactomePathwaysRelation.txt",
     "reactome/current", "ReactomePathwaysRelation.txt"),
]

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Mapping of FMS dataType/dataSubType to local filename expected by project.xml.
# Format: (fms_dataType, fms_dataSubType, target_dir_relative, target_filename)
# target_dir is relative to data_dir (e.g., "fms" -> /root/data/fms/)
#
# project.xml references these files in /root/data/fms/ and /root/data/genes/
FILE_MAP: List[tuple] = [
    # Combined Alliance data files (TSV)
    ("DISEASE-ALLIANCE", "COMBINED", "fms", "DISEASE-ALLIANCE_COMBINED.tsv"),
    ("ORTHOLOGY-ALLIANCE", "COMBINED", "fms", "ORTHOLOGY-ALLIANCE_COMBINED.tsv"),
    ("VARIANT-ALLELE", "COMBINED", "fms", "VARIANT-ALLELE_COMBINED.tsv"),
    ("EXPRESSION-ALLIANCE", "COMBINED", "fms", "EXPRESSION-ALLIANCE_COMBINED.tsv"),
    # Ontology files (OBO)
    ("ONTOLOGY", "DOID", "fms", "ONTOLOGY_DOID.obo"),
    ("ONTOLOGY", "GO", "fms", "ONTOLOGY_GO.obo"),
    ("ONTOLOGY", "ECO", "fms", "ONTOLOGY_ECO.obo"),
    ("ONTOLOGY", "MMO", "fms", "ONTOLOGY_MMO.obo"),
    ("ONTOLOGY", "EMAPA", "fms", "ONTOLOGY_EMAPA.obo"),
    ("ONTOLOGY", "ZFA", "fms", "ONTOLOGY_ZFA.obo"),
    ("ONTOLOGY", "WBBT", "fms", "ONTOLOGY_WBBT.obo"),
    ("ONTOLOGY", "FBBT", "fms", "ONTOLOGY_FBBT.obo"),
    ("ONTOLOGY", "HP", "fms", "ONTOLOGY_HP.obo"),
    ("ONTOLOGY", "MP", "fms", "ONTOLOGY_MP.obo"),
    ("ONTOLOGY", "PATO", "fms", "ONTOLOGY_PATO.obo"),
    ("ONTOLOGY", "SO", "fms", "ONTOLOGY_SO.obo"),
    # FASTA genome sequences
    ("FASTA", "WBcel235", "fms", "FASTA_WB.fa"),
    ("FASTA", "R627", "fms", "FASTA_R627.fa"),
    ("FASTA", "GRCz11", "fms", "FASTA_GRCz11.fa"),
    ("FASTA", "GRCm38", "fms", "FASTA_GRCm38.fa"),
    ("FASTA", "Rnor60", "fms", "FASTA_Rnor60.fa"),
    ("FASTA", "XT9.1", "fms", "FASTA_XT9.1.fa"),
    ("FASTA", "HUMAN", "fms", "FASTA_HUMAN.fa"),
    # GO annotation files (GAF per MOD)
    ("GAF", "FB", "fms", "GAF_FB.gaf"),
    ("GAF", "MGI", "fms", "GAF_MGI.gaf"),
    ("GAF", "RGD", "fms", "GAF_RGD.gaf"),
    ("GAF", "SGD", "fms", "GAF_SGD.gaf"),
    ("GAF", "WB", "fms", "GAF_WB.gaf"),
    ("GAF", "ZFIN", "fms", "GAF_ZFIN.gaf"),
    ("GAF", "HUMAN", "fms", "GAF_HUMAN.gaf"),
    ("GAF", "XB", "fms", "GAF_XB.gaf"),
    # BGI (Basic Gene Information) per MOD -> /root/data/genes/
    ("BGI", "FB", "genes", "BGI_FB.json"),
    ("BGI", "MGI", "genes", "BGI_MGI.json"),
    ("BGI", "RGD", "genes", "BGI_RGD.json"),
    ("BGI", "SGD", "genes", "BGI_SGD.json"),
    ("BGI", "WB", "genes", "BGI_WB.json"),
    ("BGI", "ZFIN", "genes", "BGI_ZFIN.json"),
    ("BGI", "HUMAN", "genes", "BGI_HUMAN.json"),
    ("BGI", "XBXL", "genes", "BGI_XBXL.json"),
    ("BGI", "XBXT", "genes", "BGI_XBXT.json"),
    # GFF files per MOD
    ("GFF", "FB", "fms", "GFF_FB.gff"),
    ("GFF", "MGI", "fms", "GFF_MGI.gff"),
    ("GFF", "RGD", "fms", "GFF_RGD.gff"),
    ("GFF", "SGD", "fms", "GFF_SGD.gff"),
    ("GFF", "WB", "fms", "GFF_WB.gff"),
    ("GFF", "ZFIN", "fms", "GFF_ZFIN.gff"),
    ("GFF", "HUMAN", "fms", "GFF_HUMAN.gff"),
    ("GFF", "XBXL", "fms", "GFF_XBXL.gff"),
    ("GFF", "XBXT", "fms", "GFF_XBXT.gff"),
]


class AllianceDataExtractor:
    """Downloads data files from Alliance FMS snapshot API."""

    def __init__(self, data_dir: Path, release: Optional[str] = None, release_type: str = "next"):
        self.data_dir = data_dir
        self.release = release
        self.release_type = release_type
        self.snapshot_files: Dict[tuple, dict] = {}

    def get_release_version(self) -> str:
        """Fetch release version from FMS API if not explicitly set."""
        if self.release:
            logger.info(f"Using specified release: {self.release}")
            return self.release

        url = f"{FMS_API_BASE}/releaseversion/{self.release_type}"
        logger.info(f"Fetching {self.release_type} release version from FMS...")

        try:
            with urlopen(url) as response:
                data = json.loads(response.read())
                version = data.get("releaseVersion")
                if not version:
                    raise ValueError("No releaseVersion in API response")
                logger.info(f"Alliance Release: {version} ({self.release_type})")
                self.release = version
                return version
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get release version: {e}")
            sys.exit(1)

    def load_snapshot(self) -> None:
        """Fetch the FMS snapshot for the release and index by (dataType, dataSubType)."""
        release = self.get_release_version()
        url = f"{FMS_API_BASE}/snapshot/release/{release}"
        logger.info(f"Fetching FMS snapshot for release {release}...")

        try:
            with urlopen(url) as response:
                data = json.loads(response.read())
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.error(f"Failed to fetch snapshot: {e}")
            sys.exit(1)

        if data.get("status") != "success":
            logger.error(f"Snapshot API returned status: {data.get('status')}")
            sys.exit(1)

        files = data.get("snapShot", {}).get("dataFiles", [])
        logger.info(f"Snapshot contains {len(files)} files")

        for f in files:
            dt = f.get("dataType", {}).get("name", "")
            ds = f.get("dataSubType", {}).get("name", "")
            if dt and ds:
                self.snapshot_files[(dt, ds)] = f

    def download_file(self, fms_type: str, fms_subtype: str, target_dir: str, target_name: str) -> bool:
        """Download a single file from the FMS snapshot."""
        key = (fms_type, fms_subtype)
        file_info = self.snapshot_files.get(key)

        if not file_info:
            logger.warning(f"  {fms_type}/{fms_subtype} not found in snapshot, skipping")
            return False

        s3_url = file_info.get("s3Url", "")
        if not s3_url:
            logger.warning(f"  No S3 URL for {fms_type}/{fms_subtype}")
            return False

        out_dir = self.data_dir / target_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / target_name

        logger.info(f"  {fms_type}/{fms_subtype} -> {target_dir}/{target_name}")

        try:
            # FMS files may be gzipped (.gz extension)
            is_gzipped = s3_url.endswith(".gz")

            if is_gzipped:
                # Download to temp, then decompress
                tmp_path = out_path.with_suffix(out_path.suffix + ".gz")
                urlretrieve(s3_url, tmp_path)
                with gzip.open(tmp_path, "rb") as f_in:
                    with open(out_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                tmp_path.unlink()
            else:
                urlretrieve(s3_url, out_path)

            size_mb = out_path.stat().st_size / (1024 * 1024)
            logger.info(f"    OK ({size_mb:.1f} MB)")
            return True

        except (HTTPError, URLError, OSError) as e:
            logger.warning(f"    FAILED: {e}")
            return False

    def download_s3_data(self) -> bool:
        """Download SGD/external data from S3 (ontologies, orthologs, protein data, etc.)."""
        target_dir = self.data_dir / "intermine"
        target_dir.mkdir(parents=True, exist_ok=True)

        s3_uri = f"s3://{S3_DATA_BUCKET}/{S3_DATA_PREFIX}"
        logger.info(f"Syncing SGD/external data from {s3_uri}...")

        try:
            result = subprocess.run(
                ["aws", "s3", "cp", s3_uri, str(target_dir), "--recursive"],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                logger.warning(f"  S3 sync failed: {result.stderr.strip()}")
                return False

            # Count downloaded files
            file_count = sum(1 for _ in target_dir.rglob("*") if _.is_file())
            total_size = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file())
            logger.info(f"  S3 sync complete: {file_count} files, {total_size / (1024**2):.1f} MB")
            return True

        except FileNotFoundError:
            logger.warning("  aws CLI not found, skipping S3 data download")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("  S3 sync timed out after 600s")
            return False

    def fetch_api_data(self) -> bool:
        """Run the alliancemine-bio-sources API fetcher orchestrator.

        Outputs nine TSVs into /root/data/api/ that project.xml's API-backed
        bio-source modules consume. The SQLite cache lives under
        /root/data/api-cache/ via ALLIANCE_FETCH_CACHE so reruns are fast.
        """
        api_dir = self.data_dir / "api"
        cache_dir = self.data_dir / "api-cache"
        api_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        orchestrator = Path("/root/alliancemine-bio-sources/scripts/fetch_all.py")
        if not orchestrator.exists():
            logger.error(f"  API fetcher orchestrator not found: {orchestrator}")
            logger.error("  Rebuild the image with BIO_SOURCES_BRANCH set to a branch "
                         "that includes scripts/fetch_all.py (Phase-5 work).")
            return False

        logger.info(f"Running API fetchers -> {api_dir}/")
        env = {**os.environ, "ALLIANCE_FETCH_CACHE": str(cache_dir)}
        try:
            subprocess.run(
                ["python3", str(orchestrator), "--out-dir", str(api_dir), "--verbose"],
                check=True,
                env=env,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"  API fetch failed (exit {e.returncode})")
            return False

    def _download_url(self, url: str, dest: Path) -> bool:
        """Generic URL -> file helper with one retry. Used by Phase 6 flatfile
        downloads. Returns True on success."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                logger.info(f"  GET {url}")
                urlretrieve(url, dest)
                size = dest.stat().st_size
                logger.info(f"  -> {dest} ({size:,} bytes)")
                return True
            except (HTTPError, URLError) as e:
                if attempt == 0:
                    logger.warning(f"  retry after error: {e}")
                    continue
                logger.error(f"  download failed: {e}")
                return False
        return False

    def download_flatfiles(self) -> Dict[str, str]:
        """Phase 6a/6b: download UniProt, InterPro, KEGG, Reactome flat files.

        Each group is independent; one source's failure doesn't block the
        others. The InterMine bio-source loaders for each will fail later
        during project_build if a critical file is missing - we report what
        succeeded so an operator can see in advance.
        """
        result = {}
        for label, files in (
            ("uniprot", UNIPROT_FILES),
            ("interpro", INTERPRO_FILES),
            ("kegg", KEGG_FILES),
            ("reactome", REACTOME_FILES),
        ):
            logger.info(f"=== Phase-6 flatfile download: {label} ({len(files)} files) ===")
            ok = 0
            for url, target_dir, target_name in files:
                dest = self.data_dir / target_dir / target_name
                if dest.exists() and dest.stat().st_size > 0:
                    logger.info(f"  cached: {dest}")
                    ok += 1
                    continue
                if self._download_url(url, dest):
                    ok += 1
            result[label] = f"{ok}/{len(files)}"
            logger.info(f"  {label}: {ok}/{len(files)} files present")
        return result

    def download_all(
        self,
        skip_fms: bool = False,
        skip_api: bool = False,
        skip_flatfiles: bool = False,
    ) -> Dict[str, int]:
        """Download all configured data files.

        Order matters: FMS first, since some API fetchers reuse FMS artefacts
        (BGI gene seeds, EXPRESSION-ALLIANCE per-MOD files, allele/disease seeds).
        Flat-file downloads are independent of both and run last so an FMS or
        API failure surfaces before we burn time on multi-GB UniProt/InterPro
        pulls.
        """
        stats = {"success": 0, "failed": 0, "skipped": 0, "total": len(FILE_MAP),
                 "api": "skipped", "flatfiles": "skipped"}

        if not skip_fms:
            # SGD/external data from S3
            self.download_s3_data()

            # FMS snapshot data
            self.load_snapshot()

            for fms_type, fms_subtype, target_dir, target_name in FILE_MAP:
                if (fms_type, fms_subtype) not in self.snapshot_files:
                    stats["skipped"] += 1
                    continue
                if self.download_file(fms_type, fms_subtype, target_dir, target_name):
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
        else:
            logger.info("Skipping FMS / S3 downloads (--skip-fms)")

        if not skip_api:
            stats["api"] = "ok" if self.fetch_api_data() else "failed"
        else:
            logger.info("Skipping API fetchers (--skip-api)")

        if not skip_flatfiles:
            stats["flatfiles"] = self.download_flatfiles()
        else:
            logger.info("Skipping Phase-6 flat-file downloads (--skip-flatfiles)")

        return stats

    def verify(self) -> None:
        """Print download summary."""
        total_size = 0
        file_count = 0
        for subdir in ["fms", "genes", "intermine", "api"]:
            d = self.data_dir / subdir
            if not d.exists():
                continue
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    size_mb = f.stat().st_size / (1024 * 1024)
                    total_size += f.stat().st_size
                    file_count += 1
                    logger.info(f"  {f.relative_to(self.data_dir)}: {size_mb:.1f} MB")

        logger.info("=" * 50)
        logger.info("Download Summary:")
        logger.info(f"  Files: {file_count}")
        logger.info(f"  Total size: {total_size / (1024**3):.2f} GB")
        logger.info(f"  Data directory: {self.data_dir}")
        logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Download AllianceMine data from FMS")
    parser.add_argument("--release", default=None, help="Specific release version (e.g., 9.0.0); omit to auto-resolve from FMS")
    parser.add_argument(
        "--release-type",
        choices=["next", "current"],
        default="next",
        help="Release type if --release not given (default: next)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--skip-fms",
        action="store_true",
        help="Skip FMS snapshot + S3 sync, run only the API fetchers",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip the Alliance API fetchers (FMS-only behaviour)",
    )
    parser.add_argument(
        "--skip-flatfiles",
        action="store_true",
        help="Skip the Phase-6 flat-file downloads (UniProt, InterPro, KEGG, Reactome)",
    )

    args = parser.parse_args()

    if args.skip_fms and args.skip_api and args.skip_flatfiles:
        logger.error("--skip-fms, --skip-api, and --skip-flatfiles together leave nothing to do")
        sys.exit(2)

    # Environment variable fallback
    release = args.release or os.environ.get("ALLIANCE_RELEASE")

    logger.info("=" * 50)
    logger.info("AllianceMine Data Extraction")
    logger.info("=" * 50)

    extractor = AllianceDataExtractor(args.data_dir, release=release, release_type=args.release_type)
    extractor.get_release_version()

    stats = extractor.download_all(skip_fms=args.skip_fms, skip_api=args.skip_api, skip_flatfiles=args.skip_flatfiles)
    extractor.verify()

    logger.info(
        f"FMS: {stats['success']} succeeded, {stats['failed']} failed, "
        f"{stats['skipped']} not in snapshot, out of {stats['total']}. "
        f"API fetch: {stats['api']}."
    )

    if stats["failed"] > 0:
        logger.warning("Some FMS downloads failed - build may have incomplete data")
        sys.exit(1)

    if stats["api"] == "failed":
        logger.error("API fetchers failed - the new API-backed bio-sources will be empty")
        sys.exit(1)

    if not args.skip_fms and stats["success"] == 0:
        logger.error("No FMS files downloaded")
        sys.exit(1)


if __name__ == "__main__":
    main()

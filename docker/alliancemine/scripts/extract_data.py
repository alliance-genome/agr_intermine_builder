#!/usr/bin/env python3
"""
AllianceMine Data Extraction Script

Downloads data files from Alliance FMS snapshot API for InterMine integration.
Uses the snapshot API to discover S3 URLs, downloads gzipped files, and
renames them to match alliancemine project.xml expectations.

Data is placed in /root/data/fms/ (main data) and /root/data/genes/ (BGI).

Usage:
    python3 extract_data.py --release 8.3.0
    python3 extract_data.py --release-type current
    python3 extract_data.py --release 8.3.0 --data-dir /root/data
"""

import gzip
import os
import shutil
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

    def download_all(self) -> Dict[str, int]:
        """Download all configured data files."""
        self.load_snapshot()

        stats = {"success": 0, "failed": 0, "skipped": 0, "total": len(FILE_MAP)}

        for fms_type, fms_subtype, target_dir, target_name in FILE_MAP:
            if (fms_type, fms_subtype) not in self.snapshot_files:
                stats["skipped"] += 1
                continue
            if self.download_file(fms_type, fms_subtype, target_dir, target_name):
                stats["success"] += 1
            else:
                stats["failed"] += 1

        return stats

    def verify(self) -> None:
        """Print download summary."""
        total_size = 0
        file_count = 0
        for subdir in ["fms", "genes"]:
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
    parser.add_argument("--release", default=None, help="Specific release version (e.g., 8.3.0)")
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

    args = parser.parse_args()

    # Environment variable fallback
    release = args.release or os.environ.get("ALLIANCE_RELEASE")

    logger.info("=" * 50)
    logger.info("AllianceMine Data Extraction")
    logger.info("=" * 50)

    extractor = AllianceDataExtractor(args.data_dir, release=release, release_type=args.release_type)
    extractor.get_release_version()

    stats = extractor.download_all()
    extractor.verify()

    logger.info(
        f"Results: {stats['success']} succeeded, {stats['failed']} failed, "
        f"{stats['skipped']} not in snapshot, out of {stats['total']}"
    )

    if stats["failed"] > 0:
        logger.warning("Some downloads failed - build may have incomplete data")
        sys.exit(1)

    if stats["success"] == 0:
        logger.error("No files downloaded")
        sys.exit(1)


if __name__ == "__main__":
    main()

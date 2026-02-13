#!/usr/bin/env python3
"""
AllianceMine Data Extraction Script

Downloads data files from Alliance FMS API for InterMine integration.
Populates /root/data/ with gene, allele, disease, phenotype, orthology,
and GO annotation files.

Usage:
    python3 extract_data.py --release 8.3.0
    python3 extract_data.py --release-type next
    python3 extract_data.py --release-type current --data-dir /root/data
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError

FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("/root/data")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Actual FMS data types used by AllianceMine project.xml
# Format: (data_type, subdirectory, filename)
FILE_SPECS: List[Tuple[str, str, str]] = [
    ("gene-basic", "genes", "GENE-BASIC_AGR.json"),
    ("allele", "alleles", "ALLELE_AGR.json"),
    ("disease", "disease", "DISEASE-ANNOTATION_AGR.json"),
    ("phenotype", "phenotype", "PHENOTYPE-ANNOTATION_AGR.json"),
    ("orthology", "orthology", "ORTHOLOGY-ALLIANCE_COMBINED.json"),
    ("go-annotation", "go", "GO-ANNOTATION_AGR.gaf"),
]


class AllianceDataExtractor:
    """Downloads data files from Alliance FMS API."""

    def __init__(self, data_dir: Path, release: Optional[str] = None, release_type: str = "next"):
        self.data_dir = data_dir
        self.release = release
        self.release_type = release_type
        self.data_dir.mkdir(parents=True, exist_ok=True)

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

    def download_file(self, file_type: str, subdir: str, filename: str) -> bool:
        """Download a data file from FMS using the direct URL pattern."""
        release = self.get_release_version()
        output_dir = self.data_dir / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # FMS direct download URL
        url = f"https://fms.alliancegenome.org/api/datafile/{file_type}/{release}/{filename}"
        logger.info(f"Downloading {file_type} -> {subdir}/{filename}")

        try:
            urlretrieve(url, output_path)
            size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"  Downloaded {filename} ({size_mb:.2f} MB)")
            return True
        except (HTTPError, URLError) as e:
            # Try the metadata API as fallback (gets S3 URL)
            logger.warning(f"  Direct download failed: {e}, trying metadata API...")
            return self._download_via_metadata(file_type, subdir, filename)

    def _download_via_metadata(self, file_type: str, subdir: str, filename: str) -> bool:
        """Fallback: fetch S3 URL from FMS metadata API."""
        release = self.release
        api_url = f"{FMS_API_BASE}/datafile/by/{release}/{file_type}/AGR"

        try:
            with urlopen(api_url) as response:
                file_info = json.loads(response.read())
                s3_url = file_info.get("s3Url")
                if not s3_url:
                    logger.warning(f"  No S3 URL for {file_type}, skipping")
                    return False

                output_dir = self.data_dir / subdir
                output_path = output_dir / filename
                urlretrieve(s3_url, output_path)

                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"  Downloaded via S3: {filename} ({size_mb:.2f} MB)")
                return True
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.warning(f"  Failed to download {file_type}: {e}")
            return False

    def download_all(self) -> Dict[str, int]:
        """Download all configured data files."""
        stats = {"success": 0, "failed": 0, "total": len(FILE_SPECS)}

        for file_type, subdir, filename in FILE_SPECS:
            if self.download_file(file_type, subdir, filename):
                stats["success"] += 1
            else:
                stats["failed"] += 1

        return stats

    def verify(self) -> None:
        """Print download summary."""
        files = [f for f in self.data_dir.rglob("*") if f.is_file()]
        total_size = sum(f.stat().st_size for f in files)

        logger.info("=" * 50)
        logger.info("Download Summary:")
        logger.info(f"  Files: {len(files)}")
        logger.info(f"  Total size: {total_size / (1024**3):.2f} GB")
        logger.info(f"  Data directory: {self.data_dir}")
        for f in sorted(files):
            size_mb = f.stat().st_size / (1024 * 1024)
            logger.info(f"    {f.relative_to(self.data_dir)}: {size_mb:.1f} MB")
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

    logger.info(f"Results: {stats['success']} succeeded, {stats['failed']} failed out of {stats['total']}")

    if stats["failed"] > 0:
        logger.warning("Some downloads failed - build may have incomplete data")
        sys.exit(1)


if __name__ == "__main__":
    main()

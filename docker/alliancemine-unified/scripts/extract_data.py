#!/usr/bin/env python3
"""
AllianceMine Data Extraction Script

Downloads data files from Alliance FMS API for InterMine integration.
Defaults to 'next' release for builds, use 'current' for testing.

Usage:
    python3 extract_data.py [--release-type next|current] [--data-dir /path]
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError


# Configuration
FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("/opt/intermine/data/fms")


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class AllianceDataExtractor:
    """Downloads data files from Alliance FMS API."""

    def __init__(self, data_dir: Path, release_type: str = "next"):
        self.data_dir = data_dir
        self.release_type = release_type
        self.release_version: Optional[str] = None

        # Create data directory
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_release_version(self) -> str:
        """Fetch release version from FMS API."""
        url = f"{FMS_API_BASE}/releaseversion/{self.release_type}"

        logger.info(f"Fetching {self.release_type} release version from FMS...")

        try:
            with urlopen(url) as response:
                data = json.loads(response.read())
                version = data.get("releaseVersion")

                if not version:
                    raise ValueError("No releaseVersion in API response")

                logger.info(f"Alliance Release: {version} ({self.release_type})")
                self.release_version = version
                return version

        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get release version: {e}")
            sys.exit(1)

    def download_datafile(self, data_subtype: str, data_type: str) -> bool:
        """
        Download a specific data file from FMS.

        Args:
            data_subtype: File subtype (e.g., 'FASTA', 'GFF', 'ONTOLOGY')
            data_type: Specific type (e.g., 'WB', 'FB', 'DOID')

        Returns:
            True if download successful, False otherwise
        """
        if not self.release_version:
            self.get_release_version()

        api_url = f"{FMS_API_BASE}/datafile/by/{self.release_version}/{data_subtype}/{data_type}"

        logger.info(f"Fetching {data_subtype}/{data_type} metadata...")

        try:
            with urlopen(api_url) as response:
                file_info = json.loads(response.read())

                s3_url = file_info.get("s3Url")
                if not s3_url:
                    logger.warning(f"No S3 URL found for {data_subtype}/{data_type}")
                    return False

                filename = Path(s3_url).name
                target_path = self.data_dir / filename

                logger.info(f"Downloading {filename}...")
                urlretrieve(s3_url, target_path)

                file_size = target_path.stat().st_size / (1024 * 1024)  # MB
                logger.info(f"✅ Downloaded {filename} ({file_size:.2f} MB)")
                return True

        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to download {data_subtype}/{data_type}: {e}")
            return False

    def download_all_files(self, file_specs: List[tuple]) -> Dict[str, int]:
        """
        Download all specified data files.

        Args:
            file_specs: List of (data_subtype, data_type) tuples

        Returns:
            Dict with download statistics
        """
        stats = {"success": 0, "failed": 0, "total": len(file_specs)}

        for data_subtype, data_type in file_specs:
            if self.download_datafile(data_subtype, data_type):
                stats["success"] += 1
            else:
                stats["failed"] += 1

        return stats

    def verify_downloads(self) -> None:
        """Verify downloaded files and print summary."""
        files = list(self.data_dir.glob("*"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        logger.info("=" * 50)
        logger.info("Download Summary:")
        logger.info(f"  Files downloaded: {len(files)}")
        logger.info(f"  Total size: {total_size / (1024**3):.2f} GB")
        logger.info(f"  Data directory: {self.data_dir}")
        logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Download AllianceMine data from FMS API"
    )
    parser.add_argument(
        "--release-type",
        choices=["next", "current"],
        default="next",
        help="Release type to download (default: next)"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data download directory (default: {DEFAULT_DATA_DIR})"
    )

    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("AllianceMine Data Extraction")
    logger.info("=" * 50)

    extractor = AllianceDataExtractor(args.data_dir, args.release_type)
    extractor.get_release_version()

    # TODO: Define actual file specifications from project.xml
    # This is a template - needs to be populated with actual FMS data types

    file_specs = [
        # Example format:
        # ("FASTA", "WB"),
        # ("FASTA", "FB"),
        # ("GFF", "WB"),
        # ("ONTOLOGY", "DOID"),
    ]

    if not file_specs:
        logger.warning("=" * 50)
        logger.warning("NO FILE SPECIFICATIONS DEFINED")
        logger.warning("Update extract_data.py with actual FMS data types")
        logger.warning("See project.xml for required data sources")
        logger.warning("=" * 50)
        return

    stats = extractor.download_all_files(file_specs)
    extractor.verify_downloads()

    logger.info(f"Downloads: {stats['success']} succeeded, {stats['failed']} failed")

    if stats['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

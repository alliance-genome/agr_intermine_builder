#!/usr/bin/env python3
"""
AllianceMine Data Downloader

Downloads required data files from Alliance FMS API for InterMine integration.
Uses the FMS API which provides S3 URLs for each file.

Usage:
    python3 download_data.py [--release-type next|current] [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError


# FMS API Configuration
FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("data")


# Data files required based on project.xml analysis
# Format: (data_subtype, data_type, target_subdir)
REQUIRED_FILES = [
    # FASTA genome files
    ("FASTA", "WB", "fms"),           # C. elegans
    ("FASTA", "FB", "fms"),           # Drosophila
    ("FASTA", "ZFIN", "fms"),         # Zebrafish
    ("FASTA", "MGI", "fms"),          # Mouse
    ("FASTA", "RGD", "fms"),          # Rat
    ("FASTA", "XB", "fms"),           # Xenopus

    # Ontology files
    ("ONTOLOGY", "DOID", "fms"),      # Disease Ontology
    ("ONTOLOGY", "GO", "fms"),        # Gene Ontology
    ("ONTOLOGY", "ECO", "fms"),       # Evidence & Conclusion Ontology
    ("ONTOLOGY", "MMO", "fms"),       # Measurement Method Ontology
    ("ONTOLOGY", "EMAPA", "fms"),     # Mouse Anatomy
    ("ONTOLOGY", "ZFA", "fms"),       # Zebrafish Anatomy
    ("ONTOLOGY", "WBBT", "fms"),      # Worm Anatomy
    ("ONTOLOGY", "FBBT", "fms"),      # Fly Anatomy
    ("ONTOLOGY", "SO", "fms"),        # Sequence Ontology

    # Alliance combined data files
    ("DISEASE-ALLIANCE", "COMBINED", "fms"),
    ("ORTHOLOGY-ALLIANCE", "COMBINED", "fms"),
    ("ALLELE", "COMBINED", "fms"),
    ("EXPRESSION", "COMBINED", "fms"),

    # GO Annotations (organism-specific)
    ("GAF", "WB", "fms"),
    ("GAF", "FB", "fms"),
    ("GAF", "ZFIN", "fms"),
    ("GAF", "MGI", "fms"),
    ("GAF", "RGD", "fms"),
    ("GAF", "SGD", "fms"),
    ("GAF", "XB", "fms"),
]


def create_directory_structure(data_dir: Path) -> None:
    """Create the complete directory structure for data files."""
    print("\n📁 Creating directory structure...")

    directories = [
        data_dir / "fms",
        data_dir / "genes",
        data_dir / "intermine" / "ontology",
        data_dir / "intermine" / "gff",
        data_dir / "intermine" / "gff-utr",
        data_dir / "intermine" / "db-utr",
        data_dir / "intermine" / "yeast_orthologs" / "fungidb",
        data_dir / "intermine" / "yeast_orthologs" / "CGOB",
        data_dir / "intermine" / "yeast_orthologs" / "C.glabrata",
        data_dir / "intermine" / "yeast_orthologs" / "pombe",
        data_dir / "intermine" / "yeast_orthologs" / "homolog_genes",
        data_dir / "intermine" / "protein-properties",
        data_dir / "intermine" / "protein-ntermini",
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"   ✅ {directory.relative_to(data_dir.parent)}")

    print(f"\n✅ Directory structure created at: {data_dir.absolute()}")


def get_release_version(release_type: str = "next") -> str:
    """Fetch release version from FMS API."""
    url = f"{FMS_API_BASE}/releaseversion/{release_type}"

    print(f"\n📋 Fetching {release_type} release version from FMS...")

    try:
        with urlopen(url) as response:
            data = json.loads(response.read())
            version = data.get("releaseVersion")

            if not version:
                raise ValueError("No releaseVersion in API response")

            print(f"   Alliance Release: {version} ({release_type})")
            return version

    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"❌ Failed to get release version: {e}")
        sys.exit(1)


def download_datafile(
    release_version: str,
    data_subtype: str,
    data_type: str,
    data_dir: Path,
    target_subdir: str,
    dry_run: bool = False
) -> bool:
    """
    Download a specific data file from FMS API.

    Args:
        release_version: Alliance release version (e.g., "8.3.0")
        data_subtype: File subtype (e.g., 'FASTA', 'ONTOLOGY')
        data_type: Specific type (e.g., 'WB', 'DOID')
        data_dir: Base data directory
        target_subdir: Subdirectory to save file in (e.g., 'fms', 'genes')
        dry_run: If True, don't actually download

    Returns:
        True if download successful, False otherwise
    """
    api_url = f"{FMS_API_BASE}/datafile/by/{release_version}/{data_subtype}/{data_type}"

    try:
        with urlopen(api_url) as response:
            file_list = json.loads(response.read())

            # API returns a list of file entries (one per release)
            # Get the first entry which contains the file metadata
            if not file_list or len(file_list) == 0:
                print(f"   ⚠️  No files found for {data_subtype}/{data_type}")
                return False

            file_info = file_list[0]

            # Try s3Url first, fallback to stableURL
            s3_url = file_info.get("s3Url") or file_info.get("stableURL")
            if not s3_url:
                print(f"   ⚠️  No download URL found for {data_subtype}/{data_type}")
                return False

            filename = Path(s3_url).name
            target_dir = data_dir / target_subdir
            target_path = target_dir / filename

            # Check if file already exists
            if target_path.exists():
                file_size = target_path.stat().st_size / (1024 * 1024)  # MB
                print(f"   ⏭️  Skipping (exists): {filename} ({file_size:.2f} MB)")
                return True

            if dry_run:
                print(f"   [DRY RUN] Would download: {filename} from {s3_url[:50]}...")
                return True

            print(f"   ⬇️  Downloading: {filename}")
            urlretrieve(s3_url, target_path)

            file_size = target_path.stat().st_size / (1024 * 1024)  # MB
            print(f"   ✅ Downloaded: {filename} ({file_size:.2f} MB)")
            return True

    except HTTPError as e:
        if e.code == 404:
            print(f"   ⚠️  Not found: {data_subtype}/{data_type} (may not exist for this release)")
        else:
            print(f"   ⚠️  HTTP error downloading {data_subtype}/{data_type}: {e}")
        return False
    except (URLError, json.JSONDecodeError) as e:
        print(f"   ⚠️  Failed to download {data_subtype}/{data_type}: {e}")
        return False


def download_all_files(
    release_version: str,
    data_dir: Path,
    file_specs: List[Tuple[str, str, str]],
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Download all specified data files.

    Args:
        release_version: Alliance release version
        data_dir: Base data directory
        file_specs: List of (data_subtype, data_type, target_subdir) tuples
        dry_run: If True, don't actually download

    Returns:
        Dict with download statistics
    """
    stats = {"success": 0, "failed": 0, "skipped": 0, "total": len(file_specs)}

    print(f"\n📦 Downloading {stats['total']} data files...")

    for data_subtype, data_type, target_subdir in file_specs:
        result = download_datafile(
            release_version,
            data_subtype,
            data_type,
            data_dir,
            target_subdir,
            dry_run
        )

        if result:
            stats["success"] += 1
        else:
            stats["failed"] += 1

    return stats


def verify_downloads(data_dir: Path) -> None:
    """Verify downloaded files and print summary."""
    files = list(data_dir.rglob("*"))
    file_list = [f for f in files if f.is_file()]
    total_size = sum(f.stat().st_size for f in file_list)

    print("\n" + "=" * 50)
    print("Download Summary:")
    print(f"  Files downloaded: {len(file_list)}")
    print(f"  Total size: {total_size / (1024**3):.2f} GB")
    print(f"  Data directory: {data_dir}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Download AllianceMine data from FMS API"
    )
    parser.add_argument(
        "--release-type",
        choices=["next", "current"],
        default="current",
        help="Release type to download: 'current' (stable) or 'next' (upcoming). Default: current"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data download directory (default: {DEFAULT_DATA_DIR})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("🚀 AllianceMine Data Downloader")
    print("=" * 50)
    print(f"Release type: {args.release_type}")
    print(f"Local data directory: {args.data_dir}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'DOWNLOAD'}")
    print("=" * 50)

    # Get release version from FMS API
    release_version = get_release_version(args.release_type)

    # Create directory structure
    create_directory_structure(args.data_dir)

    # Download all files
    try:
        stats = download_all_files(
            release_version,
            args.data_dir,
            REQUIRED_FILES,
            args.dry_run
        )

        verify_downloads(args.data_dir)

        print(f"\n📊 Results: {stats['success']} succeeded, {stats['failed']} failed")

        if args.dry_run:
            print("\n✅ Dry run complete")
        else:
            print("\n✅ Download complete!")
            print("\nNext steps:")
            print("  1. Start container: docker-compose up -d")
            print("  2. Run build: python3 build_mine.py")
        print("=" * 50)

        if stats['failed'] > 0:
            print(f"\n⚠️  Warning: {stats['failed']} files failed to download")
            print("   Some data sources may not be available for this release")

    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()

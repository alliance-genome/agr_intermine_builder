#!/usr/bin/env python3
"""
AllianceMine Data Downloader

Downloads ALL required data files from Alliance FMS using the snapshot API.
This matches Alliance's official FMSExtractor behavior.

Usage:
    python3 download_data.py [--release-type current|next] [--dry-run]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError


# FMS API Configuration
FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("data")


# Data types to download (filters for the snapshot)
WANTED_DATA_TYPES = {
    # Ontologies
    "ONTOLOGY",

    # Alliance combined files
    "DISEASE-ALLIANCE", "DISEASE-ALLIANCE-JSON",
    "ORTHOLOGY-ALLIANCE", "ORTHOLOGY-ALLIANCE-JSON",
    "ALLELE", "ALLELE-GFF",
    "EXPRESSION", "EXPRESSION-ALLIANCE", "EXPRESSION-ALLIANCE-JSON",

    # Gene annotations
    "GAF",
    "BGI",

    # FASTA genome sequences
    "FASTA",

    # GFF files
    "GFF",

    # Gene descriptions
    "GENE-DESCRIPTION-JSON", "GENE-DESCRIPTION-TXT", "GENE-DESCRIPTION-TSV",

    # Cross references
    "GENECROSSREFERENCE", "GENECROSSREFERENCEJSON",
    "CROSSREFERENCEUNIPROT",
}


def create_directory_structure(data_dir: Path) -> None:
    """Create the complete directory structure for data files."""
    print("\n📁 Creating directory structure...")

    directories = [
        data_dir / "fms",
        data_dir / "genes",
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"   ✅ {directory.relative_to(data_dir.parent)}")

    print(f"\n✅ Directory structure created")


def get_release_version(release_type: str = "latest") -> str:
    """Fetch release version from FMS API."""
    url = f"{FMS_API_BASE}/releaseversion/all"

    print(f"\n📋 Fetching release versions from FMS...")

    try:
        with urlopen(url) as response:
            versions = json.loads(response.read())

            if not versions:
                raise ValueError("No versions returned from API")

            # Sort by release date to get latest
            sorted_versions = sorted(versions, key=lambda x: x['releaseDate'], reverse=True)

            if release_type == "latest":
                version = sorted_versions[0]['releaseVersion']
                print(f"   Latest release: {version}")
            elif release_type == "previous":
                if len(sorted_versions) < 2:
                    raise ValueError("No previous release available")
                version = sorted_versions[1]['releaseVersion']
                print(f"   Previous release: {version}")
            else:
                raise ValueError(f"Unknown release_type: {release_type}")

            return version

    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"❌ Failed to get release version: {e}")
        sys.exit(1)


def get_snapshot_files(release_version: str) -> List[Dict]:
    """Fetch complete snapshot from FMS API."""
    url = f"{FMS_API_BASE}/snapshot/release/{release_version}"

    print(f"\n📦 Fetching snapshot from FMS...")

    try:
        with urlopen(url) as response:
            data = json.loads(response.read())

            if data.get("status") != "success":
                raise ValueError(f"Snapshot API returned status: {data.get('status')}")

            files = data["snapShot"]["dataFiles"]
            print(f"   Total files in snapshot: {len(files)}")

            return files

    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"❌ Failed to get snapshot: {e}")
        sys.exit(1)


def filter_wanted_files(files: List[Dict]) -> List[Dict]:
    """Filter snapshot to only include wanted data types."""
    wanted = []

    for f in files:
        data_type = f["dataType"]["name"]
        if data_type in WANTED_DATA_TYPES:
            wanted.append(f)

    print(f"   Files to download: {len(wanted)}")

    # Show breakdown by data type
    by_type = {}
    for f in wanted:
        dt = f["dataType"]["name"]
        by_type[dt] = by_type.get(dt, 0) + 1

    print("\n   Files by type:")
    for dt in sorted(by_type.keys()):
        print(f"      {dt:30} {by_type[dt]:4} files")

    return wanted


def download_file(
    file_info: Dict,
    data_dir: Path,
    dry_run: bool = False
) -> bool:
    """Download a single file from the snapshot."""
    s3_url = file_info.get("s3Url")

    if not s3_url:
        print(f"   ⚠️  No URL for {file_info['dataType']['name']}")
        return False

    # Determine filename from s3Path
    s3_path = file_info["s3Path"]
    filename = Path(s3_path).name

    target_dir = data_dir / "fms"
    target_path = target_dir / filename

    if target_path.exists():
        file_size = target_path.stat().st_size / (1024 * 1024)
        # Don't print for every existing file to reduce clutter
        return True

    if dry_run:
        print(f"   [DRY RUN] {filename}")
        return True

    print(f"   ⬇️  {filename}")

    try:
        urlretrieve(s3_url, target_path)
        file_size = target_path.stat().st_size / (1024 * 1024)
        return True

    except (HTTPError, URLError) as e:
        print(f"   ❌ Failed: {filename}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download AllianceMine data from FMS snapshot API"
    )
    parser.add_argument(
        "--release-type",
        choices=["latest", "previous"],
        default="latest",
        help="Release type: 'latest' (most recent) or 'previous'. Default: latest"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data directory (default: {DEFAULT_DATA_DIR})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🚀 AllianceMine Data Downloader")
    print("=" * 70)
    print(f"Release type: {args.release_type}")
    print(f"Data directory: {args.data_dir}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'DOWNLOAD'}")
    print("=" * 70)

    # Get release version
    release_version = get_release_version(args.release_type)

    # Create directory structure
    create_directory_structure(args.data_dir)

    # Get snapshot
    all_files = get_snapshot_files(release_version)

    # Filter to wanted files
    wanted_files = filter_wanted_files(all_files)

    # Track statistics
    stats = {"success": 0, "failed": 0, "skipped": 0}

    # Download files
    print(f"\n📦 Downloading files...")
    print("=" * 70)

    for file_info in wanted_files:
        if download_file(file_info, args.data_dir, args.dry_run):
            stats["success"] += 1
        else:
            stats["failed"] += 1

    # Count existing files
    existing_count = 0
    for f in wanted_files:
        filename = Path(f["s3Path"]).name
        if (args.data_dir / "fms" / filename).exists():
            existing_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("📊 Download Summary:")
    print(f"  Total files: {len(wanted_files)}")
    print(f"  Already present: {existing_count}")
    print(f"  Downloaded: {stats['success'] - existing_count}")
    print(f"  Failed: {stats['failed']}")
    print(f"  Data directory: {args.data_dir.absolute()}")
    print("=" * 70)

    if args.dry_run:
        print("\n✅ Dry run complete")
    else:
        print("\n✅ Download complete!")
        print("\nNext steps:")
        print("  1. Build container: docker-compose build")
        print("  2. Start container: docker-compose up -d")
        print("  3. Run build: python3 build_mine.py")

    print("=" * 70)

    if stats["failed"] > 0:
        print(f"\n⚠️  Warning: {stats['failed']} files failed to download")


if __name__ == "__main__":
    main()

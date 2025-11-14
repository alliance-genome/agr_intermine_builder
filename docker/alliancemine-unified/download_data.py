#!/usr/bin/env python3
"""
AllianceMine Data Downloader

Downloads ALL required data files from Alliance FMS using the snapshot API.
This matches Alliance's official FMSExtractor behavior.

Usage:
    python3 download_data.py [--release-type current|next] [--dry-run]
"""

import argparse
import gzip
import json
import re
import shutil
import sys
from pathlib import Path
from typing import List, Dict, Optional
from urllib.request import urlopen, urlretrieve
from urllib.error import HTTPError, URLError


# FMS API Configuration
FMS_API_BASE = "https://fms.alliancegenome.org/api"
DEFAULT_DATA_DIR = Path("data")


# Required files mapping - based on project.xml
# Maps FMS file name patterns to expected output names
REQUIRED_FILES = {
    # Alliance combined TSV files (exact matches)
    "DISEASE-ALLIANCE_COMBINED": "DISEASE-ALLIANCE_COMBINED.tsv",
    "EXPRESSION-ALLIANCE_COMBINED": "EXPRESSION-ALLIANCE_COMBINED.tsv",
    "ORTHOLOGY-ALLIANCE_COMBINED": "ORTHOLOGY-ALLIANCE_COMBINED.tsv",

    # These are in project.xml but may not be used yet
    "VARIANT-ALLELE_COMBINED": "VARIANT-ALLELE_COMBINED.tsv",
    "INTERACTION-GEN_COMBINED": "INTERACTION-GEN_COMBINED.tsv",
    # Note: project.xml has typo "NTERACTION-MOL" but file is "INTERACTION-MOL"
    "INTERACTION-MOL_COMBINED": "NTERACTION-MOL_COMBINED.tsv",
}

# File prefixes that should be downloaded (partial matches)
REQUIRED_FILE_PREFIXES = {
    "GAF_",  # All GAF files (*.gaf pattern in project.xml)
    "ONTOLOGY_",  # All ontology files (.obo files for SO, GO, DO, ECO, etc.)
}


# SGD Data Sources
# Based on project.xml SGD sources and typical SGD data locations
SGD_DATA_SOURCES = {
    # SGD GFF files
    "sgd-gff": {
        "url": "https://downloads.yeastgenome.org/curation/chromosomal_feature/saccharomyces_cerevisiae.gff",
        "target_dir": "intermine/gff",
        "filename": "saccharomyces_cerevisiae.gff"
    },

    # SGD annotations and features data
    # These are typically accessed via SGD database/API rather than flat files
    # For now, we'll note them but may need additional implementation
}


# Yeast Ortholog Data Sources
# Based on project.xml yeast_orthologs sources
YEAST_ORTHOLOG_SOURCES = {
    # These typically come from specialized databases
    # Will need to determine exact URLs and file formats
    "fungidb": {
        "target_dir": "intermine/yeast_orthologs/fungidb",
        "note": "FungiDB ortholog data - needs URL specification"
    },
    "cgob": {
        "target_dir": "intermine/yeast_orthologs/CGOB",
        "note": "CGOB (Candida Gene Order Browser) ortholog data"
    },
    "cglabrata": {
        "target_dir": "intermine/yeast_orthologs/C.glabrata",
        "note": "C. glabrata ortholog data"
    },
    "pombe": {
        "target_dir": "intermine/yeast_orthologs/pombe",
        "note": "S. pombe ortholog data"
    },
}


def create_directory_structure(data_dir: Path) -> None:
    """Create the complete directory structure for data files."""
    print("\n📁 Creating directory structure...")

    directories = [
        # FMS data
        data_dir / "fms",

        # Alliance genes
        data_dir / "genes",

        # SGD directories
        data_dir / "intermine" / "gff",
        data_dir / "intermine" / "gff-utr",
        data_dir / "intermine" / "db-utr",
        data_dir / "intermine" / "protein-properties",
        data_dir / "intermine" / "protein-ntermini",

        # Yeast ortholog directories
        data_dir / "intermine" / "yeast_orthologs" / "fungidb",
        data_dir / "intermine" / "yeast_orthologs" / "CGOB",
        data_dir / "intermine" / "yeast_orthologs" / "C.glabrata",
        data_dir / "intermine" / "yeast_orthologs" / "pombe",
        data_dir / "intermine" / "yeast_orthologs" / "homolog_genes",
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


def is_required_file(filename: str) -> bool:
    """Check if a file is required based on project.xml expectations."""
    # Remove version suffix and extension for matching
    base_name = re.sub(r'_\d+\.(tsv|json|gaf|txt)\.gz$', '', filename)
    base_name = re.sub(r'\.(tsv|json|gaf|txt)\.gz$', '', base_name)
    base_name = re.sub(r'_\d+\.(tsv|json|gaf|txt)$', '', base_name)
    base_name = re.sub(r'\.(tsv|json|gaf|txt)$', '', base_name)

    # Check exact matches
    if base_name in REQUIRED_FILES:
        return True

    # Check prefix matches
    for prefix in REQUIRED_FILE_PREFIXES:
        if base_name.startswith(prefix):
            return True

    return False


def filter_wanted_files(files: List[Dict]) -> List[Dict]:
    """Filter snapshot to only include files required by project.xml."""
    wanted = []

    for f in files:
        s3_path = f.get("s3Path", "")
        filename = Path(s3_path).name

        if is_required_file(filename):
            wanted.append(f)

    print(f"   Files to download: {len(wanted)}")

    # Show files
    print("\n   Required files found:")
    for f in wanted:
        filename = Path(f["s3Path"]).name
        print(f"      {filename}")

    return wanted


def normalize_filename(filename: str) -> str:
    """
    Normalize FMS filename to match project.xml expectations.

    Removes version suffixes like _1, _2, etc. and .gz extension.
    Maps to expected names from REQUIRED_FILES.

    Examples:
        EXPRESSION-ALLIANCE_COMBINED_1.tsv.gz -> EXPRESSION-ALLIANCE_COMBINED.tsv
        DISEASE-ALLIANCE_COMBINED_7.tsv.gz -> DISEASE-ALLIANCE_COMBINED.tsv
        GAF_MGI_1.gaf.gz -> GAF_MGI.gaf
    """
    # Remove .gz extension if present
    if filename.endswith('.gz'):
        filename = filename[:-3]

    # Remove version suffix pattern: _<digit> before extension
    filename = re.sub(r'_\d+\.', '.', filename)

    # Check if this matches a required file pattern and use mapped name
    base_name = re.sub(r'\.(tsv|json|gaf|txt)$', '', filename)

    # Check for exact match in required files
    if base_name in REQUIRED_FILES:
        return REQUIRED_FILES[base_name]

    # Check for prefix match (like GAF files)
    for prefix in REQUIRED_FILE_PREFIXES:
        if base_name.startswith(prefix):
            # Keep original name (just remove version suffix)
            return filename

    return filename


def decompress_and_normalize(file_path: Path) -> Optional[Path]:
    """
    Decompress .gz file and rename to normalized name.

    Returns the path to the final decompressed file, or None on error.
    """
    if not file_path.name.endswith('.gz'):
        # Not a gzip file, just normalize the name
        normalized_name = normalize_filename(file_path.name)
        if normalized_name != file_path.name:
            normalized_path = file_path.parent / normalized_name
            file_path.rename(normalized_path)
            return normalized_path
        return file_path

    # Decompress and normalize
    normalized_name = normalize_filename(file_path.name)
    output_path = file_path.parent / normalized_name

    # Skip if already decompressed
    if output_path.exists():
        return output_path

    try:
        with gzip.open(file_path, 'rb') as f_in:
            with open(output_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove the .gz file after successful decompression
        file_path.unlink()

        return output_path

    except Exception as e:
        print(f"   ⚠️  Failed to decompress {file_path.name}: {e}")
        return None


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

    # Check if normalized file already exists
    normalized_name = normalize_filename(filename)
    normalized_path = target_dir / normalized_name

    if normalized_path.exists():
        # Already downloaded and processed
        return True

    if target_path.exists():
        # Downloaded but not processed - decompress it
        if not dry_run:
            decompress_and_normalize(target_path)
        return True

    if dry_run:
        print(f"   [DRY RUN] {filename}")
        return True

    print(f"   ⬇️  {filename}")

    try:
        urlretrieve(s3_url, target_path)

        # Decompress and normalize after download
        final_path = decompress_and_normalize(target_path)

        if final_path:
            file_size = final_path.stat().st_size / (1024 * 1024)
            print(f"      → {final_path.name} ({file_size:.1f} MB)")

        return True

    except (HTTPError, URLError) as e:
        print(f"   ❌ Failed: {filename}")
        return False


def download_sgd_data(data_dir: Path, dry_run: bool = False) -> Dict[str, int]:
    """
    Download SGD-specific data files.

    Returns dict with download statistics.
    """
    print("\n" + "=" * 70)
    print("📦 Downloading SGD Data...")
    print("=" * 70)

    stats = {"success": 0, "failed": 0, "skipped": 0}

    for source_name, source_info in SGD_DATA_SOURCES.items():
        url = source_info.get("url")
        if not url:
            print(f"   ⚠️  {source_name}: No URL specified (needs manual configuration)")
            stats["skipped"] += 1
            continue

        target_dir = data_dir / source_info["target_dir"]
        target_file = target_dir / source_info["filename"]

        if target_file.exists():
            print(f"   ✅ {source_name}: Already exists")
            stats["success"] += 1
            continue

        if dry_run:
            print(f"   [DRY RUN] {source_name}: Would download from {url}")
            stats["success"] += 1
            continue

        print(f"   ⬇️  {source_name}: Downloading...")
        try:
            urlretrieve(url, target_file)
            file_size = target_file.stat().st_size / (1024 * 1024)
            print(f"      → {target_file.name} ({file_size:.1f} MB)")
            stats["success"] += 1
        except (HTTPError, URLError) as e:
            print(f"   ❌ {source_name}: Failed - {e}")
            stats["failed"] += 1

    return stats


def download_yeast_ortholog_data(data_dir: Path, dry_run: bool = False) -> Dict[str, int]:
    """
    Download yeast ortholog data files.

    Returns dict with download statistics.
    """
    print("\n" + "=" * 70)
    print("📦 Yeast Ortholog Data...")
    print("=" * 70)

    stats = {"success": 0, "failed": 0, "skipped": 0}

    for source_name, source_info in YEAST_ORTHOLOG_SOURCES.items():
        print(f"   ⚠️  {source_name}: {source_info.get('note', 'Needs URL specification')}")
        stats["skipped"] += 1

    print("\n   ℹ️  Yeast ortholog data sources need URLs to be configured")
    print("   ℹ️  These will be skipped for now - can be added later")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Download AllianceMine data from FMS snapshot API and other sources"
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

    # Download FMS files
    print(f"\n📦 Downloading FMS files...")
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

    # Download SGD data
    sgd_stats = download_sgd_data(args.data_dir, args.dry_run)

    # Download yeast ortholog data
    yeast_stats = download_yeast_ortholog_data(args.data_dir, args.dry_run)

    # Summary
    print("\n" + "=" * 70)
    print("📊 Download Summary:")
    print("\n  FMS Data:")
    print(f"    Total files: {len(wanted_files)}")
    print(f"    Already present: {existing_count}")
    print(f"    Downloaded: {stats['success'] - existing_count}")
    print(f"    Failed: {stats['failed']}")
    print("\n  SGD Data:")
    print(f"    Success: {sgd_stats['success']}")
    print(f"    Failed: {sgd_stats['failed']}")
    print(f"    Skipped: {sgd_stats['skipped']}")
    print("\n  Yeast Ortholog Data:")
    print(f"    Skipped: {yeast_stats['skipped']} (needs configuration)")
    print(f"\n  Data directory: {args.data_dir.absolute()}")
    print("=" * 70)

    if args.dry_run:
        print("\n✅ Dry run complete")
    else:
        print("\n✅ Download complete!")
        print("\nNext steps:")
        print("  1. Run automated build: python3 build_mine.py")
        print("     (This will set DB version, restart container, and run buildDB)")
        print("  2. Or see QUICKSTART.md for manual steps")

    print("=" * 70)

    if stats["failed"] > 0:
        print(f"\n⚠️  Warning: {stats['failed']} files failed to download")


if __name__ == "__main__":
    main()

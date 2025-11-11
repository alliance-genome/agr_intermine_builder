#!/usr/bin/env python3
"""
AllianceMine Data Downloader

Downloads ALL required data files for InterMine:
1. Alliance FMS API data (ontologies, annotations, combined data)
2. Genome FASTA files from Model Organism Databases

Usage:
    python3 download_data.py [--release-type current|next] [--dry-run]
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


# Genome source URLs for each organism
GENOME_SOURCES = {
    "WB": {
        "name": "C. elegans",
        "source": "WormBase FTP",
        "url": "https://ftp.wormbase.org/pub/wormbase/releases/WS292/species/c_elegans/PRJNA13758/c_elegans.PRJNA13758.WS292.genomic.fa.gz",
        "filename": "FASTA_WB.fa.gz"
    },
    "FB": {
        "name": "Drosophila melanogaster",
        "source": "FlyBase FTP",
        "url": "ftp://ftp.flybase.net/genomes/Drosophila_melanogaster/current/fasta/dmel-all-chromosome-r6.55.fasta.gz",
        "filename": "FASTA_FB.fa.gz"
    },
    "SGD": {
        "name": "S. cerevisiae",
        "source": "SGD",
        "url": "https://downloads.yeastgenome.org/sequence/S288C_reference/genome_releases/S288C_reference_genome_R64-4-1_20230830.fsa",
        "filename": "FASTA_SGD.fa"
    },
    "ZFIN": {
        "name": "Zebrafish",
        "source": "Ensembl",
        "url": "https://ftp.ensembl.org/pub/release-111/fasta/danio_rerio/dna/Danio_rerio.GRCz11.dna.toplevel.fa.gz",
        "filename": "FASTA_GRCz11.fa.gz"
    },
    "MGI": {
        "name": "Mouse",
        "source": "Ensembl",
        "url": "https://ftp.ensembl.org/pub/release-111/fasta/mus_musculus/dna/Mus_musculus.GRCm39.dna.toplevel.fa.gz",
        "filename": "FASTA_GRCm39.fa.gz"
    },
    "RGD": {
        "name": "Rat",
        "source": "Ensembl",
        "url": "https://ftp.ensembl.org/pub/release-111/fasta/rattus_norvegicus/dna/Rattus_norvegicus.mRatBN7.2.dna.toplevel.fa.gz",
        "filename": "FASTA_Rnor7.2.fa.gz"
    },
    "XB": {
        "name": "Xenopus tropicalis",
        "source": "Ensembl",
        "url": "https://ftp.ensembl.org/pub/release-111/fasta/xenopus_tropicalis/dna/Xenopus_tropicalis.Xenopus_tropicalis_v9.1.dna.toplevel.fa.gz",
        "filename": "FASTA_XT10.fa.gz"
    }
}


# FMS API data files (ontologies, annotations, combined data)
# Format: (data_subtype, data_type, target_subdir)
FMS_FILES = [
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

    print(f"\n✅ Directory structure created")


def get_release_version(release_type: str = "current") -> str:
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


def download_fms_file(
    release_version: str,
    data_subtype: str,
    data_type: str,
    data_dir: Path,
    target_subdir: str,
    dry_run: bool = False
) -> bool:
    """Download a file from FMS API."""
    api_url = f"{FMS_API_BASE}/datafile/by/{release_version}/{data_subtype}/{data_type}"

    try:
        with urlopen(api_url) as response:
            file_list = json.loads(response.read())

            if not file_list or len(file_list) == 0:
                print(f"   ⚠️  Not found: {data_subtype}/{data_type}")
                return False

            file_info = file_list[0]
            s3_url = file_info.get("s3Url") or file_info.get("stableURL")

            if not s3_url:
                print(f"   ⚠️  No URL: {data_subtype}/{data_type}")
                return False

            filename = Path(s3_url).name
            target_dir = data_dir / target_subdir
            target_path = target_dir / filename

            if target_path.exists():
                file_size = target_path.stat().st_size / (1024 * 1024)
                print(f"   ⏭️  Exists: {filename} ({file_size:.1f} MB)")
                return True

            if dry_run:
                print(f"   [DRY RUN] {filename}")
                return True

            print(f"   ⬇️  Downloading: {filename}")
            urlretrieve(s3_url, target_path)

            file_size = target_path.stat().st_size / (1024 * 1024)
            print(f"   ✅ Downloaded: {filename} ({file_size:.1f} MB)")
            return True

    except HTTPError as e:
        if e.code != 404:
            print(f"   ⚠️  HTTP error: {data_subtype}/{data_type}")
        return False
    except (URLError, json.JSONDecodeError) as e:
        print(f"   ⚠️  Failed: {data_subtype}/{data_type}")
        return False


def download_genome_file(
    org_code: str,
    genome_info: Dict,
    data_dir: Path,
    dry_run: bool = False
) -> bool:
    """Download a genome FASTA file from MOD source."""
    target_path = data_dir / "fms" / genome_info["filename"]

    if target_path.exists():
        file_size = target_path.stat().st_size / (1024 * 1024)
        print(f"   ⏭️  Exists: {genome_info['filename']} ({file_size:.1f} MB)")
        return True

    if dry_run:
        print(f"   [DRY RUN] {genome_info['filename']}")
        return True

    print(f"   ⬇️  Downloading: {genome_info['filename']}")
    print(f"      From: {genome_info['source']}")

    try:
        urlretrieve(genome_info["url"], target_path)
        file_size = target_path.stat().st_size / (1024 * 1024)
        print(f"   ✅ Downloaded: {genome_info['filename']} ({file_size:.1f} MB)")
        return True
    except (HTTPError, URLError) as e:
        print(f"   ❌ Failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download AllianceMine data from FMS API and MOD sources"
    )
    parser.add_argument(
        "--release-type",
        choices=["next", "current"],
        default="current",
        help="Release type: 'current' (stable) or 'next' (upcoming). Default: current"
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

    # Track statistics
    stats = {"fms": {"success": 0, "failed": 0}, "genomes": {"success": 0, "failed": 0}}

    # Download FMS API files
    print(f"\n📦 Downloading FMS API files ({len(FMS_FILES)} files)...")
    print("=" * 70)
    for data_subtype, data_type, target_subdir in FMS_FILES:
        if download_fms_file(
            release_version,
            data_subtype,
            data_type,
            args.data_dir,
            target_subdir,
            args.dry_run
        ):
            stats["fms"]["success"] += 1
        else:
            stats["fms"]["failed"] += 1

    # Download genome FASTA files
    print(f"\n🧬 Downloading genome FASTA files ({len(GENOME_SOURCES)} organisms)...")
    print("=" * 70)
    for org_code, genome_info in GENOME_SOURCES.items():
        print(f"\n{org_code}: {genome_info['name']}")
        if download_genome_file(org_code, genome_info, args.data_dir, args.dry_run):
            stats["genomes"]["success"] += 1
        else:
            stats["genomes"]["failed"] += 1

    # Summary
    print("\n" + "=" * 70)
    print("📊 Download Summary:")
    print(f"  FMS files: {stats['fms']['success']} succeeded, {stats['fms']['failed']} failed")
    print(f"  Genomes: {stats['genomes']['success']} succeeded, {stats['genomes']['failed']} failed")
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

    if stats["fms"]["failed"] > 0 or stats["genomes"]["failed"] > 0:
        print(f"\n⚠️  Warning: Some files failed to download")
        print("   This is normal - not all data may be available for this release")


if __name__ == "__main__":
    main()

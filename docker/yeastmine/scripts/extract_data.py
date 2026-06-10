#!/usr/bin/env python3
"""YeastMine data extraction.

Stages the FILE sources referenced by yeastmine/project.xml into
/root/data/intermine/. The DATABASE sources (sgd, sgd-complementation-db,
go-annotation-db, disease, sgd-complexes) need no extraction — they read live
from db.sgd.

Two passes:
  1. S3 sync of the SGD subset from s3://agr-db-backups/alliancemine/intermine/
     (yeast_orthologs/*, protein-properties, protein-ntermini, gff, gff-utr,
     db-utr, psi-mi.obo, goslim_yeast.obo) — the same data AllianceMine stages.
  2. Direct downloads of the ontologies YeastMine wants in their canonical form
     (go-basic.obo, doid.obo, eco.obo, so.obo) into ontology/.

Use --skip-s3 / --skip-ontology to run only one pass.
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlretrieve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("yeastmine-extract")

DATA_DIR = Path("/root/data")
INTERMINE_DIR = DATA_DIR / "intermine"

S3_DATA_BUCKET = "agr-db-backups"
S3_DATA_PREFIX = "alliancemine/intermine/"

# Ontologies YeastMine reads at the exact paths in project.xml (relative to
# /root/data/intermine/). Pulled from OBO Foundry canonical URLs.
ONTOLOGY_DOWNLOADS = [
    ("ontology/go-basic.obo", "http://purl.obolibrary.org/obo/go/go-basic.obo"),
    ("ontology/doid.obo", "http://purl.obolibrary.org/obo/doid.obo"),
    ("ontology/eco.obo", "http://purl.obolibrary.org/obo/eco.obo"),
    ("ontology/so.obo", "http://purl.obolibrary.org/obo/so.obo"),
]


def sync_s3() -> bool:
    """aws s3 cp the SGD/external subset into /root/data/intermine/."""
    INTERMINE_DIR.mkdir(parents=True, exist_ok=True)
    s3_uri = f"s3://{S3_DATA_BUCKET}/{S3_DATA_PREFIX}"
    logger.info(f"Syncing SGD/external data from {s3_uri} -> {INTERMINE_DIR}/ ...")
    try:
        result = subprocess.run(
            ["aws", "s3", "cp", s3_uri, str(INTERMINE_DIR), "--recursive"],
            capture_output=True, text=True, timeout=900,
        )
        if result.returncode != 0:
            logger.error(f"  S3 sync failed: {result.stderr.strip()}")
            return False
        files = sum(1 for _ in INTERMINE_DIR.rglob("*") if _.is_file())
        size = sum(f.stat().st_size for f in INTERMINE_DIR.rglob("*") if f.is_file())
        logger.info(f"  S3 sync complete: {files} files, {size / (1024**2):.1f} MB")
        return True
    except FileNotFoundError:
        logger.error("  aws CLI not found")
        return False
    except subprocess.TimeoutExpired:
        logger.error("  S3 sync timed out after 900s")
        return False


def download_ontologies() -> int:
    """Download the canonical-form ontologies. Returns failure count."""
    failures = 0
    for rel_path, url in ONTOLOGY_DOWNLOADS:
        out = INTERMINE_DIR / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading {url} -> {out}")
        try:
            urlretrieve(url, out)
            mb = out.stat().st_size / (1024 * 1024)
            logger.info(f"  OK ({mb:.1f} MB)")
        except (HTTPError, URLError, OSError) as e:
            logger.error(f"  FAILED: {e}")
            failures += 1
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="YeastMine data extraction")
    ap.add_argument("--skip-s3", action="store_true", help="skip the S3 sync pass")
    ap.add_argument("--skip-ontology", action="store_true", help="skip ontology downloads")
    args = ap.parse_args()

    ok = True
    if not args.skip_s3:
        ok = sync_s3() and ok
    else:
        logger.info("Skipping S3 sync (--skip-s3)")

    if not args.skip_ontology:
        failures = download_ontologies()
        ok = (failures == 0) and ok
    else:
        logger.info("Skipping ontology downloads (--skip-ontology)")

    if not ok:
        logger.error("extract_data finished with errors")
        return 1
    logger.info("extract_data complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

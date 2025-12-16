#!/usr/bin/env python3
"""
Generate removal lists for WormMine post-processing

Queries WormMine webapp to find problematic data and generates
text files listing items to remove (genes, proteins, etc.)

Usage:
    python generate_removal_lists.py <wormmine_url> [--output-dir <dir>]

Example:
    python generate_removal_lists.py http://localhost:8080/wormmine
    python generate_removal_lists.py https://intermine.wormbase.org/wormmine --output-dir /tmp/removal_lists
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, urljoin
from urllib.error import URLError, HTTPError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class InterMineClient:
    """Simple InterMine REST API client using only stdlib"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.service_url = f"{self.base_url}/service"
        self.version = self._get_version()

    def _get_version(self):
        """Get InterMine version"""
        try:
            url = f"{self.service_url}/version"
            with urlopen(url, timeout=30) as response:
                return response.read().decode('utf-8').strip()
        except Exception:
            return "unknown"

    def query(self, xml_query):
        """Execute a PathQuery and return results as JSON"""
        url = f"{self.service_url}/query/results"
        params = {
            'query': xml_query,
            'format': 'json'
        }

        full_url = f"{url}?{urlencode(params)}"

        try:
            req = Request(full_url)
            req.add_header('Accept', 'application/json')
            with urlopen(req, timeout=120) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data.get('results', [])
        except HTTPError as e:
            logger.error(f"HTTP Error {e.code}: {e.reason}")
            return []
        except URLError as e:
            logger.error(f"URL Error: {e.reason}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return []


def build_query(root_class, views, constraints):
    """Build PathQuery XML"""
    view_str = " ".join(views)
    constraint_xml = ""

    for i, (path, op, value) in enumerate(constraints):
        code = chr(65 + i)  # A, B, C, etc.
        if value is None:
            constraint_xml += f'    <constraint path="{path}" op="{op}" code="{code}"/>\n'
        else:
            constraint_xml += f'    <constraint path="{path}" op="{op}" value="{value}" code="{code}"/>\n'

    return f'''<query model="genomic" view="{view_str}" sortOrder="{views[0]} ASC">
{constraint_xml}</query>'''


def save_removal_list(class_name, rows, output_dir):
    """Save removal list to file"""
    output_file = output_dir / f'to_remove_{class_name.lower()}.txt'

    with open(output_file, 'w') as f:
        for row in rows:
            # Results come as arrays, first element is primaryIdentifier
            identifier = row[0] if isinstance(row, list) else row.get('primaryIdentifier', row)
            f.write(f"{identifier}\n")

    logger.info(f"Saved {len(rows)} {class_name} items to {output_file}")
    return len(rows)


def find_genes_without_organism(client, output_dir):
    """Find genes without organism"""
    logger.info("Searching for genes without organism...")

    query = build_query(
        "Gene",
        ["Gene.primaryIdentifier", "Gene.symbol"],
        [("Gene.organism", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("gene", rows, output_dir)
        logger.warning(f"Found {len(rows)} genes without organism")
    else:
        logger.info("No genes without organism found")

    return len(rows)


def find_proteins_without_organism(client, output_dir):
    """Find proteins without organism"""
    logger.info("Searching for proteins without organism...")

    query = build_query(
        "Protein",
        ["Protein.primaryIdentifier"],
        [("Protein.organism", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("protein", rows, output_dir)
        logger.warning(f"Found {len(rows)} proteins without organism")
    else:
        logger.info("No proteins without organism found")

    return len(rows)


def find_transcripts_without_gene(client, output_dir):
    """Find transcripts without gene"""
    logger.info("Searching for transcripts without gene...")

    query = build_query(
        "Transcript",
        ["Transcript.primaryIdentifier"],
        [("Transcript.gene", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("transcript", rows, output_dir)
        logger.warning(f"Found {len(rows)} transcripts without gene")
    else:
        logger.info("No transcripts without gene found")

    return len(rows)


def find_cds_without_gene(client, output_dir):
    """Find CDS without gene"""
    logger.info("Searching for CDS without gene...")

    query = build_query(
        "CDS",
        ["CDS.primaryIdentifier"],
        [("CDS.gene", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("cds", rows, output_dir)
        logger.warning(f"Found {len(rows)} CDS without gene")
    else:
        logger.info("No CDS without gene found")

    return len(rows)


def find_genes_without_symbol(client, output_dir):
    """Find genes without symbol"""
    logger.info("Searching for genes without symbol...")

    query = build_query(
        "Gene",
        ["Gene.primaryIdentifier"],
        [
            ("Gene.symbol", "IS NULL", None),
            ("Gene.organism.shortName", "=", "C. elegans")
        ]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("gene_no_symbol", rows, output_dir)
        logger.warning(f"Found {len(rows)} C. elegans genes without symbol")
    else:
        logger.info("No C. elegans genes without symbol found")

    return len(rows)


def find_orphan_exons(client, output_dir):
    """Find exons without transcript"""
    logger.info("Searching for orphan exons...")

    query = build_query(
        "Exon",
        ["Exon.primaryIdentifier"],
        [("Exon.transcripts", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("exon", rows, output_dir)
        logger.warning(f"Found {len(rows)} orphan exons")
    else:
        logger.info("No orphan exons found")

    return len(rows)


def find_rnai_without_gene(client, output_dir):
    """Find RNAi experiments without gene"""
    logger.info("Searching for RNAi without gene...")

    query = build_query(
        "RNAi",
        ["RNAi.primaryIdentifier"],
        [("RNAi.gene", "IS NULL", None)]
    )

    rows = client.query(query)
    if rows:
        save_removal_list("rnai", rows, output_dir)
        logger.warning(f"Found {len(rows)} RNAi without gene")
    else:
        logger.info("No RNAi without gene found")

    return len(rows)


def run_all_checks(service_url, output_dir):
    """Run all data quality checks"""
    logger.info(f"Connecting to WormMine at {service_url}")

    try:
        client = InterMineClient(service_url)
        logger.info(f"Connected to WormMine version {client.version}")
    except Exception as e:
        logger.error(f"Failed to connect to WormMine: {e}")
        sys.exit(1)

    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")

    # Run all checks
    total_issues = 0
    checks = [
        find_genes_without_organism,
        find_proteins_without_organism,
        find_transcripts_without_gene,
        find_cds_without_gene,
        find_genes_without_symbol,
        find_orphan_exons,
        find_rnai_without_gene,
    ]

    for check in checks:
        try:
            count = check(client, output_dir)
            total_issues += count
        except Exception as e:
            logger.error(f"Error running {check.__name__}: {e}")

    logger.info("=" * 60)
    if total_issues > 0:
        logger.warning(f"Found {total_issues} total issues")
        logger.info(f"Removal lists saved to: {output_dir}")
        logger.info("Next steps:")
        logger.info("  1. Review the removal lists")
        logger.info("  2. Run post-processing scripts to clean database")
    else:
        logger.info("No data quality issues found!")

    return total_issues


def main():
    parser = argparse.ArgumentParser(
        description='Generate removal lists for WormMine post-processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'url',
        help='WormMine URL (e.g., http://localhost:8080/wormmine)'
    )

    parser.add_argument(
        '--output-dir', '-o',
        default='./removal_lists',
        help='Output directory for removal lists (default: ./removal_lists)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run checks
    issues_found = run_all_checks(args.url, args.output_dir)

    # Exit with error code if issues found
    sys.exit(0 if issues_found == 0 else 1)


if __name__ == '__main__':
    main()

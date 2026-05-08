#!/usr/bin/env python3
"""
Build the 14-column Gene.tsv that AllianceGenesConverter expects from the
per-MOD BGI JSON files that extract_data.py drops into /root/data/genes/.

Background: 8.3.0 used Gene.tsv produced by Alliance's
agr_intermine_data_extractor (Neo4j-backed Java tool). That tool is no longer
in the build path. Without Gene.tsv the alliance-genes source loads zero
rows from this directory because the converter parses tab-delimited 14-col
input and BGI JSON does not satisfy that contract.

This script reads BGI_*.json (Alliance schema 1.0.2.x) and emits the same
14-column TSV layout the converter understands.

Schema (matches /data/genes/Gene.tsv from the 8.3.0 host):
    1  Id                  basicGeneticEntity.primaryId
    2  SecondaryId         basicGeneticEntity.secondaryIds[0] (or empty)
    3  Synonyms            "[a, b, c]" from basicGeneticEntity.synonyms
    4  CrossRefs           "[a, b, c]" from basicGeneticEntity.crossReferences[].id
    5  Name                top-level name
    6  Symbol              top-level symbol
    7  MOD Description     geneSynopsis
    8  Auto Description    blank (BGI does not carry this; the original
                           extractor pulled it from Neo4j separately)
    9  Species             basicGeneticEntity.taxonId  (e.g. "NCBITaxon:10090")
    10 Chromosome          genomeLocations[0].chromosome (or empty)
    11 Start               genomeLocations[0].startPosition (or empty)
    12 End                 genomeLocations[0].endPosition (or empty)
    13 Strand              genomeLocations[0].strand (or empty)
    14 SoTerm              soTermId (e.g. "SO:0001217")

Usage:
    python3 bgi_to_genes_tsv.py
    python3 bgi_to_genes_tsv.py --data-dir /root/data/genes --out Gene.tsv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("bgi-to-tsv")


HEADER = [
    "Id",
    "SecondaryId",
    "Synonyms",
    "CrossRefs",
    "Name",
    "Symbol",
    "MOD Description",
    "Auto Description",
    "Species",
    "Chromosome",
    "Start",
    "End",
    "Strand",
    "SoTerm",
]


def _scrub(value) -> str:
    """Flatten tabs / newlines that would corrupt the TSV row."""
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _list_literal(values: Iterable[str]) -> str:
    """Format a list as "[a, b, c]" — same shape AllianceGenesConverter
    parses for synonyms / crossrefs columns. Each element is scrubbed of
    tab/newline (BGI synonyms occasionally embed those, which would otherwise
    split a TSV row mid-field)."""
    items = [_scrub(v) for v in values if v]
    return "[" + ", ".join(items) + "]"


def load_so_id_to_name(obo_path: Path) -> dict[str, str]:
    """Parse a Sequence Ontology OBO file and return {SO:NNNNN: name}.

    AllianceGenesConverter switches on the term *name* (e.g.
    "protein_coding_gene", "lncRNA_gene") to pick the right Item subclass.
    BGI JSON only carries the term ID, so we translate here."""
    mapping: dict[str, str] = {}
    if not obo_path.exists():
        logger.warning("SO OBO not found at %s; SoTerm column will be IDs", obo_path)
        return mapping
    cur_id = None
    cur_name = None
    is_term = False
    with obo_path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line == "[Term]":
                is_term = True
                cur_id = None
                cur_name = None
                continue
            if line.startswith("["):
                # Some other stanza ([Typedef] etc) — stop collecting until next [Term]
                is_term = False
                continue
            if not is_term:
                continue
            if line.startswith("id: SO:"):
                cur_id = line[4:].strip()
            elif line.startswith("name: ") and cur_id:
                cur_name = line[6:].strip()
                mapping[cur_id] = cur_name
                cur_id = None
                cur_name = None
    logger.info("Loaded %d SO term names from %s", len(mapping), obo_path)
    return mapping


def row_for_gene(gene: dict, so_names: dict[str, str]) -> list[str]:
    bge = gene.get("basicGeneticEntity") or {}
    primary_id = bge.get("primaryId", "")
    secondary_ids = bge.get("secondaryIds") or []
    secondary = secondary_ids[0] if secondary_ids else ""

    synonyms = bge.get("synonyms") or []
    crossrefs = [
        c.get("id", "")
        for c in (bge.get("crossReferences") or [])
        if isinstance(c, dict) and c.get("id")
    ]

    locs = bge.get("genomeLocations") or []
    loc = locs[0] if locs else {}

    so_id = gene.get("soTermId", "")
    so_term = so_names.get(so_id, so_id) if so_id else ""

    # AllianceGenesConverter checks `if (!start.equals("null") || !end.equals("null"))`
    # to skip location creation. Empty strings would NOT match "null" and the
    # converter would attempt to build a Location with blank ints → NPE in
    # loadSingleSource. Match 8.3.0's Gene.tsv exactly: write the literal
    # string "null" for any missing position field (chr/start/end/strand).
    chromosome = _scrub(loc.get("chromosome", "")) or "null"
    start_pos = _scrub(loc.get("startPosition", "")) or "null"
    end_pos = _scrub(loc.get("endPosition", "")) or "null"
    strand = _scrub(loc.get("strand", "")) or "null"

    return [
        _scrub(primary_id),
        _scrub(secondary),
        _list_literal(synonyms),
        _list_literal(crossrefs),
        _scrub(gene.get("name", "")),
        _scrub(gene.get("symbol", "")),
        _scrub(gene.get("geneSynopsis", "")),
        "",  # Auto Description — not in BGI
        _scrub(bge.get("taxonId", "")),
        chromosome,
        start_pos,
        end_pos,
        strand,
        _scrub(so_term),
    ]


def emit_tsv(input_files: list[Path], out_path: Path, so_names: dict[str, str]) -> int:
    """Write header + every gene row to out_path. Returns row count."""
    rows_written = 0
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(HEADER) + "\n")
        for f in input_files:
            logger.info("Reading %s", f.name)
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Skipping %s: %s", f.name, exc)
                continue
            genes = payload.get("data") or []
            for g in genes:
                if not isinstance(g, dict):
                    continue
                fh.write("\t".join(row_for_gene(g, so_names)) + "\n")
                rows_written += 1
    tmp.replace(out_path)
    return rows_written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build 14-column Gene.tsv from BGI_*.json files",
    )
    parser.add_argument(
        "--data-dir",
        default="/root/data/genes",
        help="Directory holding BGI_*.json (default: /root/data/genes)",
    )
    parser.add_argument(
        "--out",
        default="Gene.tsv",
        help="Output filename inside data-dir (default: Gene.tsv)",
    )
    parser.add_argument(
        "--so-obo",
        default="/root/data/fms/ONTOLOGY_SO.obo",
        help="Sequence Ontology OBO for SO ID -> name translation",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        logger.error("Data dir does not exist: %s", data_dir)
        return 1

    bgi_files = sorted(data_dir.glob("BGI_*.json"))
    if not bgi_files:
        logger.error("No BGI_*.json found in %s", data_dir)
        return 1

    so_names = load_so_id_to_name(Path(args.so_obo))

    out_path = data_dir / args.out
    n = emit_tsv(bgi_files, out_path, so_names)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    logger.info("Wrote %d rows to %s (%.1f MB)", n, out_path, size_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())

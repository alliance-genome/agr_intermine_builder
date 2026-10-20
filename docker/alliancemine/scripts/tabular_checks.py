"""Checks for the tab-delimited inputs: gene2pubmed, PANTHER, OrthoDB, KEGG, Reactome and the
Alliance API / FMS TSVs (used by check_downloads.py).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from alliance_idmap import ALLIANCE_TAXA
from download_checks import (
    FAIL,
    GENE_CURIE,
    OK,
    WARN,
    Checker,
    Result,
    Source,
    check_yeast_taxon,
    lines,
    report_curies,
    report_taxa,
    scan_limit,
    taxa_list,
)

SPECIES_TO_TAXON = {
    "Saccharomyces cerevisiae": "559292",
    "Homo sapiens": "9606",
    "Mus musculus": "10090",
    "Rattus norvegicus": "10116",
    "Caenorhabditis elegans": "6239",
    "Drosophila melanogaster": "7227",
    "Danio rerio": "7955",
    "Xenopus tropicalis": "8364",
    "Xenopus laevis": "8355",
}


KEGG_ORG_BY_TAXON = {
    "4932": "sce",
    "9606": "hsa",
    "10090": "mmu",
    "10116": "rno",
    "6239": "cel",
    "7227": "dme",
    "7955": "dre",
}


PANTHER_SPECIES = {
    "YEAST": "559292",
    "HUMAN": "9606",
    "MOUSE": "10090",
    "RAT": "10116",
    "CAEEL": "6239",
    "DROME": "7227",
    "DANRE": "7955",
    "XENTR": "8364",
    "XENLA": "8355",
}


MIN_ROWS = {
    "alphafold.tsv": 40_000,
    "string-interactions.tsv": 1_000_000,
    "chembl-targets.tsv": 1_500,
    "molecules.tsv": 3_000,
    "crispr-screens.tsv": 1_000,
    "htp-datasets.tsv": 10_000,
    "htp-samples.tsv": 100_000,
    "mouse-strains.tsv": 50_000,
    "worm-rnai.tsv": 6_000,
}


def tsv_rows(path: Path, limit: int | None) -> Iterator[list[str]]:
    for line in lines(path, limit):
        if line.startswith("#") or not line.strip():
            continue
        yield line.rstrip("\n").split("\t")


def check_pubmed_gene(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        counts: Counter = Counter()
        ids, bad = [], 0
        for cols in tsv_rows(path, scan_limit(checker, path)):
            if len(cols) != 3:
                bad += 1
                continue
            counts[cols[0]] += 1
            ids.append(cols[1])
        if bad:
            result.add(FAIL, f"{bad} rows without 3 columns")
        report_taxa(result, counts, taxa_list(source, "pubmed.organisms"), False)
        report_curies(checker, result, ids, "gene2pubmed")
        check_yeast_taxon(source, result, "pubmed.organisms", bool(counts.get("559292")))


def check_panther(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        counts: Counter = Counter()
        ids, bad = [], 0
        for cols in tsv_rows(path, scan_limit(checker, path)):
            if len(cols) < 5:
                bad += 1
                continue
            for gene in cols[:2]:
                parts = gene.split("|")
                counts[PANTHER_SPECIES.get(parts[0], parts[0])] += 1
                ids.append(parts[1].rpartition("=")[2] if len(parts) > 1 else "")
        if bad:
            result.add(FAIL, f"{bad} rows with fewer than 5 columns")
        unknown = [s for s in counts if s not in ALLIANCE_TAXA]
        if unknown:
            result.add(FAIL, f"species the organism repository may not know: {unknown}")
        report_taxa(result, counts, list(ALLIANCE_TAXA), False)
        report_curies(checker, result, ids, "PANTHER")
        check_yeast_taxon(source, result, "panther.organisms", bool(counts.get("559292")))


def check_orthodb(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    organisms = taxa_list(source, "orthodb.organisms")
    for path in files:
        counts: Counter = Counter()
        ids, bad = [], 0
        for cols in tsv_rows(path, scan_limit(checker, path)):
            match = re.search(r"species:(\d+);", cols[4]) if len(cols) >= 9 else None
            if not match:
                bad += 1
                continue
            counts[match.group(1)] += 1
            ids.append(cols[3])
        if bad:
            result.add(FAIL, f"{bad} rows not in the 9-column OrthoDB layout")
        report_taxa(result, counts, organisms, False)
        report_curies(checker, result, ids, "OrthoDB")
    if "6239" in organisms:
        result.add(WARN, "orthodb.organisms lists 6239; the converter keys worm genes on "
                   "secondaryIdentifier (orthodb_config.properties) and the data omits worm")  # fmt: skip


def check_kegg(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    by_name = {p.name: p for p in files}
    titles = by_name.get("map_title.tab")
    if titles is None:
        result.add(FAIL, "map_title.tab missing")
    else:
        bad = sum(1 for cols in tsv_rows(titles, None) if len(cols) < 2)
        result.add(FAIL if bad else OK, f"map_title.tab: {bad} rows without 2 columns")
    organisms = taxa_list(source, "kegg.organisms")
    if "559292" in organisms:
        result.add(WARN, "kegg.organisms lists 559292; kegg_config.properties maps sce to 4932, "
                   "so yeast needs 4932")  # fmt: skip
    for taxon in organisms:
        org = KEGG_ORG_BY_TAXON.get(taxon)
        if org is None:
            continue
        path = by_name.get(f"{org}_gene_map.tab")
        if path is None:
            result.add(FAIL, f"{org}_gene_map.tab missing for taxon {taxon}")
            continue
        rows = list(tsv_rows(path, None))
        if not rows:
            result.add(FAIL, f"{org}_gene_map.tab has no rows")
            continue
        genes = [cols[0].removeprefix("Dmel_") for cols in rows]
        if len(set(genes)) != len(genes):
            result.add(FAIL, f"{org}_gene_map.tab lists a gene twice (the converter aborts)")
        if org == "dme" and not all(cols[0].startswith("Dmel_") for cols in rows):
            result.add(FAIL, "dme genes must start with Dmel_")
        result.add(OK, f"{org}_gene_map.tab: {len(rows)} genes")
        report_curies(checker, result, genes, f"KEGG {org}")


def check_reactome(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        counts: Counter = Counter()
        bad = 0
        for line in lines(path, None):
            cols = line.rstrip("\n").split("\t")
            if len(cols) != 6:
                bad += 1
                continue
            counts[SPECIES_TO_TAXON.get(cols[5], cols[5])] += 1
        if bad:
            result.add(FAIL, f"{path.name}: {bad} lines without exactly 6 columns (load aborts)")
        report_taxa(result, counts, taxa_list(source, "reactome.organisms"), False)
        check_yeast_taxon(source, result, "reactome.organisms", bool(counts.get("559292")))


def check_tsv(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    """Alliance API / FMS TSVs: consistent columns, taxon counts and gene CURIE coverage."""
    for path in files:
        limit = scan_limit(checker, path)
        widths: Counter = Counter()
        taxa: Counter = Counter()
        gene_ids: list[str] = []
        rows = 0
        for cols in tsv_rows(path, limit):
            rows += 1
            widths[len(cols)] += 1
            for value in cols:
                if value.startswith("NCBITaxon:"):
                    taxa[value.split(":", 1)[1]] += 1
                elif GENE_CURIE.match(value):
                    gene_ids.append(value)
        scope = "sampled" if limit else "total"
        result.add(OK, f"{path.name}: {rows} rows ({scope})")
        minimum = MIN_ROWS.get(path.name)
        if minimum and not limit and rows < minimum:
            result.add(FAIL, f"{path.name}: {rows} rows, fewer than the expected {minimum}")
        if len(widths) > 1:
            common = widths.most_common(1)[0]
            odd = rows - common[1]
            result.add(WARN, f"{path.name}: {odd} rows differ from {common[0]} columns")
        if taxa:
            report_taxa(result, taxa, [], bool(limit))
        if gene_ids and checker.idmap is not None:
            valid = sum(1 for i in gene_ids if checker.idmap.has_curie(i))
            result.add(OK, f"gene-like CURIEs in ID map: {100 * valid / len(gene_ids):.1f}%")

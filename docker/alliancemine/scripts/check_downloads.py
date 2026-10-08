#!/usr/bin/env python3
"""Check that every active source in a project.xml has the data its loader expects.

For each <source>: the src.data.dir / src.data.file exists and is non-empty, include patterns
match at least one file, files are not gzip (the file converters read plain text), and the
first records look like what the loader parses (per-type sniff: FASTA, OBO, GAF, GFF, UniProt /
InterPro / keyword XML, the flat TSV layouts, Alliance TSVs). Where it is cheap it counts rows
per taxon, and for the files whose gene IDs were rewritten to Alliance CURIEs it reports the
fraction of gene IDs that are CURIEs present in the gene ID map. Sources that read nothing
from disk (SGD database, entrez-organism, update-publications) are reported as RUNTIME.

Exit status is 1 if any source FAILs. Standard library only; runs inside the build container.

Usage:
    python3 check_downloads.py --project-xml /root/alliancemine/project.xml
    python3 check_downloads.py --project-xml project.xml --data-root /tmp/dl --json report.json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

from alliance_idmap import ALLIANCE_TAXA, TAXON_PREFIX, GeneIdMap, load_or_build

CONTAINER_DATA_ROOT = "/root/data"
OK, WARN, FAIL, RUNTIME = "OK", "WARN", "FAIL", "RUNTIME"
SEVERITY = {OK: 0, RUNTIME: 0, WARN: 1, FAIL: 2}
GZIP_MAGIC = b"\x1f\x8b"
FULL_SCAN_BYTES = 512 * 1024 * 1024
CURIE_FAIL_BELOW = 0.95
CURIE_WARN_BELOW = 0.995

GENE_CURIE = re.compile(
    r"^(HGNC:\d+|MGI:\d+|RGD:\d+|ZFIN:ZDB-GENE-[\d-]+|FB:FBgn\d+|WB:WBGene\d+|SGD:S\d+"
    r"|Xenbase:XB-GENE-\d+)$"
)
YEAST_UPSTREAM_TAXON = "4932"
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
PROTEIN2IPR_MEMBER_PREFIXES = (
    "PF", "SM", "SSF", "SFLD", "PS", "PR", "PTHR", "G3DSA", "TIGR", "PD", "PIRSF", "MF_", "cd",
)  # fmt: skip
OBO_TYPES = {
    "do", "go", "eco", "mmo", "emapa", "zfa", "wbbt", "fbbt", "so", "psi-mi-ontology",
    "go-slim", "hpo", "mpo", "pato",
}  # fmt: skip


@dataclass
class Source:
    name: str
    type: str
    props: dict[str, str]


@dataclass
class Result:
    source: str
    type: str
    status: str = OK
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, status: str, note: str) -> None:
        if SEVERITY[status] > SEVERITY[self.status]:
            self.status = status
        self.notes.append(f"{status}: {note}" if status in (WARN, FAIL) else note)


@dataclass
class Checker:
    data_root: Path
    idmap: GeneIdMap | None
    sample_lines: int
    deep: bool
    flat_report: dict

    def remap(self, location: str) -> Path:
        if location.startswith(CONTAINER_DATA_ROOT):
            return self.data_root / location[len(CONTAINER_DATA_ROOT) :].lstrip("/")
        return Path(location)


def parse_project(path: Path) -> list[Source]:
    root = ET.parse(path).getroot()
    sources = []
    for element in root.iter("source"):
        props = {
            p.get("name", ""): p.get("value") if p.get("value") is not None else p.get("location")
            for p in element.findall("property")
        }
        sources.append(Source(element.get("name", ""), element.get("type", ""), props))
    return sources


def head_bytes(path: Path, size: int = 4096) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(size)


def tail_bytes(path: Path, size: int = 4096) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(max(0, path.stat().st_size - size))
        return handle.read()


def lines(path: Path, limit: int | None) -> Iterator[str]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield from islice(handle, limit) if limit else handle


def scan_limit(checker: Checker, path: Path) -> int | None:
    """None (whole file) when cheap or --deep, else the sample size."""
    if checker.deep or path.stat().st_size <= FULL_SCAN_BYTES:
        return None
    return checker.sample_lines


def taxa_list(source: Source, prop: str) -> list[str]:
    return (source.props.get(prop) or "").split()


# ---------------------------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------------------------


def resolve_files(checker: Checker, source: Source, result: Result) -> list[Path] | None:
    """Files the loader will read, or None when the source reads nothing from disk."""
    data_file = source.props.get("src.data.file")
    data_dir = source.props.get("src.data.dir")
    if data_file is not None and not data_dir:
        if not data_file.startswith("/"):
            return None
        path = checker.remap(data_file)
        if not path.is_file():
            result.add(FAIL, f"src.data.file {path} missing")
            return []
        return [path]
    if not data_dir:
        return None
    directory = checker.remap(data_dir)
    if not directory.is_dir():
        result.add(FAIL, f"src.data.dir {directory} missing")
        return []
    include_prop = next(
        (p for p in ("src.data.dir.includes", "fasta.includes") if p in source.props), None
    )
    candidates = sorted(
        p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    leftovers = [p.name for p in candidates if p.name.endswith(".tmp")]
    if leftovers:
        result.add(WARN, f"unfinished downloads in {directory}: {', '.join(leftovers)}")
    if include_prop is None:
        return [p for p in candidates if not p.name.endswith(".tmp")]
    patterns = (source.props.get(include_prop) or "").replace(",", " ").split()
    if not patterns:
        result.add(FAIL, f"{include_prop} is empty")
        return []
    matched = [p for p in candidates if any(fnmatch.fnmatch(p.name, pat) for pat in patterns)]
    if not matched:
        result.add(FAIL, f"{include_prop}={' '.join(patterns)} matches nothing in {directory}")
    return matched


def check_common(files: list[Path], result: Result) -> list[Path]:
    """Existence, size and gzip checks; returns the files worth sniffing."""
    usable = []
    for path in files:
        if path.stat().st_size == 0:
            result.add(FAIL, f"{path.name} is empty")
            continue
        if head_bytes(path, 2) == GZIP_MAGIC:
            result.add(FAIL, f"{path.name} is gzip-compressed; the loader reads plain text")
            continue
        usable.append(path)
    return usable


# ---------------------------------------------------------------------------------------------
# ID checks
# ---------------------------------------------------------------------------------------------


def report_curies(checker: Checker, result: Result, ids: list[str], what: str) -> None:
    if not ids:
        result.add(WARN, f"no {what} gene IDs found to check")
        return
    if checker.idmap is None:
        result.add(WARN, f"no gene ID map; {len(ids)} {what} gene IDs not checked")
        return
    valid = sum(1 for i in ids if GENE_CURIE.match(i) and checker.idmap.has_curie(i))
    fraction = valid / len(ids)
    status = OK
    if fraction < CURIE_FAIL_BELOW:
        status = FAIL
    elif fraction < CURIE_WARN_BELOW:
        status = WARN
    result.add(status, f"{what} gene IDs in ID map: {valid}/{len(ids)} ({100 * fraction:.1f}%)")


def report_taxa(result: Result, counts: Counter, expected: list[str], sampled: bool) -> None:
    label = "rows per taxon (sample)" if sampled else "rows per taxon"
    result.add(OK, f"{label}: " + ", ".join(f"{t}={counts[t]}" for t in sorted(counts)))
    expected = ["559292" if t == YEAST_UPSTREAM_TAXON else t for t in expected]
    missing = [t for t in expected if not counts.get(t)]
    if missing and not sampled:
        result.add(WARN, f"no rows for taxa {' '.join(missing)}")


def report_flat_stats(checker: Checker, source: Source, result: Result) -> None:
    entry = checker.flat_report.get(source.name) or checker.flat_report.get(source.type)
    if not entry:
        return
    if entry.get("status") != "ok":
        result.add(FAIL, f"last download failed: {entry.get('error', 'unknown error')}")
    if entry.get("sample"):
        result.add(WARN, f"downloaded in sample mode ({entry['sample']} records per file)")
    rewrites = entry.get("gene_ids") or {}
    if rewrites:
        parts = []
        for taxon, counts in sorted(rewrites.items()):
            total = counts["mapped"] + counts["unmapped"]
            pct = 100.0 * counts["mapped"] / total if total else 0.0
            parts.append(f"{taxon}={pct:.0f}%")
        result.add(OK, "rewrite mapped: " + " ".join(parts))


def check_yeast_taxon(source: Source, result: Result, prop: str, has_yeast: bool) -> None:
    organisms = taxa_list(source, prop)
    if has_yeast and YEAST_UPSTREAM_TAXON not in organisms:
        result.add(
            WARN,
            f"yeast rows present but {prop} lacks 4932; the converter maps yeast to 4932 and "
            "will skip them",
        )


# ---------------------------------------------------------------------------------------------
# Per-type checks
# ---------------------------------------------------------------------------------------------


def check_fasta(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        first = head_bytes(path, 1)
        if first != b">":
            result.add(FAIL, f"{path.name} does not start with '>'")
            continue
        if source.props.get("fasta.className", "").endswith(".Protein"):
            counts = Counter(
                m.group(1)
                for line in lines(path, None)
                if line.startswith(">")
                for m in [re.search(r" OX=(\d+)", line)]
                if m
            )
            report_taxa(result, counts, list(ALLIANCE_TAXA), sampled=False)
            check_yeast_taxon(source, result, "fasta.taxonId", bool(counts.get("559292")))
        else:
            result.add(OK, f"{path.name}: {path.stat().st_size:,} bytes")


def check_obo(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        head = "".join(lines(path, 200))
        if "format-version:" not in head and "[Term]" not in head:
            result.add(FAIL, f"{path.name} does not look like OBO")
        else:
            result.add(OK, f"{path.name}: OBO, {path.stat().st_size:,} bytes")


def check_gaf(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        if not head_bytes(path, 32).startswith(b"!gaf-version"):
            result.add(FAIL, f"{path.name} lacks a !gaf-version header")
    result.add(OK, f"{len(files)} GAF files")


def check_xml_file(path: Path, root_close: bytes, result: Result) -> bool:
    if not head_bytes(path, 64).lstrip().startswith(b"<?xml"):
        result.add(FAIL, f"{path.name} does not start with <?xml")
        return False
    if root_close not in tail_bytes(path):
        result.add(FAIL, f"{path.name} is truncated (no {root_close.decode()})")
        return False
    return True


UNIPROT_GENE_ID = {
    "9606": re.compile(r'<dbReference type="GeneID" id="([^"]+)"'),
    "10090": re.compile(r'<dbReference type="MGI" id="([^"]+)"'),
    "10116": re.compile(r'<dbReference type="RGD" id="([^"]+)"'),
    "7227": re.compile(r'<dbReference type="FlyBase" id="([^"]+)"'),
    "559292": re.compile(r'<dbReference type="SGD" id="([^"]+)"'),
}
UNIPROT_GENE_PROPERTY = re.compile(r'<property type="gene ID" value="([^"]+)"')


def uniprot_gene_ids(path: Path, taxon: str, limit: int | None) -> tuple[list[str], int]:
    ids: list[str] = []
    entries = 0
    pattern = UNIPROT_GENE_ID.get(taxon, UNIPROT_GENE_PROPERTY)
    for line in lines(path, limit):
        if "<entry " in line:
            entries += 1
        match = pattern.search(line)
        if match:
            value = match.group(1)
            if taxon == "6239" and not value.startswith("WB:"):
                continue
            ids.append(f"RGD:{value}" if taxon == "10116" else value)
    return ids, entries


def check_uniprot(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    by_name = {p.name: p for p in files}
    for taxon in taxa_list(source, "uniprot.organisms"):
        for label, required in (("sprot", True), ("trembl", False)):
            path = by_name.get(f"{taxon}_uniprot_{label}.xml")
            if path is None:
                result.add(FAIL if required else WARN, f"{taxon}_uniprot_{label}.xml missing")
                continue
            if not check_xml_file(path, b"</uniprot>", result):
                continue
            limit = scan_limit(checker, path)
            ids, entries = uniprot_gene_ids(path, taxon, limit)
            scope = "sample" if limit else "all"
            result.add(OK, f"{path.name}: {entries} entries ({scope})")
            if entries == 0:
                result.add(FAIL if required else WARN, f"{path.name} has no entries")
            if taxon in UNIPROT_GENE_ID or taxon == "6239":
                report_curies(checker, result, ids, f"{taxon} {label}")
    stray = [p.name for p in files if p.name.endswith(".xml") and "_uniprot_" in p.name]
    wanted = {f"{t}_uniprot_{lab}.xml" for t in taxa_list(source, "uniprot.organisms")
              for lab in ("sprot", "trembl")}  # fmt: skip
    extra = sorted(set(stray) - wanted)
    if extra:
        result.add(WARN, f"files for taxa not in uniprot.organisms: {', '.join(extra)}")


def check_keywords(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        if check_xml_file(path, b"</keywordList>", result):
            result.add(OK, f"{path.name}: {path.stat().st_size:,} bytes")


def check_interpro(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    if [p.name for p in files] != ["interpro.xml"]:
        result.add(FAIL, f"dir must hold only interpro.xml, found {[p.name for p in files]}")
    for path in files:
        if not check_xml_file(path, b"</interprodb>", result):
            continue
        bad = 0
        with open(path, "rb") as handle:
            for line in handle:
                try:
                    line.decode("utf-8")
                except UnicodeDecodeError:
                    bad += 1
        result.add(FAIL if bad else OK, f"{path.name}: {bad} lines with invalid UTF-8")


def check_protein2ipr(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        bad_cols = unknown = rows = 0
        for line in lines(path, scan_limit(checker, path)):
            cols = line.rstrip("\n").split("\t")
            rows += 1
            if len(cols) != 6:
                bad_cols += 1
            elif not cols[3].startswith(PROTEIN2IPR_MEMBER_PREFIXES):
                unknown += 1
        result.add(OK, f"{path.name}: {rows} rows checked")
        if bad_cols:
            result.add(FAIL, f"{bad_cols} rows without 6 columns")
        if unknown:
            result.add(FAIL, f"{unknown} rows with member DBs Protein2iprConverter rejects")
    organisms = taxa_list(source, "protein2ipr.organisms")
    if "559292" in organisms and YEAST_UPSTREAM_TAXON not in organisms:
        result.add(WARN, "protein2ipr.organisms lacks 4932; UniProt loads yeast proteins as 4932")


def check_interpro_go(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        bad = [line for line in lines(path, None) if not line.startswith("InterPro:")]
        result.add(FAIL if bad else OK, f"{path.name}: {len(bad)} lines not 'InterPro:... ; GO:'")


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
        if len(widths) > 1:
            common = widths.most_common(1)[0]
            odd = rows - common[1]
            result.add(WARN, f"{path.name}: {odd} rows differ from {common[0]} columns")
        if taxa:
            report_taxa(result, taxa, [], bool(limit))
        if gene_ids and checker.idmap is not None:
            valid = sum(1 for i in gene_ids if checker.idmap.has_curie(i))
            result.add(OK, f"gene-like CURIEs in ID map: {100 * valid / len(gene_ids):.1f}%")


def check_generic(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        name = path.name.lower()
        if name.endswith((".gff", ".gff3")) and not head_bytes(path, 16).startswith(b"##gff"):
            result.add(FAIL, f"{path.name} lacks a ##gff-version header")
        elif name.endswith(".obo"):
            check_obo(checker, source, [path], result)
    total = sum(p.stat().st_size for p in files)
    result.add(OK, f"{len(files)} files, {total:,} bytes")


CHECKS: dict[str, Callable[[Checker, Source, list[Path], Result], None]] = {
    "fasta": check_fasta,
    "uniprot": check_uniprot,
    "uniprot-keywords": check_keywords,
    "interpro": check_interpro,
    "protein2ipr": check_protein2ipr,
    "interpro-go": check_interpro_go,
    "pubmed-gene": check_pubmed_gene,
    "panther": check_panther,
    "orthodb": check_orthodb,
    "kegg-pathway": check_kegg,
    "reactome": check_reactome,
    "go-annotation": check_gaf,
}


def check_source(checker: Checker, source: Source) -> Result:
    result = Result(source.name, source.type)
    files = resolve_files(checker, source, result)
    if files is None:
        result.status = RUNTIME
        result.notes.append("reads no files (database or fetched at load time)")
        return result
    result.files = files
    if not files:
        if result.status == OK:
            result.add(FAIL, "no input files")
        return result
    usable = check_common(files, result)
    if not usable:
        return result
    if source.type in CHECKS:
        check = CHECKS[source.type]
    elif source.type in OBO_TYPES:
        check = check_obo
    elif all(p.suffix in (".tsv", ".tab", ".txt") for p in usable):
        check = check_tsv
    else:
        check = check_generic
    check(checker, source, usable, result)
    report_flat_stats(checker, source, result)
    return result


def render(results: list[Result]) -> str:
    rows = [("SOURCE", "TYPE", "STATUS", "FILES", "DETAIL")]
    for r in results:
        rows.append((r.source, r.type, r.status, str(len(r.files)), "; ".join(r.notes)))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    out = []
    for row in rows:
        out.append("  ".join(row[i].ljust(widths[i]) for i in range(4)) + "  " + row[4])
    counts = Counter(r.status for r in results)
    out.append("")
    out.append("  ".join(f"{status}={counts[status]}" for status in (OK, WARN, FAIL, RUNTIME)))
    return "\n".join(out)


def load_idmap(data_root: Path, explicit: Path | None) -> GeneIdMap | None:
    cache = explicit or data_root / "idmap" / "gene_idmap.tsv"
    if cache.exists() and explicit:
        return GeneIdMap.read_tsv(cache)
    try:
        return load_or_build(data_root / "genes", cache)
    except FileNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check downloaded data against project.xml")
    parser.add_argument("--project-xml", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path(CONTAINER_DATA_ROOT))
    parser.add_argument("--idmap", type=Path, help="Gene ID map TSV (default: <root>/idmap/...)")
    parser.add_argument("--only", help="Comma-separated source names to check")
    parser.add_argument("--sample-lines", type=int, default=200_000)
    parser.add_argument("--deep", action="store_true", help="Scan whole files, however large")
    parser.add_argument("--json", type=Path, help="Also write the results as JSON")
    args = parser.parse_args()

    report_path = args.data_root / "flatfiles_report.json"
    flat_report = json.loads(report_path.read_text()) if report_path.exists() else {}
    checker = Checker(
        data_root=args.data_root,
        idmap=load_idmap(args.data_root, args.idmap),
        sample_lines=args.sample_lines,
        deep=args.deep,
        flat_report=flat_report,
    )
    sources = parse_project(args.project_xml)
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s.name in wanted]
    results = [check_source(checker, s) for s in sources]
    print(render(results))
    if checker.idmap is None:
        print("note: no gene ID map found; CURIE checks were skipped")
    else:
        taxa = ", ".join(f"{t}={n}" for t, n in sorted(checker.idmap.taxon_counts().items()))
        print(f"gene ID map: {len(checker.idmap)} genes ({taxa})")
        missing = [t for t in TAXON_PREFIX if t not in checker.idmap.taxon_counts()]
        if missing:
            print(f"note: gene ID map has no genes for taxa {' '.join(missing)}")
    if args.json:
        payload = [{**r.__dict__, "files": [str(p) for p in r.files]} for r in results]
        args.json.write_text(json.dumps(payload, indent=2))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

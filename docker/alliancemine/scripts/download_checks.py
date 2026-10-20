"""Per-type content checks used by check_downloads.py: sniff each source's files the way its
InterMine 5.1.0 loader will read them, count rows per taxon and measure gene CURIE coverage.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

from alliance_idmap import ALLIANCE_TAXA, GeneIdMap

CONTAINER_DATA_ROOT = "/root/data"
OK, WARN, FAIL, RUNTIME = "OK", "WARN", "FAIL", "RUNTIME"
SEVERITY = {OK: 0, RUNTIME: 0, WARN: 1, FAIL: 2}
GZIP_MAGIC = b"\x1f\x8b"
FULL_SCAN_BYTES = 512 * 1024 * 1024
CURIE_FAIL_BELOW = 0.95
CURIE_WARN_BELOW = 0.995
REWRITE_FAIL_BELOW = 0.90
REWRITE_WARN_BELOW = 0.99

GENE_CURIE = re.compile(
    r"^(HGNC:\d+|MGI:\d+|RGD:\d+|ZFIN:ZDB-GENE-[\d-]+|FB:FBgn\d+|WB:WBGene\d+|SGD:S\d+"
    r"|Xenbase:XB-GENE-\d+)$"
)
YEAST_UPSTREAM_TAXON = "4932"
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
        result.add(FAIL, f"no rows for taxa {' '.join(missing)}")


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
        status = OK
        for taxon, counts in sorted(rewrites.items()):
            total = counts["mapped"] + counts["unmapped"]
            fraction = counts["mapped"] / total if total else 0.0
            parts.append(f"{taxon}={100 * fraction:.0f}%")
            if fraction < REWRITE_FAIL_BELOW:
                status = FAIL
            elif fraction < REWRITE_WARN_BELOW and status == OK:
                status = WARN
        result.add(status, "rewrite mapped: " + " ".join(parts))


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


def check_generic(checker: Checker, source: Source, files: list[Path], result: Result) -> None:
    for path in files:
        name = path.name.lower()
        if name.endswith((".gff", ".gff3")) and not head_bytes(path, 16).startswith(b"##gff"):
            result.add(FAIL, f"{path.name} lacks a ##gff-version header")
        elif name.endswith(".obo"):
            check_obo(checker, source, [path], result)
    total = sum(p.stat().st_size for p in files)
    result.add(OK, f"{len(files)} files, {total:,} bytes")

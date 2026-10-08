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
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from alliance_idmap import TAXON_PREFIX, GeneIdMap, load_or_build
from download_checks import (
    CONTAINER_DATA_ROOT,
    FAIL,
    GZIP_MAGIC,
    OBO_TYPES,
    OK,
    RUNTIME,
    WARN,
    Checker,
    Result,
    Source,
    check_fasta,
    check_gaf,
    check_generic,
    check_interpro,
    check_interpro_go,
    check_keywords,
    check_obo,
    check_protein2ipr,
    check_uniprot,
    head_bytes,
    report_flat_stats,
)
from tabular_checks import (
    check_kegg,
    check_orthodb,
    check_panther,
    check_pubmed_gene,
    check_reactome,
    check_tsv,
)


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

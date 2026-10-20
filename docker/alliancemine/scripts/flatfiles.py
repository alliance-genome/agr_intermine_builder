#!/usr/bin/env python3
"""Download the Phase-6 flat files for the InterMine-core bio-sources (B7/B8).

Each source is streamed from upstream, restricted to the AllianceMine taxa, rewritten to what
the InterMine 5.1.0 converter reads (see flatfile_rewriters.py) and written atomically under
<data-dir>/<source>/current/. Multi-GB inputs (UniProt, protein2ipr, OrthoDB, PANTHER,
gene2pubmed) are filtered while streaming; the unfiltered files are never written.

A run writes <data-dir>/flatfiles_report.json with per-source status and per-taxon mapped /
unmapped gene ID counts, which check_downloads.py shows next to its own checks.

Usage:
    python3 flatfiles.py --data-dir /root/data
    python3 flatfiles.py --data-dir /tmp/dl --sources kegg-pathway,reactome --sample 2000
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import sys
import tarfile
import time
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import flatfile_rewriters as rw
from alliance_idmap import ALLIANCE_TAXA, GeneIdMap, RewriteStats, load_or_build

logger = logging.getLogger("flatfiles")

USER_AGENT = "agr-intermine-builder (AllianceMine data download)"
HTTP_TIMEOUT = 600
HTTP_ATTEMPTS = 3

UNIPROT_REST = "https://rest.uniprot.org/uniprotkb"
UNIPROT_FTP = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete"
INTERPRO_FTP = "https://ftp.ebi.ac.uk/pub/databases/interpro/current_release"
INTERPRO2GO_URL = "https://ftp.ebi.ac.uk/pub/databases/GO/goa/external2go/interpro2go"
GENE2PUBMED_URL = "https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2pubmed.gz"
PANTHER_FTP = "https://data.pantherdb.org/ftp/ortholog/current_release"
ORTHODB_DUMP = "https://data.orthodb.org/v12/download/odb_data_dump"
KEGG_REST = "https://rest.kegg.jp"
REACTOME_URL = "https://reactome.org/download/current/UniProt2Reactome_All_Levels.txt"

PANTHER_FILE = os.environ.get("PANTHER_ORTHOLOG_FILE", "AllOrthologs")
ORTHODB_VERSION = os.environ.get("ORTHODB_VERSION", "odb12v2")
ORTHODB_LEVEL = os.environ.get("ORTHODB_LEVEL", "2759")
ORTHODB_MAX_GROUP = int(os.environ.get("ORTHODB_MAX_GROUP", "200"))
KEGG_REQUEST_GAP = 0.5

DOWNLOAD_ERRORS = (OSError, URLError, HTTPError, EOFError, zlib.error, tarfile.TarError, ValueError)

STALE_FILES = {
    "uniprot/current": ["uniprot_sprot.xml.gz", "uniprot_sprot_varsplic.fasta.gz"],
    "interpro/current": ["interpro.xml.gz"],
    "interpro/match_complete/current": ["protein2ipr.dat.gz"],
    "reactome/current": [
        "Ensembl2Reactome_All_Levels.txt",
        "ReactomePathways.txt",
        "ReactomePathwaysRelation.txt",
    ],
}


@dataclass
class Context:
    data_dir: Path
    idmap: GeneIdMap
    sample: int | None = None
    force: bool = False
    report: dict = field(default_factory=dict)
    idmap_hash: str = ""

    def path(self, relative: str) -> Path:
        return self.data_dir / relative

    def limit(self, items: Iterable) -> Iterable:
        return islice(items, self.sample) if self.sample else items

    def meta(self) -> dict:
        return {"idmap_sha256": self.idmap_hash, "sample": self.sample}

    def stamp(self, *paths: Path) -> None:
        """Record the ID map hash and sample flag the outputs were written with."""
        for p in paths:
            meta_path(p).write_text(json.dumps(self.meta(), sort_keys=True), encoding="utf-8")

    def cached(self, *paths: Path) -> bool:
        if self.force:
            return False
        return all(p.exists() and p.stat().st_size > 0 and self.stamped(p) for p in paths)

    def stamped(self, path: Path) -> bool:
        try:
            recorded = json.loads(meta_path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return recorded == self.meta()


def meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_url(url: str) -> IO[bytes]:
    for attempt in range(1, HTTP_ATTEMPTS + 1):
        try:
            logger.info("  GET %s", url)
            return urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=HTTP_TIMEOUT)
        except (HTTPError, URLError, OSError) as exc:
            if attempt == HTTP_ATTEMPTS:
                raise
            logger.warning("  %s (attempt %d/%d), retrying", exc, attempt, HTTP_ATTEMPTS)
            time.sleep(10 * attempt)
    raise URLError(url)


def text_lines(stream: IO[bytes], gz: bool = False) -> Iterator[str]:
    raw = gzip.GzipFile(fileobj=stream) if gz else stream
    yield from io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


def byte_lines(stream: IO[bytes], gz: bool = False) -> Iterator[bytes]:
    yield from gzip.GzipFile(fileobj=stream) if gz else stream


def write_atomic(dest: Path, lines: Iterable, binary: bool = False) -> int:
    """Write lines to dest via a temporary file; returns the number of lines written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    count = 0
    with open(tmp, "wb" if binary else "w", encoding=None if binary else "utf-8") as out:
        for line in lines:
            out.write(line)
            count += 1
    tmp.replace(dest)
    logger.info("  -> %s (%d lines, %s bytes)", dest, count, f"{dest.stat().st_size:,}")
    return count


def remove_stale(ctx: Context) -> None:
    for relative, names in STALE_FILES.items():
        for name in names:
            stale = ctx.path(relative) / name
            if stale.exists():
                logger.info("  removing stale %s", stale)
                stale.unlink()


# ---------------------------------------------------------------------------------------------
# UniProt
# ---------------------------------------------------------------------------------------------


def uniprot_url(taxon: str, reviewed: bool, sample: int | None) -> str:
    query = f"organism_id:{taxon} AND reviewed:{'true' if reviewed else 'false'}"
    params = {"compressed": "true", "format": "xml", "query": query}
    if sample:
        return f"{UNIPROT_REST}/search?{urlencode({**params, 'size': str(min(sample, 500))})}"
    return f"{UNIPROT_REST}/stream?{urlencode(params)}"


def accession_file(ctx: Context, xml: Path) -> Path:
    return ctx.path("uniprot/accessions") / (xml.stem + ".txt")


def fetch_uniprot(ctx: Context) -> dict:
    stats = RewriteStats("uniprot")
    files = []
    for taxon in ALLIANCE_TAXA:
        for reviewed, label in ((True, "sprot"), (False, "trembl")):
            dest = ctx.path("uniprot/current") / f"{taxon}_uniprot_{label}.xml"
            acc_file = accession_file(ctx, dest)
            files.append(str(dest))
            if ctx.cached(dest, acc_file):
                logger.info("  cached: %s", dest)
                continue
            accessions: set[str] = set()
            with open_url(uniprot_url(taxon, reviewed, ctx.sample)) as resp:
                lines = rw.rewrite_uniprot_xml(
                    text_lines(resp, gz=True), taxon, ctx.idmap, stats, accessions
                )
                write_atomic(dest, lines)
            if not tail_contains(dest, b"</uniprot>"):
                dest.unlink()
                raise ValueError(f"{dest.name}: truncated UniProt stream (no </uniprot>)")
            write_atomic(acc_file, (f"{a}\n" for a in sorted(accessions)))
            ctx.stamp(dest, acc_file)
    stats.log()
    return {"files": files, "gene_ids": stats.summary()}


def tail_contains(path: Path, marker: bytes, size: int = 4096) -> bool:
    with open(path, "rb") as handle:
        handle.seek(max(0, path.stat().st_size - size))
        return marker in handle.read()


def fetch_uniprot_keywords(ctx: Context) -> dict:
    dest = ctx.path("uniprot/current/keywlist.xml")
    if not ctx.cached(dest):
        with open_url(f"{UNIPROT_FTP}/docs/keywlist.xml.gz") as resp:
            payload = resp.read()
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        if not payload.lstrip().startswith(b"<?xml"):
            raise ValueError("keywlist.xml is not XML after decompression")
        write_atomic(dest, [payload], binary=True)
    return {"files": [str(dest)]}


def fetch_uniprot_fasta(ctx: Context) -> dict:
    dest = ctx.path("uniprot/current/uniprot_sprot_varsplic.fasta")
    if not ctx.cached(dest):
        with open_url(f"{UNIPROT_FTP}/uniprot_sprot_varsplic.fasta.gz") as resp:
            write_atomic(dest, rw.filter_varsplic_fasta(ctx.limit(text_lines(resp, gz=True))))
    return {"files": [str(dest)]}


# ---------------------------------------------------------------------------------------------
# InterPro
# ---------------------------------------------------------------------------------------------


def fetch_interpro(ctx: Context) -> dict:
    dest = ctx.path("interpro/current/interpro.xml")
    counts = {"lines_with_invalid_utf8": 0}
    if not ctx.cached(dest):

        def clean(lines: Iterable[bytes]) -> Iterator[bytes]:
            for line in lines:
                text = line.decode("utf-8", errors="ignore")
                if len(text.encode("utf-8")) != len(line):
                    counts["lines_with_invalid_utf8"] += 1
                yield text.encode("utf-8")

        with open_url(f"{INTERPRO_FTP}/interpro.xml.gz") as resp:
            write_atomic(dest, clean(ctx.limit(byte_lines(resp, gz=True))), binary=True)
    return {"files": [str(dest)], "counts": counts}


def load_accessions(ctx: Context) -> set[bytes]:
    files = sorted(ctx.path("uniprot/accessions").glob("*.txt"))
    if not files:
        raise ValueError("no UniProt accession lists; run the uniprot download first")
    accessions: set[bytes] = set()
    for path in files:
        with open(path, "rb") as handle:
            accessions.update(line.rstrip(b"\n") for line in handle if line.strip())
    logger.info("  %d UniProt accessions from %d lists", len(accessions), len(files))
    return accessions


def fetch_protein2ipr(ctx: Context) -> dict:
    dest = ctx.path("interpro/match_complete/current/protein2ipr.dat")
    counts: dict[str, int] = {}
    if not ctx.cached(dest):
        accessions = load_accessions(ctx)
        with open_url(f"{INTERPRO_FTP}/protein2ipr.dat.gz") as resp:
            lines = rw.filter_protein2ipr(ctx.limit(byte_lines(resp, gz=True)), accessions, counts)
            write_atomic(dest, lines, binary=True)
    return {"files": [str(dest)], "counts": counts}


def fetch_interpro_go(ctx: Context) -> dict:
    dest = ctx.path("interpro/ontology/current/interpro2go")
    if not ctx.cached(dest):
        with open_url(INTERPRO2GO_URL) as resp:
            write_atomic(dest, rw.filter_interpro2go(text_lines(resp)))
    return {"files": [str(dest)]}


# ---------------------------------------------------------------------------------------------
# Gene-keyed sources
# ---------------------------------------------------------------------------------------------


def fetch_pubmed_gene(ctx: Context) -> dict:
    dest = ctx.path("pubmed/current/gene2pubmed")
    stats = RewriteStats("pubmed-gene")
    if not ctx.cached(dest):
        with open_url(GENE2PUBMED_URL) as resp:
            lines = ctx.limit(text_lines(resp, gz=True))
            write_atomic(dest, rw.rewrite_gene2pubmed(lines, ctx.idmap, stats))
        stats.log()
    return {"files": [str(dest)], "gene_ids": stats.summary()}


def tar_member_lines(stream: IO[bytes]) -> Iterator[str]:
    with tarfile.open(fileobj=stream, mode="r|gz") as tar:
        for member in tar:
            if member.isfile():
                handle = tar.extractfile(member)
                if handle is not None:
                    for line in handle:
                        yield line.decode("utf-8", errors="replace")


def fetch_panther(ctx: Context) -> dict:
    dest = ctx.path("panther/current/panther_orthologs.tsv")
    stats = RewriteStats("panther")
    if not ctx.cached(dest):
        with open_url(f"{PANTHER_FTP}/{PANTHER_FILE}.tar.gz") as resp:
            lines = ctx.limit(tar_member_lines(resp))
            write_atomic(dest, rw.rewrite_panther(lines, ctx.idmap, stats))
        stats.log()
    return {"files": [str(dest)], "gene_ids": stats.summary(), "upstream": PANTHER_FILE}


def fetch_orthodb(ctx: Context) -> dict:
    dest = ctx.path("orthodb/current/orthodb_alliance.tab")
    stats = RewriteStats("orthodb")
    counts: dict[str, int] = {}
    if not ctx.cached(dest):
        with open_url(f"{ORTHODB_DUMP}/{ORTHODB_VERSION}_genes.tab.gz") as resp:
            genes = rw.orthodb_gene_map(ctx.limit(text_lines(resp, gz=True)), ctx.idmap, stats)
        stats.log()
        with open_url(f"{ORTHODB_DUMP}/{ORTHODB_VERSION}_OG2genes.tab.gz") as resp:
            lines = rw.rewrite_orthodb(
                ctx.limit(text_lines(resp, gz=True)),
                genes,
                ORTHODB_LEVEL,
                ORTHODB_MAX_GROUP,
                counts,
            )
            write_atomic(dest, lines)
    return {
        "files": [str(dest)],
        "gene_ids": stats.summary(),
        "counts": counts,
        "level": ORTHODB_LEVEL,
        "version": ORTHODB_VERSION,
    }


def kegg_raw(ctx: Context, operation: str, name: str) -> list[str]:
    dest = ctx.path("kegg/raw") / name
    if ctx.force or not (dest.exists() and dest.stat().st_size > 0):
        time.sleep(KEGG_REQUEST_GAP)
        with open_url(f"{KEGG_REST}/{operation}") as resp:
            write_atomic(dest, text_lines(resp))
    with open(dest, encoding="utf-8") as handle:
        return list(ctx.limit(handle))


def fetch_kegg(ctx: Context) -> dict:
    current = ctx.path("kegg/current")
    stats = RewriteStats("kegg-pathway")
    files = [current / "map_title.tab"]
    write_atomic(files[0], rw.kegg_map_titles(kegg_raw(ctx, "list/pathway", "list_pathway.txt")))
    for org in rw.KEGG_ORGANISMS:
        link = kegg_raw(ctx, f"link/pathway/{org}", f"link_pathway_{org}.txt")
        conv = kegg_raw(ctx, f"conv/ncbi-geneid/{org}", f"conv_ncbi-geneid_{org}.txt")
        dest = current / f"{org}_gene_map.tab"
        write_atomic(dest, rw.kegg_gene_map(org, link, conv, ctx.idmap, stats))
        files.append(dest)
    stats.log()
    return {"files": [str(f) for f in files], "gene_ids": stats.summary()}


def fetch_reactome(ctx: Context) -> dict:
    dest = ctx.path("reactome/current/UniProt2Reactome_All_Levels.txt")
    counts: dict[str, int] = {}
    if not ctx.cached(dest):
        with open_url(REACTOME_URL) as resp:
            write_atomic(dest, rw.filter_reactome(ctx.limit(text_lines(resp)), counts))
    return {"files": [str(dest)], "counts": counts}


SOURCES: dict[str, Callable[[Context], dict]] = {
    "uniprot": fetch_uniprot,
    "uniprot-keywords": fetch_uniprot_keywords,
    "uniprot-fasta": fetch_uniprot_fasta,
    "interpro": fetch_interpro,
    "protein2ipr": fetch_protein2ipr,
    "interpro-go": fetch_interpro_go,
    "pubmed-gene": fetch_pubmed_gene,
    "orthodb": fetch_orthodb,
    "panther": fetch_panther,
    "kegg-pathway": fetch_kegg,
    "reactome": fetch_reactome,
}


def run(
    data_dir: Path,
    sources: Iterable[str] | None = None,
    sample: int | None = None,
    force: bool = False,
) -> dict[str, dict]:
    """Download the given (default: all) sources; returns the per-source report."""
    selected = list(sources) if sources else list(SOURCES)
    unknown = [s for s in selected if s not in SOURCES]
    if unknown:
        raise ValueError(f"unknown flat-file sources: {', '.join(unknown)}")
    idmap = load_or_build(data_dir / "genes", data_dir / "idmap" / "gene_idmap.tsv")
    ctx = Context(
        data_dir=data_dir,
        idmap=idmap,
        sample=sample,
        force=force,
        idmap_hash=file_sha256(data_dir / "idmap" / "gene_idmap.tsv"),
    )
    remove_stale(ctx)
    report: dict[str, dict] = {}
    for name in selected:
        logger.info("=== flat files: %s ===", name)
        started = time.time()
        try:
            entry = SOURCES[name](ctx)
            entry["status"] = "ok"
            ctx.stamp(*(Path(f) for f in entry.get("files", [])))
        except DOWNLOAD_ERRORS as exc:
            logger.error("  %s failed: %s", name, exc)
            entry = {"status": "failed", "error": str(exc)}
        entry["seconds"] = round(time.time() - started, 1)
        entry["sample"] = sample
        report[name] = entry
    write_report(data_dir / "flatfiles_report.json", report)
    return report


def write_report(path: Path, report: dict[str, dict]) -> None:
    merged: dict[str, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8") as handle:
            merged = json.load(handle)
    merged.update(report)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as out:
        json.dump(merged, out, indent=2, sort_keys=True)
    shutil.move(str(tmp), str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the Phase-6 flat files")
    parser.add_argument("--data-dir", type=Path, default=Path("/root/data"))
    parser.add_argument("--sources", help=f"Comma-separated subset of: {', '.join(SOURCES)}")
    parser.add_argument(
        "--sample",
        type=int,
        help="Read at most N upstream records per file (local format testing only)",
    )
    parser.add_argument("--force", action="store_true", help="Re-download existing outputs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    sources = args.sources.split(",") if args.sources else None
    report = run(args.data_dir, sources, args.sample, args.force)
    failed = [name for name, entry in report.items() if entry["status"] != "ok"]
    if failed:
        logger.error("Flat-file downloads failed: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

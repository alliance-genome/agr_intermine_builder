#!/usr/bin/env python3
"""Gene ID map from the release's FMS BGI files, keyed on Alliance gene CURIEs.

AllianceMine keys genes on Alliance CURIEs (HGNC:8620, MGI:97490, RGD:3258, ZFIN:ZDB-GENE-...,
FB:FBgn..., WB:WBGene..., SGD:S000..., Xenbase:XB-GENE-...). Upstream InterMine loaders key
genes on Entrez, Ensembl or prefix-less MOD IDs, so every gene-keyed flat file is rewritten
to CURIEs with this map before it is loaded (blocker B10).

Per gene the map records: taxon, prefix-less MOD ID, Entrez IDs, Ensembl gene IDs, UniProtKB
accessions, the symbol, and other IDs the MOD lists under its own prefix (e.g. SGD ORF names
such as SGD:YDR022C). Lookups return a CURIE only when the ID resolves to exactly one gene.

Usage:
    python3 alliance_idmap.py --genes-dir /root/data/genes --out /root/data/idmap/gene_idmap.tsv
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("alliance-idmap")

TAXON_PREFIX = {
    "559292": "SGD",
    "9606": "HGNC",
    "10090": "MGI",
    "10116": "RGD",
    "6239": "WB",
    "7227": "FB",
    "7955": "ZFIN",
    "8364": "Xenbase",
    "8355": "Xenbase",
}
ALLIANCE_TAXA = tuple(TAXON_PREFIX)

KINDS = ("curie", "native", "entrez", "ensembl", "uniprot", "alias", "symbol")
TSV_COLUMNS = ("curie", "taxon", "symbol", "entrez", "ensembl", "uniprot", "aliases")

_ENSEMBL_VERSION = re.compile(r"\.\d+$")


def strip_ensembl_version(value: str) -> str:
    return _ENSEMBL_VERSION.sub("", value)


def native_id(curie: str) -> str:
    """MOD ID without the Alliance prefix (MGI:97490 -> 97490, FB:FBgn0000001 -> FBgn0000001)."""
    return curie.split(":", 1)[1] if ":" in curie else curie


@dataclass
class GeneIds:
    curie: str
    taxon: str
    symbol: str = ""
    entrez: set[str] = field(default_factory=set)
    ensembl: set[str] = field(default_factory=set)
    uniprot: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)


class GeneIdMap:
    def __init__(self) -> None:
        self.genes: dict[str, GeneIds] = {}
        self._index: dict[tuple[str, str], set[str]] = defaultdict(set)

    def __len__(self) -> int:
        return len(self.genes)

    def add(self, gene: GeneIds) -> None:
        self.genes[gene.curie] = gene
        self._index[("curie", gene.curie)].add(gene.curie)
        self._index[("native", native_id(gene.curie))].add(gene.curie)
        if gene.symbol:
            self._index[("symbol", gene.symbol)].add(gene.curie)
        for kind in ("entrez", "ensembl", "uniprot"):
            for value in getattr(gene, kind):
                self._index[(kind, value)].add(gene.curie)
        for value in gene.aliases:
            self._index[("alias", value)].add(gene.curie)

    def has_curie(self, curie: str) -> bool:
        return curie in self.genes

    def taxon_of(self, curie: str) -> str | None:
        gene = self.genes.get(curie)
        return gene.taxon if gene else None

    def lookup(self, kind: str, value: str, taxon: str | None = None) -> str | None:
        """Unique CURIE for an ID of the given kind, optionally restricted to one taxon."""
        if not value:
            return None
        if kind == "ensembl":
            value = strip_ensembl_version(value)
        curies = self._index.get((kind, value))
        if not curies:
            return None
        if taxon is not None:
            curies = {c for c in curies if self.genes[c].taxon == taxon}
        return next(iter(curies)) if len(curies) == 1 else None

    def resolve(self, value: str, taxon: str | None, kinds: Iterable[str]) -> str | None:
        """First unique hit over the given ID kinds, in order."""
        for kind in kinds:
            curie = self.lookup(kind, value, taxon)
            if curie:
                return curie
        return None

    def taxon_counts(self) -> Counter:
        return Counter(g.taxon for g in self.genes.values())

    def write_tsv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as out:
            out.write("\t".join(TSV_COLUMNS) + "\n")
            genes = sorted(self.genes.values(), key=lambda g: (g.taxon, g.curie))
            out.writelines(_tsv_row(gene) for gene in genes)
        tmp.replace(path)

    @classmethod
    def read_tsv(cls, path: Path) -> GeneIdMap:
        idmap = cls()
        with open(path, encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            if tuple(header) != TSV_COLUMNS:
                raise ValueError(f"{path}: unexpected header {header}")
            for line in handle:
                cols = line.rstrip("\n").split("\t")
                idmap.add(
                    GeneIds(
                        curie=cols[0],
                        taxon=cols[1],
                        symbol=cols[2],
                        entrez=_split_set(cols[3]),
                        ensembl=_split_set(cols[4]),
                        uniprot=_split_set(cols[5]),
                        aliases=_split_set(cols[6]),
                    )
                )
        return idmap


def _tsv_row(gene: GeneIds) -> str:
    sets = (gene.entrez, gene.ensembl, gene.uniprot, gene.aliases)
    cols = [gene.curie, gene.taxon, gene.symbol] + [",".join(sorted(v)) for v in sets]
    return "\t".join(cols) + "\n"


def _split_set(value: str) -> set[str]:
    return {v for v in value.split(",") if v}


def gene_from_bgi(record: dict) -> GeneIds | None:
    """GeneIds for one BGI 'data' record, or None when it isn't one of the AllianceMine taxa."""
    entity = record.get("basicGeneticEntity") or {}
    curie = entity.get("primaryId") or ""
    taxon = (entity.get("taxonId") or "").replace("NCBITaxon:", "")
    if not curie or taxon not in TAXON_PREFIX:
        return None
    gene = GeneIds(curie=curie, taxon=taxon, symbol=record.get("symbol") or "")
    own_prefix = curie.split(":", 1)[0]
    for xref in entity.get("crossReferences") or []:
        for xref_id in (xref.get("id") or "").split("|"):
            prefix, _, value = xref_id.partition(":")
            if not value:
                continue
            if prefix == "NCBI_Gene":
                gene.entrez.add(value)
            elif prefix == "ENSEMBL":
                gene.ensembl.add(strip_ensembl_version(value))
            elif prefix == "UniProtKB":
                gene.uniprot.add(value)
            elif prefix == own_prefix and xref_id != curie:
                gene.aliases.add(value)
    return gene


def build_from_bgi(paths: Iterable[Path]) -> GeneIdMap:
    idmap = GeneIdMap()
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle).get("data") or []
        kept = 0
        for record in data:
            gene = gene_from_bgi(record)
            if gene:
                idmap.add(gene)
                kept += 1
        logger.info("%s: %d of %d genes in the AllianceMine taxa", path.name, kept, len(data))
    return idmap


def load_or_build(genes_dir: Path, cache: Path) -> GeneIdMap:
    """The cached TSV if it is newer than every BGI file, else a fresh build (and cache)."""
    bgi_files = sorted(genes_dir.glob("BGI_*.json"))
    if cache.exists() and all(cache.stat().st_mtime >= p.stat().st_mtime for p in bgi_files):
        idmap = GeneIdMap.read_tsv(cache)
        logger.info("Gene ID map: %d genes from %s", len(idmap), cache)
        return idmap
    if not bgi_files:
        raise FileNotFoundError(f"No BGI_*.json in {genes_dir} and no ID map at {cache}")
    idmap = build_from_bgi(bgi_files)
    idmap.write_tsv(cache)
    logger.info("Gene ID map: %d genes written to %s", len(idmap), cache)
    return idmap


class RewriteStats:
    """Mapped / unmapped gene identifier counts per taxon for one rewritten source."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.mapped: Counter = Counter()
        self.unmapped: Counter = Counter()

    def record(self, taxon: str, mapped: bool) -> None:
        (self.mapped if mapped else self.unmapped)[taxon] += 1

    def fraction_mapped(self) -> float:
        total = sum(self.mapped.values()) + sum(self.unmapped.values())
        return sum(self.mapped.values()) / total if total else 0.0

    def summary(self) -> dict[str, dict[str, int]]:
        taxa = sorted(set(self.mapped) | set(self.unmapped))
        return {t: {"mapped": self.mapped[t], "unmapped": self.unmapped[t]} for t in taxa}

    def log(self) -> None:
        for taxon, counts in self.summary().items():
            total = counts["mapped"] + counts["unmapped"]
            logger.info(
                "  %s taxon %s: %d/%d gene IDs mapped to CURIEs (%.1f%%), %d dropped",
                self.source,
                taxon,
                counts["mapped"],
                total,
                100.0 * counts["mapped"] / total if total else 0.0,
                counts["unmapped"],
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--genes-dir", type=Path, default=Path("/root/data/genes"))
    parser.add_argument("--out", type=Path, default=Path("/root/data/idmap/gene_idmap.tsv"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    bgi_files = sorted(args.genes_dir.glob("BGI_*.json"))
    if not bgi_files:
        logger.error("No BGI_*.json files in %s", args.genes_dir)
        return 1
    idmap = build_from_bgi(bgi_files)
    idmap.write_tsv(args.out)
    for taxon, count in sorted(idmap.taxon_counts().items()):
        logger.info("  taxon %s: %d genes", taxon, count)
    logger.info("Wrote %d genes to %s", len(idmap), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Per-source rewriters that turn upstream flat files into what the InterMine 5.1.0 converters
read, restricted to the AllianceMine taxa and with gene identifiers rewritten to Alliance
CURIEs (blocker B10). Every function works on iterables of lines so it can stream GB-sized
inputs and be unit-tested on small fixtures; downloading lives in flatfiles.py.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from alliance_idmap import ALLIANCE_TAXA, GeneIdMap, RewriteStats

SPECIES_NAME = {
    "559292": "Saccharomyces cerevisiae",
    "9606": "Homo sapiens",
    "10090": "Mus musculus",
    "10116": "Rattus norvegicus",
    "6239": "Caenorhabditis elegans",
    "7227": "Drosophila melanogaster",
    "7955": "Danio rerio",
    "8364": "Xenopus tropicalis",
    "8355": "Xenopus laevis",
}

# ---------------------------------------------------------------------------------------------
# UniProt XML (UniprotConverter + uniprot_config.properties, bio-source-uniprot 5.1.0)
#
# The converter takes the gene identifier from a dbReference (dbref) or from a property of a
# dbReference (gene-designation), per taxon. Yeast entries (559292) are mapped to taxon 4932 by
# '4932.subspecies = 559292' and then use the SGD dbref. Rat IDs get 'RGD:' prepended by the
# converter itself, so they stay bare. Zebrafish and Xenopus fall back to
# 'default.primaryIdentifier.dbref = Ensembl', which only reads Ensembl 'gene ID' properties when
# a gene-designation is configured for the taxon; none is, so those entries get no gene until the
# config is patched. Their Ensembl gene IDs and their ZFIN / Xenbase dbReference ids are rewritten
# anyway so a patched config (gene-designation or dbref) just works.
# ---------------------------------------------------------------------------------------------

UNIPROT_GENE_DBREF = {
    "9606": ("GeneID", "entrez"),
    "10090": ("MGI", "curie"),
    "10116": ("RGD", "rgd"),
    "7227": ("FlyBase", "native"),
    "559292": ("SGD", "native"),
    "7955": ("ZFIN", "native"),
    "8364": ("Xenbase", "native"),
    "8355": ("Xenbase", "native"),
}
UNIPROT_GENE_PROPERTY = {
    "6239": ("WormBase", "native"),
    "7955": ("Ensembl", "ensembl"),
    "8364": ("Ensembl", "ensembl"),
    "8355": ("Ensembl", "ensembl"),
}

_DBREF_OPEN = re.compile(r'^(\s*<dbReference type=")([^"]+)(" id=")([^"]*)(".*)$')
_GENE_ID_PROPERTY = re.compile(r'^(\s*<property type="gene ID" value=")([^"]*)(".*)$')
_ACCESSION = re.compile(r"<accession>([^<]+)</accession>")


def _uniprot_dbref_curie(idmap: GeneIdMap, kind: str, value: str, taxon: str) -> str | None:
    if kind == "rgd":
        return value if idmap.lookup("curie", f"RGD:{value}", taxon) else None
    return idmap.lookup(kind, value, taxon)


def rewrite_uniprot_xml(
    lines: Iterable[str],
    taxon: str,
    idmap: GeneIdMap,
    stats: RewriteStats,
    accessions: set[str],
) -> Iterator[str]:
    """Rewrite the gene identifiers UniprotConverter uses for this taxon to CURIEs.

    Unmapped gene dbReferences are renamed '<type>-unmapped' (the converter then finds no gene
    for them); unmapped gene-ID properties are dropped. Each entry's primary accession is added
    to `accessions` (the protein2ipr filter).
    """
    dbref = UNIPROT_GENE_DBREF.get(taxon)
    prop = UNIPROT_GENE_PROPERTY.get(taxon)
    open_type = None
    first_accession = False
    for line in lines:
        if "<entry " in line:
            first_accession = True
        elif first_accession and "<accession>" in line:
            match = _ACCESSION.search(line)
            if match:
                accessions.add(match.group(1))
            first_accession = False
        match = _DBREF_OPEN.match(line)
        if match:
            db_type = match.group(2)
            open_type = None if line.rstrip().endswith("/>") else db_type
            if dbref and db_type == dbref[0]:
                curie = _uniprot_dbref_curie(idmap, dbref[1], match.group(4), taxon)
                stats.record(taxon, curie is not None)
                if curie:
                    line = f"{match.group(1)}{db_type}{match.group(3)}{curie}{match.group(5)}\n"
                else:
                    line = (
                        f"{match.group(1)}{db_type}-unmapped{match.group(3)}"
                        f"{match.group(4)}{match.group(5)}\n"
                    )
                    if open_type:
                        open_type = f"{db_type}-unmapped"
        elif "</dbReference>" in line:
            open_type = None
        elif prop and open_type == prop[0]:
            match = _GENE_ID_PROPERTY.match(line)
            if match:
                curie = idmap.lookup(prop[1], match.group(2), taxon)
                stats.record(taxon, curie is not None)
                if not curie:
                    continue
                line = f"{match.group(1)}{curie}{match.group(3)}\n"
        yield line


# ---------------------------------------------------------------------------------------------
# uniprot_sprot_varsplic.fasta (UniProtFastaLoaderTask): organism comes from 'OS=Genus species'
# looked up against fasta.taxonId. The yeast OS carries a strain suffix that the loader's regex
# turns into 'Saccharomyces cerevisiae ' (trailing space), which never matches; normalise it.
# ---------------------------------------------------------------------------------------------

_OX = re.compile(r" OX=(\d+)")
_YEAST_OS = re.compile(r"OS=Saccharomyces cerevisiae \([^)]*\)")


def filter_varsplic_fasta(
    lines: Iterable[str], taxa: Iterable[str] = ALLIANCE_TAXA
) -> Iterator[str]:
    wanted = set(taxa)
    keep = False
    for line in lines:
        if line.startswith(">"):
            match = _OX.search(line)
            keep = bool(match and match.group(1) in wanted)
            if keep:
                line = _YEAST_OS.sub("OS=Saccharomyces cerevisiae", line)
        if keep:
            yield line


# ---------------------------------------------------------------------------------------------
# protein2ipr.dat (Protein2iprConverter): 6 tab columns. getSource() throws on member database
# IDs it doesn't know (e.g. NCBIfam 'NF...', PIRSR), so those rows are dropped here.
# ---------------------------------------------------------------------------------------------

PROTEIN2IPR_MEMBER_PREFIXES = (
    b"PF",
    b"SM",
    b"SSF",
    b"SFLD",
    b"PS",
    b"PR",
    b"PTHR",
    b"G3DSA",
    b"TIGR",
    b"PD",
    b"PIRSF",
    b"MF_",
    b"cd",
)


def filter_protein2ipr(
    lines: Iterable[bytes], accessions: set[bytes], counts: dict[str, int]
) -> Iterator[bytes]:
    for line in lines:
        tab = line.find(b"\t")
        if tab < 0 or line[:tab] not in accessions:
            continue
        cols = line.split(b"\t")
        if len(cols) != 6:
            counts["bad_columns"] = counts.get("bad_columns", 0) + 1
            continue
        if not cols[3].startswith(PROTEIN2IPR_MEMBER_PREFIXES):
            counts["unknown_member_db"] = counts.get("unknown_member_db", 0) + 1
            continue
        counts["kept"] = counts.get("kept", 0) + 1
        yield line


def filter_interpro2go(lines: Iterable[str]) -> Iterator[str]:
    """interpro2go without its '!' header lines (InterproGoConverter splits every line on ';')."""
    for line in lines:
        if line.startswith("InterPro:") and ";" in line:
            yield line


# ---------------------------------------------------------------------------------------------
# gene2pubmed (PubMedGeneConverter): tax_id, GeneID, PubMed_ID. Without an ID resolver the
# converter uses column 2 verbatim as Gene.primaryIdentifier, so Entrez IDs become CURIEs here.
# It maps tax_id 559292 to 4932 itself, so pubmed.organisms must list 4932 for yeast.
# ---------------------------------------------------------------------------------------------


def rewrite_gene2pubmed(
    lines: Iterable[str], idmap: GeneIdMap, stats: RewriteStats
) -> Iterator[str]:
    yield "#tax_id\tGeneID\tPubMed_ID\n"
    for line in lines:
        if line.startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) != 3 or cols[0] not in ALLIANCE_TAXA:
            continue
        curie = idmap.lookup("entrez", cols[1], cols[0])
        stats.record(cols[0], curie is not None)
        if curie:
            yield f"{cols[0]}\t{curie}\t{cols[2]}\n"


# ---------------------------------------------------------------------------------------------
# PANTHER ortholog files (PantherConverter): 'SPECIES|DB=ID|UniProtKB=ACC' x2, type, ancestor,
# family. The converter keeps the text after the last '=' (prefixing MGI/RGD/HGNC), so genes are
# written as 'SPECIES|AGR=<CURIE>|UniProtKB=ACC'. Species codes resolve through the organism
# repository; YEAST is 4932 there, so panther.organisms must list 4932 for yeast.
# ---------------------------------------------------------------------------------------------

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
_PANTHER_CURIE_DBS = {"HGNC", "MGI", "RGD"}
_PANTHER_NATIVE_DBS = {"FlyBase", "WormBase", "SGD", "ZFIN", "Xenbase"}
_PANTHER_ENSEMBL_DBS = {"Ensembl", "EnsemblGenome"}


def _panther_gene(field: str, idmap: GeneIdMap) -> tuple[str, str | None, str] | None:
    """(taxon, CURIE or None, rewritten field) for one PANTHER gene field, None if off-taxa."""
    parts = field.split("|")
    taxon = PANTHER_SPECIES.get(parts[0])
    if taxon is None or len(parts) < 2:
        return None
    db, _, ident = parts[1].rpartition("=")
    db = db.split("=")[0]
    uniprot = parts[2].split("=", 1)[1] if len(parts) > 2 and "=" in parts[2] else ""
    curie = None
    if db in _PANTHER_CURIE_DBS:
        curie = idmap.lookup("curie", f"{db}:{ident}", taxon)
    elif db in _PANTHER_NATIVE_DBS:
        curie = idmap.lookup("native", ident, taxon)
    elif db in _PANTHER_ENSEMBL_DBS:
        curie = idmap.lookup("ensembl", ident, taxon)
    if curie is None and uniprot:
        curie = idmap.lookup("uniprot", uniprot, taxon)
    return taxon, curie, f"{parts[0]}|AGR={curie}|UniProtKB={uniprot}"


def rewrite_panther(lines: Iterable[str], idmap: GeneIdMap, stats: RewriteStats) -> Iterator[str]:
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 5:
            continue
        gene1 = _panther_gene(cols[0], idmap)
        gene2 = _panther_gene(cols[1], idmap)
        if gene1 is None or gene2 is None:
            continue
        stats.record(gene1[0], gene1[1] is not None)
        stats.record(gene2[0], gene2[1] is not None)
        if gene1[1] is None or gene2[1] is None or gene1[1] == gene2[1]:
            continue
        yield "\t".join([gene1[2], gene2[2], *cols[2:5]]) + "\n"


# ---------------------------------------------------------------------------------------------
# OrthoDB (OrthodbConverter): reads the old 9-column 'ALL' layout (level, OG, protein ID, gene ID,
# organism, UniProt species, UniProt acc, description, InterPro), grouped by OG. The current dump
# is split into odb*_genes.tab and odb*_OG2genes.tab, so the layout is rebuilt here from one
# taxonomic level. The organism column uses the 'name species:<taxon>;' form the converter parses
# directly, which keeps yeast on 559292. orthodb_config.properties makes the converter put worm
# IDs (6239) in Gene.secondaryIdentifier, which would create duplicate genes, so worm is left out.
# The converter links every pair within an OG, so very large OGs are skipped.
# ---------------------------------------------------------------------------------------------

ORTHODB_EXCLUDED_TAXA = {"6239"}


def orthodb_gene_map(
    lines: Iterable[str], idmap: GeneIdMap, stats: RewriteStats
) -> dict[str, tuple[str, str]]:
    """OrthoDB gene ID -> (CURIE, taxon) from odb*_genes.tab for the AllianceMine taxa."""
    taxa = set(ALLIANCE_TAXA) - ORTHODB_EXCLUDED_TAXA
    out: dict[str, tuple[str, str]] = {}
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 7:
            continue
        taxon = cols[1].split("_", 1)[0]
        if taxon not in taxa:
            continue
        curie = None
        if cols[6].isdigit():
            curie = idmap.lookup("entrez", cols[6], taxon)
        for ensembl in filter(None, cols[5].split(",")):
            curie = curie or idmap.lookup("ensembl", ensembl, taxon)
        curie = curie or idmap.lookup("uniprot", cols[4], taxon)
        for candidate in (cols[3], cols[2]):
            curie = curie or idmap.resolve(candidate, taxon, ("native", "alias"))
        stats.record(taxon, curie is not None)
        if curie:
            out[cols[0]] = (curie, taxon)
    return out


def rewrite_orthodb(
    og2genes: Iterable[str],
    genes: dict[str, tuple[str, str]],
    level: str,
    max_group: int,
    counts: dict[str, int],
) -> Iterator[str]:
    suffix = f"at{level}"

    def flush(og: str, members: dict[str, str]) -> Iterator[str]:
        if len(members) < 2:
            return
        if len(members) > max_group:
            counts["groups_too_large"] = counts.get("groups_too_large", 0) + 1
            return
        counts["groups"] = counts.get("groups", 0) + 1
        for curie, taxon in members.items():
            organism = f"{SPECIES_NAME[taxon]} species:{taxon};"
            yield f"{level}\t{og}\t{curie}\t{curie}\t{organism}\t{taxon}\t-\t-\t-\n"

    current = None
    members: dict[str, str] = {}
    for line in og2genes:
        og, _, gene = line.rstrip("\n").partition("\t")
        if not og.endswith(suffix):
            continue
        if og != current:
            if current is not None:
                yield from flush(current, members)
            current, members = og, {}
        hit = genes.get(gene)
        if hit:
            members[hit[0]] = hit[1]
    if current is not None:
        yield from flush(current, members)


# ---------------------------------------------------------------------------------------------
# KEGG (KeggPathwayConverter): map_title.tab ('00010<TAB>name') and <org>_gene_map.tab
# ('<gene><TAB>00010 00020 ...', one line per gene; a gene seen twice with different pathways
# aborts the load). D. melanogaster genes must carry a 'Dmel_' prefix, which the converter strips.
# kegg_config.properties fixes the taxon per organism code (sce = 4932), so kegg.organisms must
# list 4932 for yeast. Xenopus has no entry in that config and is not downloaded.
# ---------------------------------------------------------------------------------------------

KEGG_ORGANISMS = {
    "sce": "559292",
    "hsa": "9606",
    "mmu": "10090",
    "rno": "10116",
    "cel": "6239",
    "dme": "7227",
    "dre": "7955",
}
_KEGG_LOCAL_PREFIXES = ("Dmel_", "CELE_")


def kegg_map_titles(lines: Iterable[str]) -> Iterator[str]:
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) >= 2 and cols[0]:
            yield f"{re.sub(r'^(path:)?[a-z]+', '', cols[0])}\t{cols[1]}\n"


def kegg_gene_map(
    org: str,
    link_lines: Iterable[str],
    conv_lines: Iterable[str],
    idmap: GeneIdMap,
    stats: RewriteStats,
) -> Iterator[str]:
    taxon = KEGG_ORGANISMS[org]
    entrez: dict[str, list[str]] = {}
    for line in conv_lines:
        kegg_id, _, ncbi = line.rstrip("\n").partition("\t")
        if ncbi.startswith("ncbi-geneid:"):
            entrez.setdefault(kegg_id, []).append(ncbi.split(":", 1)[1])
    pathways: dict[str, set[str]] = {}
    for line in link_lines:
        kegg_id, _, path = line.rstrip("\n").partition("\t")
        if path:
            pathways.setdefault(kegg_id, set()).add(re.sub(r"^path:[a-z]+", "", path))
    by_curie: dict[str, set[str]] = {}
    for kegg_id, paths in pathways.items():
        curie = None
        for gene_id in entrez.get(kegg_id, []):
            curie = curie or idmap.lookup("entrez", gene_id, taxon)
        local = kegg_id.split(":", 1)[-1]
        for prefix in _KEGG_LOCAL_PREFIXES:
            local = local.removeprefix(prefix)
        curie = curie or idmap.resolve(local, taxon, ("native", "alias"))
        stats.record(taxon, curie is not None)
        if curie:
            by_curie.setdefault(curie, set()).update(paths)
    gene_prefix = "Dmel_" if org == "dme" else ""
    for curie in sorted(by_curie):
        yield f"{gene_prefix}{curie}\t{' '.join(sorted(by_curie[curie]))}\n"


# ---------------------------------------------------------------------------------------------
# Reactome (ReactomeConverter): UniProt2Reactome_All_Levels.txt, exactly 6 columns per line
# (anything else aborts the load), protein-keyed. Species names resolve through the organism
# repository ('Saccharomyces cerevisiae' -> 4932), so reactome.organisms must list 4932.
# ---------------------------------------------------------------------------------------------


def filter_reactome(lines: Iterable[str], counts: dict[str, int]) -> Iterator[str]:
    names = set(SPECIES_NAME.values())
    for line in lines:
        cols = line.rstrip("\n").split("\t")
        if len(cols) == 6 and cols[5] in names:
            counts[cols[5]] = counts.get(cols[5], 0) + 1
            yield line if line.endswith("\n") else line + "\n"

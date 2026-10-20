import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import flatfile_rewriters as rw
from alliance_idmap import GeneIdMap, GeneIds, RewriteStats, gene_from_bgi


def make_idmap() -> GeneIdMap:
    idmap = GeneIdMap()
    for gene in (
        GeneIds("HGNC:8620", "9606", "PAX6", {"5080"}, {"ENSG00000007372"}, {"P26367"}),
        GeneIds("MGI:97490", "10090", "Pax6", {"18508"}, set(), {"P63015"}),
        GeneIds("RGD:3258", "10116", "Pax6", {"25509"}, set(), {"P63016"}),
        GeneIds("FB:FBgn0005558", "7227", "ey", {"43812"}, set(), {"O18381"}),
        GeneIds("WB:WBGene00006870", "6239", "vab-3", {"175898"}, set(), {"P34675"}),
        GeneIds("SGD:S000001855", "559292", "STE2", {"850518"}, set(), {"D6VTK4"}, {"YFL026W"}),
        GeneIds("ZFIN:ZDB-GENE-990415-200", "7955", "pax6a", {"30737"}, {"ENSDARG00000103379"}),
        GeneIds("Xenbase:XB-GENE-865046", "8364", "pax6", {"394602"}, {"ENSXETG00000025091"}),
    ):
        idmap.add(gene)
    return idmap


class IdMapTest(unittest.TestCase):
    def test_gene_from_bgi_record(self):
        record = {
            "symbol": "trnt1",
            "basicGeneticEntity": {
                "primaryId": "Xenbase:XB-GENE-478054",
                "taxonId": "NCBITaxon:8364",
                "crossReferences": [
                    {"id": "UniProtKB:Q6P873"},
                    {"id": "ENSEMBL:ENSXETG00000025091.3"},
                    {"id": "NCBI_Gene:394602"},
                    {"id": "RefSeq:KAE8612060|RefSeq:NP_989006"},
                    {"id": "Xenbase:XB-GENEPAGE-478053"},
                    {"id": "Xenbase:XB-GENE-478054"},
                ],
            },
        }
        gene = gene_from_bgi(record)
        self.assertEqual(gene.taxon, "8364")
        self.assertEqual(gene.entrez, {"394602"})
        self.assertEqual(gene.ensembl, {"ENSXETG00000025091"})
        self.assertEqual(gene.uniprot, {"Q6P873"})
        self.assertEqual(gene.aliases, {"XB-GENEPAGE-478053"})

    def test_gene_from_bgi_skips_other_taxa(self):
        record = {"basicGeneticEntity": {"primaryId": "X:1", "taxonId": "NCBITaxon:2697049"}}
        self.assertIsNone(gene_from_bgi(record))

    def test_lookup_requires_unique_hit(self):
        idmap = make_idmap()
        idmap.add(GeneIds("HGNC:1", "9606", "DUP", {"5080"}))
        self.assertIsNone(idmap.lookup("entrez", "5080", "9606"))
        self.assertEqual(idmap.lookup("ensembl", "ENSG00000007372.12", "9606"), "HGNC:8620")
        self.assertEqual(idmap.lookup("native", "S000001855", "559292"), "SGD:S000001855")
        self.assertIsNone(idmap.lookup("native", "S000001855", "9606"))

    def test_tsv_round_trip(self):
        idmap = make_idmap()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.tsv"
            idmap.write_tsv(path)
            again = GeneIdMap.read_tsv(path)
        self.assertEqual(len(again), len(idmap))
        self.assertEqual(again.lookup("alias", "YFL026W", "559292"), "SGD:S000001855")


UNIPROT_HUMAN = """<entry dataset="Swiss-Prot" created="1991-08-01">
  <accession>P26367</accession>
  <accession>Q99413</accession>
  <dbReference type="GeneID" id="5080"/>
  <dbReference type="GeneID" id="999999"/>
  <dbReference type="HGNC" id="HGNC:8620"/>
</entry>
"""

UNIPROT_YEAST = """<entry dataset="Swiss-Prot">
  <accession>D6VTK4</accession>
  <dbReference type="SGD" id="S000001855">
    <property type="gene designation" value="STE2"/>
  </dbReference>
</entry>
"""

UNIPROT_WORM = """<entry dataset="Swiss-Prot">
  <accession>P34675</accession>
  <dbReference type="WormBase" id="F14F3.1a">
    <property type="protein sequence ID" value="CE00001"/>
    <property type="gene ID" value="WBGene00006870"/>
    <property type="gene designation" value="vab-3"/>
  </dbReference>
  <dbReference type="WormBase" id="X.1">
    <property type="gene ID" value="WBGene99999999"/>
  </dbReference>
  <dbReference type="Ensembl" id="T1">
    <property type="gene ID" value="WBGene00006870"/>
  </dbReference>
</entry>
"""


def rewrite(text, taxon, idmap=None):
    stats = RewriteStats("uniprot")
    accessions = set()
    out = "".join(
        rw.rewrite_uniprot_xml(
            text.splitlines(True), taxon, idmap or make_idmap(), stats, accessions
        )
    )
    return out, stats, accessions


class UniprotTest(unittest.TestCase):
    def test_human_geneid_to_hgnc(self):
        out, stats, accessions = rewrite(UNIPROT_HUMAN, "9606")
        self.assertIn('<dbReference type="GeneID" id="HGNC:8620"/>', out)
        self.assertIn('<dbReference type="GeneID-unmapped" id="999999"/>', out)
        self.assertIn('<dbReference type="HGNC" id="HGNC:8620"/>', out)
        self.assertEqual(accessions, {"P26367"})
        self.assertEqual(stats.summary(), {"9606": {"mapped": 1, "unmapped": 1}})

    def test_yeast_sgd_prefixed(self):
        out, _, _ = rewrite(UNIPROT_YEAST, "559292")
        self.assertIn('<dbReference type="SGD" id="SGD:S000001855">', out)
        self.assertIn("</dbReference>", out)

    def test_rat_stays_bare_when_known(self):
        text = '<dbReference type="RGD" id="3258"/>\n<dbReference type="RGD" id="1"/>\n'
        out, _, _ = rewrite(text, "10116")
        self.assertIn('<dbReference type="RGD" id="3258"/>', out)
        self.assertIn('<dbReference type="RGD-unmapped" id="1"/>', out)

    def test_worm_gene_id_property(self):
        out, stats, _ = rewrite(UNIPROT_WORM, "6239")
        self.assertIn('<property type="gene ID" value="WB:WBGene00006870"/>', out)
        self.assertNotIn("WBGene99999999", out)
        self.assertEqual(out.count("WB:WBGene00006870"), 1)
        self.assertEqual(stats.summary(), {"6239": {"mapped": 1, "unmapped": 1}})

    def test_zebrafish_ensembl_gene_id(self):
        text = (
            '<dbReference type="Ensembl" id="ENSDART1">\n'
            '  <property type="gene ID" value="ENSDARG00000103379"/>\n'
            "</dbReference>\n"
        )
        out, _, _ = rewrite(text, "7955")
        self.assertIn('value="ZFIN:ZDB-GENE-990415-200"', out)


class FlatFilesTest(unittest.TestCase):
    def test_varsplic_filters_taxa_and_fixes_yeast(self):
        lines = [
            (
                ">sp|P1-2|A_YEAST Isoform 2 OS=Saccharomyces cerevisiae "
                "(strain ATCC 204508 / S288c) OX=559292 GN=X\n"
            ),
            "MKV\n",
            ">sp|P2-2|B_ARATH Isoform 2 OS=Arabidopsis thaliana OX=3702\n",
            "MAA\n",
        ]
        out = list(rw.filter_varsplic_fasta(lines))
        self.assertEqual(len(out), 2)
        self.assertIn("OS=Saccharomyces cerevisiae OX=559292", out[0])

    def test_protein2ipr(self):
        lines = [
            b"P26367\tIPR1\tname\tPF00292\t1\t10\n",
            b"P26367\tIPR2\tname\tNF000001\t1\t10\n",
            b"Q00000\tIPR1\tname\tPF00292\t1\t10\n",
        ]
        counts = {}
        out = list(rw.filter_protein2ipr(lines, {b"P26367"}, counts))
        self.assertEqual(out, [lines[0]])
        self.assertEqual(counts, {"kept": 1, "unknown_member_db": 1})

    def test_interpro2go(self):
        lines = ["!version date: 2026\n", "InterPro:IPR000003 RXR > GO:DNA binding ; GO:0003677\n"]
        self.assertEqual(list(rw.filter_interpro2go(lines)), lines[1:])

    def test_gene2pubmed(self):
        stats = RewriteStats("pubmed-gene")
        lines = [
            "#tax_id\tGeneID\tPubMed_ID\n",
            "9606\t5080\t111\n",
            "9606\t1\t222\n",
            "559292\t850518\t333\n",
            "9913\t5\t444\n",
        ]
        out = list(rw.rewrite_gene2pubmed(lines, make_idmap(), stats))
        self.assertEqual(out[1:], ["9606\tHGNC:8620\t111\n", "559292\tSGD:S000001855\t333\n"])
        self.assertEqual(stats.unmapped["9606"], 1)

    def test_panther(self):
        stats = RewriteStats("panther")
        lines = [
            (
                "HUMAN|HGNC=8620|UniProtKB=P26367\tMOUSE|MGI=MGI=97490|UniProtKB=P63015"
                "\tLDO\tEuarchontoglires\tPTHR24329\n"
            ),
            "HUMAN|HGNC=8620|UniProtKB=P26367\tRAT|RGD=3258|UniProtKB=P63016\tO\tX\tPTHR24329\n",
            "DROME|FlyBase=FBgn0005558|UniProtKB=O18381\tCHICK|Ensembl=E|UniProtKB=Q\tO\tX\tP\n",
            "XENTR|Ensembl=ENSXETG00000025091|UniProtKB=A\tDANRE|Gene=pax6a|UniProtKB=Z\tO\tX\tP\n",
            "YEAST|SGD=S000001855|UniProtKB=D6VTK4\tCAEEL|WormBase=WBGene0|UniProtKB=Q\tO\tX\tP\n",
        ]
        out = list(rw.rewrite_panther(lines, make_idmap(), stats))
        self.assertEqual(len(out), 2)
        self.assertTrue(
            out[0].startswith("HUMAN|AGR=HGNC:8620|UniProtKB=P26367\tMOUSE|AGR=MGI:97490")
        )
        self.assertIn("RAT|AGR=RGD:3258", out[1])
        self.assertEqual(stats.unmapped["7955"], 1)
        self.assertEqual(stats.unmapped["6239"], 1)

    def test_orthodb(self):
        stats = RewriteStats("orthodb")
        genes_tab = [
            "9606_1:000001\t9606_1\tNP_1\tPAX6\tP26367\tENSG00000007372\t5080\tpaired box\n",
            "10090_1:000002\t10090_1\tNP_2\tPax6\tP63015\t\t18508\tpaired box\n",
            "559292_0:000003\t559292_0\tNP_3\tYFL026W\t\t\t\tSTE2\n",
            "6239_0:000004\t6239_0\tNP_4\tvab-3\tP34675\t\t175898\tvab-3\n",
            "9913_0:000005\t9913_0\tNP_5\tPAX6\t\t\t1\tcow\n",
        ]
        gene_map = rw.orthodb_gene_map(genes_tab, make_idmap(), stats)
        self.assertEqual(gene_map["559292_0:000003"], ("SGD:S000001855", "559292"))
        self.assertNotIn("6239_0:000004", gene_map)
        og2genes = [
            "1at2759\t9606_1:000001\n",
            "1at2759\t10090_1:000002\n",
            "1at2759\t9913_0:000005\n",
            "1at7742\t9606_1:000001\n",
            "2at2759\t559292_0:000003\n",
        ]
        counts = {}
        out = list(rw.rewrite_orthodb(og2genes, gene_map, "2759", 200, counts))
        self.assertEqual(len(out), 2)
        cols = out[0].rstrip("\n").split("\t")
        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[2], "HGNC:8620")
        self.assertEqual(cols[4], "Homo sapiens species:9606;")
        self.assertEqual(counts, {"groups": 1})

    def test_kegg(self):
        stats = RewriteStats("kegg")
        titles = list(rw.kegg_map_titles(["map00010\tGlycolysis / Gluconeogenesis\n"]))
        self.assertEqual(titles, ["00010\tGlycolysis / Gluconeogenesis\n"])
        link = [
            "dme:Dmel_CG1234\tpath:dme00010\n",
            "dme:Dmel_CG1234\tpath:dme00020\n",
            "dme:Dmel_CG9999\tpath:dme00010\n",
        ]
        conv = ["dme:Dmel_CG1234\tncbi-geneid:43812\n"]
        out = list(rw.kegg_gene_map("dme", link, conv, make_idmap(), stats))
        self.assertEqual(out, ["Dmel_FB:FBgn0005558\t00010 00020\n"])
        sce = list(
            rw.kegg_gene_map(
                "sce", ["sce:YFL026W\tpath:sce04011\n"], [], make_idmap(), RewriteStats("k")
            )
        )
        self.assertEqual(sce, ["SGD:S000001855\t04011\n"])

    def test_reactome(self):
        counts = {}
        lines = [
            "P26367\tR-HSA-1\turl\tname\tTAS\tHomo sapiens\n",
            "Q1\tR-BTA-1\turl\tname\tIEA\tBos taurus\n",
            "bad\tline\n",
        ]
        self.assertEqual(list(rw.filter_reactome(lines, counts)), lines[:1])
        self.assertEqual(counts, {"Homo sapiens": 1})


if __name__ == "__main__":
    unittest.main()

import gzip
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_downloads as cd
from alliance_idmap import GeneIdMap, GeneIds

PROJECT = """<project type="bio"><sources>
  <source name="xl-fasta" type="fasta">
    <property name="fasta.includes" value="FASTA_XL10.1.fa"/>
    <property name="src.data.dir" location="/root/data/fms"/>
  </source>
  <source name="empty-includes" type="fasta">
    <property name="fasta.includes" value=""/>
    <property name="src.data.dir" location="/root/data/fms"/>
  </source>
  <source name="gzipped" type="alliance-genes">
    <property name="src.data.dir" location="/root/data/api"/>
    <property name="src.data.dir.includes" value="genes.tsv"/>
  </source>
  <source name="sgd" type="sgd"/>
  <source name="entrez-organism" type="entrez-organism">
    <property name="src.data.file" location="organisms.xml"/>
  </source>
  <source name="reactome" type="reactome">
    <property name="src.data.dir" location="/root/data/reactome/current"/>
    <property name="src.data.dir.includes" value="UniProt2Reactome_All_Levels.txt"/>
    <property name="reactome.organisms" value="4932 9606"/>
  </source>
  <source name="kegg-pathway" type="kegg-pathway">
    <property name="src.data.dir" location="/root/data/kegg/current"/>
    <property name="kegg.organisms" value="559292 9606"/>
  </source>
  <source name="pubmed-gene" type="pubmed-gene">
    <property name="src.data.dir" location="/root/data/pubmed/current"/>
    <property name="pubmed.organisms" value="4932 9606"/>
  </source>
  <source name="interactions" type="alliance-genetic-interactions">
    <property name="src.data.dir" location="/root/data/api"/>
    <property name="src.data.dir.includes" value="interactions.tsv"/>
  </source>
</sources></project>
"""


class CheckDownloadsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        files = {
            "fms/FASTA_XL10.1.fa": ">chr1\nACGT\n",
            "reactome/current/UniProt2Reactome_All_Levels.txt": (
                "P1\tR-HSA-1\tu\tn\tTAS\tHomo sapiens\nP2\tR-SCE-1\tu\tn\tIEA\n"
            ),
            "kegg/current/map_title.tab": "00010\tGlycolysis\n",
            "kegg/current/hsa_gene_map.tab": "HGNC:1\t00010\nHGNC:1\t00020\n",
            "pubmed/current/gene2pubmed": (
                "#tax_id\tGeneID\tPubMed_ID\n9606\tHGNC:1\t1\n559292\tSGD:S000000001\t2\n"
            ),
            "api/interactions.tsv": "a\tb\nHGNC:1\tNCBITaxon:9606\nHGNC:2\tNCBITaxon:9606\n",
        }
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (root / "api/genes.tsv").write_bytes(gzip.compress(b"x\ty\n"))
        project = root / "project.xml"
        project.write_text(PROJECT)
        idmap = GeneIdMap()
        idmap.add(GeneIds("HGNC:1", "9606"))
        idmap.add(GeneIds("SGD:S000000001", "559292"))
        checker = cd.Checker(root, idmap, sample_lines=1000, deep=False, flat_report={})
        self.results = {s.name: cd.check_source(checker, s) for s in cd.parse_project(project)}

    def tearDown(self):
        self.tmp.cleanup()

    def notes(self, name):
        return " | ".join(self.results[name].notes)

    def test_fasta_ok(self):
        self.assertEqual(self.results["xl-fasta"].status, cd.OK)

    def test_empty_includes_fail(self):
        self.assertEqual(self.results["empty-includes"].status, cd.FAIL)
        self.assertIn("is empty", self.notes("empty-includes"))

    def test_gzip_fails(self):
        self.assertEqual(self.results["gzipped"].status, cd.FAIL)
        self.assertIn("gzip", self.notes("gzipped"))

    def test_runtime_sources(self):
        self.assertEqual(self.results["sgd"].status, cd.RUNTIME)
        self.assertEqual(self.results["entrez-organism"].status, cd.RUNTIME)

    def test_reactome_column_count(self):
        self.assertEqual(self.results["reactome"].status, cd.FAIL)
        self.assertIn("exactly 6 columns", self.notes("reactome"))

    def test_kegg_duplicate_gene_and_taxon_warning(self):
        notes = self.notes("kegg-pathway")
        self.assertEqual(self.results["kegg-pathway"].status, cd.FAIL)
        self.assertIn("lists a gene twice", notes)
        self.assertIn("needs 4932", notes)

    def test_pubmed_counts_and_curies(self):
        notes = self.notes("pubmed-gene")
        self.assertEqual(self.results["pubmed-gene"].status, cd.OK)
        self.assertIn("559292=1", notes)
        self.assertIn("2/2 (100.0%)", notes)

    def test_alliance_tsv(self):
        notes = self.notes("interactions")
        self.assertIn("9606=2", notes)
        self.assertIn("gene-like CURIEs in ID map: 50.0%", notes)


if __name__ == "__main__":
    unittest.main()

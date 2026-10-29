import contextlib
import gzip
import io
import sys
import unittest
from unittest import mock
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_downloads as cd
import download_checks as dc
import tabular_checks as tc
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


class RewriteGateTest(unittest.TestCase):
    def _flat(self, mapped, unmapped):
        checker = dc.Checker(
            Path("."), None, 1000, False,
            {"pubmed-gene": {"status": "ok", "gene_ids": {"9606": {"mapped": mapped, "unmapped": unmapped}}}},
        )
        result = dc.Result("pubmed-gene", "pubmed-gene")
        dc.report_flat_stats(checker, dc.Source("pubmed-gene", "pubmed-gene", {}), result)
        return result.status

    def test_mapped_percentage_thresholds(self):
        self.assertEqual(self._flat(995, 5), dc.OK)
        self.assertEqual(self._flat(95, 5), dc.WARN)
        self.assertEqual(self._flat(89, 11), dc.FAIL)

    def test_missing_taxon_fails(self):
        result = dc.Result("s", "t")
        dc.report_taxa(result, Counter({"9606": 5}), ["9606", "7955"], sampled=False)
        self.assertEqual(result.status, dc.FAIL)
        self.assertIn("7955", " ".join(result.notes))

    def test_missing_taxon_in_sample_is_not_checked(self):
        result = dc.Result("s", "t")
        dc.report_taxa(result, Counter({"9606": 5}), ["9606", "7955"], sampled=True)
        self.assertEqual(result.status, dc.OK)


class MinimumRowsTest(unittest.TestCase):
    def _check(self, name, rows):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text("h\n" + "r\n" * rows)
            checker = dc.Checker(Path(tmp), None, 1000, False, {})
            result = dc.Result("s", "alliance-x")
            tc.check_tsv(checker, dc.Source("s", "alliance-x", {}), [path], result)
            return result

    def test_all_new_tsvs_have_a_minimum(self):
        self.assertEqual(
            set(tc.MIN_ROWS),
            {"alphafold.tsv", "string-interactions.tsv", "chembl-targets.tsv", "molecules.tsv",
             "htp-datasets.tsv", "htp-samples.tsv", "mouse-strains.tsv",
             "worm-rnai.tsv"},
        )

    def test_short_file_fails(self):
        result = self._check("molecules.tsv", 10)
        self.assertEqual(result.status, dc.FAIL)
        self.assertIn("fewer than the expected", " ".join(result.notes))

    def test_crispr_screens_empty_is_not_gated(self):
        self.assertEqual(self._check("crispr-screens.tsv", 0).status, dc.OK)

    def test_estimated_minimum_only_warns(self):
        self.assertEqual(self._check("htp-datasets.tsv", 10).status, dc.WARN)

    def test_unlisted_file_is_not_gated(self):
        self.assertEqual(self._check("other.tsv", 1).status, dc.OK)


class IdMapReportTest(unittest.TestCase):
    def _run(self, genes):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project.xml"
            project.write_text('<project type="bio"><sources></sources></project>')
            idmap = GeneIdMap()
            for gene in genes:
                idmap.add(gene)
            out = root / "out.json"
            argv = ["check_downloads", "--project-xml", str(project), "--data-root", str(root),
                    "--json", str(out)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                cd, "load_idmap", return_value=idmap
            ), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = cd.main()
            return code, stdout.getvalue(), out.read_text()

    def test_missing_taxa_fail_and_appear_in_report_and_json(self):
        code, stdout, payload = self._run([])
        self.assertEqual(code, 1)
        self.assertIn("FAIL: no genes for taxa", stdout)
        self.assertIn("no genes for taxa", payload)


if __name__ == "__main__":
    unittest.main()

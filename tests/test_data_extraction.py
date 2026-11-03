"""Required extraction failures must prevent integration of incomplete data."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def extractor(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[1] / "docker/alliancemine/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("extract_data")
    instance = module.AllianceDataExtractor(tmp_path, release="9.0.0")
    instance.snapshot_files = {(row[0], row[1]): {} for row in module.FILE_MAP}
    monkeypatch.setattr(instance, "download_s3_data", lambda: True)
    monkeypatch.setattr(instance, "load_snapshot", lambda: None)
    monkeypatch.setattr(instance, "download_file", lambda *args: True)
    monkeypatch.setattr(instance, "build_genes_tsv", lambda: True)
    monkeypatch.setattr(instance, "fetch_api_data", lambda: True)
    monkeypatch.setattr(instance, "verify", lambda: None)
    monkeypatch.setattr(module, "AllianceDataExtractor", lambda *args, **kwargs: instance)
    monkeypatch.setattr(sys, "argv", ["extract_data.py", "--release", "9.0.0"])
    return module, instance


@pytest.mark.parametrize("step", ["download_s3_data", "build_genes_tsv"])
def test_required_failure_returns_nonzero(extractor, monkeypatch, step):
    module, instance = extractor
    monkeypatch.setattr(instance, step, lambda: False)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1


@pytest.mark.parametrize("skip", ["--skip-fms", "--skip-api", None])
def test_success_and_intentional_skips(extractor, monkeypatch, skip):
    module, instance = extractor
    if skip:
        monkeypatch.setattr(sys, "argv", [*sys.argv, skip])
    if skip == "--skip-fms":
        monkeypatch.setattr(instance, "download_s3_data", lambda: pytest.fail("S3 was not skipped"))
    if skip == "--skip-api":
        monkeypatch.setattr(instance, "fetch_api_data", lambda: pytest.fail("API was not skipped"))
    assert module.main() is None


def test_skip_fms_still_requires_gene_tsv(extractor, monkeypatch):
    module, instance = extractor
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--skip-fms"])
    monkeypatch.setattr(instance, "build_genes_tsv", lambda: False)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1


@pytest.fixture
def real_extractor(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[1] / "docker/alliancemine/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("extract_data")
    (tmp_path / "genes").mkdir()
    (tmp_path / "fms").mkdir()
    (tmp_path / "fms/ONTOLOGY_SO.obo").write_text(
        "[Term]\nid: SO:0001217\nname: protein_coding_gene\n"
    )
    return module.AllianceDataExtractor(tmp_path, release="9.0.0")


@pytest.mark.parametrize("payload", ['{"data": []}', '{"data": ['])
def test_unusable_bgi_preserves_previous_gene_file(real_extractor, payload):
    genes = real_extractor.data_dir / "genes"
    (genes / "BGI_SGD.json").write_text(payload)
    (genes / "Gene.tsv").write_text("previous complete gene file\n")
    assert real_extractor.build_genes_tsv() is False
    assert (genes / "Gene.tsv").read_text() == "previous complete gene file\n"


def test_gene_file_uses_ontology_from_selected_data_directory(real_extractor):
    gene = {
        "basicGeneticEntity": {"primaryId": "SGD:S000001", "taxonId": "NCBITaxon:559292"},
        "symbol": "ACT1",
        "soTermId": "SO:0001217",
    }
    genes = real_extractor.data_dir / "genes"
    (genes / "BGI_SGD.json").write_text(json.dumps({"data": [gene]}))
    assert real_extractor.build_genes_tsv() is True
    rows = (genes / "Gene.tsv").read_text().splitlines()
    assert len(rows) == 2
    assert rows[1].split("\t")[0] == "SGD:S000001"
    assert rows[1].split("\t")[-1] == "protein_coding_gene"


def test_empty_s3_download_is_failure(real_extractor, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", "")
    )
    assert real_extractor.download_s3_data() is False

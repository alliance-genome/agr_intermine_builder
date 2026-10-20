import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_data
import flatfiles
from alliance_idmap import GeneIdMap


def _row(dt, ds, date, url):
    return {
        "dataType": {"name": dt},
        "dataSubType": {"name": ds},
        "uploadDate": date,
        "s3Url": url,
    }


class LatestUploadsTest(unittest.TestCase):
    def test_keeps_latest_upload_per_subtype(self):
        rows = [
            _row("BGI", "SGD", "2026-09-24T20:14:55.504+00:00", "new"),
            _row("BGI", "SGD", "2026-03-18T21:15:42.111+00:00", "old"),
            _row("BGI", "ZFIN", "2026-08-04T15:52:03.107+00:00", "zfin"),
            _row("BGI", "", "2026-09-30T00:00:00+00:00", "no-subtype"),
        ]
        latest = extract_data.latest_uploads(rows)
        self.assertEqual(latest[("BGI", "SGD")]["s3Url"], "new")
        self.assertEqual(latest[("BGI", "ZFIN")]["s3Url"], "zfin")
        self.assertEqual(len(latest), 2)


class FetchApiDataTest(unittest.TestCase):
    def _run(self, returncode):
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "fetch_all.py"
            script.write_text("")
            extractor = extract_data.AllianceDataExtractor(Path(tmp) / "data", release="9.2.0")
            completed = mock.Mock(returncode=returncode)
            with (
                mock.patch.object(extract_data, "FETCH_ALL_SCRIPT", script),
                mock.patch.object(extract_data.subprocess, "run", return_value=completed) as run,
                mock.patch.dict(extract_data.os.environ, {"ALLIANCE_FETCH_WORKERS": "3"}),
            ):
                status = extractor.fetch_api_data()
            self.assertTrue((Path(tmp) / "data" / "fms-cache").is_dir())
            return status, run.call_args

    def test_pins_release_cache_and_workers(self):
        status, call = self._run(0)
        self.assertEqual(status, "ok")
        cmd = call.args[0]
        env = call.kwargs["env"]
        self.assertEqual(cmd[cmd.index("--release") + 1], "9.2.0")
        self.assertEqual(cmd[cmd.index("--workers") + 1], "3")
        self.assertEqual(env["ALLIANCE_RELEASE"], "9.2.0")
        self.assertTrue(env["ALLIANCE_FMS_CACHE"].endswith("fms-cache"))
        self.assertTrue(env["ALLIANCE_FETCH_CACHE"].endswith("api-cache"))

    def test_release_mismatch_exit_is_reported(self):
        status, _ = self._run(2)
        self.assertEqual(status, "release-mismatch")

    def test_other_failures(self):
        status, _ = self._run(1)
        self.assertEqual(status, "failed")


def _extractor(tmp, fms_keys, release="9.2.0"):
    extractor = extract_data.AllianceDataExtractor(Path(tmp) / "data", release=release)
    extractor.fms_files = {key: {"s3Url": "u"} for key in fms_keys}
    return extractor


class RequiredFmsTypesTest(unittest.TestCase):
    def test_all_required_types_present(self):
        keys = [(t, s) for t, s, _, _ in extract_data.FILE_MAP]
        with TemporaryDirectory() as tmp:
            self.assertEqual(_extractor(tmp, keys).missing_required(), [])

    def test_missing_bgi_gff_disease_orthology_reported(self):
        keys = [(t, s) for t, s, _, _ in extract_data.FILE_MAP]
        dropped = [("BGI", "XBXL"), ("GFF", "ZFIN"), ("DISEASE-ALLIANCE", "COMBINED"),
                   ("ORTHOLOGY-ALLIANCE", "COMBINED")]
        keys = [k for k in keys if k not in dropped]
        with TemporaryDirectory() as tmp:
            self.assertEqual(sorted(_extractor(tmp, keys).missing_required()), sorted(dropped))

    def test_missing_optional_type_is_not_required(self):
        keys = [(t, s) for t, s, _, _ in extract_data.FILE_MAP if t != "GAF"]
        with TemporaryDirectory() as tmp:
            self.assertEqual(_extractor(tmp, keys).missing_required(), [])

    def test_download_all_stops_before_downloading(self):
        keys = [(t, s) for t, s, _, _ in extract_data.FILE_MAP if (t, s) != ("BGI", "ZFIN")]
        with TemporaryDirectory() as tmp:
            extractor = _extractor(tmp, keys)
            with (
                mock.patch.object(extractor, "check_api_release", return_value=True),
                mock.patch.object(extractor, "load_fms_files"),
                mock.patch.object(extractor, "download_s3_data") as s3,
                mock.patch.object(extractor, "download_file") as download,
            ):
                stats = extractor.download_all(skip_api=True, skip_flatfiles=True)
            self.assertEqual(stats["failed"], 1)
            s3.assert_not_called()
            download.assert_not_called()


class ClearOtherReleaseTest(unittest.TestCase):
    def _marker(self, data):
        return data / extract_data.RELEASE_MARKER_DIR / "fms" / "release"

    def _seed(self, tmp, stamp):
        data = Path(tmp) / "data"
        for _, _, target_dir, name in extract_data.FILE_MAP[:3]:
            (data / target_dir).mkdir(parents=True, exist_ok=True)
            (data / target_dir / name).write_text("old")
        if stamp:
            self._marker(data).parent.mkdir(parents=True, exist_ok=True)
            self._marker(data).write_text(stamp)
        return data

    def test_other_release_files_removed_and_marker_stamped(self):
        with TemporaryDirectory() as tmp:
            data = self._seed(tmp, "9.1.0\n")
            _extractor(tmp, []).clear_other_release()
            name = extract_data.FILE_MAP[0][3]
            self.assertFalse((data / "fms" / name).exists())
            self.assertEqual(self._marker(data).read_text().strip(), "9.2.0")

    def test_no_marker_inside_source_dirs(self):
        with TemporaryDirectory() as tmp:
            data = self._seed(tmp, "9.1.0\n")
            _extractor(tmp, []).clear_other_release()
            for target_dir in {e[2] for e in extract_data.FILE_MAP}:
                self.assertEqual(
                    [p.name for p in (data / target_dir).iterdir() if p.name.startswith(".")], []
                )

    def test_same_release_keeps_files(self):
        with TemporaryDirectory() as tmp:
            data = self._seed(tmp, "9.2.0\n")
            _extractor(tmp, []).clear_other_release()
            self.assertTrue((data / "fms" / extract_data.FILE_MAP[0][3]).exists())

    def test_unstamped_directory_is_cleared(self):
        with TemporaryDirectory() as tmp:
            data = self._seed(tmp, None)
            _extractor(tmp, []).clear_other_release()
            self.assertFalse((data / "fms" / extract_data.FILE_MAP[0][3]).exists())


class FailedDownloadTest(unittest.TestCase):
    def test_failed_download_unstamps_so_rerun_clears_partials(self):
        keys = [(t, s) for t, s, _, _ in extract_data.FILE_MAP]
        with TemporaryDirectory() as tmp:
            extractor = _extractor(tmp, keys)
            with (
                mock.patch.object(extractor, "load_fms_files"),
                mock.patch.object(extractor, "download_s3_data"),
                mock.patch.object(extractor, "download_file", return_value=False),
            ):
                extractor.download_all(skip_api=True, skip_flatfiles=True)
            markers = list((Path(tmp) / "data" / extract_data.RELEASE_MARKER_DIR).glob("*/release"))
            self.assertEqual(markers, [])


class CheckApiReleaseTest(unittest.TestCase):
    def _check(self, served):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"releaseVersion": "%s"}' % served.encode()
        )
        with TemporaryDirectory() as tmp:
            extractor = _extractor(tmp, [])
            with mock.patch.object(extract_data, "urlopen", return_value=response):
                return extractor.check_api_release()

    def test_matching_release(self):
        self.assertTrue(self._check("9.2.0"))

    def test_other_release(self):
        self.assertFalse(self._check("9.1.0"))

    def test_unreachable_api_fails(self):
        with TemporaryDirectory() as tmp:
            extractor = _extractor(tmp, [])
            error = extract_data.URLError("down")
            with mock.patch.object(extract_data, "urlopen", side_effect=error):
                self.assertFalse(extractor.check_api_release())

    def test_malformed_body_fails(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>"
        with TemporaryDirectory() as tmp:
            with mock.patch.object(extract_data, "urlopen", return_value=response):
                self.assertFalse(_extractor(tmp, []).check_api_release())

    def test_download_all_checks_release_before_any_download(self):
        with TemporaryDirectory() as tmp:
            extractor = _extractor(tmp, [])
            with (
                mock.patch.object(extractor, "check_api_release", return_value=False),
                mock.patch.object(extractor, "download_s3_data") as s3,
                mock.patch.object(extractor, "load_fms_files") as load,
            ):
                stats = extractor.download_all()
            self.assertEqual(stats["api"], "release-mismatch")
            s3.assert_not_called()
            load.assert_not_called()


class FlatfileCacheTest(unittest.TestCase):
    def _ctx(self, tmp, idmap_hash="a", sample=None, force=False):
        return flatfiles.Context(
            data_dir=Path(tmp), idmap=GeneIdMap(), sample=sample, force=force, idmap_hash=idmap_hash
        )

    def _output(self, tmp):
        out = Path(tmp) / "pubmed" / "gene2pubmed"
        out.parent.mkdir(parents=True)
        out.write_text("x\n")
        return out

    def test_unstamped_output_is_not_cached(self):
        with TemporaryDirectory() as tmp:
            out = self._output(tmp)
            self.assertFalse(self._ctx(tmp).cached(out))

    def test_stamped_output_is_cached(self):
        with TemporaryDirectory() as tmp:
            out = self._output(tmp)
            ctx = self._ctx(tmp)
            ctx.stamp(out)
            self.assertTrue(ctx.cached(out))
            self.assertFalse(self._ctx(tmp, force=True).cached(out))

    def test_sidecar_is_outside_output_dir(self):
        with TemporaryDirectory() as tmp:
            out = self._output(tmp)
            self._ctx(tmp).stamp(out)
            self.assertEqual([p.name for p in out.parent.iterdir()], ["gene2pubmed"])
            self.assertTrue(
                (Path(tmp) / flatfiles.META_DIR / "pubmed" / "gene2pubmed.meta").is_file()
            )

    def test_idmap_change_invalidates(self):
        with TemporaryDirectory() as tmp:
            out = self._output(tmp)
            self._ctx(tmp, idmap_hash="a").stamp(out)
            self.assertFalse(self._ctx(tmp, idmap_hash="b").cached(out))

    def test_sample_flag_invalidates_both_ways(self):
        with TemporaryDirectory() as tmp:
            out = self._output(tmp)
            self._ctx(tmp, sample=100).stamp(out)
            self.assertFalse(self._ctx(tmp).cached(out))
            self._ctx(tmp).stamp(out)
            self.assertFalse(self._ctx(tmp, sample=100).cached(out))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import extract_data  # noqa: E402


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
            with mock.patch.object(extract_data, "FETCH_ALL_SCRIPT", script), mock.patch.object(
                extract_data.subprocess, "run", return_value=completed
            ) as run, mock.patch.dict(extract_data.os.environ, {"ALLIANCE_FETCH_WORKERS": "3"}):
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


if __name__ == "__main__":
    unittest.main()

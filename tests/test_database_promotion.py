"""Promotion must never delete the previous production database."""

import importlib
import re
import subprocess
from pathlib import Path

import pytest

SOURCE = "alliancemine_9_0_0_rc2"
TARGET = "alliancemine_9_0_0"
SCRIPTS = Path(__file__).resolve().parents[1] / "docker/alliancemine/scripts"


class Postgres:
    def __init__(self):
        self.databases = {SOURCE, TARGET}
        self.mutations = []
        self.fail_rename = False

    def run(self, command, **kwargs):
        sql = command[-1]
        code, output = 0, ""
        if sql.startswith("SELECT 1 FROM pg_database"):
            name = re.search(r"datname\s*=\s*'([^']+)'", sql).group(1)
            output = "1" if name in self.databases else ""
        else:
            self.mutations.append(sql)
            if sql.startswith("DROP DATABASE"):
                self.databases.remove(sql.split('"')[1])
            elif sql.startswith("ALTER DATABASE"):
                source, target = re.findall(r'"([^"]+)"', sql)
                if self.fail_rename or target in self.databases:
                    code = 1
                else:
                    self.databases.remove(source)
                    self.databases.add(target)
            elif not sql.startswith("SELECT pg_terminate_backend"):
                raise AssertionError(f"Unexpected SQL: {sql}")
        return subprocess.CompletedProcess(command, code, output, "synthetic error" if code else "")


@pytest.fixture(params=[("promote_db", "promote"), ("promote_to_production", "promote_database")])
def promotion(request, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module, name = request.param
    return getattr(importlib.import_module(module), name)


@pytest.fixture
def postgres(monkeypatch):
    server = Postgres()
    monkeypatch.setattr(subprocess, "run", server.run)
    return server


@pytest.mark.parametrize("dry_run", [False, True])
def test_existing_production_is_preserved(promotion, postgres, dry_run):
    assert promotion("9.0.0", 2, dry_run=dry_run) is False
    assert postgres.databases == {SOURCE, TARGET}
    assert postgres.mutations == []


def test_promotion_renames_candidate_when_target_is_free(promotion, postgres):
    postgres.databases.remove(TARGET)
    assert promotion("9.0.0", 2) is True
    assert postgres.databases == {TARGET}


def test_dry_run_does_not_rename_or_terminate_connections(promotion, postgres):
    postgres.databases.remove(TARGET)
    assert promotion("9.0.0", 2, dry_run=True) is True
    assert postgres.databases == {SOURCE}
    assert postgres.mutations == []


def test_failed_rename_preserves_candidate(promotion, postgres):
    postgres.databases.remove(TARGET)
    postgres.fail_rename = True
    assert promotion("9.0.0", 2) is False
    assert postgres.databases == {SOURCE}


def test_missing_candidate_does_not_touch_production(promotion, postgres):
    postgres.databases.remove(SOURCE)
    assert promotion("9.0.0", 2) is False
    assert postgres.databases == {TARGET}
    assert postgres.mutations == []

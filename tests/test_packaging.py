"""Run the wheel's advertised commands without the checkout on sys.path."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from hatchling.build import build_wheel


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory):
    directory = tmp_path_factory.mktemp("wheel")
    project = Path(__file__).resolve().parents[1]
    previous = Path.cwd()
    try:
        os.chdir(project)
        wheel = directory / build_wheel(str(directory))
    finally:
        os.chdir(previous)
    installed = directory / "site-packages"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    return installed


@pytest.mark.parametrize("command", ["mine", "build-mines", "rds-manager"])
def test_installed_console_command(installed_wheel, command):
    launch = """
import sys
from importlib.metadata import distribution
sys.path.insert(0, sys.argv.pop(1))
name = sys.argv.pop(1)
entry = next(e for e in distribution('agr-intermine-builder').entry_points if e.name == name)
sys.argv = [name, '--help']
entry.load()()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", launch, str(installed_wheel), command],
        check=False,
        cwd=installed_wheel.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize("command", ["mine", "build-mines"])
def test_installed_launcher_needs_no_dependencies(installed_wheel, tmp_path, command):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    launch = """
import sys
from importlib.metadata import distribution
sys.path.insert(0, sys.argv.pop(1))
name = sys.argv.pop(1)
entry = next(e for e in distribution('agr-intermine-builder').entry_points if e.name == name)
sys.argv[0] = name
raise SystemExit(entry.load()())
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            launch,
            str(installed_wheel),
            command,
            "--directory",
            str(tmp_path),
            "--dry-run",
            "alliancemine",
            "run",
            "pwd",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path) in result.stdout
    assert "alliancemine-builder pwd" in result.stdout


def test_legacy_module_lists_mines_without_optional_imports(tmp_path):
    result = subprocess.run(
        [sys.executable, "-S", "-B", "-m", "src.cli.build_mines", "list"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "yeastmine" in result.stdout

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scout.settings import Settings, load_settings  # noqa: E402


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway copy of config/ with an empty data/ folder."""
    shutil.copytree(PROJECT_ROOT / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def settings(project: Path) -> Settings:
    return load_settings(project)

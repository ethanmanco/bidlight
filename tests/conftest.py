from datetime import datetime, timezone
from pathlib import Path

import pytest

from bidlight.config import load_profile
from bidlight.extract import file_chunks, read_notices

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample.csv"

# The fixture was cut from the extract SAM.gov published on 2026-11-16.
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def profile():
    return load_profile(ROOT / "profile.yaml")


@pytest.fixture(scope="session")
def notices():
    return list(read_notices(file_chunks(FIXTURE)))


@pytest.fixture(scope="session")
def by_id(notices):
    """Look up a fixture notice by the first 8 characters of its NoticeId."""
    table = {n.notice_id[:8]: n for n in notices}
    return lambda prefix: table[prefix]

from datetime import datetime, timezone

import pytest

from bidlight.extract import (
    ExtractFormatError,
    decode_line,
    file_chunks,
    read_notices,
    split_lines,
)
from bidlight.notice import normalize_set_aside, parse_deadline

from .conftest import FIXTURE


def test_reads_every_row(notices):
    assert len(notices) == 59
    assert all(len(n.notice_id) == 32 for n in notices)
    assert len({n.notice_id for n in notices}) == 59


def test_fields_are_mapped(by_id):
    n = by_id("73f1f0e3")
    assert n.title == "IMT HDB Service IDIQ Contract"
    assert n.solicitation_number == "140R4026R0021"
    assert n.agency == "INTERIOR, DEPARTMENT OF THE"
    assert n.notice_type == "Solicitation"
    assert n.naics == "541511"
    assert n.set_aside_code == "SBA"
    assert "Hydrological Database" in n.description


def test_public_link_not_the_login_link(by_id):
    # The extract's Link column points at the SAM.gov workspace, which needs a login.
    assert by_id("73f1f0e3").url == "https://sam.gov/opp/73f1f0e3fd98489ab214a6075799a3f1/view"


def test_windows_1252_row_decodes(by_id):
    # This row's bytes are not valid UTF-8 (0x93 is a Windows-1252 left quote).
    raw = FIXTURE.read_bytes()
    assert b'subpart 12.6, \x93Streamlined' in raw
    text = by_id("10e97575").description
    assert "“Streamlined Procedures" in text
    assert "�" not in text


def test_utf8_row_is_not_garbled(by_id):
    text = by_id("f4466075").description
    assert any(ord(c) > 127 for c in text)
    assert "�" not in text
    assert "â€" not in text  # classic UTF-8-read-as-1252 garbage


def test_decode_line_prefers_utf8():
    assert decode_line("café".encode("utf-8")) == "café"
    assert decode_line(b"\x93quoted\x94") == "“quoted”"


def test_chunk_size_does_not_change_results(notices):
    tiny = list(read_notices(file_chunks(FIXTURE, size=7)))
    assert [n.notice_id for n in tiny] == [n.notice_id for n in notices]
    assert [n.description for n in tiny] == [n.description for n in notices]


def test_split_lines_keeps_partial_last_line():
    assert list(split_lines([b"a\nb", b"c\n", b"d"])) == [b"a\n", b"bc\n", b"d"]


def test_missing_column_stops_the_run():
    header = b'"NoticeId","Title"\n"abc","x"\n'
    with pytest.raises(ExtractFormatError, match="Sol#"):
        list(read_notices([header]))


def test_empty_file_stops_the_run():
    with pytest.raises(ExtractFormatError):
        list(read_notices([b""]))


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SBA", "SBA"),
        ('["SBA"]', "SBA"),
        ('[""]', ""),
        ("NONE", ""),
        ("", ""),
        ("sdvosbc", "SDVOSBC"),
    ],
)
def test_set_aside_normalized(raw, expected):
    assert normalize_set_aside(raw) == expected


def test_bracketed_set_aside_in_real_row(by_id):
    assert by_id("cd3041b7").set_aside_code == "SBA"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2027-01-15T15:00:00-05:00", datetime(2027, 1, 15, 20, 0, tzinfo=timezone.utc)),
        ("2026-12-18T10:00:00+03:00", datetime(2026, 12, 18, 7, 0, tzinfo=timezone.utc)),
        # Date only: end of that day, US Eastern.
        ("2026-12-02", datetime(2026, 12, 3, 4, 59, tzinfo=timezone.utc)),
        # No zone: US Eastern.
        ("2026-12-04T17:00:00", datetime(2026, 12, 4, 22, 0, tzinfo=timezone.utc)),
        ("", None),
        ("not a date", None),
    ],
)
def test_deadline_formats(raw, expected):
    assert parse_deadline(raw) == expected


def test_real_rows_with_each_deadline_format(by_id):
    assert by_id("03925549").deadline == datetime(2026, 12, 3, 4, 59, tzinfo=timezone.utc)
    assert by_id("402aab2c").deadline == datetime(2026, 12, 4, 22, 0, tzinfo=timezone.utc)
    assert by_id("6061b69e").deadline == datetime(2026, 12, 18, 7, 0, tzinfo=timezone.utc)
    assert by_id("7d87b348").deadline is None


def test_amendments_share_a_group_key(notices):
    pqc = [n for n in notices if n.title.startswith("Post Quantum Cryptography")]
    assert len(pqc) == 8
    assert len({n.notice_id for n in pqc}) == 8
    assert len({n.group_key for n in pqc}) == 1

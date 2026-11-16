"""Stream and parse the SAM.gov Contract Opportunities CSV extract.

The file is about 200 MB, so it is never loaded whole: bytes arrive in
chunks, are split into lines, decoded one line at a time, and fed to the
csv module, which yields one row at a time.

The file's text encoding is mixed. Most of it is Windows-1252 (smart quotes
as byte 0x93), but some rows hold UTF-8. Each line is tried as UTF-8 first
and falls back to Windows-1252, so both kinds come out readable.
"""

from __future__ import annotations

import csv
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

import requests

from .notice import Notice, normalize_set_aside, parse_deadline, parse_posted

EXTRACT_URL = (
    "https://s3.amazonaws.com/falextracts/Contract%20Opportunities/datagov/"
    "ContractOpportunitiesFullCSV.csv"
)

# Columns Bidlight reads. If SAM.gov renames or drops one, the run stops with
# a clear message instead of quietly matching nothing.
REQUIRED_COLUMNS = (
    "NoticeId",
    "Title",
    "Sol#",
    "Department/Ind.Agency",
    "Sub-Tier",
    "Office",
    "PostedDate",
    "Type",
    "SetASideCode",
    "SetASide",
    "ResponseDeadLine",
    "NaicsCode",
    "PopCity",
    "PopState",
    "PopCountry",
    "Description",
)

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


class ExtractFormatError(RuntimeError):
    """The extract's header no longer has the columns Bidlight needs."""


def decode_line(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Windows-1252 leaves 5 byte values undefined; replace those.
        return raw.decode("cp1252", errors="replace")


def split_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Turn a stream of byte chunks into lines, keeping the line endings."""
    pending = b""
    for chunk in chunks:
        if not chunk:
            continue
        pending += chunk
        lines = pending.split(b"\n")
        pending = lines.pop()
        for line in lines:
            yield line + b"\n"
    if pending:
        yield pending


def decoded_lines(chunks: Iterable[bytes]) -> Iterator[str]:
    for raw in split_lines(chunks):
        yield decode_line(raw)


def file_chunks(path: str | Path, size: int = 1 << 20) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(size):
            yield chunk


def url_chunks(url: str = EXTRACT_URL, size: int = 1 << 20, timeout: int = 60) -> Iterator[bytes]:
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        yield from response.iter_content(chunk_size=size)


def check_header(header: list[str]) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ExtractFormatError(
            "The SAM.gov extract is missing expected column(s): "
            + ", ".join(missing)
            + ". The file format may have changed; see the README."
        )


def row_to_notice(row: dict[str, str]) -> Notice:
    return Notice(
        notice_id=row["NoticeId"].strip(),
        title=row["Title"].strip(),
        solicitation_number=row["Sol#"].strip(),
        agency=row["Department/Ind.Agency"].strip(),
        sub_tier=row["Sub-Tier"].strip(),
        office=row["Office"].strip(),
        posted=parse_posted(row["PostedDate"]),
        notice_type=row["Type"].strip(),
        set_aside_code=normalize_set_aside(row["SetASideCode"]),
        set_aside=row["SetASide"].strip(),
        deadline=parse_deadline(row["ResponseDeadLine"]),
        naics=row["NaicsCode"].strip(),
        pop_city=row["PopCity"].strip(),
        pop_state=row["PopState"].strip().upper(),
        pop_country=row["PopCountry"].strip().upper(),
        description=row["Description"],
        source="extract",
    )


def read_notices(chunks: Iterable[bytes]) -> Iterator[Notice]:
    """Yield one Notice per data row of the extract."""
    reader = csv.reader(decoded_lines(chunks))
    try:
        header = next(reader)
    except StopIteration:
        raise ExtractFormatError("The SAM.gov extract is empty.") from None
    header = [h.lstrip("﻿").strip() for h in header]
    check_header(header)
    width = len(header)
    for values in reader:
        if not values:
            continue
        if len(values) < width:
            values = values + [""] * (width - len(values))
        row = dict(zip(header, values))
        if not row.get("NoticeId", "").strip():
            continue
        yield row_to_notice(row)

"""Copy chosen rows from a downloaded extract into a small test fixture.

Rows are copied byte for byte (no re-encoding), so the fixture keeps the
real file's mixed Windows-1252 / UTF-8 text.

Usage: python scripts/cut_fixture.py EXTRACT.csv OUT.csv ID [ID ...]
Every row that shares an opportunity (solicitation number + agency) with a
chosen id is copied too, so amendments come along.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bidlight.extract import check_header, decode_line, file_chunks, row_to_notice, split_lines  # noqa: E402


def rows_with_bytes(path: str):
    """Yield (raw_bytes, row_dict) for every record, header first as (bytes, None)."""
    raw_lines = split_lines(file_chunks(path))
    buffer: list[bytes] = []

    def feed():
        for raw in raw_lines:
            buffer.append(raw)
            yield decode_line(raw)

    reader = csv.reader(feed())
    header = [h.lstrip("\ufeff") for h in next(reader)]
    check_header(header)
    yield b"".join(buffer), None
    buffer.clear()
    for values in reader:
        raw = b"".join(buffer)
        buffer.clear()
        yield raw, dict(zip(header, values))


def main() -> None:
    src, out, *ids = sys.argv[1:]
    wanted = set(ids)
    keys = set()
    for _, row in rows_with_bytes(src):
        if row and row["NoticeId"] in wanted:
            keys.add(row_to_notice(row).group_key)
    with open(out, "wb") as f:
        for raw, row in rows_with_bytes(src):
            if row is None or row["NoticeId"] in wanted or row_to_notice(row).group_key in keys:
                f.write(raw)


if __name__ == "__main__":
    main()

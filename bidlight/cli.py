"""Run Bidlight: python -m bidlight [options]."""

from __future__ import annotations

import argparse
import itertools
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import extract
from .config import load_profile
from .digest import DigestInput, render
from .github import GitHubError, post_issue
from .match import find_matches
from .sam_api import fetch_recent
from .state import SentLog
from .summarize import summarize

log = logging.getLogger("bidlight")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bidlight", description="Daily federal contract radar.")
    p.add_argument("--profile", default="profile.yaml")
    p.add_argument("--capability", default="capability.md")
    p.add_argument("--state", default="state/sent.json")
    p.add_argument("--file", help="read a local copy of the extract instead of downloading it")
    p.add_argument("--out", default="digest.md", help="where to write the digest Markdown")
    p.add_argument("--now", help="pretend the current time is this ISO timestamp (testing)")
    p.add_argument("--post", action="store_true", help="post the digest as a GitHub issue")
    p.add_argument("--dry-run", action="store_true", help="do not post and do not update the state file")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    profile = load_profile(args.profile)
    capability_path = Path(args.capability)
    capability = capability_path.read_text(encoding="utf-8") if capability_path.exists() else ""

    if args.file:
        log.info("Reading %s", args.file)
        chunks = extract.file_chunks(args.file)
    else:
        log.info("Streaming %s", extract.EXTRACT_URL)
        chunks = extract.url_chunks()
    notices = extract.read_notices(chunks)
    source_notes = ["Source: SAM.gov Contract Opportunities extract (rebuilt nightly)."]

    api_key = os.environ.get("SAM_API_KEY", "").strip()
    if api_key and profile.sam_api.enabled and profile.naics:
        api = fetch_recent(api_key, profile.naics, now, profile.sam_api.max_requests_per_run)
        log.info(api.note)
        source_notes.append(api.note)
        notices = itertools.chain(notices, api.notices)

    matches, stats = find_matches(notices, profile, now)
    log.info("Scanned %s notices, %s opportunities match", f"{stats['scanned']:,}", len(matches))

    sent = SentLog.load(args.state)
    first_run = sent.is_first_run
    sorted_ = sent.sort(matches)
    log.info("%d new, %d amended, %d already sent", len(sorted_.new), len(sorted_.amended), sorted_.unchanged)

    ai = summarize(sorted_.new[: profile.top_n], capability, profile.ai)

    digest = render(
        DigestInput(
            profile=profile,
            now=now,
            new=sorted_.new,
            amended=sorted_.amended,
            summaries=ai.summaries,
            stats=stats,
            source_note=" ".join(source_notes),
            ai_note=ai.note,
            first_run=first_run,
        )
    )
    if digest is None:
        log.info("Nothing new or amended. No digest today.")
        Path(args.out).unlink(missing_ok=True)
    else:
        Path(args.out).write_text(f"<!-- {digest.title} -->\n{digest.body}\n", encoding="utf-8")
        log.info("Wrote %s: %s", args.out, digest.title)

    if args.dry_run:
        return 0

    if digest is not None and args.post:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        if not repo or not token:
            log.error("--post needs GITHUB_REPOSITORY and GITHUB_TOKEN (set automatically in GitHub Actions).")
            return 1
        try:
            url = post_issue(repo, token, digest.title, digest.body)
        except GitHubError as exc:
            # Leave the state untouched so tomorrow's run sends these again.
            log.error("Posting failed: %s", exc)
            return 1
        log.info("Posted %s", url)

    for m in sorted_.new:
        sent.record(m, now)
    for m, _ in sorted_.amended:
        sent.record(m, now)
    pruned = sent.prune(now)
    sent.save(args.state)
    log.info("Saved %s (%d tracked, %d pruned)", args.state, len(sent.entries), pruned)
    return 0


if __name__ == "__main__":
    sys.exit(main())

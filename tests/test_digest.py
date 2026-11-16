from dataclasses import replace

from bidlight.digest import DigestInput, Summary, no_dashes, render
from bidlight.match import find_matches

from .conftest import NOW


def make(profile, notices, **kw):
    matches = find_matches(notices, profile, NOW)[0]
    base = dict(profile=profile, now=NOW, new=matches, amended=[], source_note="Source: test.")
    base.update(kw)
    return DigestInput(**base)


def test_nothing_new_means_no_digest(profile):
    assert render(DigestInput(profile=profile, now=NOW, new=[], amended=[])) is None


def test_title_and_entries(profile, notices):
    d = render(make(profile, notices))
    assert d.title == "Bidlight: 6 new matches, Mon Nov 16, 2026"
    assert d.body.count("\n### ") == 6
    assert "[Official notice on SAM.gov](https://sam.gov/opp/8c1636c4e92e464c9553d5004e47c780/view)" in d.body
    assert "**Respond by:** Fri Dec 18, 11:00 AM CST (32 days)" in d.body
    assert "8 versions posted" in d.body


def test_disclaimer_always_present(profile, notices):
    body = render(make(profile, notices)).body
    assert "does not decide whether your business is eligible" in body


def test_top_n_rest_listed_as_lines(profile, notices):
    small = replace(profile, top_n=2)
    body = render(make(small, notices)).body
    assert "### 1." in body and "### 2." in body and "### 3." not in body
    assert "### Also matched (4, lower scores)" in body
    assert body.count("\n- [") == 4


def test_amended_section(profile, notices):
    inp = make(profile, notices)
    inp.amended = [(inp.new[0], ["new version posted"])]
    inp.new = []
    d = render(inp)
    assert d.title == "Bidlight: 1 amended, Mon Nov 16, 2026"
    assert "### Amended since we sent them" in d.body
    assert "**new version posted**" in d.body


def test_summaries_are_included(profile, notices):
    inp = make(profile, notices)
    inp.summaries = {inp.new[0].notice.notice_id: Summary("FEMA wants ideas.", "Mentions accessibility.")}
    body = render(inp).body
    assert "FEMA wants ideas." in body
    assert "**Fit note:** Mentions accessibility." in body


def test_no_em_dashes_even_from_notice_titles(profile, notices):
    inp = make(profile, notices)
    first = inp.new[0]
    first.notice = replace(first.notice, title="Web Portal — Phase 2 – Support")
    body = render(inp).body
    assert "—" not in body and "–" not in body
    assert "Web Portal, Phase 2 - Support" in body


def test_no_dashes_helper():
    assert no_dashes("a — b—c – d") == "a, b, c - d"


def test_body_fits_github_limit(profile, notices):
    inp = make(profile, notices)
    inp.new = inp.new * 3000
    assert len(render(inp).body) <= 60_000


def test_first_run_note(profile, notices):
    assert "First run" in render(make(profile, notices, first_run=True)).body
    assert "First run" not in render(make(profile, notices)).body

# Test fixture

`sample.csv` holds 59 real rows copied byte for byte from the SAM.gov
Contract Opportunities extract published on 2026-11-16, made with:

```
python scripts/cut_fixture.py ContractOpportunitiesFullCSV.csv tests/fixtures/sample.csv <NoticeId> ...
```

The cutter also copies every row that shares an opportunity (solicitation
number plus agency) with a chosen notice, so amendments come along.

Rows were chosen to cover:

- matches with NAICS codes and description keywords (FEMA, DLA, Navy, Interior)
- amendments: Post Quantum Cryptography (8 versions), Pilot Training (2 versions)
- one notice posted 18 times with different NAICS codes (VA small business event)
- a solicitation later closed by an award notice (VA 36C10B27R0001)
- a title-keyword match without a matching NAICS code (2019 "Job Recruiting Website Access")
- a place of performance outside the US, a deadline too soon, a stale 2018 notice with no deadline
- excluded title words ("Hardware", "Event")
- a row that is not valid UTF-8 (Windows-1252 smart quotes) and a row in UTF-8
- each deadline format: with offset, date only, no time zone, blank
- a bracketed set-aside code (`["SBA"]`)

All of it is public notice data. Contact names and emails present in the
original rows are left as published.

# ICCSearcher

Standalone Codex skill for the official International Criminal Court website.
It searches `https://www.icc-cpi.int/search`, reads linked HTML or PDF content,
and falls back to a bounded `/cases` crawl plus labelled Legal Tools ICC records
when the site's WAF blocks the native route.

Repository: <https://github.com/HuiwowICCSkills/ICCSearcher> (public).

## Install

Copy this folder into `~/.codex/skills/ICCSearcher` without `.git`, then run:

```powershell
& "$env:USERPROFILE/.codex/skills/ICCSearcher/run.ps1" doctor
```

Python dependencies are `requests`, `beautifulsoup4` and `pypdf`:

```powershell
python -m pip install -r requirements.txt
```

`run.ps1` searches for a suitable Python in the skill's `venv`, the Codex
bundled runtime, the WorkBuddy managed Python, then `python`/`python3` on PATH.

## Commands

```powershell
./run.ps1 search 'command responsibility' --limit 10
./run.ps1 search 'Ongwen' --limit 10 --offset 10
./run.ps1 fetch 'https://www.icc-cpi.int/court-record/example' --text-out ./record.txt
./run.ps1 fetch 'https://www.icc-cpi.int/sites/default/files/example.pdf' --pdf-out ./example.pdf --text-out ./example.txt
./run.ps1 doctor
```

Search results are metadata. Use `fetch` before treating a linked page or PDF as
full text. `/search` returns 25 rows per page and uses zero-based `page`
parameters. WAF challenge pages are access failures, not zero results.

See [SKILL.md](SKILL.md) for usage rules and
[references/icc-search.md](references/icc-search.md) for the verified routes and
fallback behavior.

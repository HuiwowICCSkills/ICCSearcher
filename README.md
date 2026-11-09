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

## 实测效果（2026-11-09）

以下命令与结果来自本机 `~/.codex/skills/ICCSearcher` 的实网运行；检索日期 2026-11-09（Asia/Shanghai），输出为该次运行实际返回的 JSON 报告。

```powershell
./run.ps1 search 'Ongwen' --limit 5
```

- 状态：`partial`（先失败、后走回退）。本次运行中 ICC 官网 `/search` 与 `/cases` 均返回 **HTTP 504**：`ICC site search: HTTP 504: https://www.icc-cpi.int/search?site_search_fulltext=Ongwen&sort_bef_combine=field_date_received_DESC&page=0`、`HTTP 504: https://www.icc-cpi.int/cases`。
- 随后转入 Legal Tools ICC mirror fallback（`via = icc-legal-tools-fallback`）：回退检索 `total = 4102`，本次返回 5 条。
- 分页字段：`pagination.cases-crawl = {pages_attempted: 1, queued_unvisited: 0, matched_in_visited_pages: 0, errors: ["HTTP 504: https://www.icc-cpi.int/cases"], exhaustive: false}`；`pagination.legal-tools-icc = {total: 4102, offset: 0, limit: 5, next_offset: 5}`。
- 代表性结果：

| 题名 | 类型 / 日期 | 案件号 / 文书号 | 链接 |
| --- | --- | --- | --- |
| Waran Me Mako Dominic Ongwen | arrest_warrant_indictment；07/08/2005 00:00:00 | ICC-02/04-01/15；ICC-02/04-01/15-6-tACH-Corr | http://www.legal-tools.org/doc/f4067d/ |
| Waran me mako Dominic Ongwen | arrest_warrant_indictment；07/09/2005 00:00:00 | ICC-02/04-01/05；ICC-02/04-01/05-57-tAC-Corr | http://www.legal-tools.org/doc/d4fa4c/ |
| Waran Me Mako Dominic Ongwen | arrest_warrant_indictment；07/08/2005 00:00:00 | ICC-02/04-01/05；ICC-02/04-01/05-10-tACH-Corr | http://www.legal-tools.org/doc/fc242f/ |
| Mandat d'Arrêt de Dominic Ongwen | arrest_warrant_indictment；07/08/2005 00:00:00 | ICC-02/04-01/05；ICC-02/04-01/05-10-tFRA | http://www.legal-tools.org/doc/141efe/ |
| Submission of Information Regarding Dominic Ongwen | other_court_documents；10/05/2005 00:00:00 | ICC-02/04-01/15；ICC-02/04-01/15-25 | http://www.legal-tools.org/doc/aa6d8f/ |

> 说明：这批结果**不代表 ICC 官网的实时状态，也不是"官网零命中"**。官网两条检索路径当时都返回 504（服务不可用），`/cases` 的有界爬取只尝试了 1 页、`matched_in_visited_pages = 0`、`exhaustive = false`，报告本身也写明 `Bounded /cases crawl: no hit does not establish absence from the ICC site.` 以及 `Fallback records cannot confirm current case status, completeness, or updates on the live ICC site.`。回退结果来自 Legal Tools 的 ICC mirror，是**元数据与索引片段**（`access = Legal Tools ICC mirror metadata and index snippet; full text not yet fetched`），不是文书全文，`total = 4102` 是全库检索命中数而非本案文书数；引用前须 `fetch` 对应的 PDF 并核对文书号、日期与分庭。

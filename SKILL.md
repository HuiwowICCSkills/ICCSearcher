---
name: icc-searcher
description: 独立检索国际刑事法院（ICC）官网，查找法院文书、新闻稿、案件页及其他站点内容；支持零基分页、WAF 识别、有限 /cases 回退、Legal Tools 镜像回退，以及读取链接页面或 PDF。不替代 ICC Legal Tools 全库检索。
---

# ICCSearcher

> **`<skill-dir>`** = 本 SKILL.md 所在目录。核心脚本为 `<skill-dir>/scripts/icc_search.py`；Windows 用 `<skill-dir>/run.ps1`，macOS/Linux 用 `<skill-dir>/run.sh`。接口和实测边界见 [references/icc-search.md](references/icc-search.md)，部署见 [README.md](README.md)。

这个 skill 只处理 ICC 官网渠道：

- `search`：调用 `https://www.icc-cpi.int/search`，检索法院文书、新闻稿、案件页和其他 ICC 站点页面。
- `fetch`：读取搜索结果链接的 HTML 正文或 PDF，并返回文本、页数、哈希和 PDF 链接。
- `doctor`：检查 ICC 原生站内搜索与 Legal Tools 回退是否可用。

## 命令

```powershell
# 原生站内搜索
& '<skill-dir>/run.ps1' search 'command responsibility' --limit 10

# 第二页；ICC 的 page 参数从 0 开始，本 CLI 对外使用条目 offset
& '<skill-dir>/run.ps1' search 'Ongwen' --limit 10 --offset 10

# 读取链接页面；若有 PDF 链接，会列在 pdf_links
& '<skill-dir>/run.ps1' fetch 'https://www.icc-cpi.int/court-record/example' --text-out './record.txt'

# 读取 PDF
& '<skill-dir>/run.ps1' fetch 'https://www.icc-cpi.int/sites/default/files/example.pdf' --pdf-out './example.pdf' --text-out './example.txt'

# 自检
& '<skill-dir>/run.ps1' doctor
```

通用参数：`--cache`、`--cache-ttl`、`--offline`、`--out`。`search` 另有 `--limit`（1..50）、`--offset`、`--max-pages`、`--depth`；`fetch` 另有 `--pdf-out`、`--text-out`。

## 结果边界

- `/search` 每页渲染 25 条，总数写成 `About N results`；Drupal `page` 参数为零基。
- 搜索结果只是页面元数据，不是链接文书正文。引用前必须对 `url` 运行 `fetch`，并核对实际文本、日期、文书号和程序状态。
- 搜索结果覆盖 `/court-record/`、`/news/`、`/case...` 等路径，不能把新闻稿当作法院裁判文书。
- 高位阶直接判例不足时，可继续检索同一争点在相关案件的当事人书状、程序异议和裁判中如何出现。通常先用书状或程序记录确认争点已提交，再以 `fetch` 到的裁判全文确认分庭未支持亦未否定，之后才能标为“明示未决”“以其他理由回避”或“仅提及未处理”，并记录对应段落、程序阶段和未裁判原因；搜索命中或不能证明争点曾被提出，都不能推定 ICC 留有空间。
- ICC 前门可能返回 `Loading site please wait...`、Cookie/JavaScript 挑战或 `Sorry, you have been blocked`。这些是访问失败，不是零结果。
- 原生 `/search` 失败时，`search` 才降级到有限 `/cases` 爬取和 Legal Tools ICC 机构过滤记录；回退结果会标记 `partial`，不能证明官网当前状态或完整覆盖。
- ICC Legal Tools Database 的完整检索、官方文号精确定位和 PDF 下载由独立 `LegalToolsSearcher` 承担。本 skill 只把 Legal Tools 用作 ICC 官网失败时的标注镜像回退。
- `doctor` 在原生站内搜索被 WAF 拦截但 Legal Tools 可用时返回 `degraded`，不会把站点不可达伪装成正常。

## 参考

- 路由、参数、HTML 结构、WAF 和分页实测：[references/icc-search.md](references/icc-search.md)
- 安装、依赖与排错：[README.md](README.md)

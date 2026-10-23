# ICC official site search: verified interface

Validated 2026-10-24 with direct HTTP. No login, CAPTCHA bypass, or access-control
bypass was used.

## Native search

`GET https://www.icc-cpi.int/search`

Parameters:

| Parameter | Value |
|---|---|
| `site_search_fulltext` | search query |
| `sort_bef_combine` | `field_date_received_DESC` |
| `page` | zero-based result page |

Observed server-rendered page:

- 25 `div.views-row` entries per page.
- Total count text: `About N results`.
- Pager links use `page=0` for page 1 and expose the last page number.
- Court-record rows carry `.recordTitle`, `.courtRecordcaseNameSearch` and
  `ul.tags`.
- News and other result types can expose the title only through the anchor's
  `title` or text.
- Result paths distinguish `/court-record/`, `/news/` and `/case...`.

Observed successful queries:

- `abcd`: 153 results, 18 pages.
- `Ongwen`: 446 results.
- `command responsibility`: 126 results.

## Access challenge

The ICC front door can replace the search result with:

- `Loading site please wait...`
- a Cookie/JavaScript requirement page
- `Sorry, you have been blocked`

These are `AccessError` conditions. They are never a confirmed zero. Later
requests from the same validation environment were blocked after the successful
samples above.

## Search-result fallbacks

When native `/search` fails:

1. Crawl `https://www.icc-cpi.int/cases` with a bounded page/depth budget.
2. Query Legal Tools with the ICC organisation filter:

```json
{
  "term": "<query>",
  "filter": "{\"from\":0,\"limit\":10,\"where\":{\"deleted\":false,\"organisation\":\"International Criminal Court (ICC)\"}}"
}
```

The fallback rows are labelled `icc-cases-crawl`, `icc-cases-pdf`,
`icc-cases-link`, or `icc-legal-tools-fallback`. They do not establish live ICC
case status or complete coverage.

## Fetch

`fetch <url>` accepts a URL returned by the search route or a linked ICC PDF.

- HTML: extracts the main content, reports `text_characters`, and lists PDF
  links as `pdf_links`.
- PDF: extracts page text, reports `page_count`, `needs_ocr`, SHA-256 and can
  write `--pdf-out` / `--text-out`.
- Search snippets and result metadata are not substitutes for the linked text.

## Status meanings

- `ok`: native ICC site search succeeded.
- `no-results-in-queried-index`: the native route returned an explicit zero.
- `partial`: native search failed and at least one labelled fallback route was
  used.
- `unavailable-or-incomplete`: native search failed and no fallback returned a
  row.
- `doctor=degraded`: native search is blocked but Legal Tools fallback responds.

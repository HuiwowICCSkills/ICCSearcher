"""Offline behavior tests for the standalone ICCSearcher skill."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import icc_search as s


def icc_entry(href, title, case_name="", tags=None, record_title=True):
    heading = f'<div class="recordTitle">{title}</div>' if record_title else ""
    case = (
        f'<div class="courtRecordcaseNameSearch">{case_name}</div>'
        if case_name
        else ""
    )
    tag_html = "".join(f"<li>{tag}</li>" for tag in (tags or []))
    tags_html = f'<ul class="tags">{tag_html}</ul>' if tag_html else ""
    return (
        '<div class="record-holder ms-rte-wpbox views-row">'
        f'<a class="court_record_link" href="{href}" title="{title}">'
        f'<div class="ms-srch-item">{heading}{case}{tags_html}</div>'
        "</a></div>"
    )


def icc_page(entries, total, pages, page=0):
    label = f"About {total} results" if total else "No results found"
    pager = "".join(f'<a href="?page={index}">{index + 1}</a>' for index in range(max(pages, 1)))
    return (
        '<html><body><div class="view">'
        + "".join(entries)
        + f"</div><div>{label}</div><nav class=\"pager\">{pager}</nav></body></html>"
    )


class SearchHTTP:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.evidence = []

    def get(self, url, params=None, headers=None):
        page = int((params or {}).get("page") or 0)
        self.calls.append((url, dict(params or {})))
        body = self.pages.get(page)
        if body is None:
            raise s.AccessError(f"missing ICC search fixture page {page}")
        self.evidence.append({"request_url": url, "status": 200})
        return body.encode(), {
            "request_url": url,
            "status": 200,
            "content_type": "text/html",
            "retrieved_at": "test",
            "sha256": "a" * 64,
        }


class JsonHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.evidence = []

    def json(self, url, params=None):
        self.calls.append((url, params))
        self.evidence.append({"request_url": url, "status": 200})
        return self.response, {
            "request_url": url,
            "status": 200,
            "content_type": "application/json",
            "retrieved_at": "test",
            "sha256": "b" * 64,
        }


class FetchHTTP:
    def __init__(self, body, content_type):
        self.body = body
        self.content_type = content_type
        self.evidence = []

    def get(self, url, params=None, headers=None):
        self.evidence.append({"request_url": url, "status": 200})
        return self.body, {
            "request_url": url,
            "status": 200,
            "content_type": self.content_type,
            "retrieved_at": "test",
            "sha256": "c" * 64,
        }


class ICCBehavior(unittest.TestCase):
    def test_site_search_parses_court_records_news_and_parameters(self):
        court = icc_entry(
            "/court-record/icc-02/04-01/15-2109",
            "Trust Fund for Victims report on reparations",
            "The Prosecutor v. Dominic Ongwen",
            [
                "18 June 2025",
                "Report",
                "Trust Fund for Victims",
                "ICC-02/04-01/15-2109-AnxIII",
            ],
        )
        news = icc_entry(
            "/news/statement-on-command-responsibility",
            "Statement on command responsibility",
            record_title=False,
        )
        http = SearchHTTP({0: icc_page([court, news], 27, 2, 0)})
        rows, info = s.icc_search(http, "command responsibility", 2, 0)
        self.assertEqual(info["total"], 27)
        self.assertEqual(info["pages"], 2)
        self.assertEqual(info["page_size"], 25)
        self.assertEqual(info["next_offset"], 2)
        self.assertEqual(rows[0]["via"], "icc-site-search")
        self.assertEqual(rows[0]["case_name"], "The Prosecutor v. Dominic Ongwen")
        self.assertEqual(rows[0]["case_number"], "ICC-02/04-01/15-2109-AnxIII")
        self.assertEqual(rows[0]["document_type"], "Report")
        self.assertEqual(rows[1]["title"], "Statement on command responsibility")
        self.assertEqual(rows[1]["source_type"], "ICC news or press material")
        url, params = http.calls[0]
        self.assertEqual(url, s.SEARCH_URL)
        self.assertEqual(params["site_search_fulltext"], "command responsibility")
        self.assertEqual(params["sort_bef_combine"], "field_date_received_DESC")
        self.assertEqual(params["page"], 0)

    def test_site_search_uses_zero_based_server_pages(self):
        news = icc_entry("/news/second-page", "Second page result", record_title=False)
        http = SearchHTTP({1: icc_page([news], 27, 2, 1)})
        rows, info = s.icc_search(http, "Ongwen", 1, 25)
        self.assertEqual([row["title"] for row in rows], ["Second page result"])
        self.assertEqual(info["page"], 1)
        self.assertEqual(info["next_offset"], 26)
        self.assertEqual(http.calls[0][1]["page"], 1)

    def test_confirmed_zero_is_not_a_failure(self):
        http = SearchHTTP(
            {
                0: (
                    '<html><body><div class="view-empty">'
                    "No results found"
                    "</div></body></html>"
                )
            }
        )
        rows, info = s.icc_search(http, "zzzxnonexistent785132904", 5, 0)
        self.assertEqual(rows, [])
        self.assertEqual(info["total"], 0)
        self.assertIsNone(info["next_offset"])

    def test_missing_results_is_not_zero_hits(self):
        http = SearchHTTP({0: "<html><body><h1>Search</h1></body></html>"})
        with self.assertRaisesRegex(s.AccessError, "neither a result count"):
            s.icc_search(http, "Ongwen", 5, 0)

    def test_access_challenge_is_not_zero_hits(self):
        http = SearchHTTP(
            {
                0: (
                    "<html><body>Loading site please wait... "
                    "Cookies disabled</body></html>"
                )
            }
        )
        with self.assertRaisesRegex(s.AccessError, "access challenge"):
            s.icc_search(http, "Ongwen", 5, 0)

    def test_search_uses_native_results_without_fallbacks(self):
        hit = s.result(
            "Decision",
            "https://www.icc-cpi.int/court-record/example",
            "icc-site-search",
        )
        info = {
            "total": 1,
            "offset": 0,
            "limit": 2,
            "page_size": 25,
            "page": 0,
            "pages": 1,
            "pages_fetched": 1,
            "next_offset": None,
        }
        http = SimpleNamespace(evidence=[])
        with (
            patch.object(s, "icc_search", return_value=([hit], info)),
            patch.object(s, "crawl_cases", side_effect=AssertionError("crawl should not run")),
            patch.object(
                s,
                "legal_tools_fallback",
                side_effect=AssertionError("fallback should not run"),
            ),
        ):
            report = s.search(http, "Ongwen", 2, 0)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["results"][0]["via"], "icc-site-search")
        self.assertIn("icc-site-search", report["pagination"])

    def test_search_falls_back_when_native_route_is_blocked(self):
        crawl_hit = s.result(
            "Case page",
            "https://www.icc-cpi.int/cases/example",
            "icc-cases-crawl",
        )
        mirror_hit = s.result(
            "Mirror record",
            "https://www.legal-tools.org/doc/example/",
            "icc-legal-tools-fallback",
        )
        crawl_info = {
            "pages_attempted": 1,
            "queued_unvisited": 0,
            "matched_in_visited_pages": 1,
            "errors": [],
            "exhaustive": False,
        }
        http = SimpleNamespace(evidence=[])
        with (
            patch.object(s, "icc_search", side_effect=s.AccessError("access challenge")),
            patch.object(s, "crawl_cases", return_value=([crawl_hit], crawl_info)),
            patch.object(s, "legal_tools_fallback", return_value=([mirror_hit], 1)),
        ):
            report = s.search(http, "Ongwen", 2, 0)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(
            {row["via"] for row in report["results"]},
            {"icc-cases-crawl", "icc-legal-tools-fallback"},
        )
        self.assertIn("cases-crawl", report["pagination"])
        self.assertIn("legal-tools-icc", report["pagination"])

    def test_legal_tools_fallback_filters_to_icc(self):
        response = {
            "results": [
                {
                    "hit": {
                        "title": "Decision",
                        "slug": "example",
                        "externalId": "ICC-01/04-01/06-1",
                        "organisation": s.ICC_ORGANISATION,
                        "caseNumber": "ICC-01/04-01/06",
                        "dateCreated": "2006-01-01",
                    },
                    "highlight": {"title": ["Decision"]},
                }
            ],
            "total": 1,
        }
        http = JsonHTTP(response)
        rows, total = s.legal_tools_fallback(http, "decision", 1, 0)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["via"], "icc-legal-tools-fallback")
        self.assertEqual(rows[0]["id"], "ICC-01/04-01/06-1")
        filter_value = json.loads(http.calls[0][1]["filter"])
        self.assertEqual(filter_value["where"]["organisation"], s.ICC_ORGANISATION)
        self.assertFalse(filter_value["where"]["deleted"])

    def test_fetch_extracts_html_text_and_pdf_links(self):
        body = (
            "<html><head><title>Court record</title></head><body>"
            "<nav>Navigation</nav><main><h1>Decision</h1>"
            "<p>The Chamber decided the issue.</p>"
            '<a href="/sites/default/files/decision.pdf">Decision PDF</a>'
            "</main></body></html>"
        ).encode()
        fake = FetchHTTP(body, "text/html")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(s, "HTTP", lambda *args, **kwargs: fake),
        ):
            output = s.fetch(
                "https://www.icc-cpi.int/court-record/example",
                tmp,
                text_out=str(Path(tmp) / "record.txt"),
            )
            self.assertTrue((Path(tmp) / "record.txt").is_file())
        self.assertEqual(output["title"], "Court record")
        self.assertIn("The Chamber decided the issue.", output["text"])
        self.assertNotIn("Navigation", output["text"])
        self.assertEqual(len(output["pdf_links"]), 1)
        self.assertTrue(output["pdf_links"][0]["url"].endswith("decision.pdf"))

    def test_doctor_degrades_when_native_search_is_blocked(self):
        fallback = s.result(
            "Mirror",
            "https://www.legal-tools.org/doc/example/",
            "icc-legal-tools-fallback",
        )
        with (
            patch.object(s, "HTTP", lambda *args, **kwargs: SimpleNamespace(evidence=[])),
            patch.object(s, "icc_search", side_effect=s.AccessError("access challenge")),
            patch.object(s, "legal_tools_fallback", return_value=([fallback], 1)),
        ):
            output = s.doctor("unused")
        self.assertEqual(output["status"], "degraded")
        self.assertEqual(output["native_search"]["status"], "blocked")
        self.assertEqual(output["legal_tools_fallback"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()

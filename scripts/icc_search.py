"""Standalone ICC official-site retrieval: search, fallback records, and fetch."""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import http.cookiejar
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://www.icc-cpi.int/search"
CASES_URL = "https://www.icc-cpi.int/cases"
LEGAL_TOOLS_API = "https://legal-tools.org/api/ltddocs/search"
ICC_ORGANISATION = "International Criminal Court (ICC)"
ICC_PAGE_SIZE = 25
ICC_MAX_SEARCH_PAGES = 20
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)
NOW = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

ICC_DOCUMENT_TYPES = {
    "appeal",
    "decision",
    "evidence",
    "judgment",
    "judgement",
    "motion",
    "observations",
    "order",
    "press release",
    "report",
    "request",
    "response",
    "statement",
    "submission",
    "transcript",
}


class AccessError(RuntimeError):
    pass


def clean(value):
    value = str(value or "")
    return (
        BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
        if "<" in value
        else html_lib.unescape(value)
    )


def norm(value):
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value)).casefold()
        if not unicodedata.combining(char)
    )


def terms(query):
    return re.findall(r"\w+", norm(query))


def matches(query, value):
    return all(term in norm(value) for term in terms(query))


def snippet(query, value, width=800):
    value = clean(value)
    positions = [norm(value).find(term) for term in terms(query)]
    start = max(0, min((pos for pos in positions if pos >= 0), default=0) - 120)
    return ("..." if start else "") + value[start : start + width]


def result(title, url, via, text="", **extra):
    return {"title": clean(title), "url": url, "via": via, "snippet": clean(text), **extra}


def dedupe(rows):
    found = {}
    for row in rows:
        key = row["url"].replace("http://", "https://").rstrip("/")
        found.setdefault(key, row)
    return list(found.values())


class HTTP:
    def __init__(self, cache, ttl=86400, offline=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.offline = offline
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.cookie_jar = self.cache / "icc.cookies.txt"
        self.session.cookies = http.cookiejar.LWPCookieJar(str(self.cookie_jar))
        try:
            self.session.cookies.load(ignore_discard=True)
        except (OSError, http.cookiejar.LoadError):
            pass
        self.evidence = []
        self.last = 0.0

    def get(self, url, params=None, headers=None):
        if urlparse(url).scheme not in ("https", "http"):
            raise AccessError("Only HTTP(S) URLs are supported")
        prepared = requests.Request("GET", url, params=params).prepare()
        identity = prepared.url + json.dumps(headers or {}, sort_keys=True)
        key = hashlib.sha256(identity.encode()).hexdigest()
        body_path = self.cache / (key + ".bin")
        meta_path = self.cache / (key + ".json")
        if body_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if self.offline or time.time() - meta_path.stat().st_mtime < self.ttl:
                self.evidence.append({**meta, "cached": True})
                return body_path.read_bytes(), meta
        if self.offline:
            raise AccessError("offline cache miss: " + prepared.url)
        time.sleep(max(0, 0.35 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        try:
            with self.session.get(
                url, params=params, headers=headers, timeout=(12, 45), stream=True
            ) as response:
                meta = {
                    "request_url": response.url,
                    "status": response.status_code,
                    "content_type": response.headers.get("Content-Type", ""),
                    "retrieved_at": NOW(),
                }
                if headers:
                    meta["request_headers"] = dict(headers)
                self.evidence.append(meta)
                if not response.ok:
                    raise AccessError(f"HTTP {response.status_code}: {response.url}")
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 40 * 1024 * 1024:
                        raise AccessError("40 MiB response limit: " + response.url)
                    chunks.append(chunk)
                body = b"".join(chunks)
                lower = body[:30000].lower()
                challenge_markers = [
                    b"loading site please wait",
                    b"sorry, you have been blocked",
                    b"security service to protect itself",
                    b"cookies disabled",
                    b"javascript disabled",
                    b"<title>just a moment",
                    b"<title>human verification",
                ]
                if any(marker in lower for marker in challenge_markers):
                    raise AccessError("access challenge: " + response.url)
                meta["sha256"] = hashlib.sha256(body).hexdigest()
                tmp = self.cache / (key + ".tmp")
                tmp.write_bytes(body)
                tmp.replace(body_path)
                tmp = self.cache / (key + ".meta.tmp")
                tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                tmp.replace(meta_path)
                try:
                    self.session.cookies.save(ignore_discard=True)
                except (OSError, ValueError):
                    pass
                return body, meta
        except requests.RequestException as exc:
            raise AccessError(f"{type(exc).__name__}: {url}") from exc

    def json(self, url, params=None):
        body, meta = self.get(url, params=params)
        try:
            return json.loads(body), meta
        except (ValueError, UnicodeError) as exc:
            raise AccessError(
                "Expected JSON, received " + meta.get("content_type", "") + ": " + url
            ) from exc


def html(http, url, params=None):
    body, meta = http.get(url, params=params)
    soup = BeautifulSoup(body, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    if "enable javascript to run this app" in text:
        raise AccessError("JavaScript shell without searchable content: " + url)
    if any(
        marker in text
        for marker in [
            "loading site please wait",
            "sorry, you have been blocked",
            "security service to protect itself",
            "cookies disabled",
            "javascript disabled",
        ]
    ):
        raise AccessError("access challenge: " + url)
    return soup, meta


def content(soup, selector=None):
    node = (
        (soup.select_one(selector) if selector else None)
        or soup.select_one("main, [role='main'], #main-content, #content, article")
        or soup
    )
    for item in node.select("script, style, nav, header, footer, form, .breadcrumb, .breadcrumbs"):
        item.decompose()
    return node


def pdf_pages(body):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AccessError("PDF extraction requires pypdf; install requirements.txt") from exc
    reader = PdfReader(io.BytesIO(body))
    return [
        {"page": number, "text": page.extract_text() or ""}
        for number, page in enumerate(reader.pages, 1)
    ]


def icc_results_page(http, query, page):
    """Return one zero-based page of ICC search: rows, total, pages."""
    soup, meta = html(
        http,
        SEARCH_URL,
        {
            "site_search_fulltext": query,
            "sort_bef_combine": "field_date_received_DESC",
            "page": page,
        },
    )
    text = soup.get_text(" ", strip=True)
    if re.search(r"\b(?:no|0)\s+(?:results|matches)(?:\s+found)?\b", text, re.I):
        return [], 0, 0
    count = re.search(r"\bAbout\s+([\d,]+)\s+results?\b", text, re.I)
    if not count:
        count = re.search(r"\b([\d,]+)\s+results?\b", text, re.I)
    nodes = soup.select("div.views-row")
    if not count:
        raise AccessError(
            "ICC search page carried neither a result count nor a confirmed zero; "
            "access challenge or schema change: " + meta["request_url"]
        )
    total = int(count.group(1).replace(",", ""))
    if not nodes and page == 0:
        raise AccessError(
            "ICC search page reported results but carried no result rows; schema change: "
            + meta["request_url"]
        )
    page_numbers = [
        int(value)
        for value in re.findall(r"(?:\?|&|&amp;)page=(\d+)", str(soup))
    ]
    pages = max(page_numbers) + 1 if page_numbers else (1 if total else 0)
    rows = []
    for node in nodes:
        link = node.select_one("a[href]")
        if not link:
            raise AccessError("ICC search result row has no link; schema change")
        url = urljoin(meta["request_url"], link["href"])
        title_node = node.select_one(
            ".recordTitle, .ms-srch-item-title, .views-field-title, h2, h3"
        )
        title = clean(title_node.get_text(" ", strip=True) if title_node else "")
        title = title or clean(link.get("title", "")) or clean(link.get_text(" ", strip=True))
        case_node = node.select_one(".courtRecordcaseNameSearch")
        case_name = clean(case_node.get_text(" ", strip=True)) if case_node else ""
        tags = [
            clean(item.get_text(" ", strip=True))
            for item in node.select("ul.tags li")
        ]
        row_text = node.get_text(" ", strip=True)
        date_match = re.search(
            r"\b\d{1,2}\s+"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{4}\b",
            row_text,
            re.I,
        )
        date = date_match.group(0) if date_match else next(
            (
                tag
                for tag in tags
                if re.fullmatch(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}", tag)
            ),
            None,
        )
        case_number = next(
            (tag for tag in tags if re.match(r"ICC-\d{2}/\d{2}", tag, re.I)),
            None,
        )
        document_type = next(
            (tag for tag in tags if tag.casefold() in ICC_DOCUMENT_TYPES),
            None,
        )
        path = urlparse(url).path
        if path.startswith("/court-record/"):
            source_type = "ICC court record"
        elif path.startswith("/news/"):
            source_type = "ICC news or press material"
        elif path.startswith("/case"):
            source_type = "ICC case information"
        else:
            source_type = "ICC site page"
        summary = " | ".join(
            value
            for value in [
                case_name,
                date,
                document_type,
                case_number,
                "; ".join(tags),
            ]
            if value
        )
        rows.append(
            result(
                title,
                url,
                "icc-site-search",
                snippet(query, summary or title),
                case_name=case_name,
                date=date,
                document_type=document_type,
                case_number=case_number,
                source_type=source_type,
                result_tags=tags,
                access=(
                    "official ICC site-search result metadata; "
                    "linked page and attachments not yet fetched"
                ),
                content_scope=(
                    "search-result metadata only; verify the linked record or document separately"
                ),
            )
        )
    return dedupe(rows), total, pages


def icc_search(http, query, limit, offset=0):
    page = offset // ICC_PAGE_SIZE
    base = page * ICC_PAGE_SIZE
    end = offset + limit
    rows = []
    total = pages = None
    fetched = 0
    while page * ICC_PAGE_SIZE < end and fetched < ICC_MAX_SEARCH_PAGES:
        batch, total, pages = icc_results_page(http, query, page)
        rows.extend(batch)
        fetched += 1
        if not batch or not total or (pages and page + 1 >= pages):
            break
        page += 1
    selected = rows[offset - base : offset - base + limit]
    more = total is None or offset + len(selected) < total
    return selected, {
        "total": total,
        "offset": offset,
        "limit": limit,
        "page_size": ICC_PAGE_SIZE,
        "page": base // ICC_PAGE_SIZE,
        "pages": pages,
        "pages_fetched": fetched,
        "next_offset": offset + len(selected) if selected and more else None,
    }


def crawl_cases(http, query, limit, offset, max_pages=12, depth=1):
    queue = [(CASES_URL, 0, "")]
    seen = set()
    rows = []
    errors = []
    fetched = 0

    def allowed(url):
        parsed = urlparse(url)
        return (
            parsed.scheme in ("http", "https")
            and parsed.hostname == "www.icc-cpi.int"
            and not re.search(r"\.(png|jpg|gif|mp4|mp3|zip|css|js)$", parsed.path, re.I)
            and "pdfcreator" not in url
        )

    while queue and fetched < max_pages:
        url, distance, label = queue.pop(0)
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        fetched += 1
        try:
            body, meta = http.get(url)
            if body.startswith(b"%PDF"):
                for page in pdf_pages(body):
                    if matches(query, page["text"]):
                        rows.append(
                            result(
                                label or url,
                                meta["request_url"] + "#page=" + str(page["page"]),
                                "icc-cases-pdf",
                                snippet(query, page["text"]),
                                page=page["page"],
                                access="ICC fallback crawl PDF page text",
                            )
                        )
                continue
            soup = BeautifulSoup(body, "html.parser")
            title = clean(soup.title.text if soup.title else label or url)
            node = content(soup)
            text = node.get_text(" ", strip=True)
            if matches(query, text):
                rows.append(
                    result(
                        title,
                        meta["request_url"],
                        "icc-cases-crawl",
                        snippet(query, text),
                        access="bounded ICC /cases crawl page text",
                    )
                )
            for link in node.select("a[href]"):
                target = urldefrag(urljoin(meta["request_url"], link["href"]))[0]
                label_text = clean(link.get_text(" ", strip=True))
                if not allowed(target):
                    continue
                if label_text and matches(query, label_text):
                    rows.append(
                        result(
                            label_text,
                            target,
                            "icc-cases-link",
                            label_text,
                            discovered_on=meta["request_url"],
                            access="catalogue-link label only; target not fetched",
                        )
                    )
                if distance < depth and target not in seen:
                    queue.append((target, distance + 1, label_text))
        except (AccessError, ValueError, ImportError) as exc:
            errors.append(str(exc))
    rows = dedupe(rows)
    return rows[offset : offset + limit], {
        "pages_attempted": fetched,
        "queued_unvisited": len(queue),
        "matched_in_visited_pages": len(rows),
        "errors": errors,
        "exhaustive": False,
    }


def legal_tools_fallback(http, query, limit, offset=0):
    payload = {
        "term": query,
        "filter": json.dumps(
            {
                "from": offset,
                "limit": limit,
                "where": {
                    "deleted": False,
                    "organisation": ICC_ORGANISATION,
                },
            }
        ),
    }
    data, _ = http.json(LEGAL_TOOLS_API, payload)
    if not isinstance(data.get("results"), list):
        raise AccessError("Legal Tools response schema changed")
    rows = []
    for record in data["results"]:
        hit = record["hit"]
        highlights = record.get("highlight") or {}
        highlight_text = " ".join(
            str(value)
            for values in highlights.values()
            for value in (values if isinstance(values, list) else [values])
        )
        rows.append(
            result(
                hit.get("title"),
                hit.get("documentUrl")
                or ("https://www.legal-tools.org/doc/" + hit["slug"] + "/"),
                "icc-legal-tools-fallback",
                snippet(query, highlight_text or hit.get("abstract", "")),
                id=hit.get("externalId") or hit.get("id"),
                case_number=hit.get("caseNumber"),
                case_name=hit.get("caseName_en") or hit.get("caseName"),
                date=hit.get("dateCreated"),
                organisation=hit.get("organisation"),
                author=hit.get("author"),
                document_type=hit.get("judicialDocumentType")
                or hit.get("contentType"),
                source_role=hit.get("source"),
                origin_url=(hit.get("documentOrigin") or {}).get("url"),
                pdf_url=hit.get("pdfURL"),
                download_permission_required=hit.get("requireDownloadPermission"),
                authoritative_language=hit.get("isAuthoritativeLanguage"),
                language_ids=hit.get("languageIds"),
                access=(
                    "Legal Tools ICC mirror metadata and index snippet; "
                    "full text not yet fetched"
                ),
            )
        )
    return rows, data.get("total")


def search(http, query, limit, offset=0, max_pages=12, depth=1):
    report = {
        "channel": "icc",
        "query": query,
        "status": "ok",
        "warnings": [],
        "results": [],
        "pagination": {},
        "evidence": http.evidence,
        "retrieved_at": NOW(),
    }
    try:
        rows, info = icc_search(http, query, limit, offset)
        report["pagination"]["icc-site-search"] = info
        report["results"] = rows
        if not rows and info.get("total") == 0:
            report["status"] = "no-results-in-queried-index"
        elif not rows and isinstance(info.get("total"), int) and offset >= info["total"]:
            report["status"] = "no-results-in-queried-index"
        elif rows:
            report["warnings"].append(
                "ICC site-search rows are page metadata; fetch the linked record or document "
                "before relying on its text or current status."
            )
        return report
    except (AccessError, ValueError, KeyError, TypeError) as exc:
        report["warnings"].append("ICC site search: " + str(exc))
        report["status"] = "partial"

    try:
        rows, info = crawl_cases(
            http, query, limit, offset, max_pages=max_pages, depth=depth
        )
        report["pagination"]["cases-crawl"] = info
        report["results"].extend(rows)
        report["warnings"].extend(info["errors"])
        report["warnings"].append(
            "Bounded /cases crawl: no hit does not establish absence from the ICC site."
        )
    except (AccessError, ValueError, KeyError, TypeError) as exc:
        report["warnings"].append("ICC /cases crawl: " + str(exc))

    try:
        rows, total = legal_tools_fallback(http, query, limit, offset)
        report["pagination"]["legal-tools-icc"] = {
            "total": total,
            "offset": offset,
            "limit": limit,
            "next_offset": (
                offset + len(rows)
                if rows and (not isinstance(total, int) or offset + len(rows) < total)
                else None
            ),
        }
        report["results"].extend(rows)
    except (AccessError, ValueError, KeyError, TypeError) as exc:
        report["warnings"].append("Legal Tools ICC fallback: " + str(exc))

    report["results"] = dedupe(report["results"])
    if report["results"]:
        report["warnings"].append(
            "Fallback records cannot confirm current case status, completeness, or updates "
            "on the live ICC site."
        )
    else:
        report["status"] = "unavailable-or-incomplete"
    return report


def fetch(url, cache, ttl=86400, offline=False, pdf_out=None, text_out=None):
    http = HTTP(cache, ttl=ttl, offline=offline)
    body, meta = http.get(url)
    if body.startswith(b"%PDF"):
        pages = pdf_pages(body)
        text = "\n\n".join(
            f"@@PAGE {page['page']}@@\n{page['text']}" for page in pages
        )
        if pdf_out:
            target = Path(pdf_out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        if text_out:
            target = Path(text_out)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return {
            "url": meta["request_url"],
            "sha256": meta["sha256"],
            "content_type": meta["content_type"],
            "pages": pages,
            "page_count": len(pages),
            "text_characters": len(text),
            "needs_ocr": not any(page["text"].strip() for page in pages),
            "pdf_out": str(Path(pdf_out).resolve()) if pdf_out else None,
            "text_out": str(Path(text_out).resolve()) if text_out else None,
            "evidence": http.evidence,
        }
    soup = BeautifulSoup(body, "html.parser")
    title = clean(soup.title.text if soup.title else "")
    node = content(soup)
    text = node.get_text("\n", strip=True)
    pdf_links = []
    for link in soup.select("a[href]"):
        target = urljoin(meta["request_url"], link["href"])
        if ".pdf" in urlparse(target).path.casefold():
            pdf_links.append(
                {
                    "title": clean(link.get_text(" ", strip=True)),
                    "url": target,
                }
            )
    if text_out:
        target = Path(text_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return {
        "url": meta["request_url"],
        "title": title,
        "sha256": meta["sha256"],
        "content_type": meta["content_type"],
        "text": text,
        "text_characters": len(text),
        "pdf_links": pdf_links,
        "text_out": str(Path(text_out).resolve()) if text_out else None,
        "evidence": http.evidence,
    }


def doctor(cache, ttl=86400, offline=False):
    http = HTTP(cache, ttl=ttl, offline=offline)
    output = {
        "skill": "icc-searcher",
        "dependencies": {"requests": True, "beautifulsoup4": True},
        "native_search": {},
        "legal_tools_fallback": {},
        "evidence": http.evidence,
    }
    try:
        rows, info = icc_search(http, "Ongwen", 1, 0)
        output["native_search"] = {
            "status": "ok",
            "total": info["total"],
            "top_result": rows[0]["title"] if rows else None,
        }
    except (AccessError, ValueError, KeyError, TypeError) as exc:
        output["native_search"] = {"status": "blocked", "error": str(exc)}
    try:
        rows, total = legal_tools_fallback(http, "Ongwen", 1, 0)
        output["legal_tools_fallback"] = {
            "status": "ok",
            "total": total,
            "top_result": rows[0]["title"] if rows else None,
        }
    except (AccessError, ValueError, KeyError, TypeError) as exc:
        output["legal_tools_fallback"] = {"status": "blocked", "error": str(exc)}
    native_ok = output["native_search"].get("status") == "ok"
    fallback_ok = output["legal_tools_fallback"].get("status") == "ok"
    output["status"] = "ok" if native_ok else ("degraded" if fallback_ok else "unavailable")
    return output


def write_output(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    search_parser = commands.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--offset", type=int, default=0)
    search_parser.add_argument("--max-pages", type=int, default=12)
    search_parser.add_argument("--depth", type=int, default=1)

    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--pdf-out")
    fetch_parser.add_argument("--text-out")

    doctor_parser = commands.add_parser("doctor")

    for command in (search_parser, fetch_parser, doctor_parser):
        command.add_argument("--cache", default=str(Path.cwd() / ".icc-cache"))
        command.add_argument("--cache-ttl", type=int, default=86400)
        command.add_argument("--offline", action="store_true")
        command.add_argument("--out")

    args = parser.parse_args()
    if args.command == "search":
        if not args.query.strip() or not terms(args.query):
            parser.error("Query must contain searchable text")
        if not 1 <= args.limit <= 50:
            parser.error("--limit must be between 1 and 50")
        if args.offset < 0:
            parser.error("--offset must be >= 0")
        if not 1 <= args.max_pages <= 100:
            parser.error("--max-pages must be between 1 and 100")
        if not 0 <= args.depth <= 3:
            parser.error("--depth must be between 0 and 3")
        http = HTTP(args.cache, args.cache_ttl, args.offline)
        output = search(
            http,
            args.query,
            args.limit,
            args.offset,
            args.max_pages,
            args.depth,
        )
    elif args.command == "fetch":
        try:
            output = fetch(
                args.url,
                args.cache,
                args.cache_ttl,
                args.offline,
                args.pdf_out,
                args.text_out,
            )
        except (AccessError, ValueError, ImportError) as exc:
            output = {"status": "unavailable", "error": str(exc)}
    else:
        output = doctor(args.cache, args.cache_ttl, args.offline)

    if args.out:
        path = write_output(args.out, output)
        summary = {"output": path}
        if args.command == "search":
            summary.update(
                {
                    "status": output["status"],
                    "hits": len(output["results"]),
                    "pagination": output["pagination"],
                }
            )
        elif args.command == "doctor":
            summary["status"] = output["status"]
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()

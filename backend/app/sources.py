"""Discovery sources other than YouTube: web articles, community threads (Reddit), photos/clippings.

Rules: fetch only pages a site serves to an ordinary request (no paywall or bot-block workarounds); Reddit is
never scraped — its API needs a registered app — so threads come in by paste or screenshot. Usernames are
stripped from pasted threads. All text is untrusted and goes through the same injection scan as transcripts."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from .youtube import Seg

UA = {"User-Agent": "Mozilla/5.0 (UmmaCare personal health notebook; reads one page on request)"}


class SourceUnavailable(Exception):
    pass


def site_of(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def is_reddit(url: str) -> bool:
    return site_of(url).endswith("reddit.com") or site_of(url) == "redd.it"


class _Article(HTMLParser):
    BLOCK = {"p", "li", "h2", "h3"}
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "button"}

    def __init__(self):
        super().__init__()
        self.title, self.parts, self._buf, self._tag, self._skip, self._in_title, self._in_article = "", [], "", None, 0, False, 0
        self.article_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title" and not self.title:
            self._in_title = True
        if tag in ("article", "main"):
            self._in_article += 1
        if tag in self.BLOCK:
            self._tag, self._buf = tag, ""

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        if tag in ("article", "main"):
            self._in_article = max(0, self._in_article - 1)
        if tag == self._tag:
            t = re.sub(r"\s+", " ", unescape(self._buf)).strip()
            if t and not self._skip and (len(t) > 40 or tag in ("h2", "h3")):
                (self.article_parts if self._in_article else self.parts).append(t)
            self._tag = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._tag:
            self._buf += data


def fetch_article(url: str) -> tuple[str, str, list[Seg]]:
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    except httpx.HTTPError as e:
        raise SourceUnavailable(f"Couldn't reach the page ({type(e).__name__}).")
    if r.status_code in (401, 402, 403, 429):
        raise SourceUnavailable(f"The site didn't allow automatic reading (HTTP {r.status_code}).")
    if r.status_code >= 400:
        raise SourceUnavailable(f"The page returned an error (HTTP {r.status_code}).")
    if "html" not in r.headers.get("content-type", ""):
        raise SourceUnavailable("That link isn't a web page UmmaCare can read.")
    p = _Article()
    p.feed(r.text[:3_000_000])
    paras = p.article_parts if sum(map(len, p.article_parts)) > 600 else p.parts
    text_len = sum(map(len, paras))
    if text_len < 600:
        raise SourceUnavailable("Couldn't find the article text (it may be behind a paywall or need JavaScript).")
    title = re.sub(r"\s+", " ", unescape(p.title)).strip()[:200] or site_of(url)
    return title, site_of(str(r.url)), [Seg(-1, 0, t) for t in paras[:400]]


_CHROME = re.compile(r"^(reply|share|report|save|follow|award|upvote|downvote|vote|more replies|continue this thread|"
                     r"level \d+|sort by:.*|best|top|new|controversial|old|q&a|edited.*|\d+[kKmM]?|\d+ (points?|comments?|replies)|"
                     r"•.*ago|\d+\s*(y|mo|w|d|h|m|yr|yrs|min)s?( ago)?|op|mod|posted by.*|join|promoted|single comment thread)$", re.I)


def clean_thread(text: str) -> list[Seg]:
    """Turn a pasted Reddit thread into paragraphs: drop page chrome and vote counts, remove usernames."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"\bu/[A-Za-z0-9_-]+", "[a user]", line.strip())
        if not line or _CHROME.match(line) or re.fullmatch(r"[A-Za-z0-9_-]{3,24}", line):   # bare username lines
            continue
        if out and len(out[-1]) < 300 and not re.search(r"[.!?:]$", out[-1]):
            out[-1] += " " + line
        else:
            out.append(line)
    return [Seg(-1, 0, t) for t in out if len(t) > 15][:500]


def split_text(text: str) -> list[Seg]:
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n|\n", text)]
    return [Seg(-1, 0, p) for p in paras if len(p) > 3][:500]


REDDIT_COMMUNITIES = ["Hashimotos", "thyroid", "Hypothyroidism", "Sjogrens", "Autoimmune", "Biohackers"]

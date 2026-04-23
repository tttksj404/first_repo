#!/usr/bin/env python3
"""
Collect public Threads posts related to crypto/coin trading and save
strategy-usable datasets for downstream trading-program research.

Usage example:
  .\.venv_threads\Scripts\python .\scripts\threads_coin_intel_collector.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import urllib.parse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import Page, async_playwright

THREADS_BASE = "https://www.threads.com"
DEFAULT_OUTPUT_ROOT = Path("quant_runtime/artifacts/threads_coin_intel")

# Includes both English and Korean queries.
DEFAULT_QUERIES = [
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "altcoin",
    "solana",
    "#bitcoin",
    "#btc",
    "#crypto",
    "#bitcointrading",
    "#ethereum",
    "binance futures",
    "bybit",
    "funding rate",
    "open interest btc",
    "onchain",
    "crypto bot",
    "algorithmic crypto trading",
    "crypto trading",
    "trading strategy",
    "futures trading",
    "automated trading",
    "tradingview btc",
    "\ube44\ud2b8\ucf54\uc778",
    "\uc774\ub354\ub9ac\uc6c0",
    "\uc54c\ud2b8\ucf54\uc778",
    "\ube44\ud2b8\ucf54\uc778 \uc120\ubb3c",
    "\ucf54\uc778 \uc790\ub3d9\ub9e4\ub9e4",
    "\uc628\uccb4\uc778",
    "\uc554\ud638\ud654\ud3d0",
    "\ucf54\uc778",
    "\uac00\uc0c1\uc790\uc0b0",
    "\ud2b8\ub808\uc774\ub529",
]

STRATEGY_PATTERNS: dict[str, list[str]] = {
    "accumulation_dca": [
        r"\bdca\b",
        r"\bstack(?:ing)?\b",
        r"\bbuy(?:ing)?\s+the\s+dip\b",
        r"\bcost\s+average\b",
        r"\ubd84\ud560\ub9e4\uc218",
    ],
    "trend_breakout": [
        r"\btrend\b",
        r"\bbreakout\b",
        r"\bmomentum\b",
        r"\btrendline\b",
        r"\ub3cc\ud30c",
        r"\ucd94\uc138",
    ],
    "risk_management": [
        r"\brisk\b",
        r"\bstop(?:\s|-)?loss\b",
        r"\bsl\b",
        r"\btake(?:\s|-)?profit\b",
        r"\btp\b",
        r"\bposition\s+siz",
        r"\bdrawdown\b",
        r"\uc190\uc808",
        r"\uc775\uc808",
        r"\ub9ac\uc2a4\ud06c",
        r"\ube44\uc911",
    ],
    "derivatives": [
        r"\bfutures?\b",
        r"\bperp(?:etual)?\b",
        r"\bleverage\b",
        r"\blong\b",
        r"\bshort\b",
        r"\bfunding\s+rate\b",
        r"\bopen\s+interest\b",
        r"\uc120\ubb3c",
        r"\ub808\ubc84\ub9ac\uc9c0",
    ],
    "execution_discipline": [
        r"\bentry\b",
        r"\bexit\b",
        r"\bbacktest\b",
        r"\bjournal\b",
        r"\bsetup\b",
        r"\brules?\b",
        r"\uc9c4\uc785",
        r"\uccad\uc0b0",
        r"\ubc31\ud14c\uc2a4\ud2b8",
        r"\uaddc\uce59",
    ],
    "macro_signal": [
        r"\betf\b",
        r"\bfed\b",
        r"\bcpi\b",
        r"\bon-?chain\b",
        r"\bwhale\b",
        r"\uac70\uc2dc",
        r"\uc628\uccb4\uc778",
    ],
}

ACTION_PATTERNS = [
    r"\bbuy\b",
    r"\bsell\b",
    r"\bset\b",
    r"\btake\b",
    r"\bavoid\b",
    r"\bonly\b",
    r"\bif\b",
    r"\bwhen\b",
    r"\bhold\b",
    r"\ub9e4\uc218",
    r"\ub9e4\ub3c4",
    r"\uc9c4\uc785",
    r"\uccad\uc0b0",
    r"\uc124\uc815",
]

SPAM_PATTERNS = [
    r"i will send",
    r"random person",
    r"giveaway",
    r"dm me",
    r"follow me",
    r"airdrop",
]

CRYPTO_PATTERNS = [
    r"\bcrypto\b",
    r"\bbitcoin\b",
    r"\bbtc\b",
    r"\beth(?:ereum)?\b",
    r"\baltcoin\b",
    r"\bblockchain\b",
    r"\btoken\b",
    r"\bdefi\b",
    r"\bsolana\b",
    r"\bxrp\b",
    r"\ud06c\ub9bd\ud1a0",
    r"\ube44\ud2b8\ucf54\uc778",
    r"\uc554\ud638\ud654\ud3d0",
    r"\ucf54\uc778",
    r"\uac00\uc0c1\uc790\uc0b0",
]

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(
    r"(?<![@#/])\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?:/[^\s<>()\[\]{}\"']*)?",
    re.IGNORECASE,
)
POST_URL_RE = re.compile(r"^https://www\.threads\.com/@([^/]+)/post/([^/?#]+)")
HASHTAG_RE = re.compile(r"(?<!\w)#([\w\.\-]+)", re.UNICODE)
MENTION_RE = re.compile(r"@([a-zA-Z0-9._]+)")
NUMERIC_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?[KMB]?$", re.IGNORECASE)

SKIP_LINK_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mov",
    ".avi",
    ".pdf",
    ".zip",
    ".rar",
    ".exe",
    ".dmg",
)
SKIP_LINK_SCHEMES = ("mailto:", "javascript:", "tel:")
SKIP_PATH_KEYWORDS = (
    "/login",
    "/signin",
    "/signup",
    "/register",
    "/privacy",
    "/terms",
    "/cookie",
    "/support",
    "/help",
    "/contact",
    "/about",
    "/careers",
)
ARTICLE_HINT_KEYWORDS = (
    "article",
    "blog",
    "post",
    "thread",
    "analysis",
    "research",
    "market",
    "insight",
    "strategy",
    "academy",
    "news",
    "learn",
    "guide",
    "report",
)

COMMON_TLDS = {
    "com",
    "net",
    "org",
    "io",
    "co",
    "ai",
    "app",
    "dev",
    "info",
    "me",
    "xyz",
    "finance",
    "academy",
    "blog",
    "news",
    "kr",
    "us",
    "uk",
    "jp",
    "cn",
    "de",
    "fr",
    "in",
    "ca",
    "au",
}

EXTRACT_POST_CARDS_JS = r"""
(() => {
  const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
  const seen = new Set();
  const out = [];

  function chooseCard(anchor) {
    let node = anchor;
    let best = anchor;
    let bestLen = ((best.innerText || "").trim()).length;
    for (let i = 0; i < 12 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      const text = (node.innerText || "").trim();
      const len = text.length;
      if (!len || len > 2000) continue;
      if (len >= bestLen) {
        best = node;
        bestLen = len;
      }
    }
    return best;
  }

  for (const a of anchors) {
    let href = a.getAttribute("href");
    if (!href || href.endsWith("/media")) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    const card = chooseCard(a);
    const tm = card.querySelector("time");
    out.push({
      href,
      raw_text: (card.innerText || "").trim(),
      time_label: tm ? (tm.innerText || "").trim() : null,
      datetime_iso: tm ? tm.getAttribute("datetime") : null
    });
  }
  return out;
})()
"""


@dataclass
class SearchHit:
    url: str
    username: str
    post_id: str
    source: str
    seed: str
    raw_text: str
    card_text: str
    time_label: str | None
    datetime_iso: str | None
    scraped_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_post_url(url: str) -> tuple[str, str] | None:
    m = POST_URL_RE.match(url)
    if not m:
        return None
    return m.group(1), m.group(2)


def clean_card_text(raw_text: str, username: str, time_label: str | None) -> str:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if lines and lines[0].lower() == username.lower():
        lines.pop(0)
    if lines and time_label and lines[0] == time_label:
        lines.pop(0)
    while lines and NUMERIC_RE.match(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def strip_url_punctuation(url: str) -> str:
    return url.strip().strip(".,;:!?)]}\"'")


def domain_key(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(raw_url: str, base_url: str | None = None) -> str | None:
    if not raw_url:
        return None
    raw_url = strip_url_punctuation(raw_url)
    lower = raw_url.lower()
    if lower.startswith(SKIP_LINK_SCHEMES):
        return None
    if base_url:
        raw_url = urljoin(base_url, raw_url)
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None
    path = parsed.path or ""
    if path == "/":
        path = ""
    elif path:
        path = path.rstrip("/")
    cleaned = parsed._replace(netloc=parsed.netloc.lower(), path=path, fragment="")
    return urlunparse(cleaned)


def is_crawlable_url(url: str) -> bool:
    lower = url.lower()
    if any(lower.endswith(ext) for ext in SKIP_LINK_EXTENSIONS):
        return False
    return True


def is_same_domain(url_a: str, url_b: str) -> bool:
    return domain_key(url_a) == domain_key(url_b)


def extract_candidate_urls_from_text(text: str) -> list[str]:
    if not text:
        return []
    urls: list[str] = []
    for raw in URL_RE.findall(text):
        n = normalize_url(raw)
        if n and is_crawlable_url(n):
            urls.append(n)
    for raw in BARE_DOMAIN_RE.findall(text):
        if raw.lower().startswith(("http://", "https://")):
            continue
        host = raw.split("/")[0].strip().lower().rstrip(".")
        if "." not in host:
            continue
        tld = host.rsplit(".", 1)[-1]
        if tld not in COMMON_TLDS:
            continue
        n = normalize_url(f"https://{raw}")
        if n and is_crawlable_url(n):
            urls.append(n)
    return stable_unique(urls)


def stable_unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_external_links_from_soup(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        n = normalize_url(href, base_url=base_url)
        if not n or not is_crawlable_url(n):
            continue
        host = domain_key(n)
        if host in {"threads.com", "l.threads.com", "instagram.com", "www.instagram.com"}:
            continue
        links.append(n)
    return stable_unique(links)


def extract_main_text_from_soup(soup: BeautifulSoup) -> str:
    # Remove obvious noise first.
    for tag in soup(["script", "style", "noscript", "svg", "form", "footer", "nav", "aside"]):
        tag.decompose()

    candidate_texts: list[str] = []
    for selector in ("article", "main"):
        for node in soup.select(selector):
            txt = node.get_text("\n", strip=True)
            if txt:
                candidate_texts.append(txt)
    body = soup.body
    if body:
        candidate_texts.append(body.get_text("\n", strip=True))
    else:
        candidate_texts.append(soup.get_text("\n", strip=True))

    raw = max(candidate_texts, key=len, default="")
    lines: list[str] = []
    for line in raw.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if len(compact) < 25:
            continue
        lines.append(compact)
    text = "\n".join(lines)
    return text[:25000]


def should_skip_path(path: str) -> bool:
    lower_path = path.lower()
    return any(keyword in lower_path for keyword in SKIP_PATH_KEYWORDS)


def score_child_link(url: str, anchor_text: str) -> int:
    parsed = urlparse(url)
    path = parsed.path.lower()
    score = 0
    if any(keyword in path for keyword in ARTICLE_HINT_KEYWORDS):
        score += 3
    depth = len([p for p in path.split("/") if p])
    if depth >= 2:
        score += 1
    anchor_lower = anchor_text.lower()
    if any(keyword in anchor_lower for keyword in ARTICLE_HINT_KEYWORDS):
        score += 2
    if re.search(r"\d{4}", path):
        score += 1
    return score


def extract_child_links(soup: BeautifulSoup, base_url: str, max_links: int) -> list[str]:
    scored: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        n = normalize_url(href, base_url=base_url)
        if not n or not is_crawlable_url(n):
            continue
        if not is_same_domain(base_url, n):
            continue
        if n == normalize_url(base_url):
            continue
        if should_skip_path(urlparse(n).path):
            continue
        anchor_text = a.get_text(" ", strip=True)
        scored.append((score_child_link(n, anchor_text), n))

    scored.sort(key=lambda x: (-x[0], x[1]))
    uniq = stable_unique(url for _, url in scored)
    return uniq[:max_links]


async def collect_cards(
    page: Page,
    url: str,
    source: str,
    seed: str,
    scrolls: int,
    wait_ms: int,
    max_cards: int | None = None,
) -> list[SearchHit]:
    await page.goto(url, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_timeout(wait_ms)
    for _ in range(scrolls):
        await page.mouse.wheel(0, 5000)
        await page.wait_for_timeout(wait_ms)
    cards: list[dict[str, Any]] = await page.evaluate(EXTRACT_POST_CARDS_JS)
    hits: list[SearchHit] = []
    for card in cards:
        href = card.get("href", "")
        if not href:
            continue
        absolute_url = href if href.startswith("http") else f"{THREADS_BASE}{href}"
        parsed = parse_post_url(absolute_url)
        if not parsed:
            continue
        username, post_id = parsed
        raw_text = (card.get("raw_text") or "").strip()
        time_label = card.get("time_label")
        datetime_iso = card.get("datetime_iso")
        card_text = clean_card_text(raw_text, username=username, time_label=time_label)
        hits.append(
            SearchHit(
                url=absolute_url,
                username=username,
                post_id=post_id,
                source=source,
                seed=seed,
                raw_text=raw_text,
                card_text=card_text,
                time_label=time_label,
                datetime_iso=datetime_iso,
                scraped_at=now_iso(),
            )
        )
        if max_cards and len(hits) >= max_cards:
            break
    return hits


async def collect_all_hits(
    queries: list[str],
    search_scrolls: int,
    profile_scrolls: int,
    wait_ms: int,
    max_posts_per_query: int,
    max_profile_users: int,
    max_posts_per_profile: int,
    locale: str,
) -> list[SearchHit]:
    all_hits: list[SearchHit] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale=locale)
        page = await context.new_page()

        for query in queries:
            encoded = urllib.parse.quote(query)
            url = f"{THREADS_BASE}/search?q={encoded}"
            hits = await collect_cards(
                page=page,
                url=url,
                source="search",
                seed=query,
                scrolls=search_scrolls,
                wait_ms=wait_ms,
                max_cards=max_posts_per_query,
            )
            all_hits.extend(hits)

        usernames = stable_unique(hit.username for hit in all_hits)
        for username in usernames[:max_profile_users]:
            profile_url = f"{THREADS_BASE}/@{username}"
            hits = await collect_cards(
                page=page,
                url=profile_url,
                source="profile",
                seed=username,
                scrolls=profile_scrolls,
                wait_ms=wait_ms,
                max_cards=max_posts_per_profile,
            )
            all_hits.extend(hits)

        await context.close()
        await browser.close()

    return all_hits


async def scan_post_external_links(
    post_urls: list[str],
    locale: str,
    wait_ms: int,
    max_links_per_post: int,
) -> dict[str, list[str]]:
    link_map: dict[str, list[str]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale=locale)
        page = await context.new_page()

        for post_url in post_urls:
            links: list[str] = []
            try:
                await page.goto(post_url, wait_until="domcontentloaded", timeout=120000)
                await page.wait_for_timeout(wait_ms)
                hrefs: list[str] = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
                )
                for href in hrefs:
                    n = normalize_url(href, base_url=post_url)
                    if not n or not is_crawlable_url(n):
                        continue
                    host = domain_key(n)
                    if host in {
                        "threads.com",
                        "l.threads.com",
                        "instagram.com",
                        "about.meta.com",
                        "help.instagram.com",
                        "meta.com",
                    }:
                        continue
                    links.append(n)
            except Exception:
                links = []
            link_map[post_url] = stable_unique(links)[:max_links_per_post]

        await context.close()
        await browser.close()
    return link_map


def fetch_post_meta(session: requests.Session, url: str, timeout_s: int) -> dict[str, Any]:
    try:
        resp = session.get(
            url,
            timeout=timeout_s,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; threads-coin-intel/1.0)",
                "Accept-Language": "en-US,en;q=0.8,ko;q=0.7",
            },
        )
    except requests.RequestException as exc:
        return {"error": f"request_error: {exc}"}

    if resp.status_code >= 400:
        return {"error": f"http_{resp.status_code}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    def get_meta(*pairs: tuple[str, str]) -> str | None:
        for attr, value in pairs:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return None

    description = get_meta(
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
    )
    title = get_meta(("property", "og:title"), ("name", "twitter:title"))
    canonical_url = get_meta(("property", "og:url")) or url
    external_links = extract_external_links_from_soup(soup, base_url=canonical_url)
    return {
        "title": title,
        "description": description,
        "canonical_url": canonical_url,
        "external_links": external_links,
    }


def detect_strategy_signals(text: str) -> dict[str, Any]:
    tags: list[str] = []
    for tag, patterns in STRATEGY_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            tags.append(tag)
    action_hits = sum(
        1 for pattern in ACTION_PATTERNS if re.search(pattern, text, re.IGNORECASE)
    )
    spam_flag = any(re.search(pattern, text, re.IGNORECASE) for pattern in SPAM_PATTERNS)
    score = (len(tags) * 2) + min(action_hits, 3)
    usable = bool(tags) and action_hits > 0 and not spam_flag and len(text) >= 40
    return {
        "strategy_tags": sorted(tags),
        "action_hits": action_hits,
        "strategy_score": score,
        "is_spam_like": spam_flag,
        "is_usable_for_program": usable,
    }


def detect_crypto_context(text: str) -> dict[str, Any]:
    hits = sum(1 for pattern in CRYPTO_PATTERNS if re.search(pattern, text, re.IGNORECASE))
    return {
        "crypto_context_hits": hits,
        "is_crypto_related": hits > 0,
    }


def fetch_external_page(
    session: requests.Session,
    url: str,
    timeout_s: int,
    max_children_per_page: int,
) -> dict[str, Any]:
    try:
        resp = session.get(
            url,
            timeout=timeout_s,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; threads-coin-intel/1.0)",
                "Accept-Language": "en-US,en;q=0.8,ko;q=0.7",
            },
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"ok": False, "requested_url": url, "error": f"request_error: {exc}"}

    final_url = normalize_url(str(resp.url)) or url
    content_type = (resp.headers.get("content-type") or "").lower()
    if resp.status_code >= 400:
        return {
            "ok": False,
            "requested_url": url,
            "final_url": final_url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "error": f"http_{resp.status_code}",
        }
    if "html" not in content_type:
        return {
            "ok": False,
            "requested_url": url,
            "final_url": final_url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "error": "non_html_content",
        }

    soup = BeautifulSoup(resp.text, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None
    description = None
    for attr, value in (
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
    ):
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            description = str(tag["content"]).strip()
            break

    text = extract_main_text_from_soup(soup)
    child_links = extract_child_links(
        soup=soup,
        base_url=final_url,
        max_links=max_children_per_page,
    )
    return {
        "ok": True,
        "requested_url": url,
        "final_url": final_url,
        "status_code": resp.status_code,
        "content_type": content_type,
        "title": title,
        "description": description,
        "text": text,
        "child_links": child_links,
    }


def crawl_external_documents(
    session: requests.Session,
    seed_rows: list[dict[str, Any]],
    timeout_s: int,
    max_depth: int,
    max_pages_per_root: int,
    max_total_pages: int,
    max_children_per_page: int,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    total_pages = 0

    for seed in seed_rows:
        if total_pages >= max_total_pages:
            break
        root_url = seed["seed_url"]
        root_norm = normalize_url(root_url)
        if not root_norm:
            continue

        queue: deque[tuple[str, int, str | None]] = deque()
        queue.append((root_norm, 0, None))
        seen: set[str] = set()
        pages_for_root = 0

        while queue:
            if total_pages >= max_total_pages or pages_for_root >= max_pages_per_root:
                break
            current_url, depth, parent_url = queue.popleft()
            current_norm = normalize_url(current_url)
            if not current_norm:
                continue
            if current_norm in seen:
                continue
            if not is_crawlable_url(current_norm):
                continue
            if depth > 0 and not is_same_domain(root_norm, current_norm):
                continue
            if should_skip_path(urlparse(current_norm).path):
                continue

            seen.add(current_norm)
            fetched = fetch_external_page(
                session=session,
                url=current_norm,
                timeout_s=timeout_s,
                max_children_per_page=max_children_per_page,
            )
            text = (fetched.get("text") or "").strip()
            analysis_text = "\n".join(
                part
                for part in [
                    fetched.get("title") or "",
                    fetched.get("description") or "",
                    text,
                ]
                if part
            ).strip()
            signals = (
                detect_strategy_signals(analysis_text)
                if analysis_text
                else detect_strategy_signals("")
            )
            crypto = (
                detect_crypto_context(analysis_text)
                if analysis_text
                else detect_crypto_context("")
            )
            signals["is_usable_for_program"] = (
                bool(signals["strategy_tags"])
                and not signals["is_spam_like"]
                and len(analysis_text) >= 120
                and crypto["is_crypto_related"]
            )

            record = {
                "seed_url": root_norm,
                "url": fetched.get("final_url") or current_norm,
                "requested_url": current_norm,
                "thread_post_url": seed["thread_post_url"],
                "thread_username": seed["thread_username"],
                "depth": depth,
                "parent_url": parent_url,
                "title": fetched.get("title"),
                "description": fetched.get("description"),
                "text": text,
                "status_code": fetched.get("status_code"),
                "content_type": fetched.get("content_type"),
                "ok": bool(fetched.get("ok")),
                "error": fetched.get("error"),
                "scraped_at": now_iso(),
            }
            record.update(signals)
            record.update(crypto)
            docs.append(record)
            total_pages += 1
            pages_for_root += 1

            if not fetched.get("ok"):
                continue
            if depth >= max_depth:
                continue

            for child in fetched.get("child_links") or []:
                child_norm = normalize_url(child)
                if not child_norm:
                    continue
                if child_norm in seen:
                    continue
                if not is_same_domain(root_norm, child_norm):
                    continue
                queue.append((child_norm, depth + 1, fetched.get("final_url") or current_norm))

    return docs


def to_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def to_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for row in rows for k in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect public Threads crypto posts and extract strategy-usable records."
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--queries-file", type=Path, default=None)
    parser.add_argument("--search-scrolls", type=int, default=2)
    parser.add_argument("--profile-scrolls", type=int, default=2)
    parser.add_argument("--wait-ms", type=int, default=2200)
    parser.add_argument("--max-posts-per-query", type=int, default=10)
    parser.add_argument("--max-profile-users", type=int, default=30)
    parser.add_argument("--max-posts-per-profile", type=int, default=15)
    parser.add_argument("--http-timeout-s", type=int, default=25)
    parser.add_argument("--locale", type=str, default="ko-KR")
    parser.add_argument(
        "--post-link-scan",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--post-link-scan-wait-ms", type=int, default=1200)
    parser.add_argument("--post-link-scan-max-posts", type=int, default=250)
    parser.add_argument(
        "--crawl-external-links",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--external-max-links-per-post", type=int, default=6)
    parser.add_argument("--external-max-depth", type=int, default=1)
    parser.add_argument("--external-max-pages-per-root", type=int, default=6)
    parser.add_argument("--external-max-total-pages", type=int, default=500)
    parser.add_argument("--external-max-children-per-page", type=int, default=15)
    return parser.parse_args()


def load_queries(path: Path | None) -> list[str]:
    if not path:
        return DEFAULT_QUERIES
    queries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        q = line.strip().lstrip("\ufeff")
        if not q or q.startswith("#"):
            continue
        queries.append(q)
    return queries or DEFAULT_QUERIES


def aggregate_hits(hits: list[SearchHit]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for hit in hits:
        row = merged.setdefault(
            hit.url,
            {
                "url": hit.url,
                "username": hit.username,
                "post_id": hit.post_id,
                "sources": [],
                "seeds": [],
                "card_text_candidates": [],
                "time_labels": [],
                "datetime_candidates": [],
                "first_scraped_at": hit.scraped_at,
            },
        )
        row["sources"].append(hit.source)
        row["seeds"].append(hit.seed)
        if hit.card_text:
            row["card_text_candidates"].append(hit.card_text)
        if hit.time_label:
            row["time_labels"].append(hit.time_label)
        if hit.datetime_iso:
            row["datetime_candidates"].append(hit.datetime_iso)

    for row in merged.values():
        row["sources"] = stable_unique(row["sources"])
        row["seeds"] = stable_unique(row["seeds"])
        row["time_labels"] = stable_unique(row["time_labels"])
        row["datetime_candidates"] = stable_unique(row["datetime_candidates"])
    return merged


def build_summary(
    threads_enriched: list[dict[str, Any]],
    external_enriched: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    external_enriched = external_enriched or []
    threads_usable = [row for row in threads_enriched if row["is_usable_for_program"]]
    external_usable = [row for row in external_enriched if row["is_usable_for_program"]]
    combined_usable = threads_usable + external_usable
    users = stable_unique(row["username"] for row in threads_enriched)
    external_domains = stable_unique(domain_key(row.get("url", "")) for row in external_enriched)
    external_domains = [d for d in external_domains if d]

    tag_counts: dict[str, int] = {}
    for row in combined_usable:
        for tag in row["strategy_tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    top_samples = [
        {
            "url": row["url"],
            "source_kind": row.get("source_kind", "threads_post"),
            "username": row.get("username") or row.get("thread_username"),
            "score": row["strategy_score"],
            "tags": row["strategy_tags"],
            "text_preview": row["text"][:240],
        }
        for row in sorted(combined_usable, key=lambda x: (x["strategy_score"], len(x["text"])), reverse=True)[:25]
    ]

    return {
        "generated_at": now_iso(),
        "threads_total_posts": len(threads_enriched),
        "threads_usable_posts": len(threads_usable),
        "external_total_pages": len(external_enriched),
        "external_usable_pages": len(external_usable),
        "combined_usable_count": len(combined_usable),
        "unique_threads_users": len(users),
        "unique_external_domains": len(external_domains),
        "tag_counts": dict(sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))),
        "top_usable_samples": top_samples,
    }


def summary_markdown(summary: dict[str, Any], run_dir: Path) -> str:
    lines = [
        "# Threads Coin Intel Summary",
        "",
        f"- Generated at (UTC): `{summary['generated_at']}`",
        f"- Threads posts collected: `{summary['threads_total_posts']}`",
        f"- Threads usable strategy posts: `{summary['threads_usable_posts']}`",
        f"- External pages crawled: `{summary['external_total_pages']}`",
        f"- External usable strategy pages: `{summary['external_usable_pages']}`",
        f"- Combined usable strategy records: `{summary['combined_usable_count']}`",
        f"- Unique Threads users: `{summary['unique_threads_users']}`",
        f"- Unique external domains: `{summary['unique_external_domains']}`",
        "",
        "## Strategy Tag Counts",
    ]
    if summary["tag_counts"]:
        for tag, count in summary["tag_counts"].items():
            lines.append(f"- `{tag}`: {count}")
    else:
        lines.append("- No strategy-tagged posts found.")

    lines.extend(
        [
            "",
            "## Output Files",
            f"- `{(run_dir / 'search_hits.jsonl').as_posix()}`",
            f"- `{(run_dir / 'posts_enriched.jsonl').as_posix()}`",
            f"- `{(run_dir / 'strategy_candidates.jsonl').as_posix()}`",
            f"- `{(run_dir / 'strategy_candidates.csv').as_posix()}`",
            f"- `{(run_dir / 'external_pages_enriched.jsonl').as_posix()}`",
            f"- `{(run_dir / 'external_strategy_candidates.jsonl').as_posix()}`",
            f"- `{(run_dir / 'external_strategy_candidates.csv').as_posix()}`",
            f"- `{(run_dir / 'combined_strategy_candidates.jsonl').as_posix()}`",
            f"- `{(run_dir / 'combined_strategy_candidates.csv').as_posix()}`",
            f"- `{(run_dir / 'summary.json').as_posix()}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()
    queries = load_queries(args.queries_file)
    if not queries:
        print("No queries available.")
        return 1

    run_dir = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    hits = asyncio.run(
        collect_all_hits(
            queries=queries,
            search_scrolls=args.search_scrolls,
            profile_scrolls=args.profile_scrolls,
            wait_ms=args.wait_ms,
            max_posts_per_query=args.max_posts_per_query,
            max_profile_users=args.max_profile_users,
            max_posts_per_profile=args.max_posts_per_profile,
            locale=args.locale,
        )
    )

    # Save raw hit records first.
    to_jsonl(run_dir / "search_hits.jsonl", (hit.__dict__ for hit in hits))

    merged = aggregate_hits(hits)
    post_external_link_map: dict[str, list[str]] = {}
    if args.post_link_scan and merged:
        scan_urls = list(merged.keys())[: args.post_link_scan_max_posts]
        post_external_link_map = asyncio.run(
            scan_post_external_links(
                post_urls=scan_urls,
                locale=args.locale,
                wait_ms=args.post_link_scan_wait_ms,
                max_links_per_post=max(args.external_max_links_per_post * 3, 12),
            )
        )

    enriched_rows: list[dict[str, Any]] = []
    external_seed_map: dict[str, dict[str, Any]] = {}
    with requests.Session() as session:
        for row in merged.values():
            meta = fetch_post_meta(session=session, url=row["url"], timeout_s=args.http_timeout_s)
            fallback_text = max(row["card_text_candidates"], key=len, default="")
            text = (meta.get("description") or fallback_text or "").strip()
            if not text:
                continue
            signals = detect_strategy_signals(text)
            crypto = detect_crypto_context(text)
            signals["is_usable_for_program"] = (
                signals["is_usable_for_program"] and crypto["is_crypto_related"]
            )
            hashtags = stable_unique(HASHTAG_RE.findall(text))
            mentions = stable_unique(MENTION_RE.findall(text))
            link_text_blob = "\n".join(
                part
                for part in [
                    text,
                    fallback_text,
                    "\n".join(row.get("card_text_candidates") or []),
                ]
                if part
            )
            text_links = extract_candidate_urls_from_text(link_text_blob)
            meta_links = [link for link in (meta.get("external_links") or []) if isinstance(link, str)]
            scanned_links = post_external_link_map.get(row["url"], [])
            merged_links = stable_unique(text_links + meta_links + scanned_links)
            external_links: list[str] = []
            should_expand_external = True
            if should_expand_external:
                for link in merged_links:
                    n = normalize_url(link)
                    if not n:
                        continue
                    if not is_crawlable_url(n):
                        continue
                    host = domain_key(n)
                    if host in {"threads.com", "l.threads.com", "instagram.com"}:
                        continue
                    external_links.append(n)
                external_links = stable_unique(external_links)[: args.external_max_links_per_post]

            enriched = {
                "url": row["url"],
                "username": row["username"],
                "post_id": row["post_id"],
                "title": meta.get("title"),
                "text": text,
                "sources": row["sources"],
                "seeds": row["seeds"],
                "datetime_candidates": row["datetime_candidates"],
                "time_labels": row["time_labels"],
                "hashtags": hashtags,
                "mentions": mentions,
                "external_links": external_links,
                "external_link_count": len(external_links),
                "first_scraped_at": row["first_scraped_at"],
                "meta_error": meta.get("error"),
                "source_kind": "threads_post",
            }
            enriched.update(signals)
            enriched.update(crypto)
            enriched_rows.append(enriched)

            for link in external_links:
                if link not in external_seed_map:
                    external_seed_map[link] = {
                        "seed_url": link,
                        "thread_post_url": row["url"],
                        "thread_username": row["username"],
                    }

    enriched_rows.sort(key=lambda x: (x["strategy_score"], len(x["text"])), reverse=True)
    usable_rows = [row for row in enriched_rows if row["is_usable_for_program"]]
    external_seed_rows = list(external_seed_map.values())

    external_rows: list[dict[str, Any]] = []
    if args.crawl_external_links and external_seed_rows:
        with requests.Session() as session:
            external_rows = crawl_external_documents(
                session=session,
                seed_rows=external_seed_rows,
                timeout_s=args.http_timeout_s,
                max_depth=args.external_max_depth,
                max_pages_per_root=args.external_max_pages_per_root,
                max_total_pages=args.external_max_total_pages,
                max_children_per_page=args.external_max_children_per_page,
            )
        for row in external_rows:
            row["source_kind"] = "external_link"

    external_rows.sort(key=lambda x: (x["strategy_score"], len(x.get("text", ""))), reverse=True)
    external_usable_rows = [row for row in external_rows if row["is_usable_for_program"]]

    combined_usable_rows = [*usable_rows, *external_usable_rows]
    combined_usable_rows.sort(
        key=lambda x: (x["strategy_score"], len(x.get("text", ""))),
        reverse=True,
    )

    to_jsonl(run_dir / "posts_enriched.jsonl", enriched_rows)
    to_jsonl(run_dir / "strategy_candidates.jsonl", usable_rows)
    to_csv(run_dir / "strategy_candidates.csv", usable_rows)
    to_jsonl(run_dir / "external_pages_enriched.jsonl", external_rows)
    to_jsonl(run_dir / "external_strategy_candidates.jsonl", external_usable_rows)
    to_csv(run_dir / "external_strategy_candidates.csv", external_usable_rows)
    to_jsonl(run_dir / "combined_strategy_candidates.jsonl", combined_usable_rows)
    to_csv(run_dir / "combined_strategy_candidates.csv", combined_usable_rows)

    summary = build_summary(enriched_rows, external_rows)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(summary_markdown(summary, run_dir), encoding="utf-8")
    (args.output_root / "latest_run.txt").write_text(str(run_dir.resolve()), encoding="utf-8")

    args_dump = {
        key: (str(value) if isinstance(value, Path) else value)
        for key, value in vars(args).items()
    }
    run_manifest = {
        "generated_at": now_iso(),
        "query_count": len(queries),
        "queries": queries,
        "args": args_dump,
        "raw_hits": len(hits),
        "unique_posts": len(merged),
        "post_link_scanned_posts": len(post_external_link_map),
        "enriched_posts": len(enriched_rows),
        "usable_posts": len(usable_rows),
        "external_seed_links": len(external_seed_rows),
        "external_pages_crawled": len(external_rows),
        "external_usable_pages": len(external_usable_rows),
        "combined_usable_records": len(combined_usable_rows),
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Run completed: {run_dir}")
    print(
        "Collected "
        f"{len(hits)} raw hits, {len(merged)} unique posts, "
        f"{len(usable_rows)} usable Threads posts, {len(external_rows)} external pages, "
        f"{len(combined_usable_rows)} combined usable strategy records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

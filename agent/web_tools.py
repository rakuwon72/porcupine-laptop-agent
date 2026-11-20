"""Finding websites that are NOT in the manifest: a plain web search.

Used when you ask for a site the agent has never seen. It searches the web (no API key
needed), returns the top results with their REAL addresses, and the agent then opens the
right one with learn_website - which also remembers it for next time.

Safety note: search results can include look-alike (phishing) sites, so the agent is told to
pick the OFFICIAL domain of the brand, and to say which domain it used.
"""

import base64
import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from langchain_core.tools import tool

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SEARCH_ENGINES = {"duckduckgo.com", "www.bing.com", "bing.com", "www.google.com", "google.com"}


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", text)).strip()


def parse_duckduckgo(page: str) -> list[tuple[str, str]]:
    """Pull (title, url) pairs out of DuckDuckGo's HTML results page (skipping ads)."""
    results = []
    for block in re.split(r'<div class="result[ "]', page)[1:]:
        if "result--ad" in block[:60]:
            continue
        match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not match:
            continue
        href = html.unescape(match.group(1))
        if "uddg=" in href:                         # DuckDuckGo wraps the real address in a redirect
            href = unquote(parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)["uddg"][0])
        results.append((_clean(match.group(2)), href))
    return results


def parse_bing(page: str) -> list[tuple[str, str]]:
    """Pull (title, url) pairs out of Bing's results (decoding its redirect links)."""
    results = []
    for match in re.finditer(r'<li class="b_algo".*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(match.group(1))
        encoded = parse_qs(urlparse(href).query).get("u", [""])[0]
        if encoded.startswith("a1"):                # Bing hides the address as base64 after "a1"
            try:
                href = base64.urlsafe_b64decode(encoded[2:] + "=" * (-len(encoded[2:]) % 4)).decode()
            except Exception:
                pass
        results.append((_clean(match.group(2)), href))
    return results


def web_search(query: str, limit: int = 6) -> list[tuple[str, str]]:
    """Search the web; returns up to `limit` (title, url) pairs. Tries DuckDuckGo, then Bing."""
    headers = {"User-Agent": USER_AGENT}
    attempts = (
        ("https://html.duckduckgo.com/html/", parse_duckduckgo),
        ("https://www.bing.com/search", parse_bing),
    )
    for url, parser in attempts:
        try:
            response = httpx.get(url, params={"q": query}, headers=headers, timeout=15, follow_redirects=True)
            found = [(t, u) for t, u in parser(response.text)
                     if u.startswith("http") and urlparse(u).netloc.lower() not in SEARCH_ENGINES]
        except Exception:
            continue
        if found:
            return found[:limit]
    return []


@tool
def search_web(query: str) -> str:
    """Search the web to find a website's real address (use this for any site that is NOT in the manifest).

    query: what to search, e.g. "Notion sign up" or "IIT Delhi official website".
    Returns the top results as "title - address". Pick the OFFICIAL site (the domain that matches
    the brand; avoid look-alike or unrelated domains), then open it with learn_website.
    """
    results = web_search(query)
    if not results:
        return ("The web search returned nothing (maybe no internet). Ask the user for the website address, "
                "or open the search page yourself with open_website on a search site.")
    lines = [f"{n}. {title[:70]} - {url}" for n, (title, url) in enumerate(results, start=1)]
    return "Top results:\n" + "\n".join(lines)

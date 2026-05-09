import json
import logging
import re
import time
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.rbi.org.in/commonman/english/scripts/FAQs.aspx"
SECTION_TITLE = "Foreign Exchange Management"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_FILE = "RBI_FAQ.json"
TIMEOUT_S = 30
SLEEP_S = 0.5

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("rbi_fem")

def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def qkey(s: str) -> str:
    s = norm_ws(s).casefold()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s*([?!.:,;])\s*", r"\1 ", s).strip()
    return s

def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()

def is_aspx(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".aspx")

def robots_parser(session: requests.Session, seed_url: str) -> RobotFileParser:
    robots_url = urljoin(seed_url, "/robots.txt")
    try:
        r = session.get(robots_url, timeout=TIMEOUT_S)
    except requests.RequestException:
        # network error, treat as empty robots
        rp = RobotFileParser()
        rp.parse([])
        return rp

    if r.status_code in (404, 403, 418):  # treat 418 same as missing
        rp = RobotFileParser()
        rp.parse([])
        return rp

    if r.status_code != 200:
        # any other unexpected code, still fallback
        rp = RobotFileParser()
        rp.parse([])
        return rp

    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp

def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, timeout=TIMEOUT_S)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def find_section_anchor(soup: BeautifulSoup, title: str):
    t = norm_ws(title).casefold()

    for node in soup.find_all(string=True):
        if norm_ws(str(node)).casefold() == t:
            return node.parent

    for node in soup.find_all(string=re.compile(re.escape(title), re.IGNORECASE)):
        return node.parent

    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if title.casefold() in norm_ws(h.get_text(" ", strip=True)).casefold():
            return h

    return None


def extract_section_links(soup: BeautifulSoup) -> list[str]:
    anchor = find_section_anchor(soup, SECTION_TITLE)
    if anchor is None:
        return []

    root = soup.body or soup
    started = False
    links: list[str] = []
    seen: set[str] = set()

    for el in root.descendants:
        if not getattr(el, "name", None):
            continue

        if el is anchor:
            started = True
            continue
        if not started:
            continue

        if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            txt = norm_ws(el.get_text(" ", strip=True))
            if txt and SECTION_TITLE.casefold() not in txt.casefold():
                break

        if el.name != "a":
            continue

        href = (el.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue

        full = urldefrag(urljoin(BASE_URL, href))[0]
        if not same_host(BASE_URL, full):
            continue
        if "/commonman/" not in full.casefold():
            continue
        if not is_aspx(full):
            continue
        if full == BASE_URL:
            continue

        if full not in seen:
            seen.add(full)
            links.append(full)

    return links


def is_question_block(elem, text: str) -> bool:
    bold_text = norm_ws(" ".join(b.get_text(" ", strip=True) for b in elem.find_all(["b", "strong"])))
    ratio = (len(bold_text) / max(len(text), 1)) if bold_text else 0.0
    low = text.casefold()

    if text.rstrip().endswith("?"):
        return True
    if ratio >= 0.65:
        return True
    if bold_text and len(text) <= 150 and not low.startswith(("note", "important", "warning")):
        return True
    return False


def table_to_lines(table) -> list[str]:
    rows = []
    for tr in table.find_all("tr"):
        cols = [norm_ws(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        cols = [c for c in cols if c]
        if cols:
            rows.append(" | ".join(cols))
    return rows


def parse_faq_page(session: requests.Session, url: str, seen_questions: set[str]) -> list[dict]:
    soup = get_soup(session, url)
    main = soup.find("div", id="wrapper") or soup.find("div", id="content") or soup.body or soup

    blocks = main.find_all(["h2", "h3", "h4", "h5", "p", "li", "table"])
    out: list[dict] = []

    q = None
    k = None
    ans: list[str] = []

    def flush():
        nonlocal q, k, ans
        if not q:
            return
        a = "\n".join([x for x in ans if x]).strip()
        if a and k not in seen_questions:
            out.append({"question": q, "answer": a, "source": url})
            seen_questions.add(k)
        q, k, ans = None, None, []

    for block in blocks:
        text = norm_ws(block.get_text(" ", strip=True))
        if not text and block.name != "table":
            continue

        q_like = block.name in {"h2", "h3", "h4", "h5"} or is_question_block(block, text)

        if q_like:
            flush()
            q = text
            k = qkey(text)
            continue

        if q is None:
            continue

        if block.name == "table":
            rows = table_to_lines(block)
            if rows:
                ans.append("\n".join(rows))
            continue

        if block.name == "li":
            ans.append(f"- {text}")
        else:
            ans.append(text)

    flush()

    if not out:
        log.warning("0 Qs found on page %s", url)

    return out


def run_scrape(output_file: str = OUTPUT_FILE) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})

    rp = robots_parser(session, BASE_URL)
    ua_token = "RBIFaqScraper"

    def allowed(u: str) -> bool:
        return rp.can_fetch("*", u) or rp.can_fetch(ua_token, u)

    if not allowed(BASE_URL):
        raise PermissionError(f"robots.txt disallows: {BASE_URL}")

    seed = get_soup(session, BASE_URL)
    links = extract_section_links(seed)
    if not links:
        raise RuntimeError("No FEM links found. Page structure may have changed.")

    blocked = [u for u in links if not allowed(u)]
    if blocked:
        raise PermissionError("robots.txt disallows scraping one or more section URLs.")

    all_rows: list[dict] = []
    seen: set[str] = set()

    for link in links:
        log.info("Scraping: %s", link)
        time.sleep(SLEEP_S)
        all_rows.extend(parse_faq_page(session, link, seen))

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)

    log.info("Saved %d QA items to %s", len(all_rows), output_file)
    return all_rows


run_scrape()

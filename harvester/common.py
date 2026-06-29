"""Shared DOM / table helpers used by both convert (markdown) and extract (model).
Single source of truth for table-cell nesting depth, so md and OpenAPI agree."""
import re
import bs4

NBSP = " "        # &nbsp; — nesting indent in raw HTML cells
FW   = "　"        # full-width space — nesting indent in normalized markdown
ARROWS = "▶▼►▸"        # expand/collapse glyphs to strip from tree-cell names


def soup(html: str) -> bs4.BeautifulSoup:
    return bs4.BeautifulSoup(html, "html.parser")


def parse_page(html: str, selectors: dict):
    """Return (body_element, title, time). body may be None if not found."""
    s = soup(html)
    body = s.select_one(selectors["body"]) if selectors.get("body") else s
    title_el = s.select_one(selectors["title"]) if selectors.get("title") else None
    time_el = s.select_one(selectors["time"]) if selectors.get("time") else None
    title = title_el.get_text().strip() if title_el else ""
    time = time_el.get_text().strip() if time_el else ""
    return body, title, time


def indent_depth(name_text: str, unit: int = 4):
    """Compute (depth, clean_name) from a tree cell's text.
    Depth = count of leading nbsp/full-width spaces // unit. Strips arrows and '+'."""
    s = name_text
    while s and s[0] in ARROWS:
        s = s[1:]
    i = 0
    while i < len(s) and s[i] in (NBSP, FW, " "):
        i += 1
    indent = s[:i]
    n = indent.count(NBSP) + indent.count(FW)
    depth = n // unit if unit else 0
    name = s[i:].lstrip("+").strip()
    return depth, name


def table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if cells:
            rows.append(cells)
    return rows


def cell_plain(td) -> str:
    """Plain single-line text of a cell (for OpenAPI descriptions): br -> space."""
    for br in td.find_all("br"):
        br.replace_with(" ")
    t = td.get_text()
    t = t.replace(NBSP, " ")
    return re.sub(r"\s+", " ", t).strip()


def section_tables(body, request_markers, response_markers):
    """Walk the body in document order; attach each <table> to the section whose
    marker heading most recently preceded it. Markers may be h1-6, <p> or <strong>."""
    req_markers = [m.strip() for m in request_markers]
    resp_markers = [m.strip() for m in response_markers]
    found = {"request": None, "response": None}
    cur = None
    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "table"]):
        if el.name == "table":
            if cur and found.get(cur) is None:
                found[cur] = el
            continue
        txt = el.get_text().strip()
        if not txt:
            continue
        if any(txt == m or txt.startswith(m) for m in req_markers):
            cur = "request"
        elif any(txt == m or txt.startswith(m) for m in resp_markers):
            cur = "response"
    return found["request"], found["response"]


def code_after(body, markers):
    """Return text of the first <pre> following a heading/paragraph matching markers."""
    markers = [m.strip() for m in markers]
    armed = False
    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "pre"]):
        if el.name == "pre":
            if armed:
                return el.get_text().replace("\r\n", "\n").rstrip("\n")
            continue
        txt = el.get_text().strip()
        if txt and any(txt == m or txt.startswith(m) for m in markers):
            armed = True
    return None

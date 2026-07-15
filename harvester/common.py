"""Shared DOM / table helpers used by both convert (markdown) and extract (model).
Single source of truth for table-cell nesting depth, so md and OpenAPI agree."""
import re
import shutil
import subprocess
import urllib.request

import bs4

NBSP = " "        # &nbsp; — nesting indent in raw HTML cells
FW   = "　"        # full-width space — nesting indent in normalized markdown
ARROWS = "▶▼►▸"        # expand/collapse glyphs to strip from tree-cell names
CODE_NOISE = ("复制代码", "Copy", "复制")


def fetch_url(url, headers=None, timeout=120, method="GET", data=None) -> str:
    """Fetch text with urllib first, then curl as a proxy/TLS fallback.
    data: optional request body bytes (POST/PUT)."""
    headers = dict(headers or {})
    try:
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as urllib_err:  # noqa: BLE001
        # Some local proxies break urllib's CONNECT/TLS while curl gets through.
        # Resolve curl via PATH so Windows does not silently prefer System32 curl.
        curl = shutil.which("curl")
        if not curl:
            raise
        cmd = [curl, "-sSL", "--max-time", str(max(timeout, 30)),
               "--retry", "3", "--retry-all-errors"]
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        if method and method.upper() != "GET":
            cmd.extend(["-X", method.upper()])
        if data is not None:
            cmd.extend(["--data-binary", "@-"])
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True, input=data,
                              timeout=max(timeout * 5, 60))
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(
                f"urllib failed ({urllib_err}); curl fallback failed "
                f"(rc={proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:200]}"
            ) from urllib_err
        return proc.stdout.decode("utf-8", "replace")


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


def indent_depth(name_text: str, unit: int = 4, nest_prefix: str = None):
    """Compute (depth, clean_name) from a tree cell's text.
    Depth = count of leading nbsp/full-width spaces // unit. Strips arrows and '+'.
    With nest_prefix set (e.g. "+"), each leading occurrence adds one level and is
    consumed from the name — for sites that mark children by prefix, not indent."""
    s = name_text
    while s and s[0] in ARROWS:
        s = s[1:]
    i = 0
    while i < len(s) and s[i] in (NBSP, FW, " "):
        i += 1
    indent = s[:i]
    n = indent.count(NBSP) + indent.count(FW)
    depth = n // unit if unit else 0
    rest = s[i:]
    if nest_prefix:
        while rest.startswith(nest_prefix):
            depth += 1
            rest = rest[len(nest_prefix):]
        name = rest.strip()
    else:
        name = rest.lstrip("+").strip()
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


def code_text(pre) -> str:
    """Text from a <pre>, with common line-number table wrappers removed."""
    table = pre.find("table")
    if table:
        code_cells = table.select("td.ln-text")
        if code_cells:
            text = "\n".join(td.get_text() for td in code_cells)
        else:
            lines = []
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"], recursive=False)
                if len(cells) < 2 or not cells[0].get_text(strip=True).isdigit():
                    lines = []
                    break
                lines.append(cells[1].get_text())
            text = "\n".join(lines) if lines else pre.get_text()
    else:
        text = pre.get_text()
    text = text.replace("\r\n", "\n")
    for marker in CODE_NOISE:
        i = text.find("\n" + marker)
        if i >= 0:
            text = text[:i]
    return text.rstrip("\n")


def _marker_match(txt, markers, mode="exact"):
    """exact: heading equals or starts with a marker (historical behavior).
    regex: each marker is an re.search pattern — for sites whose headings carry
    numbering/prefixes (e.g. '2. 输入参数'); opt-in via structure.section_match."""
    if mode == "regex":
        return any(re.search(m, txt) for m in markers)
    return any(txt == m or txt.startswith(m) for m in markers)


def section_tables(body, request_markers, response_markers, mode="exact"):
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
        if _marker_match(txt, req_markers, mode):
            cur = "request"
        elif _marker_match(txt, resp_markers, mode):
            cur = "response"
    return found["request"], found["response"]


def code_after(body, markers, mode="exact"):
    """Return text of the first <pre> following a heading/paragraph matching markers."""
    markers = [m.strip() for m in markers]
    armed = False
    for el in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "strong", "pre"]):
        if el.name == "pre":
            if armed:
                return code_text(el)
            continue
        txt = el.get_text().strip()
        if txt and _marker_match(txt, markers, mode):
            armed = True
    return None

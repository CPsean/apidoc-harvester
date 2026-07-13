"""Optional HTML preprocessing before Markdown conversion and extraction."""
import re

from . import common


def _attr_value(node, attr):
    if node.has_attr(attr):
        return node.get(attr)
    child = node.find(attrs={attr: True})
    return child.get(attr) if child else None


def _row_id(tr, cfg):
    id_attr = cfg.get("id_attr", "id")
    toggle_attr = cfg.get("toggle_attr", "onclick")
    row_id_regex = cfg.get("row_id_regex", r"toggle\s*\([^,]+,\s*['\"]?([^,'\")]+)")
    if tr.has_attr(id_attr):
        return str(tr.get(id_attr))
    raw = _attr_value(tr, toggle_attr)
    if raw:
        m = re.search(row_id_regex, raw)
        if m:
            return str(m.group(1))
    return None


def _parent_id(tr, cfg):
    parentid_attr = cfg.get("parentid_attr", "parentid")
    value = _attr_value(tr, parentid_attr)
    if value in (None, "", "0", "-1"):
        return None
    return str(value)


def _depth(row_id, parents, cache, visiting):
    if not row_id or row_id not in parents:
        return 0
    if row_id in cache:
        return cache[row_id]
    if row_id in visiting:
        return 0
    visiting.add(row_id)
    cache[row_id] = 1 + _depth(parents.get(row_id), parents, cache, visiting)
    visiting.remove(row_id)
    return cache[row_id]


def _table_signal(table, cfg):
    parentid_attr = cfg.get("parentid_attr", "parentid")
    if table.find(attrs={parentid_attr: True}):
        return True
    return any(cell.has_attr("colspan") for cell in table.find_all(["td", "th"]))


def _skip_table(table, cfg):
    text = table.get_text(" ", strip=True)
    return any(re.search(pattern, text) for pattern in cfg.get("skip_patterns", []))


def _expand_colspans(soup, tr):
    cells = tr.find_all(["td", "th"], recursive=False)
    expanded = []
    for cell in cells:
        span = int(cell.get("colspan", 1) or 1)
        if span > 1:
            del cell["colspan"]
        expanded.append(cell)
        for _ in range(max(span - 1, 0)):
            expanded.append(soup.new_tag(cell.name))
    return expanded


def _normalize_table(soup, table, cfg):
    if not _table_signal(table, cfg) or _skip_table(table, cfg):
        return
    rows = table.find_all("tr")
    row_ids = {tr: _row_id(tr, cfg) for tr in rows}
    parents = {
        row_id: parent_id
        for tr, row_id in row_ids.items()
        for parent_id in [_parent_id(tr, cfg)]
        if row_id and parent_id
    }
    depths = {row_id: _depth(row_id, parents, {}, set()) for row_id in parents.keys()}

    matrices = []
    for tr in rows:
        cells = _expand_colspans(soup, tr)
        matrices.append((tr, cells))
    max_cols = max((len(cells) for _, cells in matrices), default=0)

    for tr, cells in matrices:
        tr.clear()
        for cell in cells:
            tr.append(cell)
        for _ in range(max_cols - len(cells)):
            tr.append(soup.new_tag("td"))

        row_id = row_ids.get(tr)
        depth = depths.get(row_id, 0)
        if depth <= 0:
            continue
        first = tr.find(["td", "th"], recursive=False)
        if first and first.name == "td":
            text = first.get_text().strip()
            first.clear()
            first.append(common.NBSP * cfg.get("indent_unit", 4) * depth + text)


def apply(html, cfg):
    table_cfg = (cfg or {}).get("table_normalizer", {})
    if not table_cfg.get("enabled"):
        return html
    soup = common.soup(html)
    for table in soup.find_all("table"):
        _normalize_table(soup, table, table_cfg)
    return str(soup)

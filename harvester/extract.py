"""HTML body -> structured endpoint model (path, method, request/response field trees).
Field nesting is derived from the same indent logic as convert, so md and OpenAPI agree."""
import re
import json
from urllib.parse import urlparse
from . import common


def _summary(body):
    for p in body.find_all("p"):
        t = p.get_text().strip()
        if t:
            return re.sub(r"\s+", " ", t)
    return ""


def _tree_from_table(table, struct):
    if table is None:
        return []
    cols = struct["columns"]
    unit = struct.get("nested_indent_unit", 4)
    nest_prefix = struct.get("nest_prefix")
    truthy = set(struct.get("required_true_values", ["是"]))
    req_idx = cols.get("required")  # optional: 3-column docs have no required column
    max_idx = max(cols.values())
    rows = common.table_rows(table)
    if not rows:
        return []
    nodes, stack = [], []   # stack of (depth, node)
    for cells in rows[1:]:  # skip header
        if len(cells) <= max_idx:
            continue
        depth, name = common.indent_depth(cells[cols["name"]].get_text(), unit, nest_prefix)
        if not name:
            continue
        node = {
            "name": name,
            "type": cells[cols["type"]].get_text().strip(),
            "required": (cells[req_idx].get_text().strip() in truthy)
                        if req_idx is not None else False,
            "desc": common.cell_plain(cells[cols["desc"]]),
            "children": [],
        }
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1]["children"] if stack else nodes).append(node)
        stack.append((depth, node))
    return nodes


def _example(body, markers, mode="exact"):
    txt = common.code_after(body, markers, mode)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return txt.strip()


def extract_endpoint(body, page, struct):
    text = body.get_text("\n")
    pm = re.search(struct["path_regex"], text)
    mm = re.search(struct["method_regex"], text)
    mode = struct.get("section_match", "exact")
    req_tbl, resp_tbl = common.section_tables(
        body, struct["request_section"], struct["response_section"], mode)
    path = pm.group(1).strip() if pm else None
    if path and struct.get("strip_domain"):
        parsed = urlparse(path)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or "/"
    return {
        "id": page["id"],
        "title": page["title"],
        "path": path,
        "method": (mm.group(1) if mm else None),
        "summary": _summary(body),
        "request": _tree_from_table(req_tbl, struct),
        "response": _tree_from_table(resp_tbl, struct),
        "example_request": _example(body, struct.get("example_request_section", []), mode),
        "example_response": _example(body, struct.get("example_response_section", []), mode),
    }

"""HTML body -> structured endpoint model (path, method, request/response field trees).
Field nesting is derived from the same indent logic as convert, so md and OpenAPI agree."""
import re
import json
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
    truthy = set(struct.get("required_true_values", ["是"]))
    rows = common.table_rows(table)
    if not rows:
        return []
    nodes, stack = [], []   # stack of (depth, node)
    for cells in rows[1:]:  # skip header
        if len(cells) <= cols["desc"]:
            continue
        depth, name = common.indent_depth(cells[cols["name"]].get_text(), unit)
        if not name:
            continue
        node = {
            "name": name,
            "type": cells[cols["type"]].get_text().strip(),
            "required": cells[cols["required"]].get_text().strip() in truthy,
            "desc": common.cell_plain(cells[cols["desc"]]),
            "children": [],
        }
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1]["children"] if stack else nodes).append(node)
        stack.append((depth, node))
    return nodes


def _example(body, markers):
    txt = common.code_after(body, markers)
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
    req_tbl, resp_tbl = common.section_tables(
        body, struct["request_section"], struct["response_section"])
    return {
        "id": page["id"],
        "title": page["title"],
        "path": pm.group(1).strip() if pm else None,
        "method": (mm.group(1) if mm else None),
        "summary": _summary(body),
        "request": _tree_from_table(req_tbl, struct),
        "response": _tree_from_table(resp_tbl, struct),
        "example_request": _example(body, struct.get("example_request_section", [])),
        "example_response": _example(body, struct.get("example_response_section", [])),
    }

"""Endpoint models -> OpenAPI 3.1 document (inline schemas) + validation.

Type/required/nesting are derived deterministically. Enum refinement (parsing
'edit/view/preview' out of descriptions) is intentionally NOT auto-applied: it is
left to the model-assisted refinement step so generated output stays accurate."""
import re


def _scalar(t: str) -> str:
    t = (t or "").lower()
    if t in ("int", "integer", "long"):
        return "integer"
    if t in ("number", "float", "double", "decimal"):
        return "number"
    if t in ("bool", "boolean"):
        return "boolean"
    return "string"


def _object_from(children):
    props, required = {}, []
    for c in children:
        props[c["name"]] = _node_schema(c)
        if c.get("required"):
            required.append(c["name"])
    s = {"type": "object"}
    if props:
        s["properties"] = props
    if required:
        s["required"] = required
    return s


def _node_schema(node):
    t = (node.get("type") or "").strip()
    tl = t.lower()
    children = node.get("children") or []
    if t.endswith("[]") or tl == "array":
        if children:
            items = _object_from(children)
        else:
            elem = t[:-2] if t.endswith("[]") else ""
            items = {"type": _scalar(elem)} if elem else {"type": "string"}
        sch = {"type": "array", "items": items}
    elif tl == "object" or children:
        sch = _object_from(children)
    else:
        sch = {"type": _scalar(t)}
    if node.get("desc"):
        sch["description"] = node["desc"]
    return sch


def _op_id(path: str, method: str, used: set) -> str:
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", path or "") if p]
    oid = (parts[0] if parts else method.lower()) + "".join(p.capitalize() for p in parts[1:])
    oid = oid or method.lower()
    base, i = oid, 2
    while oid in used:
        oid = f"{base}{i}"
        i += 1
    used.add(oid)
    return oid


def build(models, oa_cfg):
    used = set()
    sec_headers = oa_cfg.get("security_headers", [])
    security_schemes = {
        h["key"]: {"type": "apiKey", "in": "header", "name": h["name"],
                   "description": h.get("desc", "")}
        for h in sec_headers
    }
    doc = {
        "openapi": "3.1.0",
        "info": {"title": oa_cfg.get("title", "API"), "version": str(oa_cfg.get("version", "1.0"))},
        "servers": oa_cfg.get("servers", [{"url": "https://{host}",
                              "variables": {"host": {"default": "example.com"}}}]),
        "paths": {},
    }
    if security_schemes:
        doc["components"] = {"securitySchemes": security_schemes}
        doc["security"] = [{k: [] for k in security_schemes}]

    default_method = oa_cfg.get("default_method", "POST")
    for m in models:
        if not m.get("path"):
            continue
        method = (m.get("method") or default_method).lower()
        op = {
            "summary": m["title"],
            "operationId": _op_id(m["path"], method, used),
            "description": m.get("summary", ""),
        }
        if m.get("request"):
            req_schema = _object_from(m["request"])
            content = {"schema": req_schema}
            if m.get("example_request") is not None:
                content["example"] = m["example_request"]
            op["requestBody"] = {"required": True, "content": {"application/json": content}}
        resp_schema = _object_from(m["response"]) if m.get("response") else {"type": "object"}
        resp_content = {"schema": resp_schema}
        if m.get("example_response") is not None:
            resp_content["example"] = m["example_response"]
        op["responses"] = {"200": {"description": "成功",
                                   "content": {"application/json": resp_content}}}
        doc["paths"].setdefault(m["path"], {})[method] = op
    return doc


def validate(doc):
    """Return list of error strings ([] if valid)."""
    try:
        from openapi_spec_validator import validate as _v
    except ImportError:
        return ["openapi-spec-validator not installed (pip install openapi-spec-validator)"]
    try:
        _v(doc)
        return []
    except Exception as e:  # noqa: BLE001
        return [str(e).splitlines()[0]]

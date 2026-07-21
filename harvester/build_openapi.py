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
        s["required"] = list(dict.fromkeys(required))
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
        # OpenAPI requires paths to start with "/"; RPC-style docs (e.g. Tencent
        # Cloud actions) often don't. Normalize here — models.json keeps the raw
        # path, and checks warns about the rewrite so it is never silent.
        path = m["path"] if m["path"].startswith("/") else "/" + m["path"]
        method = (m.get("method") or default_method).lower()
        op = {
            "summary": m["title"],
            "operationId": _op_id(path, method, used),
            "description": m.get("summary", ""),
        }
        path_param_names = set(re.findall(r"\{([^}/]+)\}", path))
        path_params, body_fields = [], []
        for field in m.get("request") or []:
            if field.get("name") in path_param_names:
                path_params.append(field)
            else:
                body_fields.append(field)
        if path_param_names:
            found = {p.get("name") for p in path_params}
            for name in sorted(path_param_names - found):
                path_params.append({"name": name, "type": "string", "desc": "", "children": []})
            op["parameters"] = [
                {
                    "name": p["name"],
                    "in": "path",
                    "required": True,
                    "schema": {"type": _scalar(p.get("type", ""))},
                    "description": p.get("desc", ""),
                }
                for p in path_params
            ]
        if body_fields:
            req_schema = _object_from(body_fields)
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
        doc["paths"].setdefault(path, {})[method] = op
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

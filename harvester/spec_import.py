"""Acquire an already-published OpenAPI/Swagger spec directly.

This is the cheapest, most accurate acquisition of all: the spec IS the source of
truth, so we don't scrape pages — we download it (URL or local file), optionally
convert Swagger 2.0 -> OpenAPI 3.0 via `npx swagger2openapi`, validate, and emit.

Config shape (a spec-mode config has `spec_source` instead of `pages`):

    spec_source:
      url: "https://.../swagger.json"   # or  file: "specs/foo.json"
      format: auto                      # auto | swagger2 | openapi3
      convert_to: none                  # none | openapi3
      normalize: false                  # true: deterministic lint-fix of sloppy
                                        # vendor specs (see _normalize)
    output:
      openapi: "out/<site>/openapi.yaml"
      report:  "out/<site>/checks-report.json"
"""
import os
import re
import json
import shutil
import subprocess
import tempfile
import urllib.request

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}

# Keys whose values are user data / literal payloads, not spec structure — the
# normalizer must never rewrite inside them (an example may legally contain
# {"type": "date"}).
_OPAQUE_KEYS = {"example", "examples", "default", "enum", "const", "value"}

# Invalid-but-common `type` spellings -> (canonical type, format to add if absent).
_TYPE_ALIASES = {
    "int": ("integer", None),
    "long": ("integer", "int64"),
    "float": ("number", "float"),
    "double": ("number", "double"),
    "bool": ("boolean", None),
    "date": ("string", "date"),
    "datetime": ("string", "date-time"),
    "dateTime": ("string", "date-time"),
}

# Keys the OpenAPI 3.x info object allows (anything else must be x- prefixed).
_INFO_KEYS = {"title", "summary", "description", "termsOfService", "contact",
              "license", "version"}

# Required *Url fields per oauth2 flow name.
_FLOW_REQUIRED_URLS = {
    "implicit": ["authorizationUrl"],
    "password": ["tokenUrl"],
    "clientCredentials": ["tokenUrl"],
    "authorizationCode": ["authorizationUrl", "tokenUrl"],
}

_COMPONENT_KEY_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _root_of(config_path):
    return os.path.dirname(os.path.dirname(os.path.abspath(config_path)))


def _fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as urllib_err:  # noqa: BLE001
        # Some local proxies break urllib's CONNECT/TLS while curl gets through
        # (observed: SSL UNEXPECTED_EOF behind a 127.0.0.1 forward proxy).
        # Resolve curl via PATH: on Windows, subprocess with a bare "curl" finds
        # System32's build before PATH (CreateProcess order), and that build can
        # fail the same proxy handshake that the PATH one (e.g. Git's) survives.
        curl = shutil.which("curl")
        if not curl:
            raise
        proc = subprocess.run([curl, "-sSL", "--max-time", "180",
                               "--retry", "3", "--retry-all-errors",
                               "-A", "Mozilla/5.0", url],
                              capture_output=True, timeout=900)
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(
                f"urllib failed ({urllib_err}); curl fallback failed "
                f"(rc={proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:200]}"
            ) from urllib_err
        return proc.stdout.decode("utf-8", "replace")


def _load(spec_source, root):
    url = spec_source.get("url")
    fpath = spec_source.get("file")
    if url:
        raw = _fetch_url(url)
        src = url
    elif fpath:
        p = fpath if os.path.isabs(fpath) else os.path.join(root, fpath)
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        src = p
    else:
        raise ValueError("spec_source needs `url` or `file`")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        raise ValueError(f"spec did not parse to an object: {src}")
    return doc, src


def _detect(doc):
    if str(doc.get("swagger", "")).startswith("2"):
        return "swagger2"
    if doc.get("openapi"):
        return "openapi3"
    return "unknown"


def _convert_swagger2(doc):
    """Swagger 2.0 -> OpenAPI 3.0 via npx swagger2openapi. Returns the 3.0 dict."""
    npx = "npx.cmd" if os.name == "nt" else "npx"
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "in.json")
        outp = os.path.join(td, "out.json")
        with open(inp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        cmd = [npx, "-y", "swagger2openapi", inp, "-o", outp]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not os.path.exists(outp):
            raise RuntimeError(f"swagger2openapi failed (rc={proc.returncode}): {(proc.stderr or proc.stdout)[:300]}")
        with open(outp, encoding="utf-8") as f:
            return json.load(f)


def _walk(node, fn, in_opaque=False):
    """Depth-first walk over every dict; fn(d) may mutate d in place.
    Subtrees under _OPAQUE_KEYS are visited with in_opaque=True (fn skipped)."""
    if isinstance(node, dict):
        if not in_opaque:
            fn(node)
        for k, v in list(node.items()):
            _walk(v, fn, in_opaque or k in _OPAQUE_KEYS or k.startswith("x-"))
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn, in_opaque)


# Keys holding pure literal payloads where a "$ref" is just data, not a reference.
_LITERAL_KEYS = {"example", "default", "enum", "const", "value"}


def _walk_refs(node, fn):
    """Visit every dict that can structurally hold a live $ref. Unlike _walk,
    dict-valued `examples` (media-type Example Object maps, which may be $refs)
    ARE walked; list-valued `examples` (JSON-Schema literal arrays) are not."""
    if isinstance(node, dict):
        fn(node)
        for k, v in list(node.items()):
            if k in _LITERAL_KEYS or (k == "examples" and isinstance(v, list)):
                continue
            _walk_refs(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk_refs(v, fn)


def _normalize(doc):
    """Deterministic lint-fix for sloppy vendor specs. Mechanical rules only —
    fills required-but-absent strings with "", never invents content. Returns
    {fix_bucket: count} of what was changed."""
    fixes = {}

    def bump(key, n=1):
        if n:
            fixes[key] = fixes.get(key, 0) + n

    # 1. responses missing required `description` -> ""
    def fix_responses(container):
        for resp in (container or {}).values():
            if isinstance(resp, dict) and "$ref" not in resp and "description" not in resp:
                resp["description"] = ""
                bump("response missing description -> ''")
    for item in (doc.get("paths") or {}).values():
        if isinstance(item, dict):
            for m, op in item.items():
                if m.lower() in HTTP_METHODS and isinstance(op, dict):
                    fix_responses(op.get("responses"))
    fix_responses((doc.get("components") or {}).get("responses"))

    # 2. invalid `type` spellings (int/float/double/date/...) -> canonical type+format
    def fix_types(d):
        t = d.get("type")
        if isinstance(t, str) and t in _TYPE_ALIASES:
            canon, fmt = _TYPE_ALIASES[t]
            d["type"] = canon
            if fmt and "format" not in d:
                d["format"] = fmt
            bump(f"type alias '{t}' -> '{canon}'")
        elif isinstance(t, list):  # 3.1 type arrays
            for i, ti in enumerate(t):
                if isinstance(ti, str) and ti in _TYPE_ALIASES:
                    t[i] = _TYPE_ALIASES[ti][0]
                    bump(f"type alias '{ti}' -> '{_TYPE_ALIASES[ti][0]}'")
    _walk(doc, fix_types)

    # 3. boolean `required` inside schema objects (Swagger2-ism) -> drop.
    #    Parameter/header objects, where boolean required IS legal, are
    #    recognizable by their `in`/`schema`/`content` keys.
    def fix_bool_required(d):
        if isinstance(d.get("required"), bool) and not ({"in", "schema", "content"} & d.keys()):
            del d["required"]
            bump("boolean 'required' in schema dropped")
    _walk(doc, fix_bool_required)

    # 4. component names violating ^[a-zA-Z0-9._-]+$ -> sanitized, $refs rewritten
    ref_map = {}
    for section, members in list((doc.get("components") or {}).items()):
        if not isinstance(members, dict):
            continue
        for name in list(members):
            if _COMPONENT_KEY_RE.match(name):
                continue
            clean = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
            while clean in members:
                clean += "_"
            members[clean] = members.pop(name)
            ref_map[f"#/components/{section}/{name}"] = f"#/components/{section}/{clean}"
            bump("invalid component name sanitized")
    if ref_map:
        def fix_refs(d):
            ref = d.get("$ref")
            if isinstance(ref, str) and ref in ref_map:
                d["$ref"] = ref_map[ref]
        _walk_refs(doc, fix_refs)

    # 5. non-standard keys in `info` -> x- extensions
    info = doc.get("info")
    if isinstance(info, dict):
        for k in list(info):
            if k not in _INFO_KEYS and not k.startswith("x-"):
                info[f"x-{k}"] = info.pop(k)
                bump(f"info.{k} -> info.x-{k}")

    # 6. oauth2 flows missing a required *Url -> "" (fill the slot, don't invent)
    for scheme in ((doc.get("components") or {}).get("securitySchemes") or {}).values():
        if not (isinstance(scheme, dict) and scheme.get("type") == "oauth2"):
            continue
        for flow_name, flow in (scheme.get("flows") or {}).items():
            if not isinstance(flow, dict):
                continue
            for url_key in _FLOW_REQUIRED_URLS.get(flow_name, []):
                if url_key not in flow:
                    flow[url_key] = ""
                    bump(f"oauth2 {flow_name} missing {url_key} -> ''")

    return fixes


def _dangling_refs(doc):
    """Internal $refs that don't resolve — a vendor-spec defect we surface
    (faithfully preserved, not repaired)."""
    refs = set()

    def collect(d):
        r = d.get("$ref")
        if isinstance(r, str) and r.startswith("#/"):
            refs.add(r)
    _walk_refs(doc, collect)
    dangling = []
    for r in sorted(refs):
        node = doc
        for part in r[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                dangling.append(r)
                break
    return dangling


def _validate(doc):
    """Validate; return ALL errors bucketed as ['N× first-line', ...] (not just
    the first one) so the checks report shows the full failure shape."""
    try:
        from openapi_spec_validator.validation import (
            OpenAPIV2SpecValidator, OpenAPIV30SpecValidator, OpenAPIV31SpecValidator)
    except ImportError:
        return ["openapi-spec-validator not installed (pip install openapi-spec-validator)"]
    ver = str(doc.get("openapi", ""))
    if str(doc.get("swagger", "")).startswith("2"):
        cls = OpenAPIV2SpecValidator
    elif ver.startswith("3.1"):
        cls = OpenAPIV31SpecValidator
    else:
        cls = OpenAPIV30SpecValidator
    buckets = {}
    try:
        for err in cls(doc).iter_errors():
            msg = err.message.splitlines()[0][:160]
            buckets[msg] = buckets.get(msg, 0) + 1
    except Exception as e:  # noqa: BLE001
        return [str(e).splitlines()[0]]
    ranked = sorted(buckets.items(), key=lambda kv: -kv[1])
    out = [f"{n}× {msg}" for msg, n in ranked[:15]]
    if len(ranked) > 15:
        out.append(f"... and {len(ranked) - 15} more error kinds")
    return out


def _count_ops(paths):
    return sum(1 for item in paths.values() if isinstance(item, dict)
               for m in item if m.lower() in HTTP_METHODS)


def run(config_path):
    cfg = yaml.safe_load(open(config_path, encoding="utf-8"))
    root = _root_of(config_path)
    ss = cfg["spec_source"]
    out = cfg["output"]

    fails, warns = [], []
    doc, src = _load(ss, root)

    kind = ss.get("format", "auto")
    if kind == "auto":
        kind = _detect(doc)

    converted = False
    convert_to = ss.get("convert_to", "none")
    if convert_to == "openapi3" and kind == "swagger2":
        try:
            doc = _convert_swagger2(doc)
            kind = "openapi3"
            converted = True
        except Exception as e:  # noqa: BLE001
            fails.append(f"swagger2->openapi3 conversion failed: {e}")
    elif convert_to == "openapi3" and kind == "openapi3":
        warns.append("convert_to: openapi3 ignored — source is already OpenAPI 3.x")

    normalize_fixes = {}
    if ss.get("normalize"):
        normalize_fixes = _normalize(doc)
        for bucket, n in sorted(normalize_fixes.items(), key=lambda kv: -kv[1]):
            warns.append(f"normalize: {n}× {bucket}")

    oa_errors = _validate(doc)
    fails.extend(oa_errors)

    dangling = _dangling_refs(doc)
    if dangling:
        shown = ", ".join(dangling[:8]) + (" ..." if len(dangling) > 8 else "")
        warns.append(f"{len(dangling)} dangling $ref(s) preserved from source: {shown}")

    oa_path = os.path.join(root, out["openapi"])
    os.makedirs(os.path.dirname(oa_path), exist_ok=True)
    with open(oa_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)

    paths = doc.get("paths", {}) or {}
    report = {
        "summary": {
            "source": src,
            "kind": kind,
            "converted": converted,
            "paths": len(paths),
            "operations": _count_ops(paths),
            "normalized": bool(ss.get("normalize")),
            "normalize_fixes": sum(normalize_fixes.values()),
            "openapi_valid": not oa_errors,
            "fails": len(fails),
            "warns": len(warns),
        },
        "fails": fails,
        "warns": warns,
        "ok": not fails,
    }
    rep_path = os.path.join(root, out["report"])
    os.makedirs(os.path.dirname(rep_path), exist_ok=True)
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report

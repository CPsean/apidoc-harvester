"""Acquire an already-published OpenAPI/Swagger spec directly.

This is the cheapest, most accurate acquisition of all: the spec IS the source of
truth, so we don't scrape pages — we download it (URL or local file), optionally
convert Swagger 2.0 -> OpenAPI 3.0 via `npx swagger2openapi`, validate, and emit.

Config shape (a spec-mode config has `spec_source` instead of `pages`):

    spec_source:
      url: "https://.../swagger.json"   # or  file: "specs/foo.json"
      format: auto                      # auto | swagger2 | openapi3
      convert_to: none                  # none | openapi3
    output:
      openapi: "out/<site>/openapi.yaml"
      report:  "out/<site>/checks-report.json"
"""
import os
import json
import subprocess
import tempfile
import urllib.request

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}


def _root_of(config_path):
    return os.path.dirname(os.path.dirname(os.path.abspath(config_path)))


def _load(spec_source, root):
    url = spec_source.get("url")
    fpath = spec_source.get("file")
    if url:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", "replace")
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


def _validate(doc):
    try:
        from openapi_spec_validator import validate as _v
    except ImportError:
        return ["openapi-spec-validator not installed (pip install openapi-spec-validator)"]
    try:
        _v(doc)
        return []
    except Exception as e:  # noqa: BLE001
        return [str(e).splitlines()[0]]


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

    oa_errors = _validate(doc)
    fails.extend(oa_errors)

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

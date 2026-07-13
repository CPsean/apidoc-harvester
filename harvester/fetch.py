"""Acquire a page's raw content as HTML (or markdown), using the cheapest
strategy that works. Returns a dict: {format: 'html'|'markdown', content: str}."""
import os
import json
import re
import ast
import hashlib
import urllib.request


def _get_pointer(obj, dotted):
    for part in dotted.split("."):
        if isinstance(obj, list):
            part = int(part)
        obj = obj[part]
    return obj


def _content_api(page, cfg, _root):
    ca = cfg["acquire"]["content_api"]
    if not ca.get("enabled"):
        return None
    # Template URL with the whole page dict + a doc_id alias, so configs can use
    # {doc_id} (single-id) or several keys like {nodeId}/{articleId} (multi-id).
    fields = dict(page)
    fields.setdefault("doc_id", page.get("doc_id") or page.get("id"))
    url = ca["url_template"].format(**fields)
    # Default Accept + any site-specific request headers from config
    # (some gateways 403 without an XHR marker / version header).
    headers = {"Accept": "application/json"}
    headers.update(ca.get("headers") or {})
    req = urllib.request.Request(url, method=ca.get("method", "GET"), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    fmt = ca.get("response_format", "json")
    if fmt == "json":
        data = json.loads(raw)
        content = _get_pointer(data, ca["content_pointer"])
        return {"format": ca.get("content_is", "html"), "content": content}
    return {"format": fmt, "content": raw}


def _static_html(page, cfg, root):
    sh = cfg["acquire"]["static_html"]
    if not sh.get("enabled") or not page.get("file"):
        return None
    path = os.path.join(root, sh.get("html_root", "."), page["file"])
    with open(path, encoding="utf-8") as f:
        return {"format": "html", "content": f.read()}


def _rendered(page, cfg, _root):
    rc = cfg["acquire"]["rendered"]
    if not rc.get("enabled"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("rendered strategy needs: pip install playwright && playwright install chromium")
    doc_id = page.get("doc_id") or page.get("id")
    url = rc["url_template"].format(doc_id=doc_id)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(url, wait_until="networkidle")
        if rc.get("wait_selector"):
            pg.wait_for_selector(rc["wait_selector"], timeout=15000)
        html = pg.content()
        b.close()
    return {"format": "html", "content": html}


_JS_INDEX_CACHE = {}


def _read_bundle(source, root, js_cfg, site):
    if source.startswith(("http://", "https://")):
        cache_dir = js_cfg.get("cache_dir")
        if cache_dir is None:
            cache_dir = os.path.join("out", site, "_bundle_cache")
        cache_path = os.path.join(root, cache_dir, hashlib.sha1(source.encode("utf-8")).hexdigest() + ".js")
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                return f.read()
        with urllib.request.urlopen(source, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    path = source if os.path.isabs(source) else os.path.join(root, source)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _decode_js_string(quote, value):
    try:
        return ast.literal_eval(quote + value + quote)
    except Exception:
        return value.replace(r"\/", "/").replace(r"\n", "\n").replace(r"\"", '"').replace(r"\'", "'")


def _field(obj, name):
    key = re.escape(name)
    pattern = r'(?:["\']%s["\']|%s)\s*:\s*(["\'])(?P<value>(?:\\.|(?!\1).)*)\1' % (key, key)
    m = re.search(pattern, obj, re.S)
    return _decode_js_string(m.group(1), m.group("value")) if m else None


def _records_from_bundle(text, js_cfg):
    id_field = js_cfg.get("id_field", "id")
    title_field = js_cfg.get("title_field", "title")
    content_field = js_cfg.get("content_field", "content")
    records = {}
    if js_cfg.get("record_regex"):
        for m in re.finditer(js_cfg["record_regex"], text, re.S):
            data = m.groupdict()
            pid = data.get("id")
            content = data.get("content")
            if pid and content is not None:
                records[str(pid)] = {
                    "title": data.get("title") or str(pid),
                    "content": content,
                }
        return records

    object_regex = js_cfg.get("object_regex")
    if not object_regex:
        raise ValueError("js_bundle needs record_regex or object_regex")
    for m in re.finditer(object_regex, text, re.S):
        obj = m.group(0)
        pid = _field(obj, id_field)
        content = _field(obj, content_field)
        if pid and content is not None:
            records[str(pid)] = {
                "title": _field(obj, title_field) or str(pid),
                "content": content,
            }
    return records


def _js_bundle_index(cfg, root):
    js_cfg = cfg["acquire"]["js_bundle"]
    key = json.dumps(js_cfg, sort_keys=True, ensure_ascii=False) + "|" + root
    if key in _JS_INDEX_CACHE:
        return _JS_INDEX_CACHE[key]
    index = {}
    for source in js_cfg.get("bundle_urls", []):
        text = _read_bundle(source, root, js_cfg, cfg.get("site", "site"))
        index.update(_records_from_bundle(text, js_cfg))
    _JS_INDEX_CACHE[key] = index
    return index


def _js_bundle(page, cfg, root):
    js_cfg = cfg["acquire"]["js_bundle"]
    if not js_cfg.get("enabled"):
        return None
    page_id = str(page.get(js_cfg.get("page_id_field", "doc_id")) or page.get("doc_id") or page.get("id"))
    record = _js_bundle_index(cfg, root).get(page_id)
    if not record:
        return None
    return {"format": js_cfg.get("content_is", "html"), "content": record["content"]}


STRATEGIES = {
    "content_api": _content_api,
    "js_bundle": _js_bundle,
    "static_html": _static_html,
    "rendered": _rendered,
}


def acquire(page, cfg, root):
    """Try strategies in configured order; return first non-None result."""
    errors = []
    for name in cfg["acquire"].get("order", list(STRATEGIES)):
        fn = STRATEGIES.get(name)
        if not fn:
            continue
        try:
            res = fn(page, cfg, root)
            if res:
                res["strategy"] = name
                return res
        except Exception as e:  # noqa: BLE001 — record and fall through to next strategy
            errors.append(f"{name}: {e}")
    raise RuntimeError(f"no acquisition strategy resolved for page {page.get('id')}: {errors}")

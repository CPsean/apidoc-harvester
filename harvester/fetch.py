"""Acquire a page's raw content as HTML (or markdown), using the cheapest
strategy that works. Returns a dict: {format: 'html'|'markdown', content: str}."""
import os
import json
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


STRATEGIES = {"content_api": _content_api, "static_html": _static_html, "rendered": _rendered}


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

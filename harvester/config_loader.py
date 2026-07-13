"""Load site configs and expand generated page lists."""
import json
import os

import yaml

from . import common


def root_of(config_path):
    return os.path.dirname(os.path.dirname(os.path.abspath(config_path)))


def _as_spec(value, key="path"):
    if not value:
        return None
    if isinstance(value, str):
        return {key: value}
    return dict(value)


def _rel_join(root, path):
    return path if os.path.isabs(path) else os.path.join(root, path)


def _clean_id(value):
    return str(value).replace("\\", "/").rsplit(".", 1)[0].replace("/", "_")


def _page_from_manifest_item(key, item, spec):
    id_field = spec.get("id_field", "id")
    title_field = spec.get("title_field", "title")
    file_field = spec.get("file_field", "file")
    doc_id_field = spec.get("doc_id_field", "doc_id")

    if isinstance(item, str):
        page = {"id": _clean_id(key or item), "title": _clean_id(key or item)}
        page[file_field] = item
    else:
        page = dict(item)
        if id_field != "id" and id_field in page and "id" not in page:
            page["id"] = page[id_field]
        if title_field != "title" and title_field in page and "title" not in page:
            page["title"] = page[title_field]
        if file_field != "file" and file_field in page and "file" not in page:
            page["file"] = page[file_field]
        if doc_id_field != "doc_id" and doc_id_field in page and "doc_id" not in page:
            page["doc_id"] = page[doc_id_field]
        if "id" not in page:
            page["id"] = _clean_id(key or page.get("file") or page.get("doc_id"))
        if "title" not in page:
            page["title"] = str(page["id"])
    return page


def _manifest_items(data):
    if isinstance(data, list):
        return [(None, item) for item in data]
    if isinstance(data, dict):
        for key in ("pages", "items", "docs", "data"):
            if isinstance(data.get(key), list):
                return [(None, item) for item in data[key]]
        return list(data.items())
    return []


def _pages_from_manifest(cfg, root):
    spec = _as_spec(cfg.get("pages_from_manifest"))
    if not spec:
        return []
    path = _rel_join(root, spec["path"])
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    non_api_ids = {str(x) for x in spec.get("non_api_ids", [])}
    api_default = spec.get("api_default", True)
    pages = []
    for key, item in _manifest_items(data):
        page = _page_from_manifest_item(key, item, spec)
        page["id"] = str(page["id"])
        page.setdefault("title", page["id"])
        if "api" not in page:
            page["api"] = page["id"] not in non_api_ids and api_default
        pages.append(page)
    return pages


def _title_from_html(path, selector):
    if not selector:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            soup = common.soup(f.read())
        el = soup.select_one(selector)
        return el.get_text().strip() if el else None
    except Exception:
        return None


def _pages_from_dir(cfg, root):
    spec = _as_spec(cfg.get("pages_from_dir"))
    if not spec:
        return []
    directory = _rel_join(root, spec["path"])
    pattern = spec.get("pattern", ".html")
    recursive = spec.get("recursive", True)
    static_root = cfg.get("acquire", {}).get("static_html", {}).get("html_root", ".")
    file_base = _rel_join(root, spec.get("file_base", static_root))
    title_selector = spec.get("title_selector") or cfg.get("selectors", {}).get("title")
    non_api_ids = {str(x) for x in spec.get("non_api_ids", [])}
    api_default = spec.get("api_default", True)

    files = []
    if recursive:
        for base, _, names in os.walk(directory):
            for name in names:
                if name.endswith(pattern):
                    files.append(os.path.join(base, name))
    elif os.path.isdir(directory):
        files = [
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.endswith(pattern)
        ]

    pages = []
    for path in sorted(files):
        rel_file = os.path.relpath(path, file_base).replace("\\", "/")
        rel_id = os.path.relpath(path, directory).replace("\\", "/")
        page_id = _clean_id(rel_id)
        title = _title_from_html(path, title_selector) or os.path.splitext(os.path.basename(path))[0]
        pages.append({
            "id": page_id,
            "title": title,
            "file": rel_file,
            "api": page_id not in non_api_ids and api_default,
        })
    return pages


def _merge_pages(generated, explicit):
    merged = {str(p["id"]): dict(p) for p in generated if p.get("id") is not None}
    order = [str(p["id"]) for p in generated if p.get("id") is not None]
    for page in explicit or []:
        pid = str(page["id"])
        if pid not in merged:
            order.append(pid)
        merged[pid] = dict(page)
    return [merged[pid] for pid in order]


def load_config(config_path):
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if "spec_source" in cfg:
        return cfg
    root = root_of(config_path)
    generated = []
    generated.extend(_pages_from_manifest(cfg, root))
    generated.extend(_pages_from_dir(cfg, root))
    if generated:
        cfg["pages"] = _merge_pages(generated, cfg.get("pages", []))
    return cfg

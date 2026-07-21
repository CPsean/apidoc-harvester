"""Orchestrator: fetch -> convert -> extract -> build_openapi -> checks for one config."""
import os
import json
import re

import yaml

from . import fetch, convert, extract, build_openapi, checks, common, config_loader
from . import preprocess
from . import update_state


def _root_of(config_path):
    return config_loader.root_of(config_path)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _maybe_repair_fences(md, filename, repair, warns):
    """Opt-in (output.repair_fences): close an odd trailing code fence and record a
    warn. Off by default — a broken source doc is surfaced as a checks fail, not
    silently repaired."""
    if repair and md.count("```") % 2 == 1:
        warns.append(f"fence repaired: {filename}")
        return md.rstrip("\n") + "\n```\n"
    return md


def _normalize_markdown_fence_markers(md):
    """Normalize CommonMark-valid indented bare backtick fences for python-markdown."""
    return re.sub(r"^(\s{0,3})(`{3,})\s*$", r"\2", md, flags=re.MULTILINE)


def _md_body(md_text):
    """Markdown content -> BeautifulSoup body, so markdown-format acquisitions can
    reuse the same extract_endpoint as HTML pages."""
    try:
        import markdown as _markdown
    except ImportError:
        raise RuntimeError(
            "markdown 格式页面参与抽取需要 markdown 库: pip install 'markdown>=3.4'")
    html = _markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return common.soup(html)


def _process_page_raw(page, raw, cfg, root, md_dir, unit, nest_prefix, repair, warns):
    fn = common.safe_filename(f"{page['id']}_{page['title']}") + ".md"
    if raw["format"] == "markdown":
        md = _normalize_markdown_fence_markers(raw["content"]).rstrip() + "\n"
        md = _maybe_repair_fences(md, fn, repair, warns)
        _write(os.path.join(md_dir, fn), md)
        model = None
        if page.get("api", True):
            model = extract.extract_endpoint(_md_body(md), page, cfg["structure"])
        return fn, model

    html = preprocess.apply(raw["content"], cfg.get("preprocess", {}))
    body, title, time = common.parse_page(html, cfg["selectors"])
    if body is None:
        raise ValueError(f"{page['id']} {page.get('title','')}: 未找到正文（检查 selectors.body）")
    md = convert.to_markdown(body, title or page["title"], time, page.get("url", ""),
                             unit, nest_prefix)
    md = _maybe_repair_fences(md, fn, repair, warns)
    _write(os.path.join(md_dir, fn), md)
    model = extract.extract_endpoint(body, page, cfg["structure"]) if page.get("api", True) else None
    return fn, model


def _update_report(enabled, state_file, buckets):
    report = {
        "enabled": enabled,
        "state": state_file,
        "summary": {name: len(ids) for name, ids in buckets.items()},
    }
    report.update({name: ids for name, ids in buckets.items()})
    return report


def run(config_path, update=False):
    cfg = config_loader.load_config(config_path)
    config_loader.validate_pipeline_config(cfg, config_path)
    root = _root_of(config_path)
    out = cfg["output"]
    md_dir = os.path.join(root, out["markdown_dir"])
    unit = cfg["structure"].get("nested_indent_unit", 4)
    nest_prefix = cfg["structure"].get("nest_prefix")
    repair = out.get("repair_fences", False)
    state_file = update_state.state_path(root, out)
    old_state = update_state.load(state_file) if update else {"pages": {}}
    old_pages = old_state.get("pages", {})
    next_pages = {}
    fingerprint = update_state.transform_fingerprint(cfg) if update else None
    update_buckets = {
        "added": [],
        "changed": [],
        "unchanged": [],
        "stale": [],
        "fetch_failed": [],
    }
    current_ids = {str(page["id"]) for page in cfg["pages"]}
    active_markdown_files = []

    models, page_errors, page_warns = [], [], []
    for page in cfg["pages"]:
        page_id = str(page["id"])
        try:
            raw = fetch.acquire(page, cfg, root)
        except Exception as e:
            msg = f"{page['id']} {page.get('title','')}: fetch 失败 {e}"
            (page_errors if page.get("api", True) else page_warns).append(msg)
            if update:
                update_buckets["fetch_failed"].append(page_id)
                if page_id in old_pages:
                    next_pages[page_id] = dict(old_pages[page_id])
            continue
        digest = update_state.raw_hash(raw.get("format"), raw.get("content"))
        old_entry = old_pages.get(page_id)
        if update and update_state.can_reuse(old_entry, page, digest, fingerprint, root, md_dir):
            if page.get("api", True):
                models.append(old_entry["model"])
            active_markdown_files.append(old_entry["markdown_filename"])
            entry = dict(old_entry)
            entry["stale"] = False
            next_pages[page_id] = entry
            update_buckets["unchanged"].append(page_id)
            continue
        try:
            fn, model = _process_page_raw(page, raw, cfg, root, md_dir, unit,
                                          nest_prefix, repair, page_warns)
        except ValueError as e:
            page_errors.append(str(e))
            if update:
                if page_id in old_pages:
                    next_pages[page_id] = dict(old_pages[page_id])
            continue
        if model:
            models.append(model)
        active_markdown_files.append(fn)
        if update:
            next_pages[page_id] = {
                "id": page_id,
                "title": page.get("title"),
                "api": page.get("api", True),
                "strategy": raw.get("strategy"),
                "format": raw.get("format"),
                "raw_hash": digest,
                "transform_fingerprint": fingerprint,
                "markdown_filename": fn,
                "model": model,
                "stale": False,
            }
            update_buckets["added" if old_entry is None else "changed"].append(page_id)

    doc = build_openapi.build(models, cfg.get("openapi", {}))
    oa_errors = build_openapi.validate(doc)
    _write(os.path.join(root, out["openapi"]),
           yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    _write(os.path.join(root, out["models_json"]),
           json.dumps(models, ensure_ascii=False, indent=2))

    if update:
        for page_id in sorted(set(old_pages) - current_ids):
            update_buckets["stale"].append(page_id)
            entry = dict(old_pages[page_id])
            entry["stale"] = True
            next_pages[page_id] = entry

    report = checks.run_checks(
        cfg, models, doc, oa_errors, root,
        active_markdown_files if update else None)
    if update:
        state = {
            "version": update_state.STATE_VERSION,
            "transform_fingerprint": fingerprint,
            "pages": next_pages,
        }
        update_state.save(state_file, state)
        report["update"] = _update_report(
            True, os.path.relpath(state_file, root).replace("\\", "/"), update_buckets)
    if page_warns:
        report["warns"] = report.get("warns", []) + page_warns
        report["summary"]["warns"] = len(report["warns"])
    if page_errors:
        report["fails"] = report.get("fails", []) + page_errors
        report["summary"]["fails"] = len(report["fails"])
        report["ok"] = False
    _write(os.path.join(root, out["report"]),
           json.dumps(report, ensure_ascii=False, indent=2))
    return report

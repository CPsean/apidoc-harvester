"""Orchestrator: fetch -> convert -> extract -> build_openapi -> checks for one config."""
import os
import json
import re

import yaml

from . import fetch, convert, extract, build_openapi, checks, common, config_loader
from . import preprocess


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


def run(config_path):
    cfg = config_loader.load_config(config_path)
    config_loader.validate_pipeline_config(cfg, config_path)
    root = _root_of(config_path)
    out = cfg["output"]
    md_dir = os.path.join(root, out["markdown_dir"])
    unit = cfg["structure"].get("nested_indent_unit", 4)
    nest_prefix = cfg["structure"].get("nest_prefix")
    repair = out.get("repair_fences", False)

    models, page_errors, page_warns = [], [], []
    for page in cfg["pages"]:
        try:
            raw = fetch.acquire(page, cfg, root)
        except Exception as e:
            msg = f"{page['id']} {page.get('title','')}: fetch 失败 {e}"
            (page_errors if page.get("api", True) else page_warns).append(msg)
            continue
        fn = common.safe_filename(f"{page['id']}_{page['title']}") + ".md"
        if raw["format"] == "markdown":
            md = _normalize_markdown_fence_markers(raw["content"]).rstrip() + "\n"
            md = _maybe_repair_fences(md, fn, repair, page_warns)
            _write(os.path.join(md_dir, fn), md)
            if page.get("api", True):
                models.append(extract.extract_endpoint(_md_body(md), page, cfg["structure"]))
            continue
        html = preprocess.apply(raw["content"], cfg.get("preprocess", {}))
        body, title, time = common.parse_page(html, cfg["selectors"])
        if body is None:
            page_errors.append(f"{page['id']} {page.get('title','')}: 未找到正文（检查 selectors.body）")
            continue
        md = convert.to_markdown(body, title or page["title"], time, page.get("url", ""),
                                 unit, nest_prefix)
        md = _maybe_repair_fences(md, fn, repair, page_warns)
        _write(os.path.join(md_dir, fn), md)
        if page.get("api", True):
            models.append(extract.extract_endpoint(body, page, cfg["structure"]))

    doc = build_openapi.build(models, cfg.get("openapi", {}))
    oa_errors = build_openapi.validate(doc)
    _write(os.path.join(root, out["openapi"]),
           yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    _write(os.path.join(root, out["models_json"]),
           json.dumps(models, ensure_ascii=False, indent=2))

    report = checks.run_checks(cfg, models, doc, oa_errors, root)
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

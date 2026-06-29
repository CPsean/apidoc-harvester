"""Orchestrator: fetch -> convert -> extract -> build_openapi -> checks for one config."""
import os
import json
import yaml

from . import fetch, convert, extract, build_openapi, checks, common


def _root_of(config_path):
    return os.path.dirname(os.path.dirname(os.path.abspath(config_path)))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run(config_path):
    cfg = yaml.safe_load(open(config_path, encoding="utf-8"))
    root = _root_of(config_path)
    out = cfg["output"]
    md_dir = os.path.join(root, out["markdown_dir"])
    unit = cfg["structure"].get("nested_indent_unit", 4)

    models, page_errors, page_warns = [], [], []
    for page in cfg["pages"]:
        try:
            raw = fetch.acquire(page, cfg, root)
        except Exception as e:
            msg = f"{page['id']} {page.get('title','')}: fetch 失败 {e}"
            (page_errors if page.get("api", True) else page_warns).append(msg)
            continue
        if raw["format"] == "markdown":
            md = raw["content"].rstrip() + "\n"
            _write(os.path.join(md_dir, f"{page['id']}_{page['title']}.md"), md)
            continue
        body, title, time = common.parse_page(raw["content"], cfg["selectors"])
        if body is None:
            page_errors.append(f"{page['id']} {page.get('title','')}: 未找到正文（检查 selectors.body）")
            continue
        md = convert.to_markdown(body, title or page["title"], time, page.get("url", ""), unit)
        _write(os.path.join(md_dir, f"{page['id']}_{page['title']}.md"), md)
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

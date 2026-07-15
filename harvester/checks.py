"""The evaluator / oracle. Produces a machine-readable report the loop consumes.
A 'fail' means the agent should patch a script or the config and re-run."""
import os
import re
import difflib


def _md_noise(md_dir):
    issues = []
    if not os.path.isdir(md_dir):
        return ["markdown dir missing: " + md_dir]
    for fn in sorted(os.listdir(md_dir)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(md_dir, fn), encoding="utf-8") as f:
            txt = f.read()
        if "复制代码" in txt:
            issues.append(f"{fn}: 残留代码复制按钮噪声 '复制代码'")
        if "❨" in txt or "␤" in txt:
            issues.append(f"{fn}: 残留占位符")
        if txt.count("```") % 2 != 0:
            issues.append(f"{fn}: 代码围栏不配对")
    return issues


def _golden_diff(md_dir, golden_dir):
    issues = []
    if not golden_dir or not os.path.isdir(golden_dir):
        return issues
    for fn in sorted(os.listdir(golden_dir)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(golden_dir, fn), encoding="utf-8") as f:
            gold = f.read().splitlines()
        cur_path = os.path.join(md_dir, fn)
        if not os.path.exists(cur_path):
            issues.append(f"{fn}: 缺少对应输出（golden 存在）")
            continue
        with open(cur_path, encoding="utf-8") as f:
            cur = f.read().splitlines()
        diff = [l for l in difflib.unified_diff(gold, cur, lineterm="") if l[:1] in "+-" and l[:2] not in ("++", "--")]
        if diff:
            issues.append(f"{fn}: 与 golden 不一致（{len(diff)} 行差异）")
    return issues


def run_checks(cfg, models, doc, oa_errors, root):
    out = cfg["output"]
    md_dir = os.path.join(root, out["markdown_dir"])
    golden_dir = os.path.join(root, cfg.get("golden_dir", "")) if cfg.get("golden_dir") else None
    env = cfg.get("openapi", {}).get("envelope", {})

    fails, warns = [], []

    # per-endpoint structural invariants
    for m in models:
        tag = f"{m['id']} {m['title']}"
        if not m.get("path"):
            fails.append(f"{tag}: 未解析到请求地址 path")
        if not m.get("method"):
            warns.append(f"{tag}: 未解析到请求方式 method（将用默认值）")
        if not m.get("request") and not m.get("response"):
            fails.append(f"{tag}: 请求与响应表均为空")
        resp_names = {n["name"] for n in m.get("response", [])}
        for key in (env.get("code"), env.get("msg")):
            if key and key not in resp_names:
                warns.append(f"{tag}: 响应缺少统一字段 '{key}'")
        # path {param}s absent from the request table are synthesized as string
        # parameters by build_openapi — surface that, don't let it happen silently
        if m.get("path"):
            req_names = {n["name"] for n in m.get("request", [])}
            synthesized = sorted(set(re.findall(r"\{([^}/]+)\}", m["path"])) - req_names)
            if synthesized:
                warns.append(f"{tag}: path 参数未在文档请求表中定义，"
                             f"OpenAPI 已合成 string 参数: {', '.join(synthesized)}")

    if oa_errors:
        fails.append("OpenAPI 校验失败: " + "; ".join(oa_errors))

    noise = _md_noise(md_dir)
    fails.extend(noise)
    golden = _golden_diff(md_dir, golden_dir)
    warns.extend(golden)

    report = {
        "summary": {
            "pages": len(cfg["pages"]),
            "endpoints": len(models),
            "openapi_valid": not oa_errors,
            "fails": len(fails),
            "warns": len(warns),
        },
        "fails": fails,
        "warns": warns,
        "ok": not fails,
    }
    return report

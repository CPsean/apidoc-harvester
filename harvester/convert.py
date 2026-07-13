"""HTML body -> normalized Markdown.

Hardened against the issues found while building the fadada example:
- preserves code-block indentation; strips copy-button / line-number / flattened duplicate noise
- preserves in-cell hyperlinks, bold, and <br>
- renders nested table fields with depth indentation (full-width spaces)
- demotes accidental/malformed URL anchors to plain text
"""
import re
from . import common

BR = "␤"        # placeholder for <br> in paragraph context -> markdown hard break
CODE_NOISE = ["复制代码", "Copy", "复制"]   # trailing copy-button / line-number noise inside <pre>


def _inline(node, cell=False):
    out = []
    for c in node.children:
        if isinstance(c, str):
            out.append(c)
            continue
        name = c.name
        if name in ("strong", "b"):
            out.append("**" + _inline(c, cell).strip() + "**")
        elif name in ("em", "i"):
            out.append("*" + _inline(c, cell).strip() + "*")
        elif name == "a":
            href = c.get("href", "") or ""
            txt = c.get_text()
            if txt.strip().startswith("http") or '"' in href or " " in href or not href:
                out.append(txt)                       # bare/malformed URL anchor -> plain text
            else:
                out.append("[%s](%s)" % (txt.strip(), href))
        elif name == "code":
            out.append("`" + c.get_text() + "`")
        elif name == "br":
            out.append("<br>" if cell else BR)
        elif name == "img":
            out.append("![%s](%s)" % (c.get("alt", ""), c.get("src", "")))
        else:
            out.append(_inline(c, cell))
    return "".join(out)


def _para(node):
    t = _inline(node, cell=False)
    t = re.sub(r"\s*" + BR + r"\s*", BR, t).strip().strip(BR).strip()
    return t.replace(BR, "  \n")


def _cell(td):
    raw = _inline(td, cell=True).replace(common.NBSP, " ")
    raw = re.sub(r"\s*<br>\s*", "<br>", raw)
    raw = re.sub(r"[ \t]+", " ", raw).strip()
    return raw.replace("|", "\\|")


def _first_cell(td, unit, nest_prefix=None):
    depth, name = common.indent_depth(td.get_text(), unit, nest_prefix)
    return common.FW * depth + name.replace("|", "\\|")


def _table(tb, unit, nest_prefix=None):
    matrix = []
    for tr in tb.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        row = []
        for i, td in enumerate(tds):
            if i == 0 and td.name != "th":
                row.append(_first_cell(td, unit, nest_prefix))
            else:
                row.append(td.get_text().strip().replace("|", "\\|") if td.name == "th" else _cell(td))
        matrix.append(row)
    if not matrix:
        return ""
    ncol = max(len(r) for r in matrix)
    for r in matrix:
        r += [""] * (ncol - len(r))
    lines = ["| " + " | ".join(matrix[0]) + " |", "| " + " | ".join(["---"] * ncol) + " |"]
    for r in matrix[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _pre(node):
    txt = common.code_text(node)
    return "```\n" + txt.rstrip("\n") + "\n```"


def _walk(node, unit, nest_prefix=None, skip_first_h1=None):
    parts = []
    for c in node.children:
        if isinstance(c, str):
            if c.strip():
                parts.append(c.strip())
            continue
        n = c.name
        if n in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = c.get_text().strip()
            if (
                n == "h1"
                and skip_first_h1
                and not skip_first_h1["done"]
                and text == skip_first_h1["title"]
            ):
                skip_first_h1["done"] = True
                continue
            parts.append("#" * int(n[1]) + " " + text)
        elif n == "p":
            t = _para(c)
            if t:
                parts.append(t)
        elif n == "pre":
            parts.append(_pre(c))
        elif n in ("ul", "ol"):
            items, idx = [], 1
            for li in c.find_all("li", recursive=False):
                pre = (str(idx) + ". ") if n == "ol" else "- "
                items.append(pre + _para(li))
                idx += 1
            parts.append("\n".join(items))
        elif n == "table":
            parts.append(_table(c, unit, nest_prefix))
        elif n == "img":
            parts.append("![%s](%s)" % (c.get("alt", ""), c.get("src", "")))
        elif n == "blockquote":
            parts.append("\n".join("> " + l for l in _para(c).split("\n")))
        else:
            sub = _walk(c, unit, nest_prefix, skip_first_h1)
            if sub.strip():
                parts.append(sub)
    return "\n\n".join(p for p in parts if p.strip())


def to_markdown(body, title, time, source_url, unit=4, nest_prefix=None):
    head = "# " + title + "\n\n"
    meta = []
    if time:
        meta.append("> " + time)
    if source_url:
        meta.append("> 来源：" + source_url)
    head += ("  \n".join(meta) + "\n\n") if meta else ""
    skip = {"title": title.strip(), "done": False}
    md = head + _walk(body, unit, nest_prefix, skip)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"

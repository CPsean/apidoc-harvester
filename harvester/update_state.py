"""Incremental update state helpers for page-harvesting runs."""
import hashlib
import json
import os

from . import __version__

STATE_VERSION = 1
STATE_FILENAME = ".harvest-state.json"


def state_path(root, out):
    """Place state beside the site output artifacts, normally out/<site>/."""
    md_parent = os.path.dirname(os.path.join(root, out["markdown_dir"]))
    return os.path.join(md_parent, STATE_FILENAME)


def load(path):
    if not os.path.exists(path):
        return {"version": STATE_VERSION, "pages": {}}
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state.get("pages"), dict):
        state["pages"] = {}
    return state


def save(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state = dict(state)
    state["version"] = STATE_VERSION
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def raw_hash(fmt, content):
    h = hashlib.sha256()
    h.update((fmt or "").encode("utf-8"))
    h.update(b"\0")
    h.update((content or "").encode("utf-8"))
    return h.hexdigest()


def transform_fingerprint(cfg):
    """Hash all config inputs that can change Markdown/model output."""
    material = {
        "engine_version": __version__,
        "selectors": cfg.get("selectors", {}),
        "structure": cfg.get("structure", {}),
        "preprocess": cfg.get("preprocess", {}),
        "output": {
            "repair_fences": cfg.get("output", {}).get("repair_fences", False),
        },
    }
    text = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def can_reuse(entry, page, raw_digest, fingerprint, root, md_dir):
    if not entry:
        return False
    if entry.get("raw_hash") != raw_digest:
        return False
    if entry.get("transform_fingerprint") != fingerprint:
        return False
    if entry.get("title") != page.get("title"):
        return False
    if bool(entry.get("api", True)) != bool(page.get("api", True)):
        return False
    filename = entry.get("markdown_filename")
    if not filename or not os.path.exists(os.path.join(md_dir, filename)):
        return False
    if page.get("api", True) and not entry.get("model"):
        return False
    return True

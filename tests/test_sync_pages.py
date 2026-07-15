"""Offline tests for #35 pages_from_tree --sync-pages sidecar (no network)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import yaml

from harvester import config_loader, sync_pages

TREE = {"data": {"nodes": [
    {"id": "n1", "name": "概述", "children": [
        {"id": "n11", "name": "简介", "articleId": "a11", "children": []},
    ]},
    {"id": "n2", "name": "创建合同", "articleId": "a2", "children": []},
]}}

SPEC = {
    "url": "https://docs.example.com/api/tree",
    "root_pointer": "data.nodes",
    "children_pointer": "children",
    "leaf_only": True,
    "page_fields": {"id": "id", "title": "name", "articleId": "articleId"},
    "non_api_ids": ["n11"],
}


class SyncPagesTest(unittest.TestCase):
    def _write_cfg(self, tmp, extra_pages=None):
        cfg = {"pages_from_tree": SPEC}
        if extra_pages is not None:
            cfg["pages"] = extra_pages
        path = os.path.join(tmp, "config", "site.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        return path

    def test_sync_writes_leaf_pages_with_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = self._write_cfg(tmp)
            with mock.patch("harvester.sync_pages.common.fetch_url",
                            return_value=json.dumps(TREE)) as fetched:
                out_path, count = sync_pages.sync(cfg_path)
            fetched.assert_called_once()
            self.assertEqual(count, 2)  # leaf_only: n11 and n2, not the branch n1
            side = yaml.safe_load(open(out_path, encoding="utf-8"))
            ids = [p["id"] for p in side["pages"]]
            self.assertEqual(ids, ["n11", "n2"])
            by_id = {p["id"]: p for p in side["pages"]}
            self.assertEqual(by_id["n2"]["articleId"], "a2")
            self.assertEqual(by_id["n2"]["title"], "创建合同")
            self.assertFalse(by_id["n11"]["api"])   # non_api_ids
            self.assertTrue(by_id["n2"]["api"])

    def test_normal_load_merges_sidecar_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            # inline page overrides the sidecar entry with the same id
            cfg_path = self._write_cfg(tmp, extra_pages=[
                {"id": "n2", "title": "创建合同(改)", "articleId": "a2x", "api": True}])
            with mock.patch("harvester.sync_pages.common.fetch_url",
                            return_value=json.dumps(TREE)):
                sync_pages.sync(cfg_path)
            with mock.patch("harvester.config_loader.common.soup") as never_net:
                cfg = config_loader.load_config(cfg_path)
                never_net.assert_not_called()
            by_id = {p["id"]: p for p in cfg["pages"]}
            self.assertEqual(len(cfg["pages"]), 2)
            self.assertEqual(by_id["n2"]["articleId"], "a2x")  # inline wins

    def test_sync_without_section_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config", "bare.yaml")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump({"site": "x"}, f)
            with self.assertRaises(SystemExit):
                sync_pages.sync(path)


if __name__ == "__main__":
    unittest.main()

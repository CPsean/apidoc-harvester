import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from harvester import pipeline


def _html(title, path):
    return f"""
    <html><body><main>
      <h1>{title}</h1>
      <p>请求地址 {path} 请求方式 GET</p>
      <h2>响应参数</h2>
      <table>
        <tr><th>字段</th><th>类型</th><th>描述</th></tr>
        <tr><td>code</td><td>Integer</td><td>status code</td></tr>
      </table>
    </main></body></html>
    """


class PipelineUpdateTests(unittest.TestCase):
    def _site(self, root, pages):
        os.makedirs(os.path.join(root, "config"), exist_ok=True)
        os.makedirs(os.path.join(root, "html"), exist_ok=True)
        config_path = os.path.join(root, "config", "site.yaml")
        cfg = {
            "site": "update-smoke",
            "acquire": {
                "order": ["static_html"],
                "static_html": {"enabled": True, "html_root": "html"},
            },
            "selectors": {"body": "main", "title": "h1"},
            "structure": {
                "path_regex": r"请求地址\s+(\S+)",
                "method_regex": r"请求方式\s+(GET|POST)",
                "request_section": ["请求参数"],
                "response_section": ["响应参数"],
                "columns": {"name": 0, "type": 1, "desc": 2},
            },
            "pages": pages,
            "openapi": {"title": "Update API"},
            "output": {
                "markdown_dir": "out/update-smoke/markdown",
                "openapi": "out/update-smoke/openapi.yaml",
                "models_json": "out/update-smoke/models.json",
                "report": "out/update-smoke/checks-report.json",
            },
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        return config_path, cfg

    def _write_page(self, root, name, title, path):
        os.makedirs(os.path.join(root, "html"), exist_ok=True)
        with open(os.path.join(root, "html", name), "w", encoding="utf-8") as f:
            f.write(_html(title, path))

    def _read_report(self, root):
        with open(os.path.join(root, "out", "update-smoke", "checks-report.json"),
                  encoding="utf-8") as f:
            return json.load(f)

    def test_first_update_writes_state(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, _ = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])

            report = pipeline.run(cfg_path, update=True)

            self.assertTrue(report["ok"])
            self.assertEqual(report["update"]["added"], ["ping"])
            self.assertTrue(os.path.exists(
                os.path.join(root, "out", "update-smoke", ".harvest-state.json")))

    def test_unchanged_page_reuses_existing_model(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, _ = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])
            pipeline.run(cfg_path, update=True)

            with mock.patch("harvester.pipeline.convert.to_markdown",
                            side_effect=AssertionError("should reuse")):
                report = pipeline.run(cfg_path, update=True)

            self.assertTrue(report["ok"])
            self.assertEqual(report["update"]["unchanged"], ["ping"])

    def test_changed_page_rebuilds_openapi(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, _ = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])
            pipeline.run(cfg_path, update=True)
            self._write_page(root, "ping.html", "Ping", "/v2/ping")

            report = pipeline.run(cfg_path, update=True)

            self.assertEqual(report["update"]["changed"], ["ping"])
            with open(os.path.join(root, "out", "update-smoke", "openapi.yaml"),
                      encoding="utf-8") as f:
                spec = yaml.safe_load(f)
            self.assertIn("/v2/ping", spec["paths"])
            self.assertNotIn("/v1/ping", spec["paths"])

    def test_removed_page_is_stale_and_excluded_from_openapi(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "a.html", "A", "/a")
            self._write_page(root, "b.html", "B", "/b")
            cfg_path, _ = self._site(root, [
                {"id": "a", "title": "A", "file": "a.html"},
                {"id": "b", "title": "B", "file": "b.html"},
            ])
            pipeline.run(cfg_path, update=True)
            cfg_path, _ = self._site(root, [
                {"id": "a", "title": "A", "file": "a.html"},
            ])

            report = pipeline.run(cfg_path, update=True)

            self.assertEqual(report["update"]["stale"], ["b"])
            self.assertTrue(os.path.exists(
                os.path.join(root, "out", "update-smoke", "markdown", "b_B.md")))
            with open(os.path.join(root, "out", "update-smoke", "openapi.yaml"),
                      encoding="utf-8") as f:
                spec = yaml.safe_load(f)
            self.assertIn("/a", spec["paths"])
            self.assertNotIn("/b", spec["paths"])

    def test_api_fetch_failure_still_fails_without_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, _ = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])
            pipeline.run(cfg_path, update=True)
            os.remove(os.path.join(root, "html", "ping.html"))

            report = pipeline.run(cfg_path, update=True)

            self.assertFalse(report["ok"])
            self.assertEqual(report["update"]["fetch_failed"], ["ping"])
            self.assertEqual(report["summary"]["endpoints"], 0)

    def test_transform_fingerprint_change_forces_reprocess(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, cfg = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])
            pipeline.run(cfg_path, update=True)
            cfg["structure"]["required_true_values"] = ["Required"]
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True)

            report = pipeline.run(cfg_path, update=True)

            self.assertEqual(report["update"]["changed"], ["ping"])

    def test_cli_update_writes_update_report(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_page(root, "ping.html", "Ping", "/v1/ping")
            cfg_path, _ = self._site(root, [
                {"id": "ping", "title": "Ping", "file": "ping.html"}])
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            subprocess.run(
                [sys.executable, os.path.join(repo, "run.py"), cfg_path, "--update"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(self._read_report(root)["update"]["added"], ["ping"])


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest

import yaml
from bs4 import BeautifulSoup

from harvester import build_openapi, common, config_loader, convert, extract, fetch, preprocess


class AcceptancePlanTests(unittest.TestCase):
    def test_path_params_are_emitted_and_removed_from_body(self):
        doc = build_openapi.build([
            {
                "id": "auth",
                "title": "Auth",
                "path": "/auth/{id}",
                "method": "GET",
                "summary": "",
                "request": [
                    {"name": "id", "type": "String", "required": True, "desc": "auth id", "children": []},
                    {"name": "detail", "type": "Boolean", "required": False, "desc": "", "children": []},
                ],
                "response": [],
            }
        ], {})
        op = doc["paths"]["/auth/{id}"]["get"]
        self.assertEqual(op["parameters"][0]["name"], "id")
        self.assertEqual(op["parameters"][0]["in"], "path")
        props = op["requestBody"]["content"]["application/json"]["schema"]["properties"]
        self.assertNotIn("id", props)
        self.assertIn("detail", props)
        self.assertEqual(build_openapi.validate(doc), [])

    def test_duplicate_first_h1_is_skipped(self):
        html = "<div><h1>Create App</h1><h1>Other</h1><p>Body</p></div>"
        body = BeautifulSoup(html, "html.parser").div
        md = convert.to_markdown(body, "Create App", "", "")
        self.assertEqual(md.count("# Create App"), 1)
        self.assertIn("# Other", md)

    def test_line_numbered_pre_table_is_cleaned_for_markdown_and_examples(self):
        html = """
        <div>
          <p>请求示例</p>
          <pre><table>
            <tr><td class="ln-numbers">1</td><td class="ln-text">{</td></tr>
            <tr><td class="ln-numbers">2</td><td class="ln-text">  "code": 0</td></tr>
            <tr><td class="ln-numbers">3</td><td class="ln-text">}</td></tr>
          </table></pre>
        </div>
        """
        body = BeautifulSoup(html, "html.parser").div
        md = convert.to_markdown(body, "Example", "", "")
        self.assertIn('{\n  "code": 0\n}', md)
        self.assertNotIn("1{", md)
        self.assertEqual(common.code_after(body, ["请求示例"]), '{\n  "code": 0\n}')

    def test_strip_domain_extracts_openapi_path(self):
        body = BeautifulSoup("<div><p>接口地址 https://api.example.com/a/b 请求方式 GET</p></div>", "html.parser").div
        model = extract.extract_endpoint(body, {"id": "p", "title": "P"}, {
            "path_regex": r"接口地址\s+(\S+)",
            "method_regex": r"请求方式\s+(GET|POST)",
            "strip_domain": True,
            "request_section": [],
            "response_section": [],
            "columns": {"name": 0, "type": 1, "desc": 2},
        })
        self.assertEqual(model["path"], "/a/b")

    def test_pages_from_manifest_and_dir_expand_with_explicit_override(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "config"))
            os.makedirs(os.path.join(root, "html"))
            manifest_path = os.path.join(root, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump([{"id": "a", "title": "Generated A"}, {"id": "b", "title": "Generated B"}], f)
            with open(os.path.join(root, "html", "c.html"), "w", encoding="utf-8") as f:
                f.write("<html><h1>Dir C</h1></html>")
            config_path = os.path.join(root, "config", "site.yaml")
            cfg = {
                "site": "x",
                "pages_from_manifest": "manifest.json",
                "pages_from_dir": "html",
                "acquire": {"static_html": {"enabled": True, "html_root": "."}},
                "selectors": {"title": "h1"},
                "pages": [{"id": "a", "title": "Explicit A"}],
            }
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f)
            loaded = config_loader.load_config(config_path)
        pages = {p["id"]: p for p in loaded["pages"]}
        self.assertEqual(pages["a"]["title"], "Explicit A")
        self.assertEqual(pages["b"]["title"], "Generated B")
        self.assertEqual(pages["c"]["title"], "Dir C")

    def test_table_normalizer_adds_parent_depth_indent(self):
        html = """
        <table>
          <tr><th>name</th><th>type</th><th>required</th><th>desc</th></tr>
          <tr onclick="toggle(event, 1)"><td>parent</td><td>Object</td><td>是</td><td></td></tr>
          <tr parentid="1" onclick="toggle(event, 2)"><td>child</td><td>String</td><td>否</td><td></td></tr>
        </table>
        """
        out = preprocess.apply(html, {"table_normalizer": {"enabled": True, "indent_unit": 4}})
        soup = BeautifulSoup(out, "html.parser")
        child = soup.find_all("tr")[2].find("td").get_text()
        self.assertTrue(child.startswith(common.NBSP * 4))

    def test_js_bundle_strategy_extracts_configured_record(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "bundle.js")
            with open(bundle, "w", encoding="utf-8") as f:
                f.write('docs.push({id:"p1",title:"Page 1",html:"<div>hello</div>"});')
            cfg = {
                "site": "bundle-test",
                "acquire": {
                    "order": ["js_bundle"],
                    "js_bundle": {
                        "enabled": True,
                        "bundle_urls": ["bundle.js"],
                        "record_regex": r'id:"(?P<id>[^"]+)".*?title:"(?P<title>[^"]+)".*?html:"(?P<content>[^"]+)"',
                    },
                },
            }
            raw = fetch.acquire({"id": "p1"}, cfg, root)
        self.assertEqual(raw["format"], "html")
        self.assertEqual(raw["content"], "<div>hello</div>")

    def test_js_bundle_object_regex_extracts_configured_fields(self):
        text = 'docs={id:"p2",title:"Page 2",html:"<section>ok</section>"};'
        records = fetch._records_from_bundle(text, {
            "object_regex": r"\{[^{}]+html:[^{}]+\}",
            "id_field": "id",
            "title_field": "title",
            "content_field": "html",
        })
        self.assertEqual(records["p2"]["title"], "Page 2")
        self.assertEqual(records["p2"]["content"], "<section>ok</section>")


if __name__ == "__main__":
    unittest.main()

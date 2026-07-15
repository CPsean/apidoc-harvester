"""Offline tests for #31 safe_filename, #32 repair_fences, #33 path "/" prefix,
#34 markdown-format endpoint extraction."""
import unittest

from harvester import build_openapi, checks, common, pipeline

MD_ENDPOINT = """# 创建草稿

请求地址：/api/v5/draft/create
请求方式：POST

## 请求参数

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| draft | object | 是 | 草稿 |
| +name | string | 是 | 名称 |
| ++ext | string | 否 | 扩展 |

## 响应结果

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| code | string | 是 | 状态码 |

## 响应示例

```json
{"code": "0"}
```
"""

STRUCT = {
    "path_regex": r"请求地址[:：]\s*([^\s<）)]+)",
    "method_regex": r"请求方式[:：]\s*(GET|POST|PUT|DELETE|PATCH)",
    "request_section": ["请求参数"],
    "response_section": ["响应结果"],
    "example_response_section": ["响应示例"],
    "required_true_values": ["是"],
    "columns": {"name": 0, "type": 1, "required": 2, "desc": 3},
    "nested_indent_unit": 4,
    "nest_prefix": "+",
}


class SafeFilenameTest(unittest.TestCase):
    def test_illegal_chars_and_tab(self):
        self.assertEqual(common.safe_filename("a\tb<c>:d/e"), "a_b_c__d_e")

    def test_trailing_dots_spaces_and_reserved(self):
        self.assertEqual(common.safe_filename("title. "), "title")
        self.assertTrue(common.safe_filename("CON.notes").startswith("_"))

    def test_length_cap_and_chinese_passthrough(self):
        self.assertEqual(len(common.safe_filename("x" * 300)), 150)
        self.assertEqual(common.safe_filename("01_查询应用信息"), "01_查询应用信息")


class RepairFencesTest(unittest.TestCase):
    def test_opt_in_repairs_and_warns(self):
        warns = []
        md = pipeline._maybe_repair_fences("x\n```json\n{}", "f.md", True, warns)
        self.assertEqual(md.count("```") % 2, 0)
        self.assertEqual(warns, ["fence repaired: f.md"])

    def test_default_off_untouched(self):
        warns = []
        md = pipeline._maybe_repair_fences("x\n```json\n{}", "f.md", False, warns)
        self.assertEqual(md, "x\n```json\n{}")
        self.assertEqual(warns, [])


class PathSlashTest(unittest.TestCase):
    def test_build_prefixes_and_checks_warns(self):
        models = [{"id": "01", "title": "t", "path": "DescribeBillUsage",
                   "method": "POST", "request": [], "response": [{"name": "code"}],
                   "summary": ""}]
        doc = build_openapi.build(models, {})
        self.assertIn("/DescribeBillUsage", doc["paths"])
        self.assertNotIn("DescribeBillUsage", doc["paths"])
        report = checks.run_checks(
            {"output": {"markdown_dir": "tests"}, "pages": [], "openapi": {}},
            models, doc, [], ".")
        self.assertTrue(any("缺少前导" in w for w in report["warns"]))
        # models.json input stays raw — faithful harvest
        self.assertEqual(models[0]["path"], "DescribeBillUsage")


class MarkdownExtractionTest(unittest.TestCase):
    def test_md_body_extracts_endpoint(self):
        from harvester import extract
        body = pipeline._md_body(MD_ENDPOINT)
        m = extract.extract_endpoint(body, {"id": "01", "title": "创建草稿"}, STRUCT)
        self.assertEqual(m["path"], "/api/v5/draft/create")
        self.assertEqual(m["method"], "POST")
        draft = m["request"][0]
        self.assertEqual(draft["name"], "draft")
        self.assertEqual(draft["children"][0]["name"], "name")
        self.assertEqual(draft["children"][0]["children"][0]["name"], "ext")
        self.assertEqual(m["example_response"], {"code": "0"})


if __name__ == "__main__":
    unittest.main()

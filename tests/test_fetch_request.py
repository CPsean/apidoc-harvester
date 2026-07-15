"""Offline tests for fetch request construction (#28 URL quoting, #29 env headers,
#30 POST body_template). No network — everything goes through the pure
fetch._build_request."""
import json
import os
import unittest

from harvester import fetch


class QuoteUrlTest(unittest.TestCase):
    def test_non_ascii_and_spaces_encoded(self):
        url, _, _, _ = fetch._build_request(
            {"id": "01", "doc_id": "文 档/a b"},
            {"url_template": "https://x.example.com/api/{doc_id}?v=1"})
        self.assertIn("%E6%96%87%20%E6%A1%A3/a%20b", url)
        self.assertTrue(url.startswith("https://x.example.com/api/"))
        self.assertIn("?v=1", url)

    def test_already_encoded_not_double_encoded(self):
        url = fetch._quote_url("https://x/a%20b?q=1")
        self.assertEqual(url, "https://x/a%20b?q=1")


class EnvHeaderTest(unittest.TestCase):
    def setUp(self):
        os.environ["SELFTEST_TOK"] = "s3cret"
        os.environ.pop("SELFTEST_MISSING", None)

    def tearDown(self):
        os.environ.pop("SELFTEST_TOK", None)

    def test_env_resolved(self):
        _, _, headers, _ = fetch._build_request(
            {"id": "01"},
            {"url_template": "https://x/{doc_id}",
             "headers": {"Authorization": "Bearer ${SELFTEST_TOK}"}})
        self.assertEqual(headers["Authorization"], "Bearer s3cret")

    def test_missing_var_errors_without_leaking(self):
        with self.assertRaises(RuntimeError) as ctx:
            fetch._build_request(
                {"id": "01"},
                {"url_template": "https://x/{doc_id}",
                 "headers": {"Cookie": "${SELFTEST_MISSING}"}})
        self.assertIn("SELFTEST_MISSING", str(ctx.exception))
        self.assertNotIn("s3cret", str(ctx.exception))


class BodyTemplateTest(unittest.TestCase):
    def setUp(self):
        os.environ["SELFTEST_TOK"] = "va{lu}e"

    def tearDown(self):
        os.environ.pop("SELFTEST_TOK", None)

    def test_post_body_built(self):
        url, method, headers, data = fetch._build_request(
            {"id": "01", "articleId": "A1"},
            {"url_template": "https://x/search", "method": "POST",
             "body_template": {"aid": "{articleId}", "tok": "${SELFTEST_TOK}",
                               "page": 1}})
        self.assertEqual(method, "POST")
        self.assertEqual(headers["Content-Type"], "application/json")
        body = json.loads(data.decode("utf-8"))
        # env value containing braces survives the two-stage templating
        self.assertEqual(body, {"aid": "A1", "tok": "va{lu}e", "page": 1})

    def test_get_ignores_body_template(self):
        _, method, headers, data = fetch._build_request(
            {"id": "01"},
            {"url_template": "https://x/{doc_id}",
             "body_template": {"a": "b"}})
        self.assertEqual(method, "GET")
        self.assertIsNone(data)
        self.assertNotIn("Content-Type", headers)


if __name__ == "__main__":
    unittest.main()

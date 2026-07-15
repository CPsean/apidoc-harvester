# Writing a site config

A site config is the ONLY file you write to support a new API-doc site. Copy
`config/_template.yaml` to `config/<site>.yaml` and fill these in.
`config/fadada.yaml` is a full worked example.

## spec_import — if an official spec exists, use it (cheapest, best)
Before configuring page scraping, check whether the API already publishes an
OpenAPI/Swagger spec (GitHub, a `/openapi.json`, a docs "download spec" link). If so,
write a **spec-mode** config (no `pages`/`acquire`/`selectors` needed):

```yaml
site: <name>
spec_source:
  url: "https://.../swagger.json"   # or  file: "specs/foo.json"
  format: auto                      # auto | swagger2 | openapi3
  convert_to: openapi3              # none (keep native) | openapi3 (npx swagger2openapi)
  normalize: false                  # true: deterministic lint-fix of sloppy vendor specs
output:
  openapi: "out/<name>/openapi.yaml"
  report:  "out/<name>/checks-report.json"
```

`run.py` detects `spec_source` and ingests the spec directly: download → optional
Swagger 2.0→OpenAPI 3.0 conversion (needs Node.js/`npx`) → optional normalize →
validate (ALL errors, bucketed with counts) → emit. The report carries `paths`,
`operations`, `kind`, `converted`, `normalized`, `normalize_fixes`. Worked examples:
`config/docusign-esign.yaml` (Docusign eSignature, Swagger 2.0, 213 paths) and
`config/adobesign.yaml` (Adobe Acrobat Sign, self-declared 3.1 with 1155 lint
errors, green after `normalize: true`). Only fall through to page scraping below
when there is no published spec.

For a human-readable view of any emitted `openapi.yaml` (this path produces no
Markdown), generate a self-contained HTML page beside it:
`npx -y @redocly/cli build-docs out/<name>/openapi.yaml -o out/<name>/openapi.html`
(details and the Scalar try-it alternative are in SKILL.md step 6).

`normalize: true` applies mechanical rules only — it never invents content:
missing required strings (response `description`, oauth2 flow `tokenUrl`) are
filled with `""`; invalid type spellings (`int`/`long`/`float`/`double`/`date`/
`dateTime`/`bool`) map to canonical type+format; component names violating
`^[a-zA-Z0-9._-]+$` are sanitized with every `$ref` rewritten; non-standard keys
in `info` move to `x-` extensions; boolean `required` inside schemas (a
Swagger2-ism) is dropped. Every fix is counted in the report's warns. Dangling
`$ref`s already present in the source are surfaced as a warn but faithfully
preserved, not repaired. If validation still fails with rules normalize doesn't
cover, that's a new failure signal: extend `_normalize` in
`harvester/spec_import.py` (keep it deterministic), don't hand-edit the spec.

## acquire — pick the cheapest that works
- `content_api` (best): a backend endpoint returning the doc body. Discover once via
  the browser DevTools → Network tab: load a doc page, find the XHR/fetch that returns
  the article (markdown, or JSON containing it), and record the URL shape, where the
  `{doc_id}` goes, and the JSON path to the content. Set `url_template`,
  `content_pointer`, `content_is`, `enabled: true`. After this, no browser is needed.
  - `url_template` is formatted with the page's keys: `{doc_id}` aliases `doc_id`/`id`
    for single-id sites; if the endpoint needs several ids, give each page those keys
    (e.g. `nodeId`, `articleId`) and reference them as `{nodeId}/{articleId}`.
  - `headers`: optional per-site request headers. Some gateways return 403 unless an
    XHR marker / version header is present (e.g. `X-Requested-With: XMLHttpRequest`).
    Values may embed `${ENV_VAR}` — resolved from the environment at fetch time, so
    login cookies/tokens stay out of the config file (missing var = hard error naming
    the variable; resolved values are never printed). URLs are percent-encoded
    automatically (Chinese ids in `url_template` fields are safe).
  - `body_template`: for `method: POST/PUT` content APIs (search/pagination style) —
    a JSON object; string values get the same `{page-field}` templating as
    `url_template` plus `${ENV_VAR}` interpolation; sent as `application/json`.
  - For SPA portals, the real API host is often different from the doc host — check the
  JS bundle's baseURL map. `config/fadada-dev.yaml` is a worked content_api example.
- `js_bundle`: static extraction from one or more SPA JavaScript bundles when the
  docs have no content API and the article HTML is embedded in webpack output. This
  strategy never executes JavaScript. Configure `bundle_urls` plus either a
  `record_regex` with named groups `id` and `content` (`title` optional), or an
  `object_regex` plus `id_field` / `title_field` / `content_field`. Each page is
  matched by `page_id_field` (default `doc_id`, falling back to `id`); the record's
  content is treated as `content_is` (html | markdown). Remote bundles are cached
  under `cache_dir` (default `out/<site>/_bundle_cache`) so re-runs are offline.
  Pages still come from explicit `pages`, `pages_from_manifest`, or `pages_from_dir`.
- `static_html`: point `html_root` at a folder of pre-downloaded `.html`; give each
  page a `file`.
- `rendered`: headless browser (needs `pip install playwright && playwright install
  chromium`). Only when content is truly JS-computed with no fetchable source.

## selectors — locate the content in one page's HTML
`title`, `time` (optional), `body`. Inspect one page; pick stable CSS selectors for the
article title, the "updated" timestamp, and the main content container.

## structure — how an API page is laid out
- `path_regex` / `method_regex`: capture the endpoint path and HTTP method from the body
  text. Add your site's wording as alternations.
- `strip_domain: true`: opt-in helper for docs that print full URLs such as
  `https://{host}/v1/foo`; OpenAPI paths will emit only `/v1/foo`.
- `request_section` / `response_section`: the heading text that precedes the parameter
  and response tables (a list — include all variants the site uses).
- `columns`: 0-based positions of name/type/required/desc columns in those tables.
  If request and response tables use different layouts, set `request_columns` and/or
  `response_columns`; either one falls back to `columns` when omitted. Omit
  `required` for 3-column tables.
- `required_true_values`: strings in the "required" column that mean true.
- `nested_indent_unit`: how many leading nbsp / full-width spaces equal one nesting
  level for tree-structured response fields. Inspect a nested table to measure it.
- `nest_prefix`: opt-in alternative nesting notation — each leading occurrence of this
  string on a field name (e.g. `+` in `+appStatus`, `++subField`) adds one nesting
  level and is stripped from the name. Unset keeps indent-only behavior.
- `section_match: regex`: opt-in when section headings carry numbering or prefixes
  (e.g. `2. 输入参数`) that defeat the default exact/startswith matching — every
  `*_section` marker (request/response/example) is then an `re.search` pattern,
  e.g. `'^\d+[.、]?\s*请求参数'`. Default `exact` is the historical behavior.

## pages
List each page. `static_html` needs `file`; `content_api`/`rendered` need `doc_id`.
Mark overview/non-endpoint pages `api: false` (converted to markdown, skipped for OpenAPI).
For large sites, generate the list with `pages_from_manifest` (JSON manifest) or
`pages_from_dir` (scan a local HTML directory and extract titles with a selector).
Generated pages are merged first; explicit `pages` override matching ids.

- `pages_from_manifest`: a bare path, or `{path, items_key, id_field, title_field,
  file_field, doc_id_field, api_default, non_api_ids}`. Prefer naming the manifest's
  list field with `items_key`; without it the loader probes `pages`/`items`/`docs`/
  `data`, then treats a dict as an id→item map. The `*_field` options map manifest
  fields onto the page keys `id`/`title`/`file`/`doc_id`. `non_api_ids` forces
  `api: false` for the listed ids; `api_default` sets everything else.
- `pages_from_dir`: `{path, pattern, recursive, file_base, title_selector,
  api_default, non_api_ids}`. Scans `path` for files ending in `pattern` (default
  `.html`), derives each page's `file` relative to `file_base` (default:
  `acquire.static_html.html_root`) and its title via `title_selector` (default:
  `selectors.title`, falling back to the filename).
- `pages_from_tree`: for sites with a tree/menu API (`/document/nodes`, leftMenu,
  sidebar JSON). `{url, headers, root_pointer, children_pointer, leaf_only,
  page_fields, api_default, non_api_ids}` — `page_fields` maps page keys onto tree
  fields (map a stable tree id onto `id`; the ordinal fallback shifts when nodes
  are inserted). Unlike the two loaders above, this one is **not** applied at run
  time: `python run.py config/<site>.yaml --sync-pages` fetches the tree once and
  writes a `config/<site>.pages.yaml` sidecar; normal runs merge that file
  (inline `pages:` win by id) and never hit the tree API — tree changes land as a
  reviewable git diff, and runs stay deterministic.

## preprocess
`preprocess.table_normalizer.enabled: true` normalizes tree tables before Markdown
conversion and OpenAPI extraction. The default mode handles `parentid` /
`onclick="toggle(...)"` / `colspan` wrappers; row ids come from the `id_attr`
attribute, or are pulled out of `toggle_attr` with `row_id_regex` (group 1 = id).
For VitePress-style tables that carry nesting in row attributes, set
`nesting_mode: data_level` and optionally `level_attr: data-level`. `indent_unit`
controls how many nbsp per level the normalizer writes (match
`structure.nested_indent_unit`); tables matching any `skip_patterns` regex are left
untouched. Keep preprocessing off unless a site's tables are structurally
unreadable by the standard `columns` + `nested_indent_unit` rules.

## openapi
`title`, `version`, `servers` (use a `{host}` variable if the docs don't publish a fixed
host), `envelope` (the unified `{code,msg,data}` wrapper field names, or `{}` if none),
and `security_headers` (common auth headers → apiKey securitySchemes).

## Tips
- Run, then read `out/<site>/checks-report.json`; let the failures tell you which field
  above is wrong (the loop runbook has a signal→fix table).
- When output looks right, freeze a couple of pages into `golden/<site>/` so future runs
  catch regressions.

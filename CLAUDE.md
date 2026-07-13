# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is the **apidoc-harvester skill repository** — a Claude Code skill that harvests
API documentation sites into clean Markdown + a validated OpenAPI 3.1 spec. The
repository is directly installable as a skill because `SKILL.md` lives at the root, and
the runnable engine also lives at the root.

Layout:
- `SKILL.md` — the skill entry point: trigger description (frontmatter) + workflow.
- `run.py`, `harvester/`, `config/`, `runbook/`, `CHANGELOG.md` — the runnable engine.
- `references/config-guide.md` — how to fill a site config; loaded on demand by the skill.
- `evals/` — declarative test cases: `trigger-evals.json` (should the skill fire for a
  query?) and `evals.json` (behavioral assertions). No runner in this repo; they're consumed
  by external skill-eval tooling.

## Commands

The engine is plain Python (no build, no lint config, no test suite in this repo):

```bash
pip install -r requirements.txt          # beautifulsoup4, PyYAML, openapi-spec-validator
python run.py config/fadada.yaml         # run one site's pipeline
```

Output lands in `out/<site>/`: `markdown/`, `models.json`, `openapi.yaml`,
`checks-report.json`. Exit code 0 iff the checks report is `ok`. `playwright` is only
needed for the `rendered` acquisition strategy; Node.js/`npx` only for
`spec_import` with Swagger 2.0→3.0 conversion (`npx swagger2openapi`).

The fastest end-to-end smoke test is a `spec_import` config (no page scraping):
`python run.py config/docusign-esign.yaml`.

## Architecture

**Core philosophy: script the deterministic parts; reserve the model for judgment.**
Fetching, HTML→Markdown, table→schema, schema→OpenAPI, and validation are all
deterministic scripts. The model's job (via the skill) is only to *build/improve* those
scripts, discover content endpoints, and do semantic work (enum refinement, resolving doc
contradictions).

**Engine is generic; each site is one YAML config.** Everything site-specific — CSS
selectors, path/method regexes, section headings, table column order, indent unit,
acquisition strategy — lives in `config/<site>.yaml` (start from `config/_template.yaml`).
Never hardcode site behavior into `harvester/*.py`; if a new site needs something the
config can't express, extend the config schema and keep the script generic.

**Acquisition ladder** (cheapest first, tried in `acquire.order`; `run.py` dispatches):
1. `spec_import` — config has `spec_source`: download an official OpenAPI/Swagger spec,
   optionally convert 2.0→3.0, validate, done. Skips the whole page pipeline.
2. `content_api` — the backend endpoint the doc SPA fetches its body from. Discovered
   once via browser Network tab (procedure in `runbook/LOOP.md`); after that the pipeline
   is plain HTTP. Supports custom `headers` and multi-id URL templates.
3. `static_html` — pre-downloaded HTML files.
4. `rendered` — Playwright headless browser, last resort.

**Page pipeline** (`harvester/pipeline.py` orchestrates):
```
fetch.py → convert.py → extract.py → build_openapi.py → checks.py
 raw page   Markdown     endpoint      OpenAPI 3.1 +      invariants +
                         models        validator          golden diff → checks-report.json
```
- `common.py` holds shared parsing (page body/title/time extraction, `indent_depth` for
  deriving field-nesting from indentation).
- Pages marked `api: false` are converted to Markdown but skipped for OpenAPI; their
  fetch failures are warnings, not errors.
- `build_openapi.py` deliberately does **not** auto-guess enums from prose — values stay
  in `description`; enum refinement is an optional model-assisted follow-up.

**Self-improving loop** — `checks-report.json` drives iteration: classify each failure
with the signal→fix table in `runbook/LOOP.md` (it maps failure signals to the exact
config field or script function to change), make the minimal fix (config first, script
only if needed), re-run. Never hand-edit output artifacts.

## Conventions when changing the engine

- Every behavioral change to a converter/extractor gets one appended line in
  `CHANGELOG.md` in the established format: failure signal → what changed
  where. This file is the loop's memory; entries are numbered and never rewritten.
- `golden/<site>/` holds frozen verified Markdown as a snapshot regression guard. If a
  converter change alters output, decide explicitly: improvement → update golden;
  regression → fix the script.
- Config examples double as documentation: `fadada.yaml` (static_html, full worked
  example), `fadada-dev.yaml` (content_api with auth headers + multi-id template),
  `docusign-esign.yaml` (spec_import). Keep them runnable and referenced from
  SKILL.md/config-guide when adding capabilities.
- If you change what the skill does or when it should trigger, update the SKILL.md
  frontmatter description **and** the corresponding cases in `evals/trigger-evals.json`
  / `evals.json` together.
- Harvest faithfully: preserve documentation inconsistencies (typos, examples that
  disagree with tables) and surface them, rather than silently "fixing" them.

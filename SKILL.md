---
name: apidoc-harvester
description: >-
  Harvest API documentation pages into clean Markdown and a validated OpenAPI 3.1
  spec, using a config-driven, self-improving pipeline. Use this whenever the user
  wants to scrape, extract, mirror, or archive API reference docs; convert API doc
  pages (especially JavaScript-rendered / SPA doc sites where plain fetch returns an
  empty shell) into Markdown; reverse-engineer or generate an OpenAPI / Swagger spec
  from documentation; build a local searchable copy of an API's docs; or set up a
  repeatable, low-cost doc-extraction pipeline across one or many doc sites. Trigger
  even when the user only says things like "pull these API doc pages", "turn this API
  doc into OpenAPI", "grab the docs for X API", or "keep our local copy of these docs
  in sync" — don't wait for them to name OpenAPI or scraping explicitly. Also use when
  maintaining or improving a harvester pipeline / its configs, or to ingest an
  already-published OpenAPI/Swagger spec directly (the cheapest path). Do not use for
  general non-API-doc web scraping.
---

# apidoc-harvester

Turn "scrape API doc pages → clean Markdown → validated OpenAPI 3.1" into a
**config-driven, self-improving** pipeline. The engine is generic; each site is just
a YAML config. The loop lets the pipeline get better at new sites over time.

## Core philosophy — script the deterministic parts, reserve the model for judgment

The expensive, flaky path is "drive a browser + ask the model to read every page".
Avoid it. Two ideas do almost all the work:

1. **Cheapest acquisition that works.** Doc content is almost always fetched by the
   page from a backend endpoint. Find that endpoint ONCE and the whole pipeline becomes
   a plain HTTP script — no browser, no model. Strategies, cheapest first:
   `spec_import` (an already-published OpenAPI/Swagger spec — the source of truth, best
   of all; download + validate + optional Swagger 2.0→3.0 convert + optional
   `normalize: true` deterministic lint-fix for sloppy vendor specs) → `content_api`
   (direct JSON/HTML/markdown endpoint) → `js_bundle` (explicit, static extraction from
   SPA bundles; no JS execution) → `static_html` (pre-downloaded files) → `rendered`
   (headless browser, last resort). Always check for a published spec first.
2. **Deterministic transform, not model transform.** HTML→Markdown, table→schema,
   schema→OpenAPI, and validation are all scripts. The model is only needed to
   *build/improve those scripts*, discover the content endpoint, resolve documentation
   contradictions, refine enum semantics, and produce judgment artifacts (e.g. diagrams).

## Repository model — this repo is both the skill and the engine

This repository is directly installable as a standard skill: `SKILL.md` is at the
repository root, and the runnable engine lives beside it in `run.py`, `harvester/`,
`config/`, and `runbook/`. Treat engine changes as normal repository changes so they
remain versioned, reviewable, and reversible.

**Hard rules:**
- Prefer editing the source repository under `repos/apidoc-harvester/`, then copy or
  install it explicitly into the target agent environment.
- **Before changing any engine script (`harvester/*.py`) or a site config, show the
  user a diff and get an explicit OK.** These are the user's long-lived code; treat
  edits as proposals, not faits accomplis. Per-run config authoring for a brand-new
  site is fine to do directly, but still summarize what you set.

## Workflow

### 1. Locate the engine repository
Look for an `apidoc-harvester/` project in the user's connected working folder
(in this workspace, `repos/apidoc-harvester/`). Install deps:
`pip install -r requirements.txt --break-system-packages`
(Needs: beautifulsoup4, PyYAML, openapi-spec-validator; playwright only for `rendered`.)

### 2. Configure the target site
Copy `config/_template.yaml` → `config/<site>.yaml` and fill it in. `config/fadada.yaml`
is a complete worked example. Prefer discovering a `content_api` (one-time, via the
browser Network tab — procedure in `runbook/LOOP.md`). If that's not
available, use `js_bundle` for static bundle-embedded docs, `static_html` (point at
downloaded HTML), or enable `rendered`.

### 3. Run
`python run.py config/<site>.yaml` → writes `out/<site>/{markdown/, models.json,
openapi.yaml, checks-report.json}`.

### 4. Evaluate and iterate (the loop)
Read `out/<site>/checks-report.json`. If `ok` is false, classify each failure with the
"signal → where to fix" table in `runbook/LOOP.md`, propose the **minimal**
change to a script or the config, **show the diff, get the user's OK**, apply, and re-run.
Repeat until green and stable. Read the loop runbook before your first fix — it explains
the classification and the one-time content-api discovery.

### 5. Converge and record
When output is green and stable, freeze the verified Markdown into `golden/<site>/`
(snapshot regression guard) and append one line to `CHANGELOG.md` describing the
signal→fix. This is the loop's memory; future improvements append here.

### 6. Deliver
Hand the user `out/<site>/openapi.yaml` (3.1, validator-passing), the Markdown set, and
`models.json`. Note any documentation inconsistencies you preserved rather than silently
"fixed" (e.g. field typos, examples that disagree with tables).

## What the generated OpenAPI does and doesn't do
The builder maps types, required flags, nested objects, the response envelope, and
security headers deterministically. It **does not auto-guess enums** from prose (it keeps
the values in `description`) — enum refinement is left to a model-assisted pass so the
baseline stays accurate. Offer that refinement as an optional follow-up.

## Reference files
- `runbook/LOOP.md` — the self-improving loop: signal→fix table, content-api
  discovery, when to escalate to the model, scheduling for drift detection. Read this before iterating.
- `references/config-guide.md` — how to fill a site config (selectors, structure, acquisition).
- `README.md` — engine architecture and module responsibilities.
- `config/fadada.yaml` — complete worked example (法大大 合同起草, 11 endpoints).

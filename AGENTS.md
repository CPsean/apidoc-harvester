# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this repo is

This is the **apidoc-harvester skill repository** — a Codex skill that harvests
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

## Engine copy/update discipline

When the skill is invoked, treat the current skill copy as the highest-version engine
source. If work runs from a target workspace that already contains a copied engine,
refresh only engine-owned system files before execution:

- `run.py`
- `harvester/`
- `runbook/`
- `references/`
- `requirements.txt`
- `config/_template.yaml`

Preserve user-owned project files unless the user explicitly asks for migration or
cleanup:

- `config/<site>.yaml`
- `out/`
- `golden/`
- downloaded HTML or raw documentation material

Reuse `harvester.__version__` as the single engine version source. `python run.py
--version` reports the copied engine version that will execute; use it when checking
whether a workspace is still running an old engine after the skill itself was updated.

## Accepted bug self-repair loop

When the user accepts a customer-reported BUG, treat that as approval to repair the
confirmed bug end to end without waiting for another implementation prompt. Do not treat
accepted BUGs as approval for unrelated enhancements.

Use this loop:
1. Restate the concrete failure in repo terms, ignoring customer wording that is noisy
   or speculative.
2. Classify the item:
   - **Bug**: crash, invalid output, lost documented content, broken existing behavior,
     or misleading success.
   - **Enhancement**: new configuration surface, broader site support, convenience
     behavior, or policy change. Discuss expected skill benefit before implementing.
3. Reproduce the bug with the smallest local fixture or config possible. If direct
   reproduction is impossible, add a focused regression fixture that captures the
   observed shape.
4. Add or update a failing test before the fix whenever practical:
   - `pipeline.py` / output writing changes need an end-to-end smoke test.
   - `convert.py` changes need HTML fragment → Markdown assertions.
   - `preprocess.py` changes need raw table HTML → normalized table assertions.
   - `extract.py` changes need Markdown/table → endpoint/model assertions.
   - `build_openapi.py` changes need model/endpoint → OpenAPI assertions.
5. Make the smallest generic fix:
   - Prefer config changes for site-specific variation.
   - Extend config schema only when the behavior can apply to multiple doc sites.
   - Change engine code only for generic behavior or clear correctness bugs.
   - Never hardcode one customer's selectors, paths, or examples into `harvester/*.py`.
6. Preserve docs faithfully. Do not silently "correct" vendor typos, inconsistent
   examples, or contradictory tables; keep them visible in Markdown/check output.
7. Update the project memory:
   - Append one numbered `CHANGELOG.md` line for converter/extractor/preprocessor or
     pipeline behavior changes.
   - Update `config/_template.yaml` and `references/config-guide.md` when a config
     capability changes.
   - Update `SKILL.md` and eval files only when trigger behavior or skill workflow
     changes.
8. Run the narrow test first, then the relevant smoke test. At minimum run
   `python -m unittest tests.test_acceptance_plan` after engine changes.
9. Report what was fixed, what was deliberately not changed, and any residual risk.
   If the user asks for release work, commit and push only after tests pass.

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

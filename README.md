# apidoc-harvester

> Turn API reference docs into clean Markdown + a validated OpenAPI spec — config-driven, self-improving, and as cheap as the site allows.

把「抓取 API 文档 → 干净 Markdown → 可校验的 OpenAPI」做成**配置驱动、可复用、可自改进**的流水线。引擎是通用的，每个站点只是一个 YAML 配置。

## 核心理念

**确定性的部分用脚本，需要判断的语义工作才用模型。** 能用脚本就不用浏览器、不用模型。

获取策略按"由便宜到贵"排序，命中即止（acquisition ladder）：

| 档位 | 策略 | 适用 |
|---|---|---|
| 0 | **`spec_import`** | 官方已发布 OpenAPI/Swagger spec（url/file）—— spec 即 source of truth，最优。下载 →（Swagger 2.0 经 `npx swagger2openapi` 转 3.0）→ 校验 → 输出。**接新 API 前先查有没有公开 spec。** |
| 1 | `content_api` | 文档内容接口（JSON/HTML/Markdown）。一次性找到接口后整条流水线纯 HTTP，无浏览器、无模型。支持鉴权/XHR `headers` 与多 id URL 模板。 |
| 2 | `static_html` | 已下载的静态 HTML，或直接 HTTP 取整页 HTML（SSR/静态站如 Docusaurus）。 |
| 3 | `rendered` | 无头渲染（Playwright），仅当内容确由 JS 计算且无可取数据源时兜底。 |

## 快速开始

```bash
pip install -r requirements.txt          # beautifulsoup4 / PyYAML / openapi-spec-validator
python run.py config/<site>.yaml
```

页面抓取产物在 `out/<site>/`：`markdown/`、`models.json`、`openapi.yaml`、`checks-report.json`。
spec 导入产物：`openapi.yaml` + `checks-report.json`。

> 可选依赖：`rendered` 需 `pip install playwright && playwright install chromium`；
> `spec_import` 的 `convert_to: openapi3`（Swagger 2.0→3.0）需 Node.js / `npx`。

## 两类配置

**A. 直接吃官方 spec（推荐优先）** — `config/docusign-esign.yaml`：
```yaml
site: docusign-esign
spec_source:
  url: "https://raw.githubusercontent.com/docusign/OpenAPI-Specifications/master/esignature.rest.swagger-v2.1.json"
  format: auto            # auto | swagger2 | openapi3
  convert_to: openapi3    # none | openapi3
output:
  openapi: "out/docusign-esign/openapi.yaml"
  report:  "out/docusign-esign/checks-report.json"
```

**B. 抓页面** — `config/<site>.yaml`（见 `config/_template.yaml`、`config/fadada.yaml` 完整示例）：填 `acquire`（选最便宜可行的策略）、`selectors`（title/time/body）、`structure`（路径/方法正则、请求/响应小节、列序、嵌套单位）、`pages`、`openapi`、`output`。

## 流水线（页面抓取路径）

```
fetch ──→ convert ──→ extract ──→ build_openapi ──→ checks
取原文    →Markdown   →接口模型     →OpenAPI 3.1      →不变量/校验/golden
```

- `spec_import.py` — 直接导入已发布 spec（含 2.0→3.0 转换）；`run.py` 见 config 含 `spec_source` 即走此路
- `fetch.py` — 多策略获取原文（content_api 支持自定义 headers + 多 id 模板）
- `convert.py` — HTML → 规范 Markdown（保留代码缩进、表格嵌套、单元格内链接/加粗/`<br>`，剥离"复制代码"噪声）
- `extract.py` — 正文 → 结构化接口模型（路径/方法/请求树/响应树）
- `build_openapi.py` — 模型 → OpenAPI 3.1（类型/必填/嵌套/统一响应包装/鉴权头）+ 校验
- `checks.py` — evaluator：结构不变量 + OpenAPI 校验 + golden 快照 diff，产出机器可读报告

## 自改进循环（the loop）

`run.py` → 读 `out/<site>/checks-report.json` → 若有 fail，按 `runbook/LOOP.md` 的"信号→改哪里"表做**最小**修改（优先改 config，必要才改脚本）→ 重跑，直到全绿稳定 → 把验证过的 Markdown 冻结进 `golden/<site>/`，并在 `CHANGELOG.md` 追加一行。`CHANGELOG.md` 是循环的"记忆"。

## 已验证站点（示例配置）

| 配置 | 站点 | 架构 / 策略 |
|---|---|---|
| `docusign-esign.yaml` | Docusign eSignature | 官方 Swagger 2.0 → `spec_import` → OpenAPI 3.0（213 path / 414 操作） |
| `fadada.yaml` | 法大大 合同起草 | 静态 HTML（static_html） |
| `fadada-dev.yaml` | 法大大开发者门户 | SPA + JSON content_api（鉴权头 + 多 id） |
| `tencent-qian.yaml` | 腾讯电子签 | Docusaurus 静态，直接取 HTML |

## 目录结构

```
run.py              CLI 入口（spec_source → spec_import；否则页面 pipeline）
requirements.txt
harvester/          引擎（通用，不写站点逻辑）
config/             每站一个 YAML（含 _template.yaml）
runbook/LOOP.md     自改进循环手册（信号→修复表、content_api 发现法）
golden/<site>/      验证过的 Markdown 快照（回归基线）
out/<site>/         产物（已 gitignore）
CHANGELOG.md        引擎演进史 = 循环的记忆
```

## 确定性 vs 模型介入

- **纯脚本（永久复用）**：获取、HTML→MD、表格→模型、OpenAPI 骨架、校验。
- **模型按需介入（一次性）**：发现内容接口、解决文档自身矛盾、枚举语义细化、命名、时序图等判断性产物。生成的 OpenAPI **不自动猜枚举**（取值留在 description），保证基线准确；枚举细化交给模型精修这一步。

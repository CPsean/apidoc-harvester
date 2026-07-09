# apidoc-harvester

> Turn API reference docs into clean Markdown + a validated OpenAPI spec — config-driven, self-improving, and as cheap as the site allows.

把「抓取 API 文档 → 干净 Markdown → 可校验的 OpenAPI」做成**配置驱动、可复用、可自改进**的流水线。引擎是通用的，每个站点只是一个 YAML 配置。

## 核心理念

**确定性的部分用脚本，需要判断的语义工作才用模型。** 能用脚本就不用浏览器、不用模型。

获取策略按"由便宜到贵"排序，命中即止（acquisition ladder）：

| 档位 | 策略 | 适用 |
|---|---|---|
| 0 | **`spec_import`** | 官方已发布 OpenAPI/Swagger spec（url/file）—— spec 即 source of truth，最优。下载 →（Swagger 2.0 经 `npx swagger2openapi` 转 3.0）→（可选 `normalize: true` 机械修复马虎厂商 spec：补缺失 description、映射 int/float/double/date 类型别名、清洗非法组件名并重写 $ref、info 非标准键挪 x-）→ 校验（全量分桶报错）→ 输出，源 spec 自带的悬空 $ref 作为 warn 忠实暴露。**接新 API 前先查有没有公开 spec。** |
| 1 | `content_api` | 文档内容接口（JSON/HTML/Markdown）。一次性找到接口后整条流水线纯 HTTP，无浏览器、无模型。支持鉴权/XHR `headers` 与多 id URL 模板。 |
| 2 | `static_html` | 已下载的静态 HTML，或直接 HTTP 取整页 HTML（SSR/静态站如 Docusaurus）。 |
| 3 | `rendered` | 无头渲染（Playwright），仅当内容确由 JS 计算且无可取数据源时兜底。 |

## 快速开始

```bash
pip install -r requirements.txt          # beautifulsoup4 / PyYAML / openapi-spec-validator
python run.py config/adobesign.yaml      # 零依赖示例：官方 spec 直接导入，无需任何本地文件
```

页面抓取产物在 `out/<site>/`：`markdown/`、`models.json`、`openapi.yaml`、`checks-report.json`。
spec 导入产物：`openapi.yaml` + `checks-report.json`。

> 开箱即用的示例是两个 `spec_import` 配置（`adobesign.yaml`、`docusign-esign.yaml`），只需网络。
> 页面抓取类示例中，`fadada.yaml`（static_html）依赖**不随仓库分发**的预下载 HTML，需自备；
> `fadada-dev.yaml` / `tencent-qian.yaml` 走 HTTP，可直接运行（目标站点可达时）。

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
| `adobesign.yaml` | Adobe Acrobat Sign | 官方 OpenAPI 3.1 → `spec_import` + `normalize: true`（135 path / 184 操作，1169 处机械修复后校验全绿） |
| `docusign-esign.yaml` | Docusign eSignature | 官方 Swagger 2.0 → `spec_import` → OpenAPI 3.0（213 path / 414 操作） |
| `fadada.yaml` | 法大大 合同起草 | 静态 HTML（static_html）——需自备预下载页面，不随仓库分发 |
| `fadada-dev.yaml` | 法大大开发者门户 | SPA + JSON content_api（鉴权头 + 多 id） |
| `tencent-qian.yaml` | 腾讯电子签 | Docusaurus 静态，直接取 HTML |

## 目录结构

```
run.py              CLI 入口（spec_source → spec_import；否则页面 pipeline）
requirements.txt
harvester/          引擎（通用，不写站点逻辑）
config/             每站一个 YAML（含 _template.yaml）
runbook/LOOP.md     自改进循环手册（信号→修复表、content_api 发现法）
golden/<site>/      验证过的 Markdown 快照（回归基线；内容含第三方文档，不入库仅本地）
out/<site>/         产物（已 gitignore）
CHANGELOG.md        引擎演进史 = 循环的记忆
```

## 确定性 vs 模型介入

- **纯脚本（永久复用）**：获取、HTML→MD、表格→模型、OpenAPI 骨架、校验。
- **模型按需介入（一次性）**：发现内容接口、解决文档自身矛盾、枚举语义细化、命名、时序图等判断性产物。生成的 OpenAPI **不自动猜枚举**（取值留在 description），保证基线准确；枚举细化交给模型精修这一步。

## 使用声明 / Disclaimer

本工具面向**个人与团队内部**的 API 文档归档、检索与 OpenAPI spec 生成。使用时请：

- 遵守目标站点的服务条款、robots 协议与访问频率限制；
- 注意 `out/` 与 `golden/` 中的产物**包含目标站点的版权内容**——仅作本地留存与内部使用，
  请勿公开再分发（本仓库已通过 .gitignore 将两者排除在版本库之外）；
- 忠实收割原则：工具保留文档中的原始瑕疵（错别字、示例与参数表不一致等）并在报告中
  暴露，而非静默"修正"。

This tool is for personal / internal archiving of API documentation and OpenAPI spec
generation. Respect the target sites' terms of service, robots.txt, and rate limits.
Harvested artifacts under `out/` and `golden/` contain third-party copyrighted
content — keep them local; do not redistribute (both are git-ignored here).

# 迭代历史（loop 的记忆）

转换器/抽取器的演进。每条 = 一个失败信号 → 一处脚本/配置改动。新改动往后追加。
前 4 条是把法大大示例做对的过程中真实发现的问题（最初是人肉循环，已固化进代码）。

- **#1 代码块噪声** —— 信号：`<pre>` 里混入"复制代码 + 行号 + 扁平化重复"。
  改动：`convert._pre` 在 `CODE_NOISE` 标记处截断。
- **#2 代码缩进丢失** —— 信号：JSON 示例丢了缩进（早期经 get_page_text 中转被压平）。
  改动：直接对 `<pre>` 取 `get_text()` 保留原始缩进，不走文本中转。
- **#3 字段嵌套被拍平 + 单元格内链接/加粗/换行丢失** —— 信号：响应字段层级丢失、单元格 `<a>`/`<strong>`/`<br>` 没了。
  改动：`common.indent_depth` 由缩进推导层级；`convert._cell` 走富文本内联、`<br>`→`<br>`、嵌套字段用全角空格缩进；`extract` 据此建树。
- **#4 误链接** —— 信号：示例代码里的裸 URL 被错误地变成 Markdown 链接，括号错位。
  改动：`convert._inline` 把 `http` 开头或 href 畸形的 `<a>` 降级为纯文本。
- **#5 通用化** —— 信号：要支持非法大大站点。
  改动：选择器/正则/列序/缩进单位全部外置到 `config.*`；获取改为多策略（content_api → static_html → rendered）。
- **#6 概述页缺文件不应整体失败** —— 信号：`api:false` 的概述页文件缺失导致 run 失败。
  改动：`pipeline` 把非 API 页的 fetch 失败降级为 warning。
- **#7 content_api 鉴权头 + 多 id 模板** —— 信号：法大大开发者门户(dev.fadada.com)接入时，
  内容接口在 cloud.fadada.com/api，需 `X-Requested-With`/`X-Request-Version` 头（缺则 403），
  且 URL 同时需要 nodeId(路径) 与 articleId(查询) 两个 id。
  改动：`fetch._content_api` 用整个 page dict 做 URL 模板（保留 `{doc_id}` 别名，兼容旧配置），
  并支持 `acquire.content_api.headers` 注入站点自定义请求头。见 `config/fadada-dev.yaml`。
- **#8 spec_import：直接吃官方 spec** —— 信号：很多 API（如 Docusign）官方维护并公开发布
  OpenAPI/Swagger spec，逆向文档页是下游重建上游，更差。
  改动：新增 `harvester/spec_import.py` 与 `run.py` 分发——config 含 `spec_source` 时，
  下载 spec（url/file）→（Swagger 2.0 经 `npx swagger2openapi` 转 OpenAPI 3.0）→ 校验 → 输出。
  这是获取阶梯的最顶档（spec_import > content_api > static_html > rendered）。见 `config/docusign-esign.yaml`。
- **#9 spec_import normalize：确定性修复马虎的厂商 spec** —— 信号：Adobe Sign 官方 spec 自称
  OpenAPI 3.1 但严格校验报 1155 个错（1122 个 response 缺 description、int/float/double/date
  非法类型名、乱码 schema 名、OAuth 块塞进 info、布尔 required）——全是机械性错误。
  改动：`spec_import._normalize`（`spec_source.normalize: true` 启用）按纯机械规则修复：缺失
  必填字符串补 ""（不发明内容）、类型别名映射、组件名清洗+$ref 重写（`_walk_refs` 区分
  Example 映射里的真 $ref 与字面量载荷）、info 非标准键挪到 x-；`_validate` 改为全量分桶报错
  （原先只报第一条）；新增 `_dangling_refs` 把源 spec 自带的悬空 $ref 作为 warn 暴露（忠实保留
  不修）。见 `config/adobesign.yaml`（135 paths / 184 ops，1169 处修复后校验全绿）。
- **#10 spec 下载健壮化：curl 回退** —— 信号：本机 127.0.0.1 转发代理下 urllib TLS 握手被掐
  （SSL UNEXPECTED_EOF）；且 Windows CreateProcess 先搜 System32 后搜 PATH，裸调 "curl" 会
  命中打不通同一代理的 System32 构建。
  改动：`spec_import._fetch_url`——urllib 失败时经 `shutil.which` 按 PATH 解析 curl 完整路径
  回退（`-sSL --retry 3 --retry-all-errors`），两者都失败才报错。
- **#11 `+` 前缀嵌套（config 化）** —— 信号：法大大 markdown 表用 `+field` 表示子级，
  `indent_depth` 的 `lstrip("+")` 把嵌套拍平到根层（使用者反馈 BUG-2）。
  改动：新增 config `structure.nest_prefix`（如 `"+"`）——每个前导前缀字符计一级嵌套并从
  字段名消费；未设置时行为逐字节不变。`common.indent_depth` 加参，`extract`/`convert`/
  `pipeline` 全链透传（md 渲染与 OpenAPI 树深度保持一致）。
- **#12 小节标题正则匹配（config 化）** —— 信号：Docusaurus 站标题渲染为 `2. 输入参数`
  （带编号前缀），`startswith` 匹配失败、参数表全跳过（使用者反馈 BUG-3；直接全局改
  `in` 会误伤，故做成 opt-in）。
  改动：新增 config `structure.section_match: exact|regex`（默认 exact = 现行行为）——
  regex 模式下 `*_section` 各标记按 `re.search` 匹配。`common._marker_match` 统一
  `section_tables`/`code_after` 的判定。
- **#13 required 列可选** —— 信号：腾讯云响应表只有 3 列（无"必选"列），
  `cols["required"]` KeyError、行跳过条件硬编码 `cols["desc"]`（使用者反馈 BUG-4；
  拒绝按列数自动猜列序——猜错产出静默错误的 spec）。
  改动：`extract._tree_from_table`——`columns.required` 可省略（全部字段 required=False），
  行跳过条件改用 `max(cols.values())`（对标准 4 列布局等价）。
- **#14 OpenAPI path 参数未声明** —— 信号：校验器报 `Path parameter ... was not resolved`。
  改动：`build_openapi.build` 从 path 模板提取 `{param}`，把请求表同名字段转为
  `parameters[].in=path`，并从 requestBody 中剔除。
- **#15 Markdown 顶部标题重复** —— 信号：`selectors.title` 命中 body 内首个同名 `<h1>`，
  输出出现两个相同一级标题。
  改动：`convert._walk` 透传首个 H1 跳过状态，只跳过第一个与页标题完全相同的 `<h1>`。
- **#16 行号表格代码块污染** —— 信号：`<pre><table>` 行号结构输出为 `1{2...` 或残留空白。
  改动：`common.code_text` 统一清洗 `td.ln-text` / 第一列数字行号表格，`convert._pre`
  与 `common.code_after` 共用，避免 Markdown 与 examples 分叉。
- **#17 path_regex 捕获完整 URL** —— 信号：文档写 `https://{host}/path`，OpenAPI 只需要
  `/path`，配置正则被迫复杂化。
  改动：`extract.extract_endpoint` 支持 `structure.strip_domain: true`，捕获完整 URL 后
  只发出 path 部分。
- **#18 大站点 pages 手写成本高** —— 信号：百页级文档需要手写 pages 列表。
  改动：新增 `config_loader.load_config`，支持 `pages_from_manifest` 与 `pages_from_dir`，
  生成页先展开，显式 `pages` 覆盖同 id。
- **#19 parentid/colspan 树表无法直接抽取** —— 信号：站点用 `parentid`、`onclick=toggle(...)`
  和 `colspan` 表达字段层级，标准列序抽取失败。
  改动：新增 opt-in `preprocess.table_normalizer`，在 convert/extract 前把该类 HTML 表规整为
  现有缩进规则可读取的表格。
- **#20 SPA bundle 内嵌正文但无 content API** —— 信号：正文在 JS bundle 中，rendered 策略
  成本高且环境依赖重。
  改动：`fetch` 新增 opt-in `js_bundle` 策略，按显式 `record_regex` 或
  `object_regex` + 字段名静态提取正文，不执行 JS。
- **#21 VitePress 代码块语言标签泄漏** —— 信号：`div.language-json` 中的 `span.lang`
  输出为孤立段落，且代码围栏丢失语言标识。
  改动：`convert._walk` 将语言包装层归一为单个带 info string 的代码围栏，
  `convert._pre` 从 `language-*` class 继承语言。
- **#22 旧配置/缺段落报错不清晰** —— 信号：旧版扁平配置或缺少 `output`
  时只暴露 `KeyError`，使用者无法判断是配置格式迁移问题。
  改动：`config_loader` 识别旧顶层字段并给出迁移提示，`pipeline.run` 在执行前
  校验页面采集配置的必需段落。
- **#23 现代文档站树表/混合列布局需要外部预处理** —— 信号：VitePress 表格用
  `data-level` 表达层级，且同一页面请求表 4 列、响应表 3 列时全局 `columns`
  无法准确抽取。
  改动：`preprocess.table_normalizer` 新增 opt-in `nesting_mode: data_level`，
  `extract._tree_from_table` 支持 `request_columns` / `response_columns` 覆盖。

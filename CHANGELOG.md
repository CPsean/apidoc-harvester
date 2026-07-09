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

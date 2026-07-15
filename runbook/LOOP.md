# 自改进循环（evaluator–optimizer loop）

把"人肉调试抓取器"形式化成一个可重复的循环：**模型用来生产/改进脚本，脚本确定性地永久复用。**
新页面进来只跑脚本；只有当某个不变量被打破（站点改版/文档更新）才把那一处升级给 Agent。

## 循环主体
```
        ┌─────────────────────────────────────────────┐
        ▼                                             │
  run.py <config>  ──→  checks-report.json  ──→  fails/warns?
        ▲                                       │ 有
        │                                       ▼
        └──── 改 脚本/config（最小改动） ◀── 分类失败并定位到具体阶段
                                                │ 全绿/稳定
                                                ▼
                                              停止（产物即交付）
```

每轮：
1. `python run.py config/<site>.yaml`
2. 读 `out/<site>/checks-report.json`
3. `ok=false` → 看 `fails`，分类（见下）→ **改脚本或 config，不要手改产物** → 回到 1
4. `ok=true` 且与上一轮一致 → 收敛，停。把当轮验证过的 markdown 冻结进 `golden/<site>/`（快照测试，挡住未来回归）。

## 失败分类 → 改哪里
| 失败信号（来自 checks） | 根因 | 改动位置 |
|---|---|---|
| 未解析到 path/method | 正则不匹配该站点写法 | `config.structure.path_regex/method_regex` |
| 请求/响应表为空 | 小节标题或正文选择器不对 | `config.structure.*_section` / `config.selectors` |
| 残留"复制代码"/占位符 | 代码块噪声新形态 | `convert.py: CODE_NOISE` |
| 代码围栏不配对 | `<pre>` 结构异常 | `convert.py: _pre` |
| 与 golden 不一致 | 转换器行为变了（可能是改进也可能是回归） | 人判断：是改进就更新 golden；是回归就修 `convert.py` |
| OpenAPI 校验失败 | 类型/嵌套映射缺口 | `build_openapi.py: _node_schema` |
| OpenAPI 提示 path parameter unresolved | path 模板参数未声明或请求表字段未分离 | `build_openapi.py: build` |
| 字段嵌套层级错乱 | 该站点缩进单位/字符不同 | `config.structure.nested_indent_unit` / `common.indent_depth` |
| 表格由 `parentid`/`colspan` 表示层级 | HTML 表不是标准参数表 | `preprocess.table_normalizer` |
| spec_import 校验失败且全是机械错误（缺 description、int/date 类型名、乱码组件名、info 塞 OAuth） | 厂商 spec 马虎 | `spec_source.normalize: true`；规则不够再扩 `spec_import._normalize`（保持确定性，不发明内容） |
| spec 下载失败（本机代理下 urllib TLS 被掐 / System32 curl 握手失败） | 环境代理与 TLS 客户端不合 | 已内置：`spec_import._fetch_url` urllib→PATH 解析的 curl 回退；仍失败则换网络环境 |

每次改动在 `CHANGELOG.md` 追加一行（什么信号→什么改动），循环的"记忆"。

## 一次性：发现 content_api（把浏览器/模型成本摊薄到零）
内容多为异步加载，正文背后一定有接口。**只需做一次**：
1. 浏览器打开任意文档页，开 DevTools → Network → 过滤 XHR/Fetch。
2. 找返回正文（Markdown 或含正文 HTML 的 JSON）的请求，记下 URL 形态、`{doc_id}` 位置、响应里正文的字段路径。
3. 填进 `config.acquire.content_api`（`url_template` / `content_pointer` / `content_is`），`enabled: true`。
4. 之后整模块/整站同类页面都走纯 HTTP，几秒拉完，无浏览器无模型。

> 注：沙箱网络是 allowlist 的，目标站点可能不可直连——脚本写对即可，在能访问该域名的环境执行。

### SPA 深挖方法论（Network 面板一眼找不到时）
有些 SPA（Vue/React 门户）不是"一个 XHR 返回正文"，链路藏得深。按序深挖：
1. **空壳判定**：`curl -s <doc-url> | wc -c` 小于 ~10KB 且无正文文本 → 纯 SPA，正文必经异步来源。
2. **webpack chunk 定位**：首页 HTML 里找入口 JS 与 chunk 映射（`__webpack_require__`、
   `<link rel="modulepreload">`、`assets/*.js` 清单），下载相关 chunk。
3. **bundle 内 grep API 形态**：在 JS 里搜 `/api/`、`baseURL`、`axios.create`、`.get(`、`.post(`、
   `fetch(`——拼出内容接口的 URL 形态与必带 header（法大大 dev 门户即由 baseURL map 发现，见 #7）。
   若正文直接内嵌在 bundle 里（无接口），改用 `acquire.js_bundle` 静态提取（#20）。
4. **回 Network 面板验证**：用拼出的 URL 直接请求，核对 `content_pointer` 字段路径。
5. **登录墙**：接口需要登录态时，把 cookie/token 放环境变量，config 里写
   `headers: {Cookie: "${SITE_COOKIE}"}`（`${VAR}` 取自环境，凭证不进 config/仓库）；
   POST 型内容接口配 `body_template`。slug→内部 id 的解析若藏在多级静态 JSON 配置里
   （如 esign 门户），一次 Network 抓包比纯逆向 JS 省时。

## 何时升级给 Agent（按需介入，而非每次全程）
- 新站点首次接入：写 config + 跑通循环。
- checks 出现"未见过的"失败形态：扩展对应脚本。
- 文档语义层（枚举取值、命名、矛盾修订、时序图）：模型判断后落成脚本/配置或一次性产物。
其余情况——尤其文档增量更新——交给定时任务跑脚本 + 与上次快照 diff，自动告警，无需 Agent。

## 与定时任务结合
周期性 `run.py` → 和上一份 `out/` 快照 diff → 有变化则告警（文档更新检测）。
页面清单变更（站点目录树增删改）：跑 `python run.py config/<site>.yaml --sync-pages`
→ 审 `config/<site>.pages.yaml` 的 git diff → 再跑正常 run。

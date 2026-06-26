---
name: campus-job-db
description: 抓取指定公司的校招/社招职位列表页，用可配置的模型（默认 DeepSeek deepseek-v4-flash）做结构化抽取，并为每个职位生成职位解读和准备建议，输出到 Notion 数据库、Obsidian Bases，或纯 Markdown 汇总（零依赖兜底）。可选按用户背景给职位打推荐优先级。当用户说"帮我抓 XX 公司的校招职位"、"把这个招聘页做成数据库"、"建一个求职职位库"、"/campus-job-db"，或给出 Moka/北森等招聘系统链接并希望整理成结构化清单时使用。
---

# Campus Job DB

把一家公司的招聘列表页变成结构化、可筛选/排序的职位库。三个可独立替换的环节：**抓取 → 结构化 → 输出**，每个环节都有兜底。

## 第 0 步（强制）：先自检，再报告，再动手

**任何动作之前**，先跑：

```bash
bash ~/.claude/skills/campus-job-db/scripts/check_setup.sh
```

**不要看完自检结果就自己默默选一条退化路径往下跑。** 把缺失项列给用户看，明确问清楚要怎么处理，再继续：

- 模型 key 没配 → 告诉用户"结构化抽取/推荐打分需要模型 key，现在没有，可以帮你配（分发 toolbox/api-key-manager agent），或者直接用 `--no-model` 走未结构化的版本，你选哪个？"
- opencli 没装/没连 → 告诉用户"抓取这种 JS 渲染的招聘页面需要 OpenCLI 浏览器桥，现在没连上，会退化成只能抓静态页（很可能失败）。要不要先装一下，还是直接试 WebFetch？"
- Notion/Obsidian 没配置 → 在第 5 步选输出之前问清楚目标到底是哪个，缺的环境要不要现在配

只有用户明确选了"就用现在这个降级版本"之后，才走兜底路径——不要替用户做这个决定。

## 整体流程

```
1. 确定公司 / URL + 求职意向（一次性问清，别审问式追问）
2. 抓取：先查有没有现成 API（首选，fetch_api_paginated.py）；没有才退回 opencli DOM 提取
   量大就用类别筛选器或 prefilter_large_batch.py 缩范围（数量上限按用户说的卡死）
3. 模型拆分职位边界 + 结构化抽取（API 数据干净时用 structure_from_api.py 跳过这步的模型调用）
4. 模型生成"职位解读 + 资格提示 + 准备建议"  ← deepseek-v4-flash（默认，可换），默认做
5. （可选）按用户背景打推荐优先级  ← 同一模型
6. 选输出：Notion（build_notion_pages.py 生成数据，禁止手敲）/ Obsidian Bases / 单文件 Markdown
```

**硬规则：每一步都调脚本，不在对话里现场写一次性 python/重新摸索 DOM 选择器。** 抓取前先看 `references/api-reverse-engineering.md`；Notion 写页面必须 `build_notion_pages.py` 生成 → `push_notion_pages.py` 直连 REST API 写入，**不允许把页面正文 Read 进对话再粘进 MCP 工具调用**——大批量正文在模型上下文里重复一遍是明确的 token 浪费，已经被叫停过一次，不要再犯。

---

## 第 1 步：确定公司 / URL + 求职意向

这一步要收齐两类信息：**① 抓哪个页面**（公司/URL/校招还是社招），**② 求职意向**（用于后面筛类别、打分、给建议）。但**怎么问**很关键——之前的教训是把每个维度都拆成 AskUserQuestion 的固定选项，结果像审问，而且"毕业时间"这种自由值硬塞进固定选项根本不匹配，用户只能选"我来填"再被追问一轮。

### 交互原则（按顺序）

1. **先翻对话历史，别重复问。** 用户在本次会话前面已经说过的（背景、毕业届数、感兴趣方向、甚至 URL），直接拿来用，只确认不重问。比如之前聊过"代码弱、Vibe Coding 熟、对 AI for Math 有兴趣"，这次就别再问一遍背景。

2. **默认用一条开放式提问一次性收齐，不要连发好几个 AskUserQuestion。** 推荐直接用自然语言问一句，让用户一段话答完，例如：

   > "给我招聘页链接（或公司名），再简单说下你的情况就行：校招还是社招、要实习还是全职、哪一届毕业 / 可到岗时间、想看哪些方向的岗位、以及你的背景（专业、技能、感兴趣的领域）。一段话说完就行，缺的我再问。"

   自由文本对"2027届""可实习6个月""对 AI for Math 有兴趣"这类值天然友好，比固定选项顺得多。

3. **只在「值是离散的、且用户没提」时才用 AskUserQuestion，并且合并成一次问（一个 AskUserQuestion 里放多个 question）。** 适合做成选项的只有：校招/社招、实习/全职、输出到哪（Notion/Obsidian/Markdown）。**毕业时间、可到岗时长、背景、感兴趣方向这些自由值永远不要做成固定选项**——要么从开放式回答里拿，要么单独用一句话问，绝不硬凑选项让用户被迫走"其他/我来填"再追问一轮。

4. **缺啥补啥，别一次性追求填满所有字段。** 资格判断（毕业时间/实习时长）是"有则更好"，用户嫌麻烦不想填，就跳过资格提示那部分，别卡着不让往下走。

### 确定 URL

- 用户给了 URL → 直接用。
- 只给公司名 → 用 WebSearch 找官方"校园招聘"/"社会招聘"页（搜 `<公司名> 校园招聘 site:mokahr.com` 之类，国内大厂常用 Moka(`app.mokahr.com`)、北森(Beisen)、自建系统）。校招/社招常是两个不同 URL，按用户回答选对应那个。

### 收尾

把收集到的"校招/社招 + 实习/全职 + 毕业时间/可到岗时间 + 感兴趣方向 + 背景"**合并成一段"求职意向"文本**，后面第 2 步（按类别筛规模）、第 4 步（解读+建议）、第 5 步（推荐打分）都复用这一段，不要让用户重复说。记下 URL。

## 第 2 步：抓取

**这一步可以直接派 `searcher` 子 agent 去做**——它内置的就是下面这套方法论（API 优先、DOM 退路、分页探测、去重），是通用检索能力的一部分，不是 campus-job-db 专属。派给它时说清楚要拿到的是"这个招聘列表页的全量原始数据（含职位标题/正文/链接），尽量找现成 API 直连”，让它把原始 JSON/文本交回来，你接着走第 3 步结构化——抓取的方法论维护在一处（`references/api-reverse-engineering.md`，searcher 也读这份），不用两边分别改。

也可以自己动手（比如没有 agent 调度权限、或想自己控制细节），流程一样：**先看一眼 `network`，有没有现成 API 能直接调；没有才退回浏览器 DOM 抓取。** API 方案永远更便宜更稳——零浏览器、零 debugger 冲突、翻页是改个数字、还经常自带干净的结构化字段。完整方法论见 `references/api-reverse-engineering.md`，这里只列最终落地脚本。

### 2a（首选）：API 直连

1. 打开页面，`network` 列请求，认出主站域名下的 list/query 接口，`--detail` 看响应确认（含 `total/list[...]`）。
2. hook `fetch`/`XHR` 抓真实请求体（外层包装字段猜不到，必须抓）。
3. 用固化好的脚本翻页拉全量，**不用手写循环**：

```bash
python3 ~/.claude/skills/campus-job-db/scripts/fetch_api_paginated.py \
  --url "<接口URL>" \
  --body-template '<抓到的真实请求体，去掉 pageNum/pageSize 字段>' \
  --page-field pageNum --size-field pageSize --page-size 10 \
  --data-path data.list --total-path data.totalPage --id-field positionId \
  --referer "<页面URL>" \
  --out /tmp/<company>_raw.json
```

`--data-path`/`--total-path` 是响应里 list/总页数的点号路径（按实际响应结构填，不一定是 `data.list`）。跑完直接是去重好的完整数组，不用再开浏览器。

4. 如果返回字段已经是干净的 duty/qualification（没有 DOM 噪音），**跳过模型拆分**，直接结构化：

```bash
python3 ~/.claude/skills/campus-job-db/scripts/structure_from_api.py /tmp/<company>_raw.json \
  --duty-field duty --qualification-field qualification \
  --classify-category \
  --out /tmp/<company>_structured.json
```

省了一整轮"模型识别职位边界"的调用——边界本来就是干净的，没必要为已结构化的数据再花一次模型调用。`--classify-category` 是否加看你要不要后面按类别筛（不加就全填占位类别，靠后面 prefilter 按方向筛）。

### 2b：OpenCLI DOM 提取（没有 API 时的退路）

```bash
opencli browser <s> open "<URL>"
opencli browser <s> wait time 2
opencli browser <s> extract                      # 返回 {content, next_start_char, total_chars}
opencli browser <s> extract --start <next_start_char>   # 内容长、没读完就接着抓
```

- `extract` 一次给一个 chunk，看 `next_start_char` 判断读没读完，没读完就 `--start` 续。
- 把每次 `extract` 的原始内容**原样存盘**（`/tmp/<company>_chunk1.txt`、`_chunk2.txt`...），**不要手写正则切分**，交给第 3 步的模型拆。

### 翻页

很多招聘页是"30条/页"分页。**不要凭记忆直接套用某个固定 class 名去点页码**——不同站点用的前端组件库不一样，class 名完全不同。曾经误判过"小红书/阿里分页组件坏了、消失了"，事后查证根因其实是**选择器猜错了**：那两个站不是常见的 Ant Design（`ant-pagination-item`），阿里用的是自家 Fusion/Next 组件库，真实 class 是 `next-pagination-item`，跟 Ant Design 完全不同名。组件其实一直都在，只是没用对名字去找。

**正确做法：先探测用的是哪套分页组件，再点。**

```bash
# 1. 探测页面上所有"看起来像分页"的元素，打印真实 class 名（去重）
opencli browser <s> eval "
JSON.stringify(Array.from(document.querySelectorAll('[class*=pagination i], [class*=Pagination i], [class*=pager i]'))
  .map(e=>e.className).filter((v,i,a)=>a.indexOf(v)===i))
"
```
看输出里有没有认得出的关键字，常见的有 `ant-pagination*`（Ant Design）、`next-pagination*`（阿里 Fusion/Next），或者别的自定义前缀——**直接照输出里那个真实 class 名走**，不要套用任何写死的范例。

```bash
# 2. 用探测到的真实前缀，列出所有页码节点（排除 prev/next 箭头按钮）
opencli browser <s> eval "
var items=Array.from(document.querySelectorAll('.<探测到的前缀>-item'));
JSON.stringify(items.map(e=>({text:e.textContent.trim(), cls:e.className})))
"
```

```bash
# 3. 点文本等于目标页码的那个节点
opencli browser <s> eval "
var items=Array.from(document.querySelectorAll('.<前缀>-item'));
var target=items.find(e=>e.textContent.trim()==='2');
if(target){target.click();'clicked'}else{'not found'}
"
opencli browser <s> wait time 2
opencli browser <s> extract
```

重复到所有页抓完。**用职位链接里的稳定 ID 去重**——这个 ID 集合还能反过来验证翻页是否真的生效：换页后新一批 ID 应该跟上一页完全不重叠，如果重叠说明点击没起作用（可能点到了错误的元素或页面没刷新），不是数据本身的问题。

> **「点不动」先怀疑选择器，别急着归咎于网站本身。** 实测阿里 26 个职位、3 页，按上面的探测流程翻完零重复零遗漏——分页本身没坏，只是要先认对组件库。真正"分页组件确实从 DOM 消失/卸载"的情况理论上存在，但要先排除选择器问题再下这个结论。排不掉就照实告诉用户"这页翻不动，只拿到当前页的 N 条"，别硬凑。

### 规模控制

抓之前先看页面"全部职位（N）"。N 很大（比如几百）时，后面每条要过 3 次模型调用，又慢又费 key，有两条缩范围的路：

- **网站自带「职位类别」筛选器**（点类别标签 → `wait` → 重新 extract/抓）——筛选生效在抓取之前，最省。
- **抓完全量后用 `prefilter_large_batch.py` 本地一次性预筛**——N 太大或筛选器不可靠时用这个，**一次模型调用批量判断 match+score，不跑完整解读**，省下后面 `interpret_jobs.py` 对不相关职位的调用：

```bash
python3 ~/.claude/skills/campus-job-db/scripts/prefilter_large_batch.py \
  /tmp/<company>_raw.json \
  "<第1步收集的求职意向>" \
  --duty-field duty --qualification-field qualification \
  --out /tmp/<company>_prefilter.json
```

输出 `{id: {match, score}}`，按 `match=true` 过滤出候选子集，**只对这个子集**跑后面第 3/4/5 步的完整流程（结构化→解读→打分）。用户给了数量上限（比如"不超过30"）就在这一步卡住，不要等结构化完了才发现超了。

用户坚持要全量、不缩范围，就先告诉 ta 大致耗时（约 N 个职位 × 几次模型调用）再跑。

### 抓不动时的退路

- **OpenCLI 没装/页面是纯静态**：`WebFetch(url, prompt="提取所有职位的标题、发布日期、类型、完整正文")`。SPA 会拿到空壳，失败就往下。
- **都不行**：请用户直接粘贴职位列表文本或截图。不阻塞流程。

用完 `opencli browser <s> close` 释放标签。

> **OpenCLI 报 `attach failed: chrome-extension://...` 怎么办**：这是另一个用 `chrome.debugger` 的浏览器扩展（比如 Claude in Chrome）跟 OpenCLI 抢占调试器——`chrome.debugger` 同一标签只能被一个扩展占用。**用户不一定愿意为这个临时关插件**（这是改用户环境，别默认替用户做决定）。优先回到 2a 的 API 直连方案——纯 `curl`/`urllib` 完全不碰 `chrome.debugger`，天然绕开这个冲突，而且通常比浏览器方案更快更稳。只有确认这个站没有可用 API 时，才需要用户配合关插件。

---

## 第 3 步：模型拆分 + 结构化抽取

**走 2a（API 直连）且数据已经干净的，已经在 2a 里用 `structure_from_api.py` 结构化完了，跳过本步。** 下面是走 2b（DOM 提取）时的默认做法（一步到位，模型自己识别原始文本里有哪些职位、边界在哪、再抽取字段，不用你预先切好）：

```bash
python3 ~/.claude/skills/campus-job-db/scripts/split_jobs_from_raw.py \
  /tmp/<company>_chunk1.txt /tmp/<company>_chunk2.txt ... \
  /tmp/<company>_jobs_structured.json
```

可以一次传多个 chunk 文件（比如多页分页抓的多个文件），脚本内部还会按 `--max-chunk-chars`（默认 14000）再切成适合单次模型调用的大小，跨 chunk 出现的同一个职位（比如侧边栏"最新职位"重复）按 `job_id` 自动去重合并，取信息更完整的那份。

**模型可配置**，默认 `deepseek-v4-flash` / `https://api.deepseek.com/v1` / 环境变量 `DEEPSEEK_API_KEY`，跟其他脚本一样用 `--model/--base-url/--key-env` 三个参数换：

```bash
python3 split_jobs_from_raw.py chunk1.txt chunk2.txt out.json \
  --model deepseek-v4-flash --base-url https://api.deepseek.com/v1 --key-env DEEPSEEK_API_KEY
```

**不知道该用哪个 key/模型？** 不要猜，分发 `toolbox`（或 `api-key-manager`）agent 问，给它用例（"网页内容检索/结构化抽取"），它会回环境变量名 + base_url + 推荐模型名，不会把明文 key 吐给你。

**这一步没有 `--no-model` 兜底**——拆分职位边界本身需要理解上下文，规则切分对不同站点格式不通用。没 key 时只能退回手写正则（用 `scripts/extract_jobs.py`，见下）。

脚本自带失败重试：单个 chunk 失败（常见是 `max_tokens` 不够导致 JSON 被截断）会自动对半切开重试。

抽取完确认一下条数对不对（去重后应该等于网页上写的"N 结果"，如果少了，回第 2 步检查是不是漏了分页）。

### 备用路径：内容已经是预先按职位分好的（不常用）

如果你手上的数据已经是 `{job_id: raw_text, ...}` 这种预先切好的格式（比如用户直接粘贴了已经分好的多条职位文本），可以跳过 `split_jobs_from_raw.py`，直接用 `scripts/extract_jobs.py`（参数同上，外加没 key 时可以 `--no-model` 兜底成未结构化输出——这是它和 `split_jobs_from_raw.py` 的区别，因为这种情况下"拆分"这件事已经不需要模型做了，只是格式转换，所以能有规则兜底）。

---

## 第 4 步：职位解读 + 资格提示 + 准备建议

**默认要做**（不像第 5 步那样要等用户给背景才做）——除非用户明确说不需要，或者第 0 步已经确认没有模型 key 要走降级路径。输出除了工作内容/任职要求之外，再给每个职位加：

- **职位解读**：剥开营销话术后这个岗位实际在做什么、门槛/竞争程度怎么判断、跟公司业务的关系
- **资格提示**（仅在第 1 步收集的求职意向里有毕业时间/实习时长/校招社招这类信息时才出现）：明确指出用户跟这个职位的硬性门槛（如"2027届优先""实习6个月以上"）是否冲突，不是泛泛建议，是直接判断匹不匹配
- **准备建议**：投递前该准备什么（简历侧重、作品集、技能缺口），具体可执行，不说空话

**`--profile` 直接传第 1 步收集的"求职意向"那段文本**（校招/社招 + 实习/全职 + 毕业时间/可到岗时间 + 其他背景），不要等到第 5 步才想起来传，资格提示这一段全靠它才能生成：

```bash
python3 ~/.claude/skills/campus-job-db/scripts/interpret_jobs.py \
  /tmp/<company>_jobs_structured.json \
  --out /tmp/<company>_jobs_annotated.json \
  --profile "<第1步收集的求职意向，例如：校招实习，2026届，可实习6个月，LLM知识停留在表层，Vibe Coding经验丰富，代码能力弱>"
```

没有背景信息也能跑（只是没有资格提示这一段，职位解读和准备建议会偏通用）：

```bash
python3 interpret_jobs.py structured.json --out annotated.json
```

同样吃 `--model/--base-url/--key-env`。**这一步没有 `--no-model` 兜底**——它产出的是分析判断而不是格式转换，没 key 就只能跳过（直接用 `_jobs_structured.json` 继续走第 5/6 步，输出里就不带这几段），不能用规则硬凑假内容。

之后第 5/6 步统一吃这一步产出的 `_jobs_annotated.json`（没跑这一步就还是吃 `_jobs_structured.json`）。

---

## 第 5 步（可选）：按用户背景打推荐优先级

只有用户明确给了自己的背景/偏好才做这一步，不要凭空猜。**背景信息就是第 1 步收集的"求职意向"，原样传进来，不要再问用户重复一遍。**

```bash
python3 ~/.claude/skills/campus-job-db/scripts/recommend_priority.py \
  /tmp/<company>_jobs_annotated.json \
  "<第1步收集的求职意向，跟第4步传给 interpret_jobs.py 的是同一段文本>" \
  --out /tmp/<company>_priority.json
```

同样吃 `--model/--base-url/--key-env`。这一步是判断题，没有 `--no-model` 兜底——没 key 就跳过这步，照常往下走（推荐优先级全部留空/0）。

---

## 第 6 步：选输出

**先问用户要哪个（Notion / Obsidian / 纯 Markdown），再看对应环境是否就位**——不要因为 Notion 没连上就悄悄改成出 Markdown 文件，要明确告诉用户"Notion 没连，要不要现在连，还是先出 Markdown"。

### A. 纯 Markdown（零依赖，永远能用）

```bash
python3 ~/.claude/skills/campus-job-db/scripts/render_markdown.py \
  /tmp/<company>_jobs_annotated.json \
  --mode single \
  --title "<公司名> 校园招聘职位汇总" \
  --link-template "<招聘页URL前缀>#/job/{job_id}" \
  --priority-json /tmp/<company>_priority.json \
  --out "<用户要的路径>.md"
```

`--priority-json` 留空就不带优先级。这是默认兜底输出，任何环境都能跑。

### B. Obsidian（一职位一笔记 + Bases 数据库）

**前提**：Obsidian 装了 Bases 插件（核心功能内置，较新版本自带）；需要知道 vault 根目录路径——没设过 `$OBSIDIAN_VAULT` 就直接问用户。

```bash
python3 ~/.claude/skills/campus-job-db/scripts/render_markdown.py \
  /tmp/<company>_jobs_annotated.json \
  --mode obsidian \
  --link-template "<招聘页URL前缀>#/job/{job_id}" \
  --priority-json /tmp/<company>_priority.json \
  --out "<vault路径>/<公司名>校招职位"
```

再用 Write 工具在同一目录的上一级写一个 `.base` 文件（文件名 `<公司名>校招职位.base`）：

```yaml
filters:
  and:
    - file.inFolder("<公司名>校招职位")
views:
  - type: table
    name: 按类别
    groupBy: 类别
  - type: table
    name: 推荐优先
    sort:
      - property: 推荐优先级
        direction: DESC
  - type: cards
    name: 按地点
    groupBy: 地点
```

（具体字段名跟 `render_markdown.py --mode obsidian` 写进 frontmatter 的字段保持一致：职位名称/类型/地点/发布日期/类别/推荐优先级/链接。）

### C. Notion 数据库

**建数据库这一步走 MCP（一次性、内容量小，不构成 token 负担）；批量写入页面正文这一步走脚本直连 REST API（内容量大，必须避免在对话上下文里重复一遍）。** 写入环节绝不允许把页面正文 Read 进上下文再粘进 `notion-create-pages` 工具调用——21 条职位的完整文本在上下文里过两遍是实打实的浪费，已经因此被用户叫停过一次。

**前提**：
- 建数据库需要对话里连上 Notion MCP（`ToolSearch` 搜 "notion create database" 确认）。
- 写入页面需要 `NOTION_API_TOKEN` 环境变量（Notion **internal integration secret**，`ntn_`/`secret_` 开头，去 https://www.notion.com/my-integrations 创建，这一步必须用户本人操作，不是 MCP 那套 OAuth 授权）。**且这个集成必须被手动连接到目标数据库**（数据库右上角 `•••` → Connections → 搜集成名 → 连接），否则 API 会报 401/`restricted_resource`。没配过就先问用户要不要现在配，别假装这条路随时可用。

操作步骤：

1. **建数据库**（一次性，直接调 MCP 工具，正文量小不算浪费），schema 按结构化字段设计：

   ```
   notion-create-database(
     title="<公司名>校招职位",
     schema='CREATE TABLE ("职位名称" TITLE, "类型" SELECT(...), "类别" SELECT(...),
             "地点" RICH_TEXT, "发布日期" RICH_TEXT, "推荐优先级" NUMBER, "链接" URL)'
   )
   ```

   记下返回的数据库 page id（`--database-id` 要用这个，不是 `data_source_id`）。

2. **生成页面数据——必须用脚本，禁止手敲 JSON**：

   ```bash
   python3 ~/.claude/skills/campus-job-db/scripts/build_notion_pages.py \
     /tmp/<company>_jobs_annotated.json \
     --priority-json /tmp/<company>_priority.json \
     --link-template "<招聘页URL前缀>{job_id}" \
     --sort-by-priority \
     --out /tmp/<company>_notion_pages.json
   ```

3. **直连 REST API 写入——不经过 MCP，不经过模型上下文**：

   ```bash
   python3 ~/.claude/skills/campus-job-db/scripts/push_notion_pages.py \
     /tmp/<company>_notion_pages.json \
     --database-id <第1步记下的database id>
   ```

   脚本自己读文件、自己分批 POST、自己打印每条成功/失败，**不需要把内容读进对话**，只需要看脚本的输出摘要（成功N条/跳过N条重复/失败N条）。失败的会打印对应 index，修好原因后用 `--start <index>` 续跑。默认字段类型映射是这个 skill 的标准 schema（职位名称=title，类型/类别/公司=select，地点/发布日期=rich_text，推荐优先级=number，链接=url——**地点和发布日期是 RICH_TEXT，不是 DATE**，跟第1步的 DDL 保持一致）；schema 不同就用 `--select-props`/`--rich-text-props` 等参数覆盖。

   **脚本写之前会自动按"链接"查一遍目标库里已有什么，重复的直接跳过，不用你自己判断"是不是写过了"**——这条防线是真踩过坑才加的：曾经在一次跨上下文压缩的会话里，没意识到前半段已经写过一批，恢复后又重写了一遍，21条里13条被存了两次。`--no-dedupe` 只在确定目标库是全新空库时才加，省一次查询。

4. **核对条数**：脚本结尾打印的 `created` 数量 + 跳过的重复数应该等于 `build_notion_pages.py` 输出的总数；不对就看失败列表逐条排查，不要默认"差不多就行"。

5. **建视图**（这一步内容量小，仍走 MCP 的 `notion-create-view`，传 `database_id` 这个 page id，不是 data_source_id）：
   - table，`SORT BY "推荐优先级" DESC`（always 加，这是用户最常用的视图）
   - table，`GROUP BY "类别"`（**只在这批数据类别确实混杂时加**——如果筛完全是同一类别，分组没意义，跳过）
   - gallery，`GROUP BY "地点"`（地点分散时加；地点高度集中也可跳过）

### D. 汇总到已有的多公司库（同一个数据库陆续装不同公司）

如果目标不是新建一个单公司库，而是往一个已经装了别家公司职位的汇总库里追加（比如已经有"2026校招实习职位汇总"，这次抓的是第N家公司）：

1. 先 `notion-fetch` 看一下目标库现有 schema 里有没有"公司"这个字段。没有就用 `notion-update-data-source` 加一列：`ADD COLUMN "公司" SELECT('<已有公司1>':pink, '<已有公司2>':blue, ...)`（把这次新公司也加进选项）。
2. 第2步 `build_notion_pages.py` 加 `--company "<这家公司名>"`，生成的每条页面会自动带上"公司"标签，不用写完再手动补。
3. 第3步 `push_notion_pages.py` 不用改任何参数——它默认就把"公司"当 select 处理，且去重检查是全库范围的（按链接），不会跟其他公司的条目混淆，也不会重复写。
4. 不要像手工合并三个独立库那样再走"建库→迁移页面→事后打标签"的路——那是没有 `--company`/去重机制时的临时补救手段（这次真这么干过一回，纯手工 schema 改造+迁移+查重，很费事），现在已经是第一等公民支持，直接从生成阶段就做对。

---

## 配置参考

| 用途 | 默认 | 环境变量/参数 | 缺失时的降级 |
|---|---|---|---|
| 拆分+结构化抽取模型 | `deepseek-v4-flash` | `split_jobs_from_raw.py` 的 `--model` / `JOB_EXTRACT_MODEL` | 没有 `--no-model` 兜底，没 key 退回手写正则 + `extract_jobs.py --no-model` |
| 模型 base_url | `https://api.deepseek.com/v1` | `--base-url` / `JOB_EXTRACT_BASE_URL` | 同上 |
| 模型 key 环境变量名 | `DEEPSEEK_API_KEY` | `--key-env` / `JOB_EXTRACT_KEY_ENV` | 同上 |
| 职位解读+准备建议 | 同上三项 | `interpret_jobs.py` 的 `--model/--base-url/--key-env` | 没 key 就跳过整步，不带这两段，无规则兜底 |
| 推荐优先级 | 同上三项 | `recommend_priority.py` 的同名参数 | 没 key/没背景就跳过，优先级留空 |
| 大批量预筛 | 同上三项 | `prefilter_large_batch.py` 的同名参数 | 没 key 就只能靠网站类别筛选器，或全量跑后面步骤（慢） |
| 抓取-首选 | 纯 curl/urllib（`fetch_api_paginated.py`） | 需要先逆向出接口（见 references） | 退到 OpenCLI DOM 提取 |
| 抓取-备选 | OpenCLI 浏览器桥 | 需要 `opencli` 安装 + Chrome 扩展已连接，且没有别的扩展占用 `chrome.debugger` | 退到 WebFetch，再退到用户粘贴 |
| 输出-Notion | 建库用 Notion MCP，写页面用 `push_notion_pages.py` 直连 REST API（自动按链接去重，多公司汇总库用 `build_notion_pages.py --company` 打标签） | 建库需对话连 Notion MCP；写页面需 `NOTION_API_TOKEN`（internal integration secret）+ 该集成已连接到目标数据库 | 没 token 就退到 Obsidian 或纯 Markdown，别用 MCP 工具硬写大批量页面正文（费 token） |
| 输出-Obsidian | Bases 插件 | 需要 vault 路径（问用户） | 退到纯 Markdown |
| 输出-Markdown | 无依赖 | 只需要 Write 工具 | 这是兜底，没有更低一级 |

## 最小可用版本（zero-config 路径）

什么插件都没装、什么 key 都没配，仍然能跑通：

```bash
# 1. 抓（WebFetch，仅限非 SPA 静态页；SPA 就让用户粘贴内容到一个文件）
# 2. 手动/简单正则把内容切成 {job_id: raw_text} 存成 raw.json
python3 extract_jobs.py raw.json out.json --no-model
python3 render_markdown.py out.json --mode single --out 职位汇总.md --title "XX校招"
```

产出一份未经模型清洗、但完整无遗漏的单文件 Markdown（没有职位解读/准备建议/推荐优先级，因为这三步都要模型）。后续随时可以补上模型 key 重新跑第 3/4/5 步把它结构化、加解读建议、加打分，或换更高级的输出目标——产物是分阶段叠加的，不需要推倒重来。

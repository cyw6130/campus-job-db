# campus-job-db

A [Claude Code](https://github.com/anthropics/claude-code) skill that turns any company's campus/social recruitment listing page into a structured, filterable job database — scrape → structure → (optional) personalized interpretation & priority scoring → output to Notion / Obsidian / a single Markdown file.

把任何公司的校招/社招职位列表页，自动变成结构化、可筛选排序的职位库——抓取 → 结构化 → （可选）按你的背景生成职位解读 + 推荐打分 → 输出到 Notion / Obsidian / 一份 Markdown。在 Claude Code 里跟它说一句话，剩下的全自动。

## 为什么轻量

所有脚本**零 pip 依赖**，只用 Python 标准库（`urllib`/`json`/`argparse`）。装好 Python 3（macOS/大多数 Linux 自带）和 [Claude Code](https://github.com/anthropics/claude-code) 就能跑，不需要 `pip install` 任何东西。

## 安装

把这个仓库放进 Claude Code 的 skills 目录（全局生效）：

```bash
git clone https://github.com/cyw6130/campus-job-db ~/.claude/skills/campus-job-db
```

只想在某个项目里用，放进项目根目录的 `.claude/skills/campus-job-db` 也可以，只对该项目生效。

装完新开一个 Claude Code 对话，它会自动识别这个 skill，不需要额外注册步骤。

## 快速开始

在 Claude Code 里直接说：

> 帮我抓 XX公司 的校招实习职位，整理成职位库

Claude 会先跑一遍环境自检（`scripts/check_setup.sh`），告诉你当前能解锁到哪一档，然后按下面的分级往下走——**每一档缺了什么就少什么功能，但不会因为缺一个东西就整体跑不起来**：

1. **什么都没配**（没有模型 key、没装任何检索工具）→ 照样能跑，靠内置 WebFetch 抓取 + 规则切分，产出一份未结构化但完整的 Markdown 汇总。
2. **配了模型 key**（推荐 [DeepSeek](https://platform.deepseek.com) 的 `DEEPSEEK_API_KEY`，OpenAI 兼容接口，价格便宜；其实任何 OpenAI 兼容接口都行）→ 解锁结构化抽取 + 职位解读 + 准备建议。
3. **再告诉它你的求职背景**（一段话：校招还是社招、毕业时间/可到岗时间、感兴趣方向、技能背景）→ 解锁按你的情况打推荐优先级（0–5 分），以及"这个岗位的硬性门槛跟你冲不冲突"的资格提示。
4. **想要更高级的输出目标**（Notion 数据库 / Obsidian 笔记库）→ 按需配置，没配就退回纯 Markdown，不会卡住整个流程。

## 它在做什么（流程概览）

```
1. 确定公司/URL + 你的求职意向（一次性问清楚，不会审问式连续追问）
2. 抓取职位列表：优先找网站自己的数据接口直连；没有就退到浏览器抓取
3. 模型把原始内容拆成结构化字段（职位名称/工作内容/任职要求/类别等）
4. 模型生成"职位解读 + 资格提示 + 准备建议"
5.（可选）按你的背景给每个职位打推荐优先级
6. 输出：Notion 数据库 / Obsidian 笔记库 / 单文件 Markdown
```

完整细节——每一步具体用哪个脚本、怎么处理几百条规模的数据、怎么找到网站自己的数据接口直连而不用碰浏览器——都写在 [`SKILL.md`](SKILL.md) 里。那份文档是给 Claude 看的操作手册，但写得足够清楚，人也能直接读懂整套方法论。

## 需要什么（按你想用的功能，从下往上加）

| 想要的功能 | 需要什么 | 不配会怎样 |
|---|---|---|
| 抓职位列表 + 出一份 Markdown 汇总 | 不需要任何配置 | 这是兜底路径，永远能跑 |
| 结构化抽取 + 职位解读 + 准备建议 | 一个 OpenAI 兼容的模型 API key（推荐设 `DEEPSEEK_API_KEY`） | 跳过这几步，只给工作内容/任职要求的原始整理 |
| 按你的背景打推荐优先级 | 同上，外加愿意告诉它你的背景 | 跳过，优先级留空 |
| 抓取 JS 渲染的复杂网站（且网站没有可直连的公开数据接口） | 一个浏览器自动化工具（如 [OpenCLI](https://github.com/jackwener/opencli)） | 退到内置 WebFetch，遇到纯前端渲染、需要登录的网站可能抓不到 |
| 输出到 Notion 数据库 | Claude Code 里连好 Notion 集成 + 一个 Notion internal integration secret（环境变量 `NOTION_API_TOKEN`，去 [notion.com/my-integrations](https://www.notion.com/my-integrations) 创建，并在目标数据库的 Connections 里手动连接它） | 改用 Obsidian 或 Markdown |
| 输出到 Obsidian | 一个装了 Bases 插件的 vault（较新版本自带） | 改用 Markdown |

## 脚本一览

`scripts/` 下每个脚本都能单独跑（`python3 <script>.py --help` 看参数），但正常使用不需要你自己调——跟 Claude 说清楚需求，它会照 `SKILL.md` 的流程自己选脚本、传参数、串起整条流水线。

| 脚本 | 干什么 |
|---|---|
| `check_setup.sh` | 环境自检，永远第一步先跑这个 |
| `fetch_api_paginated.py` | 找到网站数据接口后，直连翻页拉全量数据 |
| `split_jobs_from_raw.py` | 没有数据接口、靠抓原始文本时，用模型识别职位边界并结构化 |
| `structure_from_api.py` | 数据接口返回的内容已经干净时，跳过模型拆分，直接结构化 |
| `extract_jobs.py` | 输入已经是预先分好的职位文本时用，带 `--no-model` 零依赖兜底模式 |
| `prefilter_large_batch.py` | 职位数量很大（几百条）时，先批量粗筛缩小范围，省下后面的模型调用 |
| `interpret_jobs.py` | 生成职位解读 + 资格提示 + 准备建议 |
| `recommend_priority.py` | 按你的背景给每个职位打 0–5 分推荐优先级 |
| `render_markdown.py` | 渲染成单文件 Markdown 或 Obsidian 笔记 |
| `build_notion_pages.py` | 组装 Notion 页面数据（支持 `--company` 给多公司汇总库打标签） |
| `push_notion_pages.py` | 直连 Notion REST API 批量写入，写入前自动按链接去重 |

## 关于 SKILL.md 里提到的"专门的子 agent"

`SKILL.md` 里有几处提到"如果你配置了专门做 XX 的子 agent"——那是指 Claude Code 里可以额外配置的自定义子 agent（比如统一管理 API key 的、专职做网页检索的）。这些都是**可选的效率优化**，是原作者自己机器上的个人配置，不是这个 skill 的依赖项。没有这些子 agent，Claude 会自动照普通方式直接完成同样的工作，不影响功能。

## License

MIT，见 [LICENSE](LICENSE)。

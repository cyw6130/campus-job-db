#!/usr/bin/env bash
# Environment doctor for the campus-job-db skill.
# Run this first to see what's available and what will degrade.

echo "== campus-job-db 环境自检 =="
echo

echo "[1/4] 模型 API（用于结构化抽取 / 推荐打分，默认 deepseek-v4-flash）"
found_key=0
for var in DEEPSEEK_API_KEY OPENAI_API_KEY; do
  if [ -n "${!var}" ]; then
    echo "  OK   \$$var 已设置"
    found_key=1
  fi
done
if [ "$found_key" -eq 0 ]; then
  echo "  MISS 没有找到任何模型 key（DEEPSEEK_API_KEY / OPENAI_API_KEY）"
  echo "       -> 调用 toolbox / api-key-manager agent 帮忙定位或配置"
  echo "       -> 或者用 extract_jobs.py --no-model 走最小可用（未结构化）模式"
fi
echo

echo "[2/4] 抓取渠道"
if command -v opencli >/dev/null 2>&1; then
  echo "  OK   已安装 opencli"
  opencli doctor 2>&1 | grep -E "Daemon|Extension|Connectivity" | sed 's/^/       /'
else
  echo "  MISS 未安装 opencli"
  echo "       -> 退化为只能用 WebFetch 抓静态页面；遇到 SPA/JS 渲染/登录页会失败"
  echo "       -> 失败时可以请用户直接截图或粘贴职位列表文本"
fi
echo

echo "[3/4] 输出渠道 - Notion"
echo "  提示  建库通过对话里已加载的 Notion MCP 工具"
echo "        (mcp__plugin_Notion_notion__* 或 mcp__notion__*) 操作。"
echo "        用 ToolSearch 搜 'notion create database' 看是否已连接。"
if [ -n "$NOTION_API_TOKEN" ]; then
  echo "  OK   \$NOTION_API_TOKEN 已设置（写入页面用的 push_notion_pages.py 需要它）"
else
  echo "  MISS 未设置 \$NOTION_API_TOKEN"
  echo "       -> 写入页面这一步（push_notion_pages.py）需要一个 internal integration secret"
  echo "          （去 https://www.notion.com/my-integrations 创建，不是 MCP 那套 OAuth 授权）"
  echo "       -> 且该集成要手动连接到目标数据库（数据库 ··· 菜单 -> Connections），否则 401"
fi
echo

echo "[4/4] 输出渠道 - Obsidian"
if [ -n "$OBSIDIAN_VAULT" ]; then
  echo "  OK   \$OBSIDIAN_VAULT=$OBSIDIAN_VAULT"
else
  echo "  INFO 未设置 \$OBSIDIAN_VAULT，运行时直接问用户 vault 根目录路径即可"
fi
echo

echo "== 最小可用路径 =="
echo "  只要有 Bash + Write 工具（始终具备），就能走："
echo "  WebFetch 抓静态页 -> --no-model 跳过模型抽取 -> render_markdown.py --mode single"
echo "  产出一份未结构化但完整的单文件 markdown 汇总，零插件零 key 依赖。"

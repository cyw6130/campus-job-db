#!/usr/bin/env python3
"""Split + structure raw scraped job-listing text directly via a configurable
model — replaces hand-written regex splitting. Feed it the raw scraped
chunks as-is (e.g. each `opencli browser ... extract` chunk saved to its own
file); the model identifies job boundaries itself instead of relying on a
fixed anchor pattern, so it generalizes across sites with different markup.

Input:  one or more raw text files (chunks of the scraped page; order doesn't
        matter — duplicate jobs across chunks, e.g. from a "最新职位" sidebar,
        are expected and deduped by job_id)
Output: structured jobs JSON, same shape as extract_jobs.py's output, so it
        feeds straight into interpret_jobs.py / recommend_priority.py /
        render_markdown.py without any extra step.
"""
import argparse
import json
import os
import sys
import urllib.request

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"

SYSTEM_PROMPT = (
    "你是招聘信息结构化助手。输入是从某公司招聘列表页直接抓取的原始 markdown 文本片段，"
    "里面混杂着多条职位信息、导航栏、页脚、侧边栏“最新职位”等无关内容。"
    "你需要先识别出这段文本里包含哪些独立的职位条目（通常每条以类似 "
    "[职位名 发布于 日期 ... 职位描述...](#/job/<id>) 的锚点结构出现，"
    "但具体站点格式可能不同，需要靠标题+发布日期+完整职位描述正文的重复模式自行判断边界），"
    "然后对识别出的每个职位输出结构化字段。"
    "纯导航/页脚/侧边栏里那种只有标题没有完整职位描述正文的重复链接，不要当作独立职位输出。"
)

USER_TEMPLATE = """请从下面的原始文本中识别并抽取所有职位，严格输出 JSON：{{"jobs": [...]}}，每个元素：
- job_id: 优先从锚点链接里的 ID 提取（如 #/job/<id> 里的 <id>，或其他形式的稳定职位 ID）；
  如果文本里没有这种锚点，就用职位标题生成一个稳定 slug——同一个职位在文本里多次出现时
  必须给出完全相同的 job_id，方便后续按 job_id 去重。
- title: 职位名称（去掉"急"等前缀标记）
- employment_type: 全职/实习/兼职（没有则空字符串）
- category: 职能类别（如算法类/技术类/产品类/设计类/运营类/市场类/职能类，没有明确分类就按内容自行归类）
- location: 工作地点（没有则空字符串）
- post_date: 发布日期（没有则空字符串）
- duties: 工作内容/岗位职责，字符串数组，每条一条（不要带开头的 "- "），尽量保留原文措辞
- requirements: 任职要求/任职资格，字符串数组，含必须项和加分项，同上格式

关于 duties 和 requirements 的拆分，**不要机械地只认"任职要求："这种小标题**：
- 很多职位描述把职责和要求混在一段里、或只有一个统称（如"岗位描述""我们希望你"），你要按**语义**判断每句话是"这个岗位要做什么"(→duties) 还是"应聘者需要具备什么"(→requirements)，分别归类。
- 表述要求的常见信号：学历/专业/年级、"熟悉/掌握/具备/有…经验"、"优先""加分""扎实""能够"、技能工具点名等——见到这类即归入 requirements，哪怕原文没有"任职要求"四个字。
- 只有当某个职位的原文**确实通篇只讲做什么、完全没提对人的要求**时，requirements 才留空数组。不要因为"没看到标准小标题"就草率给空。
- 反过来同理：别把对人的要求误塞进 duties。

只输出 JSON，不要任何额外说明文字。

原始文本：
{chunk}
"""


def call_model(chunk: str, model: str, base_url: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(chunk=chunk)},
        ],
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]


def merge_job(existing: dict, new: dict) -> dict:
    """Keep whichever version has more total content (handles partial
    duplicates from sidebars / repeated chunks)."""

    def richness(j: dict) -> int:
        return len(j.get("duties", [])) + len(j.get("requirements", []))

    return new if richness(new) > richness(existing) else existing


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_files", nargs="+", help="raw scraped text chunk file(s)")
    ap.add_argument("output_json")
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    ap.add_argument(
        "--max-chunk-chars",
        type=int,
        default=14000,
        help="raw_files larger than this get split further before calling the model "
        "(keeps prompts well within context/output limits)",
    )
    args = ap.parse_args()

    api_key = os.environ.get(args.key_env)
    if not api_key:
        print(
            f"ERROR: env var {args.key_env} not set.\n"
            f"  -> Ask the toolbox/api-key-manager agent to locate or configure it.\n"
            f"  -> 这一步没有 --no-model 兜底（拆分职位边界本身就是需要理解上下文的判断，"
            f"规则切分对不同站点格式不通用）；没 key 就只能回退到手写正则切分。",
            file=sys.stderr,
        )
        sys.exit(1)

    chunks: list[str] = []
    for fp in args.raw_files:
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        for i in range(0, len(text), args.max_chunk_chars):
            chunks.append(text[i : i + args.max_chunk_chars])

    print(f"{len(args.raw_files)} file(s) -> {len(chunks)} model call(s)", file=sys.stderr)

    by_id: dict[str, dict] = {}
    failed_chunks: list[str] = []

    for i, chunk in enumerate(chunks, 1):
        print(f"chunk {i}/{len(chunks)} ({len(chunk)} chars)...", file=sys.stderr)
        try:
            content = call_model(chunk, args.model, args.base_url, api_key)
            parsed = json.loads(content)
            for j in parsed.get("jobs", []):
                jid = j.get("job_id")
                if not jid:
                    continue
                by_id[jid] = merge_job(by_id[jid], j) if jid in by_id else j
        except Exception as e:  # noqa: BLE001
            print(f"  chunk failed: {e}", file=sys.stderr)
            failed_chunks.append(chunk)

    if failed_chunks:
        print(f"retrying {len(failed_chunks)} failed chunk(s) with half-size split...", file=sys.stderr)
        for chunk in failed_chunks:
            half = len(chunk) // 2
            for sub in (chunk[:half], chunk[half:]):
                try:
                    content = call_model(sub, args.model, args.base_url, api_key)
                    parsed = json.loads(content)
                    for j in parsed.get("jobs", []):
                        jid = j.get("job_id")
                        if not jid:
                            continue
                        by_id[jid] = merge_job(by_id[jid], j) if jid in by_id else j
                except Exception as e:  # noqa: BLE001
                    print(f"  still failed: {e}", file=sys.stderr)

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(list(by_id.values()), f, ensure_ascii=False, indent=2)
    print(f"extracted {len(by_id)} unique jobs -> {args.output_json}")


if __name__ == "__main__":
    main()

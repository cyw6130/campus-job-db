#!/usr/bin/env python3
"""Turn raw scraped job-posting text into structured JSON via a configurable
OpenAI-compatible chat model (default: DeepSeek deepseek-v4-flash).

Input:  JSON file {job_id: raw_text, ...}
Output: JSON file [{job_id, title, employment_type, category, location,
                     post_date, duties[], requirements[]}, ...]
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"

SYSTEM_PROMPT = (
    "你是招聘信息结构化助手。输入是从公司校招页面抓取的职位原始文本"
    "(每条以 JOB_ID 分隔，文本里职位描述往往先有一段无格式的纯文本摘要，"
    "后面跟着同样内容但带项目符号/加粗的格式化版本——只需基于格式化版本输出，"
    "忽略前面重复的纯文本摘要)。"
)

USER_TEMPLATE = """请对每个 JOB_ID 抽取以下字段，严格输出 JSON：{{"jobs": [...]}}，每个元素：
- job_id: 原始 JOB_ID
- title: 职位名称（去掉"急"等前缀标记）
- employment_type: 全职/实习/兼职
- category: 职能类别（如算法类/技术类/产品类/设计类/运营类/市场类/职能类，没有明确分类就按内容自行归类）
- location: 工作地点（没有则空字符串）
- post_date: 发布日期（没有则空字符串）
- duties: 工作内容/岗位职责，字符串数组，每条一条（不要带开头的 "- "），尽量保留原文措辞
- requirements: 任职要求/任职资格，字符串数组，含必须项和加分项，同上格式

关于 duties 和 requirements 的拆分，**不要机械地只认"任职要求："这种小标题**：
- 职责和要求常混在一段、或只有统称（如"岗位描述""我们希望你"），按**语义**判断每句是"岗位要做什么"(→duties) 还是"应聘者要具备什么"(→requirements)。
- 要求的信号：学历/专业/年级、"熟悉/掌握/具备/有…经验"、"优先/加分/扎实/能够"、技能工具点名等——见到即归 requirements，哪怕没出现"任职要求"字样。
- 只有原文确实通篇只讲做什么、完全没提对人的要求时，requirements 才留空。别因没看到标准小标题就草率给空。

只输出 JSON，不要任何额外说明文字。

原始数据：
{jobs_text}
"""


def call_model(jobs_text: str, model: str, base_url: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(jobs_text=jobs_text)},
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


def fallback_extract(job_id: str, body: str) -> dict:
    """No-model degraded mode: dump raw text as a single duty line, unstructured."""
    return {
        "job_id": job_id,
        "title": body.strip().split("\n", 1)[0][:80] or job_id,
        "employment_type": "",
        "category": "未分类",
        "location": "",
        "post_date": "",
        "duties": [body.strip()],
        "requirements": [],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_json", help="JSON file: {job_id: raw_text, ...}")
    ap.add_argument("output_json")
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    ap.add_argument("--batch-size", type=int, default=6)
    ap.add_argument(
        "--no-model",
        action="store_true",
        help="Skip the model call entirely (minimum-viable degraded mode): "
        "dumps each job's raw text unstructured instead of failing.",
    )
    args = ap.parse_args()

    with open(args.input_json, encoding="utf-8") as f:
        jobs = json.load(f)
    items = list(jobs.items())

    if args.no_model:
        results = [fallback_extract(jid, body) for jid, body in items]
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[no-model mode] wrote {len(results)} unstructured jobs -> {args.output_json}")
        return

    api_key = os.environ.get(args.key_env)
    if not api_key:
        print(
            f"ERROR: env var {args.key_env} is not set.\n"
            f"  -> Ask the toolbox/api-key-manager agent to locate or configure it, "
            f"or pass --key-env pointing at the right variable, "
            f"or rerun with --no-model for the degraded (unstructured) path.",
            file=sys.stderr,
        )
        sys.exit(1)

    batches = [items[i : i + args.batch_size] for i in range(0, len(items), args.batch_size)]
    results = []
    failed = []

    for i, batch in enumerate(batches, 1):
        jobs_text = "".join(f"\n=== JOB_ID: {jid} ===\n{body}\n" for jid, body in batch)
        print(f"batch {i}/{len(batches)} ({len(batch)} jobs)...", file=sys.stderr)
        try:
            content = call_model(jobs_text, args.model, args.base_url, api_key)
            parsed = json.loads(content)
            results.extend(parsed.get("jobs", parsed if isinstance(parsed, list) else []))
        except Exception as e:  # noqa: BLE001
            print(f"  batch failed: {e}", file=sys.stderr)
            failed.extend(batch)

    if failed:
        print(f"retrying {len(failed)} jobs in smaller batches of 3...", file=sys.stderr)
        for i in range(0, len(failed), 3):
            sub = failed[i : i + 3]
            jobs_text = "".join(f"\n=== JOB_ID: {jid} ===\n{body}\n" for jid, body in sub)
            try:
                content = call_model(jobs_text, args.model, args.base_url, api_key)
                parsed = json.loads(content)
                results.extend(parsed.get("jobs", parsed if isinstance(parsed, list) else []))
            except Exception as e:  # noqa: BLE001
                print(f"  still failed for {[jid for jid, _ in sub]}: {e}", file=sys.stderr)
                results.extend(fallback_extract(jid, body) for jid, body in sub)

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"extracted {len(results)}/{len(items)} jobs -> {args.output_json}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Ask a configurable model to score each job 0-5 against a free-text user
profile. Reuses the same model config knobs as extract_jobs.py.

Output: JSON {job_id: priority_int, ...}
"""
import argparse
import json
import os
import sys
import urllib.request

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"


def call_model(prompt: str, model: str, base_url: str, api_key: str, max_tokens: int = 4000) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs_json")
    ap.add_argument("profile", help="用户背景/求职偏好描述文本")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    args = ap.parse_args()

    api_key = os.environ.get(args.key_env)
    if not api_key:
        print(
            f"ERROR: env var {args.key_env} not set. This step requires a model call "
            f"(it's a judgment call, not pure structuring) — there's no no-model fallback. "
            f"Ask the toolbox/api-key-manager agent to locate the key, or skip this step "
            f"and rank manually.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.jobs_json, encoding="utf-8") as f:
        jobs = json.load(f)

    # Keep the prompt light: title/category/requirements only, not full duties text.
    brief = [
        {
            "job_id": j["job_id"],
            "title": j["title"],
            "category": j.get("category"),
            "requirements": j.get("requirements", [])[:6],
        }
        for j in jobs
    ]

    prompt = f"""用户背景：{args.profile}

以下是候选职位列表(JSON)，请根据用户背景给每个职位打 0-5 的匹配优先级(5=最推荐，0=不建议)。
打分要基于任职要求与用户背景的真实匹配度，不要因为职位名称好听就给高分；
明显超出用户能力/兴趣范围（如要求竞赛获奖、强编程背景但用户明确说代码弱）应给低分或 0。

只输出 JSON: {{"priorities": {{"<job_id>": <0-5>, ...}}}}，不要其他文字。

职位列表：
{json.dumps(brief, ensure_ascii=False)}
"""
    content = call_model(prompt, args.model, args.base_url, api_key)
    parsed = json.loads(content)
    priorities = parsed.get("priorities", {})

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(priorities, f, ensure_ascii=False, indent=2)
    print(f"wrote priorities for {len(priorities)} jobs -> {args.out}")


if __name__ == "__main__":
    main()

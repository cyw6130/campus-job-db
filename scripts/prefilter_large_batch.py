#!/usr/bin/env python3
"""For large raw job dumps (e.g. 200+ from fetch_api_paginated.py): cheaply
match+score every job in ONE pass (title/duty/qualification snippets only,
no full interpretation) so you don't waste interpret_jobs.py calls on jobs
that don't fit. Run this BEFORE extract_jobs.py / interpret_jobs.py — only
feed the matched subset into the expensive per-job pipeline.

Input fields expected per raw job dict (use --field-map to remap if your API
uses different key names): title, duty, qualification, jobType, id.

Output: {id: {"match": bool, "score": 0-5}, ...}
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        d = json.loads(resp.read())
        return d["choices"][0]["message"]["content"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_jobs_json", help="array of raw job dicts (from fetch_api_paginated.py or similar)")
    ap.add_argument("profile", help="用户求职意向/背景，决定方向与门槛判断标准")
    ap.add_argument("--out", required=True)
    ap.add_argument("--id-field", default="id")
    ap.add_argument("--title-field", default="title")
    ap.add_argument("--duty-field", default="duty")
    ap.add_argument("--qualification-field", default="qualification")
    ap.add_argument("--jobtype-field", default="jobType")
    ap.add_argument("--snippet-chars", type=int, default=300, help="truncate duty/qualification to keep prompts cheap")
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    args = ap.parse_args()

    api_key = os.environ.get(args.key_env)
    if not api_key:
        print(f"ERROR: env var {args.key_env} not set.", file=sys.stderr)
        sys.exit(1)

    with open(args.raw_jobs_json, encoding="utf-8") as f:
        jobs = json.load(f)

    def brief(j):
        return {
            "id": j.get(args.id_field),
            "name": j.get(args.title_field, ""),
            "jobType": j.get(args.jobtype_field, ""),
            "duty": (j.get(args.duty_field) or "")[: args.snippet_chars],
            "qualification": (j.get(args.qualification_field) or "")[: args.snippet_chars],
        }

    results = {}
    batches = [jobs[i : i + args.batch_size] for i in range(0, len(jobs), args.batch_size)]
    for i, batch in enumerate(batches, 1):
        prompt = f"""用户背景：
{args.profile}

以下是候选职位（JSON），请对每个职位判断：
- match: 是否值得进入候选池（true/false）。方向要匹配用户明确想要的领域，门槛要对用户背景友好
  （不要因为用户没提到的硬性要求就误判——只用用户背景里明确说的限制来卡）。
- score: 0-5整数，match为false时给0，match为true时按匹配程度打分。

只输出JSON: {{"result": {{"<id>": {{"match": true/false, "score": N}}, ...}}}}，不要其他文字。

职位列表：
{json.dumps([brief(j) for j in batch], ensure_ascii=False)}
"""
        try:
            content = call_model(prompt, args.model, args.base_url, api_key)
            results.update(json.loads(content).get("result", {}))
            print(f"batch {i}/{len(batches)}: ok", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"batch {i}/{len(batches)} FAILED: {e} — retrying in chunks of 5", file=sys.stderr)
            for j in range(0, len(batch), 5):
                sub = batch[j : j + 5]
                try:
                    content = call_model(
                        prompt.replace(
                            json.dumps([brief(b) for b in batch], ensure_ascii=False),
                            json.dumps([brief(b) for b in sub], ensure_ascii=False),
                        ),
                        args.model,
                        args.base_url,
                        api_key,
                    )
                    results.update(json.loads(content).get("result", {}))
                except Exception as e2:  # noqa: BLE001
                    print(f"  sub-batch failed too: {e2}", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    matched = sum(1 for r in results.values() if r.get("match"))
    print(f"DONE: {len(results)} scored, {matched} matched -> {args.out}")


if __name__ == "__main__":
    main()

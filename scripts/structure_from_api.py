#!/usr/bin/env python3
"""When the source API already returns clean duty/qualification text (no DOM
noise to strip), skip the model-based split_jobs_from_raw.py entirely — just
map fields + split bullets by regex, then optionally classify category with
one cheap model pass. Much cheaper than re-deriving structure from scratch.

Input: array of raw job dicts (e.g. filtered output from fetch_api_paginated.py)
Output: array matching extract_jobs.py's structured schema, ready for
        interpret_jobs.py / recommend_priority.py / render_markdown.py.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"

CATEGORIES = ["算法类", "技术类", "产品类", "设计类", "运营类", "市场类", "职能类"]


def split_bullets(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"\n+|(?<=\D)\s*\d+[\.、]\s*", text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 2]


def call_model(prompt: str, model: str, base_url: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
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


def classify_categories(jobs: list[dict], model: str, base_url: str, api_key: str) -> dict:
    """One cheap batched pass: title + jobType -> one of CATEGORIES."""
    results = {}
    batch_size = 40
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        brief = [{"id": j["job_id"], "name": j["title"], "jobType": j.get("_jobtype", "")} for j in batch]
        prompt = f"""请给每个职位归类到一个大类：{'/'.join(CATEGORIES)}。
只根据职位名称(name)和细分岗位(jobType)判断。
只输出JSON: {{"result": {{"<id>": "<类别>", ...}}}}，不要其他文字。

职位列表：
{json.dumps(brief, ensure_ascii=False)}
"""
        try:
            content = call_model(prompt, model, base_url, api_key)
            results.update(json.loads(content).get("result", {}))
        except Exception as e:  # noqa: BLE001
            print(f"classify batch failed: {e}", file=sys.stderr)
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_jobs_json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--id-field", default="id")
    ap.add_argument("--title-field", default="title")
    ap.add_argument("--duty-field", default="duty")
    ap.add_argument("--qualification-field", default="qualification")
    ap.add_argument("--location-field", default="workplace")
    ap.add_argument("--date-field", default="publishTime")
    ap.add_argument("--jobtype-field", default="jobType")
    ap.add_argument("--employment-type", default="实习", help="static value, since API often filters this already")
    ap.add_argument("--classify-category", action="store_true", help="run one model pass to fill category field")
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    args = ap.parse_args()

    with open(args.raw_jobs_json, encoding="utf-8") as f:
        raw = json.load(f)

    structured = []
    for j in raw:
        structured.append(
            {
                "job_id": str(j.get(args.id_field)),
                "title": j.get(args.title_field, ""),
                "employment_type": args.employment_type,
                "category": "",
                "location": j.get(args.location_field, "") or "",
                "post_date": j.get(args.date_field, "") or "",
                "duties": split_bullets(j.get(args.duty_field, "")),
                "requirements": split_bullets(j.get(args.qualification_field, "")),
                "_jobtype": j.get(args.jobtype_field, ""),
            }
        )

    if args.classify_category:
        api_key = os.environ.get(args.key_env)
        if not api_key:
            print(f"ERROR: --classify-category needs {args.key_env} set", file=sys.stderr)
            sys.exit(1)
        cats = classify_categories(structured, args.model, args.base_url, api_key)
        for s in structured:
            s["category"] = cats.get(s["job_id"], "技术类")
    else:
        for s in structured:
            s["category"] = "技术类"

    for s in structured:
        s.pop("_jobtype", None)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)
    print(f"structured {len(structured)} jobs -> {args.out}")


if __name__ == "__main__":
    main()

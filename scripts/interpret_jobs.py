#!/usr/bin/env python3
"""Add a plain-language interpretation and prep-advice to each structured job,
via a configurable OpenAI-compatible chat model. Reuses the same model knobs
as extract_jobs.py / recommend_priority.py.

Input:  structured jobs JSON (array, from extract_jobs.py)
Output: same array, each job gains:
  - interpretation: str  (这个岗位实际在做什么、门槛/竞争程度、跟公司业务的关系)
  - prep_advice: list[str]  (申请前的准备建议：作品集/简历侧重/技能补齐)
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
    "你是资深招聘顾问，擅长帮求职者读懂职位描述背后的真实意图，并给出可执行的申请准备建议。"
    "不要说空话（比如“提升沟通能力”），要具体、可操作。"
)

USER_TEMPLATE = """{profile_block}以下是结构化后的职位信息(JSON，每条含 job_id/title/category/employment_type/duties/requirements)。
请对每个 job_id 输出：
- interpretation: 2-4 句话的职位解读。说清楚：这个岗位实际在做什么（去掉营销话术后的本质工作）、
  门槛/竞争激烈程度大致如何判断依据是什么（如学历/竞赛/顶会要求）、这个岗位在公司业务里大致是什么位置。
- prep_advice: 3-6 条字符串数组，申请前的具体准备建议（简历该强调什么、作品集/项目该准备什么、
  有没有明显的技能缺口需要补、投递时机或材料上有什么注意事项）。{profile_advice_note}
- eligibility_note: 字符串，**只有**用户背景里提到了毕业时间/可到岗时间/实习时长/校招还是社招这类硬性信息，
  且职位要求里写了对应的硬性门槛（比如"2027届优先""实习6个月以上""每周到岗5天"）时才填，
  明确指出用户是否满足、哪里冲突；如果背景没提这些信息，或者职位本身没写这类门槛，这个字段填空字符串，不要编造。

只输出 JSON: {{"jobs": [{{"job_id": "...", "interpretation": "...", "prep_advice": ["...", ...], "eligibility_note": "..."}}, ...]}}，
不要任何额外说明文字。

职位数据：
{jobs_text}
"""


def call_model(prompt: str, model: str, base_url: str, api_key: str, max_tokens: int = 6000) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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
    ap.add_argument("jobs_json", help="structured jobs JSON from extract_jobs.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--profile", default="", help="可选：用户背景，给出针对性准备建议而非通用建议")
    ap.add_argument("--model", default=os.environ.get("JOB_EXTRACT_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base-url", default=os.environ.get("JOB_EXTRACT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--key-env", default=os.environ.get("JOB_EXTRACT_KEY_ENV", DEFAULT_KEY_ENV))
    ap.add_argument("--batch-size", type=int, default=5)
    args = ap.parse_args()

    api_key = os.environ.get(args.key_env)
    if not api_key:
        print(
            f"ERROR: env var {args.key_env} not set. 这一步必须调模型才能产出有意义的解读/建议，"
            f"没有兜底模式——先在第 0 步问清楚用户要不要配 key，不要跳过这步直接补空字段。",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.jobs_json, encoding="utf-8") as f:
        jobs = json.load(f)

    profile_block = f"用户背景：{args.profile}\n\n" if args.profile else ""
    profile_advice_note = (
        " 结合用户背景给针对性建议（比如背景里说代码弱，就别建议“刷算法题”）。"
        if args.profile
        else ""
    )

    by_id = {j["job_id"]: j for j in jobs}
    items = list(by_id.items())
    batches = [items[i : i + args.batch_size] for i in range(0, len(items), args.batch_size)]
    annotated: dict[str, dict] = {}
    failed_ids: list[str] = []

    for i, batch in enumerate(batches, 1):
        brief = [
            {
                "job_id": jid,
                "title": j["title"],
                "category": j.get("category"),
                "employment_type": j.get("employment_type"),
                "duties": j.get("duties", []),
                "requirements": j.get("requirements", []),
            }
            for jid, j in batch
        ]
        prompt = USER_TEMPLATE.format(
            profile_block=profile_block,
            profile_advice_note=profile_advice_note,
            jobs_text=json.dumps(brief, ensure_ascii=False),
        )
        print(f"batch {i}/{len(batches)} ({len(batch)} jobs)...", file=sys.stderr)
        try:
            content = call_model(prompt, args.model, args.base_url, api_key)
            parsed = json.loads(content)
            for entry in parsed.get("jobs", []):
                annotated[entry["job_id"]] = entry
        except Exception as e:  # noqa: BLE001
            print(f"  batch failed: {e}", file=sys.stderr)
            failed_ids.extend(jid for jid, _ in batch)

    if failed_ids:
        print(f"retrying {len(failed_ids)} jobs one-by-one...", file=sys.stderr)
        for jid in failed_ids:
            j = by_id[jid]
            brief = [
                {
                    "job_id": jid,
                    "title": j["title"],
                    "category": j.get("category"),
                    "employment_type": j.get("employment_type"),
                    "duties": j.get("duties", []),
                    "requirements": j.get("requirements", []),
                }
            ]
            prompt = USER_TEMPLATE.format(
                profile_block=profile_block,
                profile_advice_note=profile_advice_note,
                jobs_text=json.dumps(brief, ensure_ascii=False),
            )
            try:
                content = call_model(prompt, args.model, args.base_url, api_key)
                parsed = json.loads(content)
                for entry in parsed.get("jobs", []):
                    annotated[entry["job_id"]] = entry
            except Exception as e:  # noqa: BLE001
                print(f"  still failed for {jid}: {e}", file=sys.stderr)

    for jid, j in by_id.items():
        extra = annotated.get(jid, {})
        j["interpretation"] = extra.get("interpretation", "")
        j["prep_advice"] = extra.get("prep_advice", [])
        j["eligibility_note"] = extra.get("eligibility_note", "")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(list(by_id.values()), f, ensure_ascii=False, indent=2)
    print(f"annotated {len(annotated)}/{len(items)} jobs -> {args.out}")


if __name__ == "__main__":
    main()

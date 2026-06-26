#!/usr/bin/env python3
"""Assemble the final pages JSON from annotated jobs + priority scores. Always
go through this script, never hand-construct page content yourself — manual
re-typing of unicode (brackets like 【】, full-width punctuation) is exactly
how titles get corrupted.

After running this, feed --out straight into push_notion_pages.py — don't
Read it into the assistant's context and don't paste it into an MCP tool call.
Both of those make the assistant's own context hold the same Chinese text
twice (once reading, once re-emitting as a tool argument), which is pure
token waste for content that a script can ship directly via the REST API.
"""
import argparse
import json


def render_list(items: list[str]) -> str:
    return "\n".join(f"- {x.lstrip('- ').strip()}" for x in items) if items else "- （无）"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("annotated_jobs_json", help="output of interpret_jobs.py (or extract_jobs.py if no annotation)")
    ap.add_argument("--priority-json", default="", help="output of recommend_priority.py, optional")
    ap.add_argument("--link-template", required=True, help='e.g. "https://example.com/jobs/{job_id}"')
    ap.add_argument(
        "--company",
        default="",
        help="stamp a 公司 property on every page — set this when the target database "
        "aggregates multiple companies, so push_notion_pages.py's dedupe and any "
        "by-company views/filters work without a manual schema patch later",
    )
    ap.add_argument("--sort-by-priority", action="store_true", help="order pages by priority desc before output")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.annotated_jobs_json, encoding="utf-8") as f:
        jobs = json.load(f)

    priorities = {}
    if args.priority_json:
        with open(args.priority_json, encoding="utf-8") as f:
            priorities = json.load(f)
            # recommend_priority.py output may be {id: int} or {id: {"score": int}}
            priorities = {
                k: (v.get("score", v.get("priority", 0)) if isinstance(v, dict) else v)
                for k, v in priorities.items()
            }

    if args.sort_by_priority:
        jobs = sorted(jobs, key=lambda j: -priorities.get(j["job_id"], 0))

    pages = []
    for j in jobs:
        link = args.link_template.format(job_id=j["job_id"])
        content = f"## 工作内容\n{render_list(j.get('duties', []))}\n\n## 任职要求\n{render_list(j.get('requirements', []))}"
        if j.get("interpretation"):
            content += f"\n\n## 职位解读\n{j['interpretation']}"
        if j.get("eligibility_note"):
            content += f"\n\n## ⚠️ 资格提示\n{j['eligibility_note']}"
        if j.get("prep_advice"):
            content += f"\n\n## 准备建议\n{render_list(j['prep_advice'])}"
        properties = {
            "职位名称": j["title"],
            "类型": j.get("employment_type", "实习") or "实习",
            "类别": j.get("category", "技术类") or "技术类",
            "地点": j.get("location", "") or "",
            "发布日期": j.get("post_date", "") or "",
            "推荐优先级": priorities.get(j["job_id"], 0),
            "链接": link,
        }
        if args.company:
            properties["公司"] = args.company
        pages.append({"properties": properties, "content": content})

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)
    print(f"{len(pages)} pages ready -> {args.out}")
    print("Now: python3 push_notion_pages.py {} --database-id <id>".format(args.out))
    print("(needs NOTION_API_TOKEN exported; pushes directly via REST, no MCP round-trip)")


if __name__ == "__main__":
    main()

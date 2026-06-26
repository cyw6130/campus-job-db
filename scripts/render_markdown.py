#!/usr/bin/env python3
"""Render structured job JSON into either:
  --mode single   : one combined .md file grouped by category (works anywhere,
                     no plugin required — this is the minimum-viable output).
  --mode obsidian : one .md note per job with frontmatter, for an Obsidian
                     vault folder (pair with a .base file — see SKILL.md).
"""
import argparse
import json
import os
from collections import defaultdict


def render_list(items: list[str]) -> str:
    return "\n".join(f"- {x.lstrip('- ').strip()}" for x in items) or "- （无）"


def single_markdown(jobs: list[dict], link_template: str, title: str) -> str:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_cat[j.get("category") or "未分类"].append(j)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda j: (-(j.get("priority") or 0), j.get("post_date") or ""), reverse=False)

    lines = [f"# {title}\n", f"> 共 {len(jobs)} 个职位，按职能类别分类。\n"]
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"\n## {cat}（{len(items)} 个职位）\n")
        for j in items:
            link = link_template.format(job_id=j["job_id"]) if link_template else j.get("job_id", "")
            loc = f" ｜ 📍{j['location']}" if j.get("location") else ""
            prio = f" ｜ ⭐{j['priority']}" if j.get("priority") else ""
            lines.append(f"### {j['title']}")
            lines.append(
                f"`{j.get('employment_type','')}`{loc}{prio} ｜ 发布于 {j.get('post_date','')} ｜ [原文链接]({link})\n"
            )
            lines.append("**工作内容：**")
            lines.append(render_list(j.get("duties", [])))
            lines.append("\n**任职要求：**")
            lines.append(render_list(j.get("requirements", [])))
            if j.get("interpretation"):
                lines.append("\n**职位解读：**")
                lines.append(j["interpretation"])
            if j.get("eligibility_note"):
                lines.append("\n**⚠️ 资格提示：**")
                lines.append(j["eligibility_note"])
            if j.get("prep_advice"):
                lines.append("\n**准备建议：**")
                lines.append(render_list(j["prep_advice"]))
            lines.append("")
    return "\n".join(lines)


def obsidian_notes(jobs: list[dict], link_template: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for j in jobs:
        link = link_template.format(job_id=j["job_id"]) if link_template else j.get("job_id", "")
        fm = (
            "---\n"
            f"职位名称: {j['title']}\n"
            f"类型: {j.get('employment_type','')}\n"
            f"地点: {j.get('location','')}\n"
            f"发布日期: {j.get('post_date','')}\n"
            f"类别: {j.get('category','')}\n"
            f"推荐优先级: {j.get('priority', 0)}\n"
            f"链接: {link}\n"
            "---\n\n"
        )
        body = (
            "## 工作内容\n" + render_list(j.get("duties", []))
            + "\n\n## 任职要求\n" + render_list(j.get("requirements", []))
        )
        if j.get("interpretation"):
            body += "\n\n## 职位解读\n" + j["interpretation"]
        if j.get("eligibility_note"):
            body += "\n\n## ⚠️ 资格提示\n" + j["eligibility_note"]
        if j.get("prep_advice"):
            body += "\n\n## 准备建议\n" + render_list(j["prep_advice"])
        safe_title = j["title"].replace("/", "-").replace(":", "-")[:80]
        path = os.path.join(out_dir, f"{safe_title}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm + body)
    print(f"wrote {len(jobs)} notes -> {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs_json")
    ap.add_argument("--mode", choices=["single", "obsidian"], default="single")
    ap.add_argument("--link-template", default="", help='e.g. "https://example.com/jobs/{job_id}"')
    ap.add_argument("--title", default="校园招聘职位汇总")
    ap.add_argument("--out", required=True, help="output .md file path (single mode) or folder (obsidian mode)")
    ap.add_argument("--priority-json", default="", help="job_id -> priority int map, from recommend_priority.py")
    ap.add_argument(
        "--employment-type",
        default="",
        help='只输出匹配的类型（逐字匹配 employment_type 字段，比如 "实习" 或 "全职"）。'
        "留空则不过滤，输出全部。可用逗号分隔多个值。",
    )
    args = ap.parse_args()

    with open(args.jobs_json, encoding="utf-8") as f:
        jobs = json.load(f)

    if args.employment_type:
        wanted = {t.strip() for t in args.employment_type.split(",") if t.strip()}
        before = len(jobs)
        jobs = [j for j in jobs if j.get("employment_type") in wanted]
        print(f"--employment-type {wanted}: {before} -> {len(jobs)} jobs")

    if args.priority_json:
        with open(args.priority_json, encoding="utf-8") as f:
            pmap = json.load(f)
        for j in jobs:
            j["priority"] = pmap.get(j["job_id"], 0)

    if args.mode == "single":
        text = single_markdown(jobs, args.link_template, args.title)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {args.out}")
    else:
        obsidian_notes(jobs, args.link_template, args.out)


if __name__ == "__main__":
    main()

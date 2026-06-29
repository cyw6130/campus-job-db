#!/usr/bin/env python3
"""Push pages JSON (output of build_notion_pages.py) straight into Notion via
the REST API — no MCP tool call, no Read-then-paste.

Why this exists: piping page content through the notion-create-pages MCP tool
means the assistant has to hold the full page text in its own context twice
(once reading the file, once re-emitting it as a tool-call argument). For two
dozen multi-paragraph job postings that's a real token cost. This script reads
the JSON once and POSTs directly — the content never has to round-trip through
the model.

Auth: export NOTION_API_TOKEN in the shell (an internal-integration secret
from https://www.notion.com/my-integrations, NOT the OAuth/MCP connection).
The integration must also be connected to the target database in the Notion
UI (database `•••` menu -> Connections -> add it), otherwise every call fails
with 401/restricted_resource.

Property type mapping is given via CLI flags rather than auto-detected from
the database schema, to avoid extra API calls and Notion API version quirks.
Defaults match this skill's standard schema (职位名称/类型/类别/公司/地点/
发布日期/推荐优先级/链接, where 地点 and 发布日期 are RICH_TEXT — that's what
`notion-create-database` in SKILL.md actually creates, not DATE) — override
per-property lists if a database differs.

Dedups by --link-prop (default 链接) against what's already in the target
database before writing anything — a duplicate-write bug (same 21 jobs
created twice across a context-compaction boundary) is exactly why this
exists. Pass --no-dedupe only if you're sure the target is empty/new.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


def markdown_to_blocks(content: str) -> list[dict]:
    blocks = []
    for line in content.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:].strip()}}]},
                }
            )
        elif line.startswith("- "):
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:].strip()}}]},
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line.strip()}}]},
                }
            )
    return blocks[:100]  # page-create children cap


def build_property_value(value, kind: str) -> dict:
    if value in (None, ""):
        if kind == "number":
            return {"number": None}
        if kind == "date":
            return {"date": None}
        if kind in ("title", "rich_text", "multi_select"):
            return {kind: []}
        return {kind: None}
    if kind == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if kind == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
    if kind == "select":
        return {"select": {"name": str(value)}}
    if kind == "multi_select":
        items = [v.strip() for v in re.split(r"[,，]", str(value)) if v.strip()]
        return {"multi_select": [{"name": v} for v in items]}
    if kind == "number":
        return {"number": value}
    if kind == "date":
        return {"date": {"start": str(value)}}
    if kind == "url":
        return {"url": str(value)}
    raise ValueError(f"unsupported property kind: {kind}")


def get_existing_links(database_id: str, token: str, link_prop: str) -> set[str]:
    existing = set()
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(
            f"{API_BASE}/databases/{database_id}/query",
            method="POST",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        for r in d["results"]:
            url_val = (r.get("properties", {}).get(link_prop) or {}).get("url")
            if url_val:
                existing.add(url_val)
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    return existing


def post(url: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages_json", help="output of build_notion_pages.py")
    ap.add_argument("--database-id", required=True)
    ap.add_argument("--title-prop", default="职位名称")
    ap.add_argument("--select-props", default="类型,类别,公司")
    ap.add_argument("--multi-select-props", default="兴趣")
    ap.add_argument("--date-props", default="")
    ap.add_argument("--number-props", default="推荐优先级")
    ap.add_argument("--url-props", default="链接")
    ap.add_argument("--rich-text-props", default="地点,发布日期")
    ap.add_argument("--link-prop", default="链接", help="property used to detect already-written pages")
    ap.add_argument("--no-dedupe", action="store_true", help="skip the pre-write existing-link check (only for a known-empty/new database)")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests, be polite to the API")
    ap.add_argument("--start", type=int, default=0, help="resume from this index after a partial failure")
    args = ap.parse_args()

    token = os.environ.get("NOTION_API_TOKEN")
    if not token:
        sys.exit("NOTION_API_TOKEN not set — export it first (internal integration secret, not MCP auth)")

    kind_map = {args.title_prop: "title"}
    for group, kind in (
        (args.select_props, "select"),
        (args.multi_select_props, "multi_select"),
        (args.date_props, "date"),
        (args.number_props, "number"),
        (args.url_props, "url"),
        (args.rich_text_props, "rich_text"),
    ):
        for p in group.split(","):
            if p:
                kind_map[p] = kind

    with open(args.pages_json, encoding="utf-8") as f:
        pages = json.load(f)

    existing_links = set()
    if not args.no_dedupe:
        existing_links = get_existing_links(args.database_id, token, args.link_prop)
        print(f"found {len(existing_links)} existing links in target database, will skip matches")

    created, skipped, failed = [], [], []
    for i, page in enumerate(pages[args.start :], start=args.start):
        title = page["properties"].get(args.title_prop)
        link = page["properties"].get(args.link_prop)
        if link and link in existing_links:
            skipped.append({"index": i, "title": title, "link": link})
            print(f"[{i + 1}/{len(pages)}] skip (already exists): {title}")
            continue
        props_out = {
            name: build_property_value(value, kind_map.get(name, "rich_text"))
            for name, value in page["properties"].items()
        }
        payload = {
            "parent": {"database_id": args.database_id},
            "properties": props_out,
            "children": markdown_to_blocks(page.get("content", "")),
        }
        try:
            result = post(f"{API_BASE}/pages", token, payload)
            created.append({"index": i, "id": result["id"], "title": title})
            print(f"[{i + 1}/{len(pages)}] ok: {title}")
        except Exception as e:
            failed.append({"index": i, "error": str(e), "title": title})
            print(f"[{i + 1}/{len(pages)}] FAILED: {title} -> {e}")
        time.sleep(args.delay)

    print(
        f"\nDONE: {len(created)} created, {len(skipped)} skipped as duplicates, "
        f"{len(failed)} failed (of {len(pages)} total, started at index {args.start})"
    )
    if failed:
        print("Retry failed ones with --start <index> after fixing the cause:")
        for f_ in failed:
            print(f"  [{f_['index']}] {f_['title']}: {f_['error']}")


if __name__ == "__main__":
    main()

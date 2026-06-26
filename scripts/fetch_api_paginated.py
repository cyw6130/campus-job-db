#!/usr/bin/env python3
"""Generic paginated-JSON-API puller. Use this whenever you've reverse-
engineered a招聘站 list API (see references/api-reverse-engineering.md for
how to find one) — it replaces all browser automation for that site.

Usage:
    python3 fetch_api_paginated.py \\
      --url "https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition" \\
      --body-template '{"recruitType":"campus","positionName":"","campusRecruitTypes":["term_intern"]}' \\
      --page-field pageNum --size-field pageSize --page-size 10 \\
      --data-path data.list --total-path data.totalPage --id-field positionId \\
      --out /tmp/jobs_raw.json

--body-template: the JSON body to send each request (without page/size fields —
  those get merged in automatically from --page-field/--size-field).
--data-path / --total-path: dotted path into the response JSON to find the
  list of items / the total page count, e.g. "data.list" -> resp["data"]["list"].
--id-field: field name in each item used for de-duplication across pages.
"""
import argparse
import json
import sys
import time
import urllib.request

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def dig(obj, dotted_path):
    for key in dotted_path.split("."):
        obj = obj[key]
    return obj


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--body-template", required=True, help="JSON string, page/size fields added automatically")
    ap.add_argument("--page-field", default="pageNum")
    ap.add_argument("--size-field", default="pageSize")
    ap.add_argument("--page-size", type=int, default=10)
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--data-path", default="data.list", help="dotted path to the item list in the response")
    ap.add_argument("--total-path", default="data.totalPage", help="dotted path to total page count")
    ap.add_argument("--id-field", default="id", help="field used to dedupe items across pages")
    ap.add_argument("--referer", default="")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between requests (be polite)")
    ap.add_argument("--max-pages", type=int, default=0, help="safety cap, 0 = no cap")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    headers = dict(DEFAULT_HEADERS)
    if args.referer:
        headers["Referer"] = args.referer

    body_base = json.loads(args.body_template)

    all_items = []
    seen_ids = set()
    page = args.start_page
    total_pages = 1

    while page <= total_pages:
        if args.max_pages and (page - args.start_page) >= args.max_pages:
            print(f"hit --max-pages cap at page {page}, stopping", file=sys.stderr)
            break
        body = dict(body_base)
        body[args.page_field] = page
        body[args.size_field] = args.page_size
        req = urllib.request.Request(
            args.url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                d = json.loads(resp.read())
        except Exception as e:  # noqa: BLE001
            print(f"page {page} request failed: {e}", file=sys.stderr)
            break

        try:
            items = dig(d, args.data_path)
            total_pages = dig(d, args.total_path)
        except (KeyError, TypeError) as e:
            print(f"ERROR: couldn't navigate response with --data-path/--total-path: {e}", file=sys.stderr)
            print(f"raw response (truncated): {json.dumps(d)[:500]}", file=sys.stderr)
            sys.exit(1)

        new_count = 0
        for item in items:
            iid = item.get(args.id_field)
            if iid is not None and iid not in seen_ids:
                seen_ids.add(iid)
                all_items.append(item)
                new_count += 1
        print(f"page {page}/{total_pages}: +{new_count} new, {len(all_items)} total unique", file=sys.stderr)
        page += 1
        time.sleep(args.delay)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False)
    print(f"DONE: {len(all_items)} unique items -> {args.out}")


if __name__ == "__main__":
    main()

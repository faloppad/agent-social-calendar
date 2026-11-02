#!/usr/bin/env python3
"""Create the Posts and Channels tables in an existing Airtable base.

Stdlib only (Python 3.9+). Safe to run more than once: existing tables are kept
and only missing fields are added.

Before you run it:
  1. Create an empty base by hand in Airtable (name it "Social Calendar").
     The API can only create bases inside a workspace when the token has
     workspace-level access, so this script doesn't try.
  2. Copy the base ID from the URL (the part starting with "app").
  3. Create a personal access token with the scopes data.records:read,
     data.records:write, schema.bases:read and schema.bases:write, limited to
     that base.

    python3 scripts/setup_airtable.py --base appXXXXXXXXXXXXXX
    python3 scripts/setup_airtable.py --seed-channels channels.csv
    python3 scripts/setup_airtable.py --dry-run

Environment (or .env in cwd / repo root): AIRTABLE_TOKEN, AIRTABLE_BASE_ID,
AIRTABLE_POSTS_TABLE (default Posts), AIRTABLE_CHANNELS_TABLE (default Channels).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATUSES = [
    ("Draft", "grayLight2"),
    ("Needs media", "orangeLight2"),
    ("To approve", "yellowLight2"),
    ("Approved", "greenLight2"),
    ("Scheduled", "cyanLight2"),
    ("Live", "blueLight2"),
    ("Manual", "purpleLight2"),
    ("Failed", "redLight2"),
    ("Rejected", "pinkLight2"),
]
PLATFORMS = ["linkedin", "x", "instagram", "facebook", "threads", "tiktok", "youtube",
             "bluesky", "pinterest", "reddit", "substack", "other"]
CHANNEL_FIELDS = ["Name", "Platform", "Upload-Post user", "Target ID", "Post time", "Timezone",
                  "Active", "Manual", "Channel file"]

NOTES = """\
Notes
- Airtable's free plan caps each base at 1,000 records and 1 GB of attachments
  (at the time of writing). One record per post per channel adds up fast, and
  every image or video in Media counts toward the 1 GB. Archive or delete old
  Live posts, or move to a paid plan.
- This script needs an existing base. Airtable's API can only create a base inside
  a workspace if the token has access to that workspace, so create an empty base
  by hand and pass its ID with --base or AIRTABLE_BASE_ID.
- Airtable doesn't document adding options to an existing single select through
  the API, so this script doesn't try. If a Status or Platform option is missing
  on an existing table, add it in the Airtable UI. New Channel
  options are added automatically the first time a post uses them (the scripts
  write with typecast)."""


def load_dotenv() -> None:
    candidates = [Path.cwd() / ".env"]
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents)[:3]:
        candidates.append(parent / ".env")
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().replace("export ", "", 1).strip()
            value = value.strip()
            if " #" in value and not value.startswith(("'", '"')):
                value = value.split(" #", 1)[0].strip()
            os.environ.setdefault(key, value.strip("'\""))
        return


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail[:600]}")
        self.status = status
        self.detail = detail


def choices(names_colors: list) -> dict:
    out = []
    for item in names_colors:
        if isinstance(item, tuple):
            out.append({"name": item[0], "color": item[1]})
        else:
            out.append({"name": item})
    return {"choices": out}


def posts_fields(channel_names: list) -> list:
    text = {"type": "singleLineText"}
    long = {"type": "multilineText"}
    return [
        dict(name="Name", **text),
        {"name": "Status", "type": "singleSelect", "options": choices(STATUSES)},
        {"name": "Scheduled for", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
        {"name": "Channel", "type": "singleSelect", "options": choices(channel_names)},
        dict(name="PostContent", **long),
        {"name": "Media", "type": "multipleAttachments"},
        dict(name="Source", **long),
        dict(name="Campaign", **text),
        dict(name="Owner", **text),
        {"name": "Live link", "type": "url"},
        {"name": "Posted at", "type": "dateTime", "options": {
            "dateFormat": {"name": "iso"}, "timeFormat": {"name": "24hour"}, "timeZone": "client"}},
        dict(name="Upload-Post ID", **text),
        dict(name="Error", **long),
    ]


def channels_fields() -> list:
    text = {"type": "singleLineText"}
    checkbox = {"type": "checkbox", "options": {"icon": "check", "color": "greenBright"}}
    return [
        dict(name="Name", **text),
        {"name": "Platform", "type": "singleSelect", "options": choices(PLATFORMS)},
        dict(name="Upload-Post user", **text),
        dict(name="Target ID", **text),
        dict(name="Post time", **text),
        dict(name="Timezone", **text),
        dict(name="Active", **checkbox),
        dict(name="Manual", **checkbox),
        dict(name="Channel file", **text),
    ]


class Api:
    def __init__(self, token: str, base: str, dry_run: bool) -> None:
        self.token = token
        self.base = base
        self.dry_run = dry_run
        self.root = (os.environ.get("AIRTABLE_API_URL") or "https://api.airtable.com").rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None, write: bool = False):
        url = self.root + path
        if write and self.dry_run:
            print(f"[dry-run] {method} {url}\n{json.dumps(body, indent=2)}")
            return {}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", "agent-social-calendar/1.0")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            die(f"network error calling Airtable: {e.reason}")


def ensure_table(api: Api, existing: dict, name: str, fields: list, description: str) -> dict | None:
    table = existing.get(name)
    if table is None:
        print(f"+ create table {name!r} with {len(fields)} fields")
        body = {"name": name, "description": description, "fields": fields}
        try:
            return api.call("POST", f"/v0/meta/bases/{api.base}/tables", body, write=True) or None
        except ApiError as e:
            empty = [f for f in fields if f["type"] == "singleSelect" and not f["options"]["choices"]]
            if e.status != 422 or not empty:
                raise
            # Airtable doesn't document whether a select may start with no options.
            for f in empty:
                f["options"]["choices"] = [{"name": "Example channel"}]
                print(f"  {f['name']!r} can't start empty; added option 'Example channel' "
                      f"(rename or delete it in Airtable)")
            return api.call("POST", f"/v0/meta/bases/{api.base}/tables", body, write=True) or None
    have = {f["name"]: f for f in table.get("fields", [])}
    print(f"= table {name!r} exists ({len(have)} fields)")
    for field in fields:
        current = have.get(field["name"])
        if current is None:
            print(f"  + add field {field['name']!r} ({field['type']})")
            api.call("POST", f"/v0/meta/bases/{api.base}/tables/{table['id']}/fields", field, write=True)
            continue
        if current.get("type") != field["type"]:
            print(f"  ! field {field['name']!r} is {current.get('type')}, expected {field['type']}. "
                  f"Change it by hand.")
        wanted = [c["name"] for c in field.get("options", {}).get("choices", [])]
        if field["type"] == "singleSelect" and wanted and field["name"] != "Channel":
            got = {c.get("name") for c in (current.get("options") or {}).get("choices", [])}
            missing = [w for w in wanted if w not in got]
            if missing:
                print(f"  ! {field['name']!r} lacks options {missing}. Add them in the Airtable UI.")
    return table


def read_seed(path: str) -> list:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        unknown = [h for h in (reader.fieldnames or []) if h not in CHANNEL_FIELDS]
        if unknown:
            die(f"unknown columns in {path}: {unknown}. Use: {', '.join(CHANNEL_FIELDS)}")
        for row in reader:
            if not (row.get("Name") or "").strip():
                continue
            rec = {}
            for k, v in row.items():
                v = (v or "").strip()
                if k in ("Active", "Manual"):
                    rec[k] = v.lower() in ("1", "true", "yes", "y", "x", "checked")
                elif k == "Platform":
                    v = v.lower()
                    if v and v not in PLATFORMS:
                        die(f"channel {row['Name']!r}: platform {v!r} not in {PLATFORMS}")
                    if v:
                        rec[k] = v
                elif v:
                    rec[k] = v
            rows.append(rec)
    return rows


def seed_channels(api: Api, table_name: str, rows: list) -> None:
    path = f"/v0/{api.base}/{urllib.parse.quote(table_name, safe='')}"
    existing = set()
    if not api.dry_run:
        offset = None
        while True:
            q = "?pageSize=100" + (f"&offset={offset}" if offset else "")
            page = api.call("GET", path + q)
            existing |= {r["fields"].get("Name") for r in page.get("records", [])}
            offset = page.get("offset")
            if not offset:
                break
    new = [r for r in rows if r["Name"] not in existing]
    for r in rows:
        if r["Name"] in existing:
            print(f"= channel {r['Name']!r} already exists, skipped")
    for i in range(0, len(new), 10):
        chunk = new[i:i + 10]
        print(f"+ add channels: {', '.join(r['Name'] for r in chunk)}")
        api.call("POST", path, {"records": [{"fields": r} for r in chunk], "typecast": True}, write=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="setup_airtable",
        description="Create the Posts and Channels tables in an existing Airtable base "
                    "(idempotent: existing tables are kept, missing fields are added).",
        epilog=NOTES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="Base ID (app...). Defaults to AIRTABLE_BASE_ID")
    ap.add_argument("--seed-channels", metavar="CSV",
                    help="CSV with columns " + ", ".join(CHANNEL_FIELDS))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the schema calls instead of sending them (still reads the base "
                         "unless --offline)")
    ap.add_argument("--offline", action="store_true",
                    help="With --dry-run: don't read the base, assume it's empty")
    args = ap.parse_args()

    load_dotenv()
    token = os.environ.get("AIRTABLE_TOKEN", "")
    base = args.base or os.environ.get("AIRTABLE_BASE_ID", "")
    posts_name = os.environ.get("AIRTABLE_POSTS_TABLE") or "Posts"
    channels_name = os.environ.get("AIRTABLE_CHANNELS_TABLE") or "Channels"
    if args.offline and not args.dry_run:
        die("--offline only works with --dry-run")
    if not base:
        die("no base ID. Create an empty base in Airtable by hand, then pass --base app... "
            "or set AIRTABLE_BASE_ID.")
    if not token and not args.offline:
        die("AIRTABLE_TOKEN is not set.")

    print(NOTES + "\n")
    seed = read_seed(args.seed_channels) if args.seed_channels else []
    api = Api(token, base, args.dry_run)

    if args.offline:
        existing = {}
    else:
        try:
            tables = api.call("GET", f"/v0/meta/bases/{base}/tables").get("tables", [])
        except ApiError as e:
            die(f"could not read base {base}: {e}. Check the base ID and the token's "
                f"schema.bases:read scope.")
        existing = {t["name"]: t for t in tables}

    try:
        ensure_table(api, existing, channels_name, channels_fields(),
                     "Routing for the publisher. Voice and strategy live in the channel markdown files.")
        ensure_table(api, existing, posts_name, posts_fields([r["Name"] for r in seed]),
                     "One record per post per channel. Status drives approval and publishing.")
        if seed:
            seed_channels(api, channels_name, seed)
    except ApiError as e:
        hint = ""
        if e.status in (401, 403):
            hint = ("\nCheck the token scopes (schema.bases:read/write, data.records:read/write) "
                    "and that the token has access to this base.")
        die(f"Airtable said {e}{hint}")

    print("\nDone." if not args.dry_run else "\nDry run finished. Nothing was changed.")
    print(f"Set AIRTABLE_BASE_ID={base} in your .env if you haven't yet.")


if __name__ == "__main__":
    main()

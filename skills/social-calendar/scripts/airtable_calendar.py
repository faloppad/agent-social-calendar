#!/usr/bin/env python3
"""Read and write the Social Calendar Airtable base.

Stdlib only (Python 3.9+). Field names, status values and env vars follow
docs/data-model.md.

Subcommands:
    list              List posts, filtered by channel, status and date range
    create            Create posts from a JSON list (file or stdin) or a planning CSV
    update            Update one record (--set Field=value) or a JSON batch
    attach            Attach local files or URLs to a post's Media field
    channels          List the Channels table
    check-duplicates  Compare planned posts with existing posts on the same channel

Environment (read from the environment first, then from a .env file in the
current directory or the repo root):
    AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_POSTS_TABLE (default Posts),
    AIRTABLE_CHANNELS_TABLE (default Channels)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

STATUSES = [
    "Draft", "Needs media", "To approve", "Approved", "Scheduled",
    "Live", "Manual", "Failed", "Rejected",
]
# Platforms that reject text-only posts.
MEDIA_REQUIRED = {"instagram", "tiktok", "youtube", "pinterest"}
POST_FIELDS = [
    "Name", "Status", "Scheduled for", "Channel", "PostContent", "Media", "Source",
    "Campaign", "Owner", "Live link", "Posted at", "Upload-Post ID", "Error",
]
CATBOX_URL = "https://catbox.moe/user/api.php"
USER_AGENT = "agent-social-calendar/1.0"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- env

def load_dotenv() -> None:
    """Load KEY=VALUE pairs from .env in cwd or a parent of this script.

    Values already in the environment win.
    """
    candidates = [Path.cwd() / ".env"]
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents)[:4]:
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
            value = value.strip("'\"")
            os.environ.setdefault(key, value)
        return


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


class Config:
    def __init__(self) -> None:
        load_dotenv()
        self.token = os.environ.get("AIRTABLE_TOKEN", "")
        self.base = os.environ.get("AIRTABLE_BASE_ID", "")
        self.posts = os.environ.get("AIRTABLE_POSTS_TABLE") or "Posts"
        self.channels = os.environ.get("AIRTABLE_CHANNELS_TABLE") or "Channels"
        # Override only for testing against a local mock.
        self.api = (os.environ.get("AIRTABLE_API_URL") or "https://api.airtable.com").rstrip("/")
        if not self.token or not self.base:
            die("AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set (environment or .env).")


# ---------------------------------------------------------------- HTTP

class HttpError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def http(method: str, url: str, headers: dict | None = None, data: bytes | None = None,
         timeout: int = 60) -> tuple:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace"))


class Airtable:
    """Minimal Airtable REST client with paging, batching and 429 retries."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._last = 0.0

    def _url(self, table: str, suffix: str = "") -> str:
        return f"{self.cfg.api}/v0/{self.cfg.base}/{urllib.parse.quote(table, safe='')}{suffix}"

    def request(self, method: str, url: str, body: dict | None = None):
        headers = {"Authorization": f"Bearer {self.cfg.token}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        for attempt in range(5):
            wait = 0.22 - (time.time() - self._last)  # stay under 5 requests/second
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                _, text = http(method, url, headers, data)
                return json.loads(text) if text else {}
            except HttpError as e:
                if e.status == 429 or e.status >= 500:
                    time.sleep(30 if e.status == 429 else 2 * (attempt + 1))
                    continue
                raise
        raise HttpError(429, "Airtable kept returning 429/5xx after 5 attempts")

    def list(self, table: str, formula: str | None = None, sort: list | None = None,
             max_records: int | None = None) -> list:
        records, offset = [], None
        while True:
            params = [("pageSize", "100")]
            if formula:
                params.append(("filterByFormula", formula))
            for i, (field, direction) in enumerate(sort or []):
                params.append((f"sort[{i}][field]", field))
                params.append((f"sort[{i}][direction]", direction))
            if max_records:
                params.append(("maxRecords", str(max_records)))
            if offset:
                params.append(("offset", offset))
            page = self.request("GET", self._url(table) + "?" + urllib.parse.urlencode(params))
            records.extend(page.get("records", []))
            offset = page.get("offset")
            if not offset:
                return records

    def get(self, table: str, record_id: str) -> dict:
        return self.request("GET", self._url(table, "/" + record_id))

    def create(self, table: str, fields_list: list, typecast: bool = True) -> list:
        out = []
        for i in range(0, len(fields_list), 10):
            chunk = [{"fields": f} for f in fields_list[i:i + 10]]
            res = self.request("POST", self._url(table), {"records": chunk, "typecast": typecast})
            out.extend(res.get("records", []))
        return out

    def update(self, table: str, updates: list, typecast: bool = True) -> list:
        """updates: list of {"id": ..., "fields": {...}}, sent 10 per request."""
        out = []
        for i in range(0, len(updates), 10):
            res = self.request("PATCH", self._url(table),
                               {"records": updates[i:i + 10], "typecast": typecast})
            out.extend(res.get("records", []))
        return out


# ---------------------------------------------------------------- helpers

def formula_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def parse_day(value: str | None) -> dt.date | None:
    """Accept YYYY-MM-DD, 'today', or a day offset like +14 or -7 (a trailing d is ok)."""
    if not value:
        return None
    v = value.strip().lower()
    if v == "today":
        return dt.date.today()
    m = re.match(r"^([+-]\d+)d?$", v)
    if m:
        return dt.date.today() + dt.timedelta(days=int(m.group(1)))
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        die(f"bad date {value!r}: use YYYY-MM-DD, today, +14 or -7")
    return None


def date_window_formula(start: dt.date | None, end: dt.date | None) -> list:
    """Loose server-side date filter (one day of slack each side).

    Airtable evaluates date maths in UTC, so the exact cut happens locally.
    """
    parts = []
    if start:
        s = (start - dt.timedelta(days=2)).isoformat()
        parts.append(f"IS_AFTER({{Scheduled for}}, DATETIME_PARSE('{s}', 'YYYY-MM-DD'))")
    if end:
        e = (end + dt.timedelta(days=2)).isoformat()
        parts.append(f"IS_BEFORE({{Scheduled for}}, DATETIME_PARSE('{e}', 'YYYY-MM-DD'))")
    return parts


def in_window(rec: dict, start: dt.date | None, end: dt.date | None) -> bool:
    day = rec.get("fields", {}).get("Scheduled for")
    if not start and not end:
        return True
    if not day:
        return False
    d = dt.date.fromisoformat(day[:10])
    return (not start or d >= start) and (not end or d <= end)


def fetch_posts(at: Airtable, channels: list | None = None, statuses: list | None = None,
                start: dt.date | None = None, end: dt.date | None = None,
                extra_formula: str | None = None) -> list:
    parts = []
    if channels:
        parts.append("OR(" + ",".join(f"{{Channel}}={formula_str(c)}" for c in channels) + ")")
    if statuses:
        parts.append("OR(" + ",".join(f"{{Status}}={formula_str(s)}" for s in statuses) + ")")
    parts += date_window_formula(start, end)
    if extra_formula:
        parts.append(extra_formula)
    formula = None
    if len(parts) == 1:
        formula = parts[0]
    elif parts:
        formula = "AND(" + ",".join(parts) + ")"
    recs = at.list(at.cfg.posts, formula=formula,
                   sort=[("Scheduled for", "asc"), ("Channel", "asc")])
    return [r for r in recs if in_window(r, start, end)]


def fetch_channels(at: Airtable) -> dict:
    return {r["fields"].get("Name", ""): r for r in at.list(at.cfg.channels)}


def encode_multipart(fields: list, files: list) -> tuple:
    """fields: [(name, value)], files: [(name, filename, bytes, mime)]."""
    boundary = "----asc" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
        out += str(value).encode("utf-8") + b"\r\n"
    for name, filename, content, mime in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def upload_to_catbox(path: str, dry_run: bool = False) -> str:
    """Upload a local file to catbox.moe and return its public URL.

    Catbox files are public and anonymous uploads can't be deleted. Airtable
    copies the file to its own CDN, so the catbox link isn't needed afterwards.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        die(f"file not found: {p}")
    if dry_run:
        print(f"[dry-run] would upload {p} to {CATBOX_URL}")
        return f"https://files.catbox.moe/DRYRUN-{p.name}"
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    body, ctype = encode_multipart([("reqtype", "fileupload")],
                                   [("fileToUpload", p.name, p.read_bytes(), mime)])
    _, text = http("POST", os.environ.get("CATBOX_URL", CATBOX_URL),
                   {"Content-Type": ctype}, body, timeout=300)
    url = text.strip()
    if not is_url(url):
        die(f"catbox upload failed for {p}: {url[:200]}")
    return url


def media_items(values, dry_run: bool = False) -> list:
    """Turn Media input (URLs, local paths or {"url": ...} dicts) into Airtable attachments."""
    out = []
    for v in values or []:
        if isinstance(v, dict):
            if "url" in v and not is_url(v["url"]):
                v = dict(v, url=upload_to_catbox(v["url"], dry_run))
            out.append(v)
        elif isinstance(v, str) and v.strip():
            v = v.strip()
            out.append({"url": v if is_url(v) else upload_to_catbox(v, dry_run)})
    return out


def short(text: str, n: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def print_table(rows: list, headers: list) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def read_json_input(path: str | None):
    raw = sys.stdin.read() if (not path or path == "-") else Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"invalid JSON: {e}")


def check_status(value) -> None:
    if value is not None and value not in STATUSES:
        die(f"invalid Status {value!r}. Use one of: {', '.join(STATUSES)}")


# ---------------------------------------------------------------- similarity

URL_RE = re.compile(r"https?://\S+")


def normalize(text: str) -> str:
    text = URL_RE.sub(" ", (text or "").lower())
    text = re.sub(r"[^\w#@]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    wa, wb = set(na.split()), set(nb.split())
    jaccard = len(wa & wb) / max(1, len(wa | wb))
    sm = difflib.SequenceMatcher(None, na, nb)
    ratio = sm.ratio() if sm.quick_ratio() > 0.4 else 0.0
    return max(jaccard, ratio)


def find_duplicates(planned: list, existing: list, threshold: float) -> list:
    """Return (planned_index, other_label, score, reason) tuples."""
    hits = []
    for i, p in enumerate(planned):
        ch, text, src = p.get("Channel"), p.get("PostContent", ""), (p.get("Source") or "").strip()
        for rec in existing:
            f = rec.get("fields", {})
            if f.get("Channel") != ch or f.get("Status") == "Rejected":
                continue
            label = f"{rec.get('id')} {f.get('Scheduled for', '?')} [{f.get('Status', '?')}]"
            score = similarity(text, f.get("PostContent", ""))
            if score >= threshold:
                hits.append((i, label, score, "similar text"))
            elif src and is_url(src) and src == (f.get("Source") or "").strip():
                hits.append((i, label, 1.0, "same source link"))
        for j in range(i):
            q = planned[j]
            if q.get("Channel") == ch:
                score = similarity(text, q.get("PostContent", ""))
                if score >= threshold:
                    hits.append((i, f"planned item #{j}", score, "similar text in this batch"))
    return hits


def print_duplicates(hits: list, planned: list) -> None:
    for i, label, score, reason in hits:
        p = planned[i]
        print(f"#{i} {p.get('Channel')} {p.get('Scheduled for', '?')} '{short(p.get('PostContent', ''), 50)}'"
              f"\n    ~ {label}  score={score:.2f} ({reason})")


# ---------------------------------------------------------------- input mapping

def rows_from_csv(path: str) -> list:
    """Map the planning CSV (Date, Channel, Content Type, Post Text, Hashtags,
    Image Suggestion) onto Posts fields."""
    posts = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            body = (row.get("Post Text") or "").strip()
            tags = (row.get("Hashtags") or "").strip()
            text = f"{body}\n\n{tags}" if tags and tags not in body else body
            post = {
                "Scheduled for": (row.get("Date") or "").strip(),
                "Channel": (row.get("Channel") or "").strip(),
                "PostContent": text,
            }
            ctype = (row.get("Content Type") or "").strip()
            if ctype:
                post["Name"] = f"{ctype} - {short(body, 40)}"
            idea = (row.get("Image Suggestion") or "").strip()
            if idea:
                post["Source"] = f"Image suggestion: {idea}"
            posts.append(post)
    return posts


def prepare_posts(posts: list, channels: dict | None, default_status: str) -> list:
    """Validate and fill defaults. Returns a list of error strings."""
    errors = []
    for i, p in enumerate(posts):
        unknown = [k for k in p if k not in POST_FIELDS]
        if unknown:
            errors.append(f"#{i}: unknown field(s) {unknown}. Use the contract field names.")
        p.setdefault("Status", default_status)
        if p["Status"] not in STATUSES:
            errors.append(f"#{i}: invalid Status {p['Status']!r}")
        day = p.get("Scheduled for", "")
        if not DATE_RE.match(str(day)):
            errors.append(f"#{i}: 'Scheduled for' must be YYYY-MM-DD, got {day!r}")
        if not p.get("Channel"):
            errors.append(f"#{i}: missing Channel")
        if not (p.get("PostContent") or "").strip():
            errors.append(f"#{i}: empty PostContent")
        if not p.get("Name"):
            p["Name"] = short(p.get("PostContent", ""), 40)
        if channels is not None and p.get("Channel"):
            ch = channels.get(p["Channel"])
            if not ch:
                errors.append(f"#{i}: Channel {p['Channel']!r} is not in the Channels table "
                              f"({', '.join(sorted(channels)) or 'empty'})")
                continue
            platform = (ch["fields"].get("Platform") or "").lower()
            if platform in MEDIA_REQUIRED and not p.get("Media") and \
                    p["Status"] in ("To approve", "Approved"):
                warn(f"#{i}: {p['Channel']} ({platform}) has no media, status set to 'Needs media'")
                p["Status"] = "Needs media"
            if not ch["fields"].get("Active"):
                warn(f"#{i}: channel {p['Channel']!r} is inactive; the publisher will skip it")
    return errors


# ---------------------------------------------------------------- commands

def cmd_list(args) -> None:
    at = Airtable(Config())
    for s in args.status or []:
        check_status(s)
    recs = fetch_posts(at, args.channel, args.status, parse_day(args.date_from),
                       parse_day(args.date_to), args.formula)
    if args.json:
        print(json.dumps(recs, indent=2, ensure_ascii=False))
        return
    rows = []
    for r in recs:
        f = r["fields"]
        rows.append([r["id"], f.get("Scheduled for", ""), f.get("Channel", ""), f.get("Status", ""),
                     len(f.get("Media") or []), short(f.get("Name", ""), 30),
                     short(f.get("PostContent", ""), 50)])
    print_table(rows, ["id", "date", "channel", "status", "media", "name", "text"])
    print(f"\n{len(rows)} post(s)")


def cmd_channels(args) -> None:
    at = Airtable(Config())
    chans = fetch_channels(at)
    if args.json:
        print(json.dumps(list(chans.values()), indent=2, ensure_ascii=False))
        return
    rows = []
    for name, r in sorted(chans.items()):
        f = r["fields"]
        if not args.all and not f.get("Active"):
            continue
        rows.append([name, f.get("Platform", ""), f.get("Upload-Post user", ""),
                     f.get("Target ID", ""), f.get("Post time", ""), f.get("Timezone", ""),
                     "yes" if f.get("Active") else "no", "yes" if f.get("Manual") else "",
                     f.get("Channel file", "")])
    print_table(rows, ["name", "platform", "upload-post user", "target id", "time", "timezone",
                       "active", "manual", "channel file"])


def load_planned(args) -> list:
    if getattr(args, "csv", False):
        if not args.input or args.input == "-":
            die("--csv needs a file path")
        return rows_from_csv(args.input)
    data = read_json_input(args.input)
    if isinstance(data, dict):
        data = data.get("records") or data.get("posts") or [data]
    return [d.get("fields", d) if isinstance(d, dict) else d for d in data]


def cmd_create(args) -> None:
    check_status(args.default_status)
    at = Airtable(Config())
    posts = load_planned(args)
    if not posts:
        die("no posts in input")
    try:
        channels = fetch_channels(at)
    except (HttpError, urllib.error.URLError, OSError) as e:
        if not args.dry_run:
            die(f"could not read the Channels table: {e}")
        warn(f"could not read Channels ({e}); skipping channel validation in dry-run")
        channels = None
    errors = prepare_posts(posts, channels, args.default_status)
    if errors:
        die("input has problems:\n  " + "\n  ".join(errors))

    if not args.allow_duplicates:
        days = [p["Scheduled for"] for p in posts]
        start = dt.date.fromisoformat(min(days)) - dt.timedelta(days=args.days_back)
        end = dt.date.fromisoformat(max(days)) + dt.timedelta(days=30)
        try:
            existing = fetch_posts(at, sorted({p["Channel"] for p in posts}), None, start, end)
            hits = find_duplicates(posts, existing, args.threshold)
        except (HttpError, urllib.error.URLError, OSError) as e:
            if not args.dry_run:
                die(f"could not check duplicates: {e} (use --allow-duplicates to skip)")
            warn(f"duplicate check skipped in dry-run: {e}")
            hits = []
        if hits:
            print("Possible duplicates:")
            print_duplicates(hits, posts)
            if not args.dry_run:
                die("not creating anything. Fix the batch or pass --allow-duplicates.", 2)

    for p in posts:
        if p.get("Media"):
            p["Media"] = media_items(p["Media"], args.dry_run)

    if args.dry_run:
        print(f"[dry-run] would create {len(posts)} record(s) in {at.cfg.posts} "
              f"({(len(posts) + 9) // 10} request(s)):")
        print(json.dumps(posts, indent=2, ensure_ascii=False))
        return
    created = at.create(at.cfg.posts, posts)
    rows = [[r["id"], r["fields"].get("Scheduled for", ""), r["fields"].get("Channel", ""),
             r["fields"].get("Status", ""), short(r["fields"].get("PostContent", ""), 50)]
            for r in created]
    print_table(rows, ["id", "date", "channel", "status", "text"])
    print(f"\nCreated {len(created)} record(s).")


def parse_sets(pairs: list) -> dict:
    fields = {}
    for pair in pairs or []:
        if "=" not in pair:
            die(f"--set expects Field=value, got {pair!r}")
        k, _, v = pair.partition("=")
        k = k.strip()
        if k not in POST_FIELDS:
            die(f"unknown field {k!r}. Valid: {', '.join(POST_FIELDS)}")
        fields[k] = v.replace("\\n", "\n") if v != "" else None
    return fields


def cmd_update(args) -> None:
    at = Airtable(Config())
    if args.json is not None:
        data = read_json_input(args.json)
        updates = [{"id": d["id"], "fields": d["fields"]} for d in data]
    else:
        if not args.record_id:
            die("give a record id with --set Field=value, or --json FILE")
        fields = parse_sets(args.set)
        if not fields:
            die("nothing to update: pass --set Field=value")
        updates = [{"id": args.record_id, "fields": fields}]
    for u in updates:
        check_status(u["fields"].get("Status"))
        day = u["fields"].get("Scheduled for")
        if day and not DATE_RE.match(day):
            die(f"{u['id']}: 'Scheduled for' must be YYYY-MM-DD")
    if args.dry_run:
        print(f"[dry-run] would PATCH {len(updates)} record(s):")
        print(json.dumps(updates, indent=2, ensure_ascii=False))
        return
    done = at.update(at.cfg.posts, updates)
    print(f"Updated {len(done)} record(s).")


def cmd_attach(args) -> None:
    at = Airtable(Config())
    new = media_items(args.media, args.dry_run)
    fields: dict = {}
    current_status = None
    if args.dry_run and args.replace:
        fields["Media"] = new
    else:
        rec = at.get(at.cfg.posts, args.record_id)
        current_status = rec.get("fields", {}).get("Status")
        keep = [] if args.replace else [{"id": m["id"]} for m in rec["fields"].get("Media") or []]
        fields["Media"] = keep + new
    if current_status == "Needs media" and not args.keep_status:
        fields["Status"] = "To approve"
    if args.status:
        check_status(args.status)
        fields["Status"] = args.status
    if args.dry_run:
        print(f"[dry-run] would PATCH {args.record_id}:")
        print(json.dumps(fields, indent=2, ensure_ascii=False))
        return
    at.update(at.cfg.posts, [{"id": args.record_id, "fields": fields}])
    msg = f"Attached {len(new)} file(s) to {args.record_id}"
    if "Status" in fields:
        msg += f", status now {fields['Status']!r}"
    print(msg + ".")


def cmd_check_duplicates(args) -> None:
    at = Airtable(Config())
    if args.text:
        if not args.channel:
            die("--text needs --channel")
        planned = [{"Channel": args.channel, "PostContent": args.text,
                    "Scheduled for": args.date or dt.date.today().isoformat()}]
    else:
        planned = load_planned(args)
    days = [p.get("Scheduled for") or dt.date.today().isoformat() for p in planned]
    start = dt.date.fromisoformat(min(days)) - dt.timedelta(days=args.days_back)
    end = dt.date.fromisoformat(max(days)) + dt.timedelta(days=30)
    existing = fetch_posts(at, sorted({p.get("Channel") for p in planned if p.get("Channel")}),
                           None, start, end)
    hits = find_duplicates(planned, existing, args.threshold)
    if args.json:
        print(json.dumps([{"planned_index": i, "match": label, "score": round(s, 3), "reason": r}
                          for i, label, s, r in hits], indent=2))
        return
    if not hits:
        print(f"No likely duplicates among {len(existing)} existing post(s) "
              f"on {len({p.get('Channel') for p in planned})} channel(s).")
        return
    print_duplicates(hits, planned)


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="airtable_calendar",
        description="Read and write the Social Calendar Airtable base (Posts and Channels).",
        epilog="Dates accept YYYY-MM-DD, 'today', or a day offset like +14 or -7.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="List posts")
    p.add_argument("--channel", action="append", help="Channel name (repeatable)")
    p.add_argument("--status", action="append", help="Status value (repeatable)")
    p.add_argument("--from", dest="date_from", help="First date, inclusive")
    p.add_argument("--to", dest="date_to", help="Last date, inclusive")
    p.add_argument("--formula", help="Extra Airtable filterByFormula, ANDed with the rest")
    p.add_argument("--json", action="store_true", help="Print raw records as JSON")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("create", help="Create posts from JSON (list of field objects) or CSV",
                       description="Input is a JSON list of objects using Posts field names. "
                                   "Media items may be URLs or local paths; local files go to "
                                   "catbox.moe first. Runs a duplicate check before writing.")
    p.add_argument("input", nargs="?", default="-", help="JSON file, or - for stdin (default)")
    p.add_argument("--csv", action="store_true",
                   help="Input is a planning CSV: Date, Channel, Content Type, Post Text, "
                        "Hashtags, Image Suggestion")
    p.add_argument("--default-status", default="To approve",
                   help="Status for items without one (default: To approve)")
    p.add_argument("--allow-duplicates", action="store_true", help="Skip the duplicate check")
    p.add_argument("--threshold", type=float, default=0.6, help="Similarity threshold (0-1)")
    p.add_argument("--days-back", type=int, default=120,
                   help="How far back to look for duplicates (days)")
    p.add_argument("--dry-run", action="store_true", help="Print what would be created")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("update", help="Update a record or a JSON batch")
    p.add_argument("record_id", nargs="?", help="Record id (rec...)")
    p.add_argument("--set", action="append", metavar="FIELD=VALUE",
                   help="Field to set (repeatable). Empty value clears the field. \\n becomes a newline.")
    p.add_argument("--json", nargs="?", const="-", default=None,
                   help='JSON list of {"id": ..., "fields": {...}} (file or stdin)')
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("attach", help="Attach files or URLs to a post's Media field",
                       description="Local files are uploaded to catbox.moe (public) first, "
                                   "because Airtable only ingests public URLs. A post in "
                                   "'Needs media' moves to 'To approve' unless --keep-status.")
    p.add_argument("record_id")
    p.add_argument("media", nargs="+", help="Local file paths or public URLs")
    p.add_argument("--replace", action="store_true", help="Replace existing media instead of appending")
    p.add_argument("--keep-status", action="store_true", help="Don't move 'Needs media' on")
    p.add_argument("--status", help="Set this status after attaching")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser("channels", help="List the Channels table")
    p.add_argument("--all", action="store_true", help="Include inactive channels")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_channels)

    p = sub.add_parser("check-duplicates", help="Compare planned posts with existing ones")
    p.add_argument("input", nargs="?", default="-", help="JSON file of planned posts, or - for stdin")
    p.add_argument("--csv", action="store_true", help="Input is a planning CSV")
    p.add_argument("--channel", help="Channel, with --text")
    p.add_argument("--text", help="Check one post text instead of a file")
    p.add_argument("--date", help="Planned date for --text (YYYY-MM-DD)")
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--days-back", type=int, default=120)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check_duplicates)

    args = ap.parse_args()
    try:
        args.func(args)
    except HttpError as e:
        die(f"Airtable request failed: {e}")
    except urllib.error.URLError as e:
        die(f"network error: {e.reason}")


if __name__ == "__main__":
    main()

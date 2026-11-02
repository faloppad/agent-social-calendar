#!/usr/bin/env python3
"""Publish approved posts from Airtable through Upload-Post.

Stdlib only (Python 3.9+). Nothing is sent unless you pass --mode, --reconcile
or --sync, and --dry-run prints every API call instead of sending it.

    --mode now        Publish Approved posts whose 'Scheduled for' is today or
                      earlier in the channel's timezone.
    --mode schedule   Hand Approved posts with a future slot to Upload-Post with
                      scheduled_date + timezone. Status becomes Scheduled.
    --sync            Push Airtable edits to jobs still waiting in Upload-Post:
                      new date or text -> edit the job; status moved back to
                      Draft/To approve/Needs media/Rejected -> cancel the job.
    --reconcile       Check Scheduled posts in Upload-Post and flip them to
                      Live or Failed.

Order when combined: sync, reconcile, then mode.

Environment (from the environment, or .env in cwd / repo root):
    AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_POSTS_TABLE, AIRTABLE_CHANNELS_TABLE,
    UPLOAD_POST_API_KEY, SLACK_WEBHOOK_URL (optional)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

USER_AGENT = "agent-social-calendar/1.0"
MEDIA_REQUIRED = {"instagram", "tiktok", "youtube", "pinterest"}
VIDEO_REQUIRED = {"youtube"}
NEVER_API = {"substack", "other"}
TARGET_FIELD = {
    "linkedin": "target_linkedin_page_id",
    "facebook": "facebook_page_id",
    "pinterest": "pinterest_board_id",
    "reddit": "subreddit",
}
CANCEL_ON = {"Draft", "To approve", "Needs media", "Rejected"}


# ---------------------------------------------------------------- env / http

def load_dotenv() -> None:
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
            os.environ.setdefault(key, value.strip("'\""))
        return


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


class HttpError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body

    def message(self) -> str:
        try:
            data = json.loads(self.body)
            return str(data.get("error") or data.get("message") or self.body)[:1000]
        except ValueError:
            return self.body[:1000]


def http(method: str, url: str, headers: dict | None = None, data: bytes | None = None,
         timeout: int = 120) -> tuple:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace"))


def encode_multipart(fields: list, files: list) -> tuple:
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


# ---------------------------------------------------------------- clients

class Airtable:
    def __init__(self, dry_run: bool) -> None:
        self.token = os.environ.get("AIRTABLE_TOKEN", "")
        self.base = os.environ.get("AIRTABLE_BASE_ID", "")
        self.posts = os.environ.get("AIRTABLE_POSTS_TABLE") or "Posts"
        self.channels = os.environ.get("AIRTABLE_CHANNELS_TABLE") or "Channels"
        self.api = (os.environ.get("AIRTABLE_API_URL") or "https://api.airtable.com").rstrip("/")
        self.dry_run = dry_run
        self._last = 0.0
        if not self.token or not self.base:
            die("AIRTABLE_TOKEN and AIRTABLE_BASE_ID must be set (environment or .env).")

    def _url(self, table: str) -> str:
        return f"{self.api}/v0/{self.base}/{urllib.parse.quote(table, safe='')}"

    def _req(self, method: str, url: str, body: dict | None = None):
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        for attempt in range(5):
            wait = 0.22 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                _, raw = http(method, url, headers, data, timeout=60)
                return json.loads(raw) if raw else {}
            except HttpError as e:
                if e.status == 429 or e.status >= 500:
                    time.sleep(30 if e.status == 429 else 2 * (attempt + 1))
                    continue
                raise
        raise HttpError(429, "Airtable kept returning 429/5xx")

    def list(self, table: str, formula: str | None = None) -> list:
        out, offset = [], None
        while True:
            params = [("pageSize", "100")]
            if formula:
                params.append(("filterByFormula", formula))
            if offset:
                params.append(("offset", offset))
            page = self._req("GET", self._url(table) + "?" + urllib.parse.urlencode(params))
            out.extend(page.get("records", []))
            offset = page.get("offset")
            if not offset:
                return out

    def update(self, record_id: str, fields: dict) -> None:
        if self.dry_run:
            print(f"  [dry-run] Airtable PATCH {self.posts}/{record_id} "
                  f"{json.dumps(fields, ensure_ascii=False)}")
            return
        self._req("PATCH", self._url(self.posts),
                  {"records": [{"id": record_id, "fields": fields}], "typecast": True})


class UploadPost:
    def __init__(self, dry_run: bool) -> None:
        self.key = os.environ.get("UPLOAD_POST_API_KEY", "")
        self.api = (os.environ.get("UPLOAD_POST_API_URL") or "https://api.upload-post.com/api").rstrip("/")
        self.dry_run = dry_run
        if not self.key and not dry_run:
            die("UPLOAD_POST_API_KEY must be set (environment or .env).")

    def _headers(self) -> dict:
        return {"Authorization": f"Apikey {self.key}"}

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self.api + path + ("?" + urllib.parse.urlencode(params) if params else "")
        _, raw = http("GET", url, self._headers())
        return json.loads(raw or b"{}")

    def send(self, method: str, path: str, body: dict | None = None) -> dict:
        """PATCH/DELETE with a JSON body. Prints instead of sending in dry-run."""
        if self.dry_run:
            print(f"  [dry-run] Upload-Post {method} {self.api}{path} "
                  f"{json.dumps(body, ensure_ascii=False) if body else ''}")
            return {"success": True, "dry_run": True}
        headers = self._headers()
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        _, raw = http(method, self.api + path, headers, data)
        return json.loads(raw or b"{}")

    def post_form(self, path: str, fields: list, files: list, idem_key: str) -> dict:
        if self.dry_run:
            shown = [(k, v if k != "title" or len(v) < 120 else v[:117] + "...") for k, v in fields]
            print(f"  [dry-run] Upload-Post POST {self.api}{path}")
            print(f"            Idempotency-Key: {idem_key}")
            for k, v in shown:
                print(f"            {k} = {json.dumps(v, ensure_ascii=False)}")
            for name, filename, content, mime in files:
                print(f"            {name} = <file {filename} ({mime}), downloaded from Airtable at send time>")
            return {"dry_run": True}
        body, ctype = encode_multipart(fields, files)
        headers = self._headers()
        headers["Content-Type"] = ctype
        headers["Idempotency-Key"] = idem_key
        _, raw = http("POST", self.api + path, headers, body, timeout=600)
        return json.loads(raw or b"{}")


# ---------------------------------------------------------------- helpers

def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def zone(name: str | None):
    if name and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            print(f"WARNING: unknown timezone {name!r}, using UTC", file=sys.stderr)
    return dt.timezone.utc


def slot(post_fields: dict, ch_fields: dict, default_time: str) -> dt.datetime:
    """Local datetime for this post: Scheduled for + channel Post time, in channel Timezone."""
    day = dt.date.fromisoformat(post_fields["Scheduled for"][:10])
    raw = (ch_fields.get("Post time") or default_time).strip()
    try:
        hh, mm = [int(x) for x in raw.split(":")[:2]]
    except ValueError:
        hh, mm = [int(x) for x in default_time.split(":")]
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone(ch_fields.get("Timezone")))


def media_kind(attachments: list) -> tuple:
    """Return ('text'|'photo'|'video', attachments_to_send) per the data model."""
    if not attachments:
        return "text", []
    for a in attachments:
        if (a.get("type") or "").startswith("video/"):
            return "video", [a]
    return "photo", list(attachments)


def download(att: dict) -> tuple:
    _, content = http("GET", att["url"], timeout=300)
    name = att.get("filename") or "media"
    mime = att.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return name, content, mime


def slack(text: str, dry_run: bool, enabled: bool) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url or not enabled:
        return
    if dry_run:
        print(f"  [dry-run] Slack webhook: {text[:200]}")
        return
    try:
        http("POST", url, {"Content-Type": "application/json"},
             json.dumps({"text": text}).encode("utf-8"), timeout=30)
    except (HttpError, urllib.error.URLError) as e:
        print(f"WARNING: Slack ping failed: {e}", file=sys.stderr)


def post_url_from(result: dict) -> str:
    return result.get("url") or result.get("post_url") or ""


# ---------------------------------------------------------------- publishing

class Run:
    def __init__(self, args) -> None:
        self.args = args
        self.at = Airtable(args.dry_run)
        self.up = UploadPost(args.dry_run)
        self.counts = {"Live": 0, "Scheduled": 0, "Failed": 0, "Manual": 0, "skipped": 0,
                       "cancelled": 0, "edited": 0}
        self.failures: list = []
        self.stop = False
        self._channels = None
        self._jobs = None

    @property
    def channels(self) -> dict:
        if self._channels is None:
            self._channels = {r["fields"].get("Name", ""): r["fields"]
                              for r in self.at.list(self.at.channels)}
        return self._channels

    def mark(self, rec: dict, status: str | None, **fields) -> None:
        if status:
            fields["Status"] = status
            self.counts[status] = self.counts.get(status, 0) + 1
            if status == "Failed":
                self.failures.append(f"{rec['fields'].get('Channel')} "
                                     f"{rec['fields'].get('Scheduled for')}: {fields.get('Error')}")
        self.at.update(rec["id"], fields)

    def label(self, rec: dict) -> str:
        f = rec["fields"]
        return f"{rec['id']} {f.get('Scheduled for', '?')} {f.get('Channel', '?')}"

    def skip(self, rec: dict, why: str) -> None:
        self.counts["skipped"] += 1
        print(f"- skip {self.label(rec)}: {why}")

    def cancel_old_job(self, rec: dict) -> None:
        job = (rec["fields"].get("Upload-Post ID") or "").strip()
        if not job:
            return
        try:
            self.up.send("DELETE", f"/uploadposts/schedule/{urllib.parse.quote(job)}")
            print(f"  cancelled earlier Upload-Post job {job}")
        except HttpError as e:
            if e.status != 404:
                print(f"  WARNING: could not cancel {job}: {e.message()}", file=sys.stderr)

    # -- approved posts ---------------------------------------------------

    def publish(self) -> None:
        mode = self.args.mode
        formula = "{Status}='Approved'"
        if self.args.channel:
            formula = "AND(" + formula + ",OR(" + ",".join(
                "{Channel}='" + c.replace("'", "\\'") + "'" for c in self.args.channel) + "))"
        recs = self.at.list(self.at.posts, formula)
        recs.sort(key=lambda r: (r["fields"].get("Scheduled for", ""), r["fields"].get("Channel", "")))
        print(f"{len(recs)} approved post(s); mode={mode}{' (dry-run)' if self.args.dry_run else ''}")
        done = 0
        for rec in recs:
            if self.stop or (self.args.limit and done >= self.args.limit):
                break
            if self.handle(rec, mode):
                done += 1

    def handle(self, rec: dict, mode: str) -> bool:
        f = rec["fields"]
        if not f.get("Scheduled for"):
            self.skip(rec, "no 'Scheduled for' date")
            return False
        ch = self.channels.get(f.get("Channel", ""))
        if ch is None:
            self.mark(rec, "Failed", Error=f"Channel {f.get('Channel')!r} not found in Channels table")
            return True
        if not ch.get("Active"):
            self.skip(rec, "channel inactive")
            return False
        when = slot(f, ch, self.args.default_time)
        local_now = now_utc().astimezone(when.tzinfo)
        due = when.date() <= local_now.date()
        if due and self.args.respect_post_time and when.date() == local_now.date() and local_now < when:
            due = False
        platform = (ch.get("Platform") or "").lower()

        if ch.get("Manual") or platform in NEVER_API:
            if not due:
                self.skip(rec, "manual channel, not due yet")
                return False
            return self.manual(rec, ch)

        if mode == "now":
            if not due:
                self.skip(rec, f"due {when.date()}")
                return False
            return self.send(rec, ch, platform, None)
        # schedule mode
        if when <= now_utc() + dt.timedelta(minutes=self.args.min_lead):
            self.skip(rec, f"slot {when.isoformat()} has passed or is too close; publish with --mode now")
            return False
        return self.send(rec, ch, platform, when)

    def manual(self, rec: dict, ch: dict) -> bool:
        f = rec["fields"]
        media = ", ".join(a.get("url", "") for a in f.get("Media") or [])
        print(f"* manual {self.label(rec)}")
        slack(f"Manual post due on *{f.get('Channel')}* ({f.get('Scheduled for')}), "
              f"owner {f.get('Owner') or 'n/a'}. Airtable record {rec['id']}.\n\n"
              f"{f.get('PostContent', '')}" + (f"\n\nMedia: {media}" if media else ""),
              self.args.dry_run, not self.args.no_slack)
        self.mark(rec, "Manual", Error=None)
        return True

    def send(self, rec: dict, ch: dict, platform: str, when: dt.datetime | None) -> bool:
        f = rec["fields"]
        text = f.get("PostContent") or ""
        kind, media = media_kind(f.get("Media") or [])
        user = (ch.get("Upload-Post user") or "").strip()
        problem = None
        if not user:
            problem = "Channel has no 'Upload-Post user'"
        elif not text.strip() and kind == "text":
            problem = "PostContent is empty"
        elif platform in MEDIA_REQUIRED and kind == "text":
            problem = f"{platform} needs an image or video; this post has no Media"
        elif platform in VIDEO_REQUIRED and kind != "video":
            problem = f"{platform} needs a video"
        elif platform == "pinterest" and not ch.get("Target ID"):
            problem = "Pinterest needs a board ID in the channel's 'Target ID'"
        elif platform == "reddit" and not ch.get("Target ID"):
            problem = "Reddit needs a subreddit in the channel's 'Target ID'"
        if problem:
            print(f"! {self.label(rec)}: {problem}")
            self.mark(rec, "Failed", Error=problem)
            return True

        self.cancel_old_job(rec)

        fields: list = [("user", user), ("platform[]", platform)]
        if platform == "reddit":
            title, _, body = text.strip().partition("\n")
            fields.append(("title", title.strip()))
            if body.strip():
                fields.append(("description", body.strip()))
        else:
            fields.append(("title", text))
        target = (ch.get("Target ID") or "").strip()
        if target and platform in TARGET_FIELD:
            fields.append((TARGET_FIELD[platform], target))
        if when is not None:
            fields.append(("scheduled_date", when.strftime("%Y-%m-%dT%H:%M:%S")))
            fields.append(("timezone", getattr(when.tzinfo, "key", None) or "UTC"))
        fields.append(("external_id", rec["id"]))

        transfer = self.args.media_transfer
        if transfer == "auto":
            # Airtable attachment URLs expire after a few hours. A scheduled job may
            # fetch media later, so upload the bytes when scheduling.
            transfer = "upload" if when is not None else "url"
        files: list = []
        field_name = "video" if kind == "video" else "photos[]"
        for att in media:
            if transfer == "url":
                fields.append((field_name, att["url"]))
            elif self.args.dry_run:
                files.append((field_name, att.get("filename", "media"), b"", att.get("type", "?")))
            else:
                try:
                    files.append((field_name,) + download(att))
                except (HttpError, urllib.error.URLError) as e:
                    self.mark(rec, "Failed", Error=f"Could not download media from Airtable: {e}")
                    return True

        path = {"text": "/upload_text", "photo": "/upload_photos", "video": "/upload"}[kind]
        digest = hashlib.sha1(json.dumps([text, f.get("Scheduled for"), [a.get("id") for a in media],
                                          when.isoformat() if when else "now"]).encode()).hexdigest()[:16]
        print(f"> {self.label(rec)} [{platform}, {kind}{', at ' + when.isoformat() if when else ''}]")
        try:
            res = self.up.post_form(path, fields, files, f"{rec['id']}-{digest}")
        except HttpError as e:
            msg = e.message()
            if e.status == 429:
                msg = "Upload-Post monthly quota reached (429). " + msg
                self.stop = True
            self.mark(rec, "Failed", Error=f"HTTP {e.status}: {msg}")
            return True
        except urllib.error.URLError as e:
            self.mark(rec, "Failed", Error=f"Network error: {e.reason}")
            return True
        if res.get("dry_run"):
            self.mark(rec, "Scheduled" if when else "Live",
                      **({"Upload-Post ID": "<job_id>"} if when else
                         {"Posted at": "<now>", "Live link": "<url>"}), Error=None)
            return True
        self.record_result(rec, platform, res, scheduled=when is not None)
        return True

    def record_result(self, rec: dict, platform: str, res: dict, scheduled: bool) -> None:
        if res.get("job_id"):
            self.mark(rec, "Scheduled", **{"Upload-Post ID": res["job_id"]}, Error=None)
            return
        results = res.get("results") or {}
        r = results.get(platform) or (next(iter(results.values())) if len(results) == 1 else None)
        if r is None and res.get("request_id"):
            # Upload-Post switched to background processing; --reconcile will finish it.
            self.mark(rec, "Scheduled", **{"Upload-Post ID": res["request_id"]},
                      Error="Processing in the background at Upload-Post. Run --reconcile.")
            return
        if r and r.get("success"):
            fields = {"Posted at": iso_utc(now_utc()), "Error": None}
            if post_url_from(r):
                fields["Live link"] = post_url_from(r)
            if res.get("request_id"):
                fields["Upload-Post ID"] = res["request_id"]
            self.mark(rec, "Live", **fields)
            return
        err = (r or {}).get("error") or res.get("error") or res.get("message") or json.dumps(res)[:800]
        self.mark(rec, "Failed", Error=str(err))

    # -- reconcile ---------------------------------------------------------

    def reconcile(self) -> None:
        recs = self.at.list(self.at.posts, "AND({Status}='Scheduled',{Upload-Post ID}!='')")
        print(f"Reconciling {len(recs)} scheduled post(s)")
        pending = self.pending_jobs() if recs else {}
        for rec in recs:
            job = rec["fields"]["Upload-Post ID"].strip()
            if job in pending:
                print(f"  {self.label(rec)}: waiting for {pending[job].get('scheduled_date')}")
                continue
            try:
                st = self.up.get("/uploadposts/status", {"job_id": job})
                key = "job_id"
                if st.get("status") == "not_found":
                    st = self.up.get("/uploadposts/status", {"request_id": job})
                    key = "request_id"
            except HttpError as e:
                print(f"  {self.label(rec)}: status check failed ({e.message()})")
                continue
            status = st.get("status")
            results = st.get("results") or []
            if status in ("pending", "queued", "processing", "in_progress", None):
                print(f"  {self.label(rec)}: still {status}")
                continue
            if status == "not_found":
                ch = self.channels.get(rec["fields"].get("Channel", ""), {})
                late = (rec["fields"].get("Scheduled for") and
                        slot(rec["fields"], ch, self.args.default_time) < now_utc() - dt.timedelta(hours=1))
                if late:
                    self.mark(rec, "Failed", Error=f"Upload-Post has no record of {job} "
                                                   f"(cancelled in the dashboard?)")
                else:
                    print(f"  {self.label(rec)}: {job} not found yet, checking again next run")
                continue
            failed = [r for r in results if not r.get("success")]
            if status == "failed" or failed:
                msg = "; ".join(f"{r.get('platform')}: {r.get('message') or r.get('error')}" for r in failed)
                self.mark(rec, "Failed", Error=msg or st.get("message") or "Upload-Post reported failure")
                continue
            fields = {"Error": None}
            stamps = sorted(r.get("upload_timestamp") for r in results if r.get("upload_timestamp"))
            fields["Posted at"] = stamps[-1] if stamps else iso_utc(now_utc())
            link = next((post_url_from(r) for r in results if post_url_from(r)), "")
            if not link:
                try:
                    hist = self.up.get("/uploadposts/history", {key: job, "limit": 10})
                    link = next((h.get("post_url") for h in hist.get("history", [])
                                 if h.get("success") and h.get("post_url")), "")
                except HttpError:
                    pass
            if link:
                fields["Live link"] = link
            self.mark(rec, "Live", **fields)

    # -- sync edits --------------------------------------------------------

    def pending_jobs(self) -> dict:
        """Jobs still waiting in Upload-Post's schedule, keyed by job_id."""
        if self._jobs is None:
            jobs, offset = {}, 0
            while True:
                page = self.up.get("/uploadposts/schedule", {"limit": 100, "offset": offset})
                items = page.get("scheduled_posts") or []
                for j in items:
                    jobs[j.get("job_id")] = j
                offset += len(items)
                if not items or offset >= int(page.get("total") or 0):
                    break
            self._jobs = jobs
        return self._jobs

    def sync(self) -> None:
        jobs = self.pending_jobs()
        recs = self.at.list(self.at.posts, "AND({Upload-Post ID}!='',"
                            "OR({Status}='Scheduled',{Status}='Draft',{Status}='To approve',"
                            "{Status}='Needs media',{Status}='Rejected'))")
        print(f"Syncing {len(recs)} post(s) against {len(jobs)} pending Upload-Post job(s)")
        for rec in recs:
            f = rec["fields"]
            job_id = f["Upload-Post ID"].strip()
            job = jobs.get(job_id)
            if job is None:
                continue  # already ran or never existed: --reconcile handles it
            if f.get("Status") in CANCEL_ON:
                print(f"  cancel {job_id} ({self.label(rec)} is now {f.get('Status')})")
                try:
                    self.up.send("DELETE", f"/uploadposts/schedule/{urllib.parse.quote(job_id)}")
                except HttpError as e:
                    print(f"  WARNING: cancel failed: {e.message()}", file=sys.stderr)
                    continue
                self.counts["cancelled"] += 1
                self.at.update(rec["id"], {"Upload-Post ID": None,
                                           "Error": f"Cancelled job {job_id} after status changed"})
                continue
            ch = self.channels.get(f.get("Channel", ""))
            if not ch or not f.get("Scheduled for"):
                continue
            when = slot(f, ch, self.args.default_time)
            body = {}
            job_when = job.get("scheduled_date") or ""
            try:
                current = dt.datetime.fromisoformat(job_when.replace("Z", "+00:00"))
                if current.tzinfo is None:
                    current = current.replace(tzinfo=dt.timezone.utc)
                moved = abs((current - when).total_seconds()) > 60
            except ValueError:
                moved = True
            if moved and when <= now_utc() + dt.timedelta(minutes=2):
                print(f"  ! {self.label(rec)}: new slot {when.isoformat()} is in the past; "
                      f"set a future date, or set Status to Approved and run --mode now")
                moved = False
            if moved:
                body["scheduled_date"] = when.strftime("%Y-%m-%dT%H:%M:%S")
                body["timezone"] = getattr(when.tzinfo, "key", None) or "UTC"
            text = f.get("PostContent") or ""
            if (f.get("Channel") and (ch.get("Platform") or "").lower() != "reddit"
                    and (job.get("title") or "") != text):
                body["title"] = text
            if not body:
                continue
            print(f"  edit {job_id} ({self.label(rec)}): {', '.join(body)}")
            try:
                self.up.send("PATCH", f"/uploadposts/schedule/{urllib.parse.quote(job_id)}", body)
                self.counts["edited"] += 1
            except HttpError as e:
                self.at.update(rec["id"], {"Error": f"Could not edit scheduled job: {e.message()}"})

    # -- summary -----------------------------------------------------------

    def summary(self) -> None:
        parts = [f"{v} {k.lower()}" for k, v in self.counts.items() if v]
        line = "Social calendar: " + (", ".join(parts) if parts else "nothing to do")
        print("\n" + line)
        for fail in self.failures:
            print(f"  failed: {fail}")
        if any(self.counts[k] for k in ("Live", "Scheduled", "Failed", "cancelled", "edited")):
            slack(line + ("\n" + "\n".join(self.failures) if self.failures else ""),
                  self.args.dry_run, not self.args.no_slack)


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="publish_approved",
        description="Publish or schedule Approved posts from the Airtable calendar via Upload-Post. "
                    "Nothing is sent unless you pass --mode, --reconcile or --sync.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  publish_approved.py --mode now --dry-run      # what a daily catch-up run would send\n"
               "  publish_approved.py --mode schedule           # queue approved posts in Upload-Post\n"
               "  publish_approved.py --sync --reconcile        # push edits, then mark Live/Failed")
    ap.add_argument("--mode", choices=["now", "schedule"],
                    help="now: publish due posts. schedule: hand future posts to Upload-Post")
    ap.add_argument("--reconcile", action="store_true", help="Flip Scheduled posts to Live/Failed")
    ap.add_argument("--sync", action="store_true",
                    help="Edit or cancel pending Upload-Post jobs whose Airtable post changed")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read Airtable, print every write and API call, send nothing")
    ap.add_argument("--channel", action="append", help="Only this channel (repeatable)")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N posts")
    ap.add_argument("--respect-post-time", action="store_true",
                    help="mode now: wait for the channel's Post time on the day (for hourly runs)")
    ap.add_argument("--min-lead", type=int, default=5,
                    help="mode schedule: minimum minutes ahead for a slot (default 5)")
    ap.add_argument("--default-time", default="09:00",
                    help="Post time when a channel has none (default 09:00)")
    ap.add_argument("--media-transfer", choices=["auto", "url", "upload"], default="auto",
                    help="Send Airtable media as URLs or as uploaded files. auto = URLs for "
                         "now, upload for schedule")
    ap.add_argument("--no-slack", action="store_true", help="Don't ping SLACK_WEBHOOK_URL")
    args = ap.parse_args()
    if not (args.mode or args.reconcile or args.sync):
        ap.error("nothing to do: pass --mode now|schedule, --reconcile or --sync")
    load_dotenv()
    if (args.reconcile or args.sync) and not os.environ.get("UPLOAD_POST_API_KEY"):
        ap.error("--reconcile and --sync read from Upload-Post, so UPLOAD_POST_API_KEY must be set "
                 "even with --dry-run")
    run = Run(args)
    try:
        if args.sync:
            run.sync()
        if args.reconcile:
            run.reconcile()
        if args.mode:
            run.publish()
    except HttpError as e:
        die(f"request failed: {e}")
    except urllib.error.URLError as e:
        die(f"network error: {e.reason}")
    run.summary()
    sys.exit(1 if run.failures else 0)


if __name__ == "__main__":
    main()

# Publishing

Once a post is `Approved`, it goes to Upload-Post with a `scheduled_date`, and Upload-Post publishes it at the right time. Airtable stays the source of truth. The post moves to `Scheduled`, then to `Live` or `Failed`.

Run only one publisher per base (one routine or one cron entry), so two runs don't pick up the same `Approved` posts at once.

## Who makes the calls

| | `publish_approved.py` | Claude calling Upload-Post itself |
|---|---|---|
| Cost | Nothing beyond the Upload-Post plan | Tokens for every post: reading the record, building the request, writing back |
| Runs | From cron, a CI job, or a Claude routine that only runs the script | Inside a conversation |
| Good for | Normal use | One-off fixes, or when Python can't run |

Use the script unless there's a reason not to. If you do make the calls yourself, follow the same rules as the script, which are written out below.

## Running it

```bash
S=skills/social-calendar/scripts

python3 $S/publish_approved.py --mode schedule --dry-run   # see every call first
python3 $S/publish_approved.py --mode schedule             # hand future approved posts to Upload-Post
python3 $S/publish_approved.py --sync                      # push Airtable edits to waiting jobs
python3 $S/publish_approved.py --reconcile                 # mark Scheduled posts Live or Failed
python3 $S/publish_approved.py --mode now                  # publish anything approved and already due
```

A sensible unattended setup is one cron entry or routine, a few times a day:

```bash
python3 $S/publish_approved.py --sync --reconcile --mode schedule
```

Add a daily `--mode now` run as well. It catches posts approved too late for their slot and handles `Manual` channels (Substack, communities), which get a Slack ping on their due date.

The script reads `.env` from the working directory or the repo root, prints a summary, posts it to `SLACK_WEBHOOK_URL` if set, and exits with code 1 if anything failed.

## What `--mode schedule` does

For every post with `Status` = `Approved`:

1. Look up its channel in the Channels table. Skip it if the channel is missing (`Failed`) or not `Active` (left as is).
2. If the channel is `Manual`, or the platform is `substack` or `other`: on the due date, ping Slack with the text and media links and set `Manual`. Before that, leave it alone.
3. Build the slot from `Scheduled for` + the channel's `Post time` (default `09:00`) in the channel's `Timezone` (default UTC). If the slot is less than 5 minutes away or already past, skip it and leave it for `--mode now`.
4. Work out the media type from `Media`: no attachments means text, any `video/*` attachment means video (the first one only), otherwise photo (all images).
5. Refuse posts the platform will reject: text-only on Instagram, TikTok, YouTube or Pinterest, non-video on YouTube, Pinterest without a board, Reddit without a subreddit. These become `Failed` with the reason in `Error`.
6. If the record already has an `Upload-Post ID` (it was scheduled before and someone set it back to `Approved`), cancel that job first.
7. Send the request and write back the result.

### The request

`POST https://api.upload-post.com/api/<endpoint>` as `multipart/form-data`, header `Authorization: Apikey <UPLOAD_POST_API_KEY>`.

| Media type | Endpoint | Media field |
|---|---|---|
| text | `/upload_text` | none |
| photo | `/upload_photos` | `photos[]`, repeated per image |
| video | `/upload` | `video` |

| Form field | Value |
|---|---|
| `user` | Channel's `Upload-Post user` |
| `platform[]` | Channel's `Platform` |
| `title` | `PostContent`. For Reddit, the first line is the title and the rest goes in `description` |
| `scheduled_date` | `YYYY-MM-DDTHH:MM:SS`, local wall-clock time with no `Z` and no offset |
| `timezone` | Channel's `Timezone`, an IANA name such as `Europe/Amsterdam` |
| `target_linkedin_page_id` | Channel's `Target ID`, LinkedIn company pages only |
| `facebook_page_id` | Channel's `Target ID`, Facebook |
| `pinterest_board_id` | Channel's `Target ID`, Pinterest |
| `subreddit` | Channel's `Target ID`, Reddit, without `r/` |
| `external_id` | The Airtable record ID, so Upload-Post's history can be traced back |

The script also sends an `Idempotency-Key` header made from the record ID and a hash of the text, date and media. If a run dies after Upload-Post accepted a post but before Airtable was updated, the retry shouldn't create a second post.

A date in `scheduled_date` with a `Z` or `+00:00` is read as UTC whatever `timezone` says. Send the naive local time plus `timezone`.

### Media

Upload-Post accepts public URLs in `photos[]` and `video`, as well as file uploads. Airtable's attachment URLs expire after a few hours, though, and a scheduled job may fetch its media later than that. So in schedule mode the script downloads each file from Airtable and uploads the bytes. In now mode it passes the URLs. Override with `--media-transfer url` or `--media-transfer upload`.

### Writing back

| Upload-Post response | Airtable update |
|---|---|
| `202` with `job_id` | `Status` = `Scheduled`, `Upload-Post ID` = job_id, `Error` cleared |
| `200` with `results.<platform>.success` true (`--mode now`) | `Status` = `Live`, `Posted at` = now, `Live link` = the result's `url`, `Upload-Post ID` = `request_id` if returned |
| `200` with `request_id` and no results (Upload-Post went async, common for long videos) | `Status` = `Scheduled`, `Upload-Post ID` = request_id, a note in `Error`. `--reconcile` finishes it |
| Error, or `success` false | `Status` = `Failed`, message in `Error` |
| `429` | `Failed` with a quota message, and the run stops |

## When a post changes in Airtable

Upload-Post keeps its own copy of a scheduled post. When someone edits the record, `--sync` brings the copy in line. It lists the pending jobs (`GET /api/uploadposts/schedule`) and compares them with the records that have an `Upload-Post ID`.

| Change in Airtable | What `--sync` does |
|---|---|
| New `Scheduled for`, or a channel's `Post time` or `Timezone` changed | `PATCH /api/uploadposts/schedule/<job_id>` with the new `scheduled_date` and `timezone` |
| `PostContent` edited | Same PATCH with the new `title` |
| `Status` set to `Draft`, `To approve`, `Needs media` or `Rejected` | `DELETE /api/uploadposts/schedule/<job_id>`, clears `Upload-Post ID`, notes it in `Error` |
| New media, or a different channel | Can't be edited. Set `Status` back to `Approved` and run `--mode schedule`. It cancels the old job and creates a new one |

Upload-Post refuses edits less than 60 seconds before a job runs (`409`), and to dates in the past. A sync that would move a job into the past is skipped with a warning. Change the date to a future one, or set the post to `Approved` and use `--mode now`.

By hand:

```bash
# reschedule and change the text
curl -s -X PATCH "https://api.upload-post.com/api/uploadposts/schedule/$JOB_ID" \
  -H "Authorization: Apikey $UPLOAD_POST_API_KEY" -H "Content-Type: application/json" \
  -d '{"scheduled_date": "2026-11-20T09:30:00", "timezone": "Europe/Amsterdam", "title": "New text"}'

# cancel (deletes the job and its media, no undo)
curl -s -X DELETE "https://api.upload-post.com/api/uploadposts/schedule/$JOB_ID" \
  -H "Authorization: Apikey $UPLOAD_POST_API_KEY"
```

## Reconciling Scheduled to Live

Upload-Post publishes on its own. Airtable only learns about it when `--reconcile` runs. For each `Scheduled` record:

1. If the job is still in the pending list, leave it.
2. Otherwise ask `GET /api/uploadposts/status?job_id=<id>`. If that returns `not_found`, try `?request_id=<id>`, which covers async uploads.
3. `completed` with every platform `success` true: set `Live`, `Posted at` = the latest `upload_timestamp`, and `Live link` from the result. If the status response has no URL, look it up with `GET /api/uploadposts/history?job_id=<id>` (`post_url`).
4. `failed`, or any platform with `success` false: set `Failed` with the platform messages in `Error`.
5. `pending`, `queued`, `processing`, `in_progress`: leave it for the next run.
6. Unknown to Upload-Post and more than an hour past its slot: set `Failed` ("cancelled in the dashboard?"). Earlier than that, wait.

Run it at least daily so the weekly review sees real `Live` posts and links.

## Doing it without the script

If you make these calls yourself in a conversation:

- Use the same field mapping and status rules as above. Never use a different status string.
- Confirm with the user before sending anything. Scheduling is a real action.
- Write back to Airtable straight after each call, not at the end of the batch, so a crash doesn't leave a scheduled post marked `Approved`. The next run would schedule it twice.
- Upload one post per request. One record maps to one channel and one platform.
- Every post costs tokens. For more than a handful, run the script.

## Not verified against the live API

These come from the Upload-Post docs, not from testing with a real account:

- Whether a scheduled job fetches URL media when it's created or when it runs. The script avoids the question by uploading bytes in schedule mode.
- How long the `Idempotency-Key` is remembered, and whether a retry after a failed request with the same key replays the failure.
- Whether `/uploadposts/status?job_id=` returns `pending` or `not_found` for a job that hasn't run yet. The script checks the pending list first, so either works.
- Whether `post_url` is filled in history for every platform. TikTok inbox uploads may have no public URL.

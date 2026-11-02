# Data model and shared conventions

Every part of the system follows this file: the Claude skills, the Python scripts and the templates. If you rename a field here, rename it everywhere.

## Repository layout

```
agent-social-calendar/
├── README.md                     # what it is, origin story, quick start
├── LICENSE                       # MIT
├── .env.example                  # AIRTABLE_TOKEN, AIRTABLE_BASE_ID, UPLOAD_POST_API_KEY, ...
├── skills/
│   ├── social-calendar/          # main skill: turn content into scheduled posts
│   │   ├── SKILL.md
│   │   ├── references/           # airtable.md, post-types.md, publishing.md, visuals.md
│   │   └── scripts/              # stdlib-only Python helpers
│   └── social-calendar-review/   # weekly feedback loop (run as a Claude routine)
│       └── SKILL.md
├── templates/                    # blank strategy + channel files to copy
│   ├── strategy.md
│   └── channels/_channel-template.md
├── examples/brightloop/          # fully worked fictional company
│   ├── strategy.md
│   └── channels/*.md
├── scripts/
│   └── setup_airtable.py         # creates the base tables via the Airtable API
└── docs/
    ├── data-model.md             # this file
    ├── setup.md                  # step by step: Airtable, Upload-Post, skills, publishing, routines
    ├── publishing.md             # how approved posts reach Upload-Post's scheduler
    ├── feedback-loop.md
    └── lessons.md                # field notes from running it
```

## The five layers

1. **Strategy layer**: `strategy.md`. Company goals, audiences, marketing OKRs, content pillars, global rules. One file per organisation.
2. **Channel layer**: `channels/<channel-slug>.md`. One file per account (company LinkedIn, founder X, an employee's LinkedIn...). Voice, goals, cadence, formats, do/don't, example posts. Plain text so that teammates can edit their own file (keeping them in a shared Google Drive folder works).
3. **Generation layer**: the `social-calendar` skill. You drop in a piece of content (a screenshot, a feature note, a podcast clip, a review, an event photo). Claude reads the strategy and channel files, checks the calendar for cadence gaps and duplicates, writes posts for each relevant channel and spreads them over days or weeks.
4. **Calendar layer**: Airtable base `Social Calendar`. The single source of truth for what goes out when. People approve posts here.
5. **Publishing layer**: `publish_approved.py` hands approved posts to Upload-Post with a `scheduled_date`, and Upload-Post's scheduler publishes them. Claude runs the script on request, or a routine or cron runs it a few times a day. It writes `Scheduled`, `Live` or `Failed` back to Airtable. No AI is needed at publish time.
6. **Feedback loop** (optional): the `social-calendar-review` skill runs weekly as a Claude routine. It checks published posts against the strategy, pulls metrics where available and proposes edits to strategy and channel files.

## Airtable base: `Social Calendar`

### Table `Posts`

| Field | Type | Notes |
|---|---|---|
| `Name` | Single line text (primary) | Short label, e.g. `Feature - CSV export` |
| `Status` | Single select | See status values below |
| `Scheduled for` | Date (ISO, no time) | `YYYY-MM-DD`. The hour comes from the channel's `Post time` |
| `Channel` | Single select | Must exactly match a `Name` in the `Channels` table |
| `PostContent` | Long text | Final post text. Real newlines. Hashtags inline |
| `Media` | Attachment | 0..n images, or 1 video. Airtable needs a public URL to ingest a file |
| `Source` | Long text | What the post was made from: a link, a note, a podcast episode |
| `Campaign` | Single line text | Groups posts from one piece of content, e.g. `2026-11 Podcast Ep 12` |
| `Owner` | Single line text | Person who approves this channel (email or name) |
| `Live link` | URL | Filled after publishing |
| `Posted at` | Date and time | Filled after publishing |
| `Upload-Post ID` | Single line text | `request_id` or `job_id` returned by Upload-Post |
| `Error` | Long text | Last publishing error, if any |

### `Status` values (exact strings, in lifecycle order)

| Value | Meaning | Who sets it |
|---|---|---|
| `Draft` | Written, not ready for review | agent |
| `Needs media` | Text ready, image or video missing (e.g. Instagram) | agent |
| `To approve` | Ready for the channel owner to review | agent |
| `Approved` | Owner approved, publish on `Scheduled for` | human (or agent if the owner opted in) |
| `Scheduled` | Handed to Upload-Post but not confirmed live yet: a `scheduled_date` job, or a long video that Upload-Post processes in the background. `--reconcile` flips it to `Live` or `Failed` | publisher |
| `Live` | Published | publisher |
| `Manual` | Platform not supported by the API (e.g. Substack). A Slack ping asks a human to post it | publisher |
| `Failed` | Publishing failed, see `Error` | publisher |
| `Rejected` | Not going out | human |

### Table `Channels`

The routing table the scripts read. Strategy and voice live in the markdown channel files, not here.

| Field | Type | Notes |
|---|---|---|
| `Name` | Single line text (primary) | e.g. `Brightloop LinkedIn`, `Maya LinkedIn`, `Maya X` |
| `Platform` | Single select | `linkedin`, `x`, `instagram`, `facebook`, `threads`, `tiktok`, `youtube`, `bluesky`, `pinterest`, `reddit`, `substack`, `other` |
| `Upload-Post user` | Single line text | Profile username in Upload-Post that holds this account's connection |
| `Target ID` | Single line text | LinkedIn company page ID / Facebook page ID / Pinterest board / subreddit. Empty for personal profiles |
| `Post time` | Single line text | Local time of day, e.g. `09:30` |
| `Timezone` | Single line text | IANA, e.g. `Europe/Amsterdam` |
| `Active` | Checkbox | Inactive channels are skipped |
| `Manual` | Checkbox | Upload-Post can't post here (Substack, communities): notify a human instead |
| `Channel file` | Single line text | Path to the channel markdown, e.g. `channels/brightloop-linkedin.md` |

## Media type detection

The publisher derives the type from `Media` and doesn't store it:
- no attachments → **text**
- any attachment whose MIME type starts with `video/` → **video** (first video only)
- otherwise → **photo** (all images, carousel where supported)

Instagram, TikTok, YouTube (video only) and Pinterest reject text-only posts. The skill never marks a text-only post for those platforms as `To approve`; it uses `Needs media`.

## Publishing rules

- **Due** means `Status = Approved` and `Scheduled for` is today or earlier, in the channel's timezone. A missed run catches up the next day.
- Channels with `Active` off are skipped and their posts stay `Approved`.
- Channels with `Manual` ticked, and every `substack` or `other` platform, are never sent to the API. The post becomes `Manual` and a human gets the text in Slack.
- A post with an unknown channel or missing required IDs (Pinterest board, subreddit) becomes `Failed` before any API call.
- Defaults when a channel has no `Post time` / `Timezone`: `09:00` and `UTC`.

## Upload-Post API (what the publishers call)

Base URL `https://api.upload-post.com/api`, header `Authorization: Apikey <UPLOAD_POST_API_KEY>`.

| Media type | Endpoint | Key fields |
|---|---|---|
| text | `POST /upload_text` | `user`, `platform[]`, `title` (= post text) |
| photo | `POST /upload_photos` | `user`, `platform[]`, `title`, `photos[]` (files or URLs) |
| video | `POST /upload` | `user`, `platform[]`, `title`, `video` (file or URL) |

Optional: `scheduled_date` (`YYYY-MM-DDTHH:MM:SS`, with `timezone`), `target_linkedin_page_id`, `facebook_page_id`, `pinterest_board_id`, `subreddit`. Scheduled jobs return a `job_id`. Verify field names against https://docs.upload-post.com before relying on them. The repo's scripts are the reference implementation.

## Environment variables

```
AIRTABLE_TOKEN=pat...            # personal access token: data.records:read/write, schema.bases:read/write
AIRTABLE_BASE_ID=app...
AIRTABLE_POSTS_TABLE=Posts
AIRTABLE_CHANNELS_TABLE=Channels
UPLOAD_POST_API_KEY=...
SLACK_WEBHOOK_URL=               # optional
STRATEGY_DIR=./my-strategy       # where strategy.md and channels/ live (local path or synced Drive folder)
```

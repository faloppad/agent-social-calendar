---
name: social-calendar
description: Turn a piece of content (a feature note, screenshot, news link, podcast clip, customer review, event photo, data point) into social media posts for every relevant channel, written in each channel's voice and scheduled into an Airtable social calendar for approval. Use when the user wants to schedule, plan, draft, spread or fill social posts across LinkedIn, X, Instagram, Facebook, Threads, TikTok, YouTube, Bluesky, Substack or employee and founder profiles; asks what is on the content calendar, where the cadence gaps are or whether a post is a duplicate; wants to attach images to posts that need media, approve or move posts, or push approved posts to Upload-Post. Triggers on "schedule posts about this", "post this on all our channels", "milk this podcast", "fill next week's calendar", "what's going out this week", "add this review to social", "make posts for the team", "approve my posts".
---

# Social calendar

Turn one piece of content into posts for many channels and put them in the Airtable calendar for people to approve. Publishing happens later through a plain script (n8n in mode A, `publish_approved.py` or Upload-Post's own scheduler in mode B), not through you.

Field names, status values and env vars come from `docs/data-model.md` in the repo. Don't rename anything. Script paths below are relative to this skill's folder.

## Before you start

1. Check that `AIRTABLE_TOKEN` and `AIRTABLE_BASE_ID` are set (environment or a `.env` in the working directory or repo root). Run `python3 scripts/airtable_calendar.py channels` as a smoke test. If the tables don't exist yet, point the user to `scripts/setup_airtable.py` at the repo root.
2. Find the strategy folder. Use `STRATEGY_DIR` if set. Otherwise look for `strategy.md` in the working directory, `./my-strategy/` and `./strategy/`. If there is none, ask where it lives. If the user has none yet, offer to copy `templates/strategy.md` and `templates/channels/_channel-template.md` and fill them in together before writing any posts.

If the Airtable MCP connector is available you can use it instead of the script for reads and writes. The rules in this file still apply. See `references/airtable.md`.

## Workflow

### 1. Read the strategy and the channel files

Read `strategy.md` in full: goals, OKRs, audiences, content pillars, global rules. Then list `channels/*.md` and read the files for the channels this content could go to. Each channel file holds that account's voice, goals, cadence, formats, do and don't lists, and example posts.

Match channel files to rows in the Channels table by the `Channel file` field. Only channels that are `Active` in Airtable can receive posts. If a channel file has no matching Channels row, say so and skip it.

### 2. Identify the post type and the campaign

Work out what the content is: feature launch, news, podcast or video clips, customer review, event photos, data or text insight, article promotion, or something else. Read `references/post-types.md` for how each type becomes posts, which channels suit it and how far to spread it.

Give the batch a `Campaign` label in the form `YYYY-MM <Type> <Label>`, for example `2026-11 Podcast Ep 12` or `2026-11 Feature CSV export`. Put the raw input in `Source` (link, file name, episode, or a one-line note).

Ask a question only when the answer changes the posts, such as "which channels?" when the strategy doesn't make it obvious, or "is this embargoed until a date?". Otherwise decide and say what you decided.

### 3. Look at the calendar

List what is already planned for the period you're about to fill (default the next 4 weeks, longer for podcast clips):

```bash
python3 scripts/airtable_calendar.py list --from today --to +28 --json > /tmp/calendar.json
```

For each target channel, work out:

- **Cadence gaps.** Posts per week against the channel file's target. Count every status except `Rejected` and `Failed`.
- **Collisions.** Days that already have a post on that channel. The default is at most one post per day per channel unless the channel file says otherwise.
- **Topic mix.** Too much of one type in a week (three news posts, two promos in a row). Push the new post to a lighter week instead.
- **Duplicates.** The same message already scheduled or recently live. The `create` command runs a similarity check. You can run it alone with `check-duplicates`.

### 4. Draft the posts

Write one post per channel per date. Each one follows that channel's file: voice, length, format, hashtags, call to action. Rules that apply everywhere:

- Use only facts that are in the source or the strategy files. Don't invent numbers, quotes, customer names or results.
- Don't paste the same text across channels. A founder's profile and the company page say different things about the same feature.
- Employee and co-founder channels are written in that person's voice and need their approval. Set `Owner` to the approver named in the channel file.
- `PostContent` holds the final text with real newlines. Emoji and Unicode are fine. Hashtags go inline, usually at the end, as the channel file says.
- LinkedIn and X show `**text**` as literal asterisks. Use `**bold**` only for channels a human pastes into a Markdown-aware editor, such as Substack. Follow the channel file if it says otherwise.
- Length limits: X splits anything over 280 characters into a thread, Threads over 500, Bluesky over 300. Write to fit unless the channel file asks for threads.
- Follow the writing rules in `strategy.md`. If it has none, write plain direct sentences and skip filler, hype words and stock phrases.

### 5. Pick the dates

`Scheduled for` is a date only, `YYYY-MM-DD`. The hour comes from the channel's `Post time` and `Timezone`, so don't put times in the post.

- Fill cadence gaps first, then spread the rest. Promotional posts for one item go over 2 to 3 weeks, not all on the same day.
- News goes out the same or next day, or not at all.
- Podcast clips go roughly one or two per channel per week over about 3 months.
- Mix types across a week: education, engagement, product, social proof.
- Never use a date in the past. Use today only if the user asks for it and knows the daily run may already have happened.
- If a week is full, move the post to the next week and say so in the report.

### 6. Host the media

Airtable only ingests public URLs. Local paths and `file://` links are silently ignored. Images and video in a create batch can be local paths. The script uploads them to catbox.moe first and passes the public URL to Airtable, which copies the file to its own storage. Catbox uploads are public and can't be deleted, so don't use it for anything confidential. Ask the user for a different host in that case. Details are in `references/airtable.md`.

For text and data posts that need a visual (Instagram, TikTok, or a channel file that asks for one), make a simple image. Follow `references/visuals.md`.

### 7. Create the records

Write the batch as a JSON list using the Posts field names:

```json
[
  {
    "Name": "Feature - CSV export",
    "Status": "To approve",
    "Scheduled for": "2026-11-12",
    "Channel": "Brightloop LinkedIn",
    "PostContent": "You can now export any report to CSV.\n\nOne click, top right.",
    "Media": ["/tmp/csv-export.png"],
    "Source": "Release note 2026-11-10",
    "Campaign": "2026-11 Feature CSV export",
    "Owner": "maya@brightloop.example"
  }
]
```

Pick the status like this:

| Situation | Status |
|---|---|
| Ready for the owner to review (the default) | `To approve` |
| Instagram, TikTok, YouTube or Pinterest post with no media yet | `Needs media` |
| The user wants to go back and forth on the text first | `Draft` |
| The user explicitly approves on behalf of their own channels (see below) | `Approved` |

Dry-run first, show the user the plan, then create:

```bash
python3 scripts/airtable_calendar.py create /tmp/batch.json --dry-run
python3 scripts/airtable_calendar.py create /tmp/batch.json
```

`create` validates field names, statuses, dates and channel names, downgrades media-less posts for image-only platforms to `Needs media`, and refuses to write if it finds likely duplicates. Fix the batch, or pass `--allow-duplicates` if the user confirms they want the repeat. It writes in batches of 10. Plans kept in a CSV with columns `Date, Channel, Content Type, Post Text, Hashtags, Image Suggestion` can go straight in with `--csv`.

### 8. Report back

Finish with a table, one row per created record, sorted by date:

| Date | Channel | Status | Name | Opening line |
|---|---|---|---|---|

Under it, list in plain sentences: channels you skipped and why, posts you pushed to a later week, posts in `Needs media` and what they need, and anything the owner should check (claims, names, links).

## Other requests

- **"Add the image to these posts."** Run `python3 scripts/airtable_calendar.py attach <record_id> <file or URL>`. A post in `Needs media` moves to `To approve` automatically.
- **"Move this post", "reject that one".** Run `update <record_id> --set "Scheduled for=2026-11-20"` or `--set Status=Rejected`. If the post is already `Scheduled` (mode B), run `python3 scripts/publish_approved.py --sync` afterwards so Upload-Post's copy changes too.
- **"What's going out this week?"** Run `list --from today --to +7` and summarise by channel and day.
- **Changes to strategy or voice.** Edit the markdown files, not Airtable. The weekly `social-calendar-review` skill proposes these edits.

## Approving on behalf of the user

Only when the user says so explicitly ("approve mine", "these can go straight out"), and only for channels where they are the `Owner`. Never approve posts on an employee's or co-founder's profile, even if asked in passing. Point the user to that person instead. Set those records to `Approved`, either at creation or with `update <record_id> --set Status=Approved`, and list them separately in the report.

## Handing off to publishing

Approved posts go out in one of two ways. Ask the user once which one they use if you can't tell from the repo's setup notes.

- **Mode A (n8n).** Nothing to do. The daily n8n run publishes `Approved` posts whose `Scheduled for` is today or earlier.
- **Mode B (direct).** Once posts are `Approved`, run `python3 scripts/publish_approved.py --mode schedule --dry-run`, show the output, then run it without `--dry-run`. Upload-Post holds the schedule and the status becomes `Scheduled`. Read `references/direct-publishing.md` for rescheduling, cancelling and reconciling. Prefer the script over making the Upload-Post calls yourself, because the script costs no tokens per post.

Never publish or schedule anything the user hasn't asked for in this conversation. Writing records with `To approve` is the normal end of this skill.

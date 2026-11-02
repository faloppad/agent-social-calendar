---
name: social-calendar-review
description: Weekly review of the social media calendar, meant to run as a scheduled Claude routine. Checks last week's published posts against the strategy and channel files, checks the next two weeks for cadence gaps, overload and off-strategy posts, pulls engagement metrics where a connector or export exists, and proposes concrete edits to strategy.md and the channel files. Use when the user asks for a weekly social review, a social media report, how last week's posts did, whether posts follow the strategy, what to change in the channel voice or cadence, or to set up the feedback loop routine for the social calendar.
---

# Social calendar review

A weekly check that closes the loop. It looks back 7 days and ahead 14 days, then writes a short report and proposes edits to the markdown files that drive the `social-calendar` skill.

This skill reads Airtable and never writes to it. It changes strategy and channel files only after the user approves the change, unless the routine prompt says otherwise.

## Setup

- `AIRTABLE_TOKEN` and `AIRTABLE_BASE_ID`, in the environment or a `.env` in the working directory or repo root.
- `STRATEGY_DIR` pointing at the folder with `strategy.md` and `channels/`. If it isn't set, look for `strategy.md` in the working directory, `./my-strategy/` and `./strategy/`.
- The calendar script from the main skill: `skills/social-calendar/scripts/airtable_calendar.py` (below, `$CAL`). The Airtable MCP connector works too if it's connected.

## Steps

### 1. Load the rules

Read `strategy.md` and every `channels/*.md` for active channels (`python3 $CAL channels`). Note for each channel: target cadence, allowed post types, voice rules, banned words or topics, hashtag rules, and the owner. Note the current OKRs and content pillars from the strategy.

If last week's review exists in `$STRATEGY_DIR/reviews/`, read it and check whether its accepted proposals were applied.

### 2. Look back 7 days

```bash
python3 $CAL list --from -7 --to today --json > /tmp/review-past.json
```

From that list, look at:

- `Live` posts. These are the main subject.
- `Failed` and `Manual` posts. Did the failures get fixed? Did someone actually post the manual ones?
- `To approve`, `Needs media` and `Approved` posts with a date in the past. These are missed approvals or a publisher that didn't run.

Check each `Live` post against its channel file and the strategy:

- Voice and format. Does it sound like the channel file's examples? Length, hashtags, links, emoji as the file says?
- Fit. Does it serve a pillar or OKR in `strategy.md`? Is the post type allowed on this channel?
- Cadence. Count per channel against the target. Note channels over or under.
- Repetition. Near-identical posts on the same channel, or the same message on every channel on the same day.
- Facts. Claims, numbers and names that the `Source` field doesn't back up.

Only report problems you can point to with a specific post. Quote the record name and date.

### 3. Look ahead 14 days

```bash
python3 $CAL list --from +1 --to +14 --json > /tmp/review-next.json
```

Per channel and week, flag:

- Gaps: weeks below the cadence target. Suggest which post type would fill them from the content that's already around (a podcast with unused clips, a recent article).
- Overload: more than one post a day on a channel, or a week dominated by one type (three news posts, back-to-back promos).
- Off-strategy posts: content that doesn't match any pillar or that the channel file rules out.
- Approval bottlenecks: `To approve` posts due in the next 3 days, grouped by `Owner`, so someone can chase them.
- `Needs media` posts due in the next 7 days, with what each one needs.

### 4. Pull metrics where you can

Try these in order and use whatever is available:

1. A platform connector, such as a LinkedIn connector or another analytics MCP. Pull impressions, reactions, comments, reposts and clicks per post for the last 7 days and match them to records by `Live link` or date and channel.
2. A web analytics connector (GA4 or similar). Pull sessions from social referrers or UTM-tagged links for the week.
3. Manual exports: CSV files in `$STRATEGY_DIR/metrics/` (for example a LinkedIn page analytics export). Use the newest file per channel and say which file you read.

When none of these exist for a channel, write "No metrics for <channel> this week" and move on. Never estimate, extrapolate or invent numbers. A review without metrics is still useful for the strategy and cadence checks.

With metrics, compare posts on the same channel only. Look for patterns that repeat over at least 3 posts, such as post type, opening style, media or no media, day of week. A single good or bad post is not a pattern.

### 5. Write the report

Save it to `$STRATEGY_DIR/reviews/YYYY-MM-DD.md` (create the folder if needed) and print it. Keep it under one screen:

```markdown
# Social review, week of 2026-11-02

## Summary
Three to five plain sentences. What went out, what broke, the one change worth making.

## Last 7 days
| Channel | Live | Target | Failed | Notes |
|---|---|---|---|---|

Specific issues, one bullet each, with record name and date.

## Metrics
Per channel: what you found and its source, or "No metrics for <channel> this week".

## Next 14 days
Gaps, overload, off-strategy posts, approvals to chase (by owner), media still needed.

## Proposed changes
Numbered list. Each one names the file, says why in one sentence, and shows a diff.
```

### 6. Propose edits to the strategy and channel files

Propose a change only when this week's evidence supports it: a repeated mistake, a rule nobody follows, a cadence that doesn't hold, or a pattern in the metrics over several posts. Each proposal is a unified diff against the current file:

```diff
--- channels/brightloop-linkedin.md
+++ channels/brightloop-linkedin.md
@@ Cadence @@
-- 5 posts per week, Monday to Friday
+- 4 posts per week, Monday to Thursday. Friday posts got under half the reactions of other days over the last 6 weeks.
```

Don't apply the diffs. List them and wait for the user to say which ones to apply. Apply them without asking only if the routine prompt explicitly allows it, and then only for the kinds of change it names. Never change another person's channel file without their approval, even when allowed to apply changes.

Don't edit Airtable records from this skill. If a planned post should change, say which one and why. The user or the `social-calendar` skill makes the change.

## Sample routine prompt

Set this up as a weekly scheduled task or routine, for example every Monday at 08:00, with the repo as the working directory:

```
Run the social-calendar-review skill for the past week.
STRATEGY_DIR is ./my-strategy. Airtable credentials are in .env.
Use the LinkedIn connector for metrics if it's available. Otherwise read the newest
CSV in ./my-strategy/metrics/ for each channel, and say plainly where there are none.
Save the report to ./my-strategy/reviews/ and post the Summary and Proposed changes
sections to #marketing in Slack.
Don't apply any proposed changes. I'll reply with the numbers I want applied.
```

To let the routine make small fixes on its own, replace the last line with something like "You may apply proposed changes to hashtag lists and posting days in my own channel files. Leave everything else as a proposal."

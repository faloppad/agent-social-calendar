# Feedback loop

Scheduling posts is half the job. The other half is checking, every week, that what went out still matches the strategy and learning which posts worked.

The `social-calendar-review` skill does this. Run it as a weekly Claude routine (a scheduled task), for example every Monday at 08:00.

## What it does

1. **Looks back 7 days.** Every `Live` post is checked against its channel file and `strategy.md`: voice, format, which pillar or OKR it serves, cadence per channel, repetition across channels, claims the `Source` doesn't back up. It also flags `Failed` posts, `Manual` posts nobody posted, and approvals that were missed.
2. **Looks ahead 14 days.** It looks for cadence gaps, days where one channel is overloaded, too much of one post type (three news reactions in a week), and planned posts that break a channel rule.
3. **Reads metrics where it can.** It uses a LinkedIn or other analytics connector if one is connected, or the newest CSV export in `STRATEGY_DIR/metrics/`. When there are no metrics for a channel, it says so in the report and doesn't guess.
4. **Writes a short report** to `STRATEGY_DIR/reviews/` and proposes concrete edits to `strategy.md` and the channel files, as diffs.

It doesn't edit Airtable and doesn't apply its proposals unless the routine prompt allows it.

## Setting it up

Use the sample prompt at the bottom of [`skills/social-calendar-review/SKILL.md`](../skills/social-calendar-review/SKILL.md). In Claude Code, create a scheduled task or routine with the repo as the working directory and paste that prompt.

To let it fix small things on its own, say so explicitly in the prompt and name what it may change ("hashtag lists and posting days in my own channel files"). Never let it change someone else's channel file without their approval.

## Why it matters

The channel files are the system's memory. If a post type keeps working (customer reviews on LinkedIn did best in the original setup), that should end up in the channel file so the next batch of posts uses it. If a voice rule keeps being broken, the rule needs to be clearer. The weekly review is how those lessons get written down.

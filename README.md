# agent-social-calendar

Run a dozen social media accounts in a couple of hours a month. You give your agent a screenshot, a feature note, a podcast clip or a customer review. It writes posts for every channel in that channel's voice, fits them into the calendar and puts them in Airtable for approval. A plain script publishes what's approved.

This is the system [Daniel Faloppa](https://github.com/faloppad) uses to run about 14 accounts for [Equidam](https://www.equidam.com) and his other companies: company pages, his own profiles, and his co-founders' and salespeople's profiles. He walked through it live at an AI meetup in Rotterdam. This repo is the open version: Claude skills, scripts, templates and a full worked example, so you can set it up with your own agent, your own Airtable and your own channels.

```mermaid
flowchart TD
  IN["Content<br/>screenshot · feature · podcast · review · news · event photo"] --> SK
  subgraph Strategy layer
    ST[strategy.md<br/>goals, OKRs, pillars, rules]
    CH[channels/*.md<br/>one file per account: voice, cadence, formats]
  end
  ST --> SK
  CH --> SK
  SK["Claude + social-calendar skill<br/>writes posts, picks dates, checks cadence and duplicates"] --> AT
  AT[("Airtable: Social Calendar<br/>To approve → Approved")]
  OW[Each owner approves<br/>their own posts] --> AT
  AT -->|Approved| PUB["publish_approved.py<br/>run by Claude, a routine or cron"]
  PUB -->|scheduled_date| UP[Upload-Post scheduler]
  UP --> NET[LinkedIn · X · Instagram · Facebook · Threads · TikTok · YouTube · ...]
  UP -.->|Live / Failed + link| AT
  AT --> REV[Weekly Claude routine<br/>social-calendar-review]
  REV -.->|proposes edits| CH
```

## How it works

1. **Strategy layer.** `strategy.md` holds goals, audiences, OKRs, content pillars and global rules. Each account gets its own `channels/<name>.md` with voice, goals, cadence, formats and example posts. They're plain text files. Keep them in a shared Drive folder and each teammate can edit their own.
2. **Generation.** You drop content into Claude: "here's the new export feature, schedule it". The `social-calendar` skill reads the strategy and channel files and checks what's already planned. If a channel is short of its 5 posts this week, a post goes on Friday. If there's too much news this week, it moves to next week. It writes one post per channel per date and creates them in Airtable.
3. **Approval.** Airtable is the shared calendar. Each person approves posts on their own profile. Nobody posts as someone else without their OK.
4. **Publishing.** Approved posts go to [Upload-Post](https://www.upload-post.com) with a `scheduled_date`, and Upload-Post's own scheduler publishes them on time. It also keeps the connections to every network alive. The hand-off is a plain script: Claude runs it when you say "schedule everything that's approved", or a routine or cron runs it a few times a day. Airtable gets the result back: `Scheduled`, then `Live` with the link, or `Failed` with the reason. [`docs/publishing.md`](docs/publishing.md)
5. **Feedback loop.** A weekly Claude routine checks last week's posts against the strategy, reads metrics where it can and proposes edits to the channel files. [`docs/feedback-loop.md`](docs/feedback-loop.md)

## What one piece of content turns into

From the [Brightloop example](examples/brightloop/), a fictional startup: the founder's podcast appearance becomes 20+ posts across the company page, the founder's LinkedIn and X, the salesperson's LinkedIn, Instagram and Substack, spread over six weeks. A customer review, a feature launch and two news reactions are mixed in. See [`sample-calendar.csv`](examples/brightloop/sample-calendar.csv).

Post types that work well (more in [`post-types.md`](skills/social-calendar/references/post-types.md)):
- **Customer reviews:** screenshot a review and drop it in. These did best on LinkedIn in the original setup.
- **Feature launches:** one screenshot and one message, and the feature is scheduled on every channel.
- **Podcast and talk clips:** 20–30 shorts per episode, spread over about three months.
- **News reactions:** a screenshot of the headline plus your take.
- **Data posts:** one number or one chart, rendered from the data as a simple card.
- **Event photos.**

## Quick start

```bash
git clone https://github.com/faloppad/agent-social-calendar.git
cd agent-social-calendar
cp .env.example .env                                   # add Airtable + Upload-Post keys
cp -r templates my-strategy                            # then fill in, or let Claude interview you
python3 scripts/setup_airtable.py                      # creates Posts + Channels tables in your base
mkdir -p ~/.claude/skills && ln -s "$PWD/skills/social-calendar" ~/.claude/skills/  # install the skills
ln -s "$PWD/skills/social-calendar-review" ~/.claude/skills/
```

Then, in Claude Code:

> Here's a screenshot of a review we got today. Schedule posts about it on our channels.

The full walkthrough is in [`docs/setup.md`](docs/setup.md). The scripts use only the Python 3.9+ standard library, with nothing to install.

## What you need

| | Why | Cost |
|---|---|---|
| Claude Code (or another agent that loads `SKILL.md` files and runs Python) | Writes and schedules posts | Your plan |
| Airtable | Shared calendar and approvals | Free to start. You'll outgrow the free record limit within months |
| Upload-Post | Connections to every network, and the scheduler that publishes on time | Depends on the number of accounts. Daniel pays about 60/month for 14 |
| Slack webhook | Daily summary, manual-post pings | Free, optional |

## Repo map

```
skills/social-calendar/          main skill: content → posts → Airtable
  references/                    airtable, post types, visuals, publishing
  scripts/airtable_calendar.py   list / create / update / attach / check-duplicates
  scripts/publish_approved.py    schedules approved posts in Upload-Post (--mode schedule | now, --sync, --reconcile)
skills/social-calendar-review/   weekly feedback loop, run as a Claude routine
scripts/setup_airtable.py        creates the Airtable tables
templates/                       blank strategy + channel files
examples/brightloop/             complete fictional example
docs/                            setup, data model, publishing, feedback loop, field notes
```

The data model (tables, fields, status values) is in [`docs/data-model.md`](docs/data-model.md). Every part of the repo follows it.

## Field notes

The short version of [`docs/lessons.md`](docs/lessons.md):
- The aim is a steady presence, not virality. Regular posting tells customers you're alive and ready to work with them.
- Spread one piece of content across every channel for months.
- Use AI to write and plan. Use scripts to publish.
- Don't build your own integrations with the social networks. They change, rate-limit and ban.
- Keep the human approval step. It's what keeps the output from being slop.

## Status

The skills and scripts are tested offline against mocked Airtable and Upload-Post APIs, but haven't been run against live accounts yet. The system itself has run Equidam's channels in production for months (on an earlier n8n-based publisher). Run `--dry-run` first and [open an issue](https://github.com/faloppad/agent-social-calendar/issues) if something breaks.

## About

Built by [Daniel Faloppa](https://github.com/faloppad), founder of [Equidam](https://www.equidam.com), a startup valuation platform. Equidam's own social channels run on this system. If you're a founder getting ready to raise, Equidam is where you can work out and defend your valuation.

MIT licensed. Pull requests welcome, especially new post types, channel templates and connectors for metrics.

# Brightloop: a worked example

Brightloop is a made-up company. Its people, customers, investors, podcast and numbers are all fictional. It exists to show what a filled-in strategy folder looks like and to let you try the system without writing your own files first.

## The company

Brightloop makes scheduling and dispatch software for installer companies with 5 to 50 technicians: heat pump installers, plumbers, electricians. It's based in Rotterdam, has 140 paying customers in the Netherlands and Belgium, and raised a €1.6M seed round in September 2026.

- Maya Verhoef, CEO. Used to plan jobs at her uncle's HVAC company. Posts on LinkedIn and X.
- Jonas Brandt, co-founder, sales. Posts on LinkedIn in English and Dutch, and approves every one of his posts himself.

In late October, Maya appeared on a (fictional) podcast, The Ground Floor, episode 58, to talk about how they raised the round. The sample calendar shows that one episode turned into posts across six channels over six weeks, mixed in with a customer review, a feature launch and two news reactions.

## What's in the folder

| File | What it shows |
|---|---|
| `strategy.md` | Goals, Q4 OKRs, content pillars with target mix, approval rules (including Maya's auto-approve opt-in on X), banned phrases, and a "What changed" log with a few entries from the weekly review |
| `channels/brightloop-linkedin.md` | Company page. Customer proof first. Reviews do best here |
| `channels/brightloop-instagram.md` | Every post needs media, so text-only drafts land in `Needs media` |
| `channels/brightloop-x.md` | Low-effort channel, cut from 4 to 3 posts a week after a review |
| `channels/maya-linkedin.md` | Founder voice, and the fundraising pillar with what she's willing to share |
| `channels/maya-x.md` | Short takes. The one channel where Claude may set posts to `Approved` |
| `channels/jonas-linkedin.md` | Salesperson voice, half in Dutch. Shows a rule added after he rejected a post |
| `channels/brightloop-substack.md` | Manual channel. The publisher pings Slack instead of posting |
| `channels.csv` | Rows for the Airtable `Channels` table |
| `sample-calendar.csv` | 23 rows for the `Posts` table, covering every status from `Draft` to `Live` |

The calendar is an excerpt. At full cadence Brightloop would have about 18 posts a week; the CSV shows the campaigns worth reading. Filter it by `Campaign` to follow one piece of content across channels.

Some things to look for:

- The same podcast clip reads differently on Maya's LinkedIn, Maya's X and the company Instagram.
- The Dekker review went out on the company page, but Jonas rejected the version on his profile. The `Source` field has his reason, and `channels/jonas-linkedin.md` now has a rule so it doesn't happen again.
- The data post is a `Draft` because Maya wants to re-check a number. The clip 5 post is a `Draft` because Noor hasn't agreed to be named yet.

## Try it

1. Follow the main setup in `docs/setup.md` (Airtable token, base ID, Upload-Post key).
2. Point your strategy folder at this example in `.env`:

   ```
   STRATEGY_DIR=./examples/brightloop
   ```

3. Create the Airtable tables:

   ```
   python3 scripts/setup_airtable.py
   ```

4. Import `channels.csv` into the `Channels` table and `sample-calendar.csv` into `Posts` (in Airtable, open the table, then "Add or import" > "CSV file"). Map the columns by name. In the CSVs, `checked` means a ticked checkbox.
5. The `Upload-Post user` and `Target ID` values are placeholders. Leave them as they are to try the writing side. To actually publish, replace them with your own Upload-Post profile names and page ID, and set every Status in the imported calendar to `Rejected` or delete the rows first, so nothing fictional goes out.
6. Open Claude Code in the repo, drop in a screenshot (a review, a headline, a product screen) and ask:

   ```
   Schedule posts from this screenshot for Brightloop. Check the calendar for
   gaps first and spread them over the next two weeks.
   ```

   Claude reads `strategy.md` and the channel files, looks at what's already in the `Posts` table, and adds new rows as `To approve` or `Needs media`. Compare what it writes for Maya and for Jonas.

When you're ready to write your own, start from [`templates/`](../../templates/).

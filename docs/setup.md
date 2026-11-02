# Setup

About an hour end to end, most of it clicking through Upload-Post connections. You need:

- **Claude Code** (CLI or desktop) or another agent that can read files, run Python 3.9+ and load a `SKILL.md`.
- **Airtable**: the free plan works to start.
- **Upload-Post** ([upload-post.com](https://www.upload-post.com)): keeps the connections to every social network alive. Pricing depends on how many accounts you connect.
- **Slack incoming webhook**: optional, for daily summaries and manual-post pings.

## 1. Get the repo

```bash
git clone https://github.com/faloppad/agent-social-calendar.git
cd agent-social-calendar
cp .env.example .env
```

## 2. Write your strategy files

```bash
mkdir -p my-strategy/channels
cp templates/strategy.md my-strategy/
cp templates/channels/_channel-template.md my-strategy/channels/<your-company>-linkedin.md
```

Fill in `strategy.md` and one file per channel. The fastest way is to let Claude interview you. [`templates/README.md`](../templates/README.md) has a prompt for that. [`examples/brightloop/`](../examples/brightloop/) shows a finished set for a made-up startup with a company page, a founder and a salesperson.

Start with 2 or 3 channels. Add more once the first ones run on their own.

If teammates should edit their own channel files, put `my-strategy/` in a shared Google Drive or Dropbox folder that syncs to your machine, and set `STRATEGY_DIR` to that path in `.env`.

## 3. Airtable

1. Create an empty base called `Social Calendar` (Airtable's API can't create bases in every workspace, so do this by hand). Copy its ID from the URL: `https://airtable.com/appXXXXXXXXXXXXXX/...`.
2. Create a personal access token at [airtable.com/create/tokens](https://airtable.com/create/tokens) with scopes `data.records:read`, `data.records:write`, `schema.bases:read`, `schema.bases:write`, limited to that base.
3. Put both in `.env` (`AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID`).
4. Create the tables:

   ```bash
   python3 scripts/setup_airtable.py --dry-run     # see what it will create
   python3 scripts/setup_airtable.py
   ```

5. Fill the `Channels` table, one row per account, either by hand or from a CSV with the same columns as [`examples/brightloop/channels.csv`](../examples/brightloop/channels.csv):

   ```bash
   python3 scripts/setup_airtable.py --seed-channels my-strategy/channels.csv
   ```

   `Name` must match the channel name you use in the channel files, character for character.

6. Optional but useful: add an Airtable view per person (filter `Owner` = them, `Status` = `To approve`) or a simple Interface, so each person only sees their own posts to approve.

Free plan limit: Airtable's free plan caps records and attachment storage per base. With one record per post per channel you'll hit it within months. Archive old `Live` rows or upgrade.

## 4. Upload-Post

1. Create an account and an API key. Put the key in `.env` as `UPLOAD_POST_API_KEY`.
2. Create one Upload-Post **profile** per person or brand (e.g. `acme`, `maya`, `jonas`). Put the profile name in the `Upload-Post user` column of the Channels table.
3. Connect each social account to its profile. For teammates' personal LinkedIn or X accounts, send them Upload-Post's connect link so they log in themselves. You never need their passwords.
4. For LinkedIn company pages and Facebook pages, copy the page ID into `Target ID`.

## 5. Install the skills

Claude Code looks for skills in `~/.claude/skills/` (all projects) or `.claude/skills/` (this project):

```bash
mkdir -p ~/.claude/skills
cp -r skills/social-calendar skills/social-calendar-review ~/.claude/skills/
```

Or symlink them so `git pull` keeps them current:

```bash
ln -s "$PWD/skills/social-calendar" ~/.claude/skills/social-calendar
ln -s "$PWD/skills/social-calendar-review" ~/.claude/skills/social-calendar-review
```

Other agents: each `SKILL.md` is plain markdown with a short YAML header. Point your agent at it as a system prompt or instruction file, and make sure it can run the Python scripts next to it.

Smoke test:

```bash
python3 skills/social-calendar/scripts/airtable_calendar.py channels
```

## 6. Publishing

Approved posts are handed to Upload-Post's scheduler by `publish_approved.py`. Decide who runs it: Claude when you ask ("schedule everything that's approved"), a Claude routine, or cron. See [publishing.md](publishing.md).

Test with a dry run first:

```bash
python3 skills/social-calendar/scripts/publish_approved.py --mode schedule --dry-run
```

## 7. First real post

In Claude Code, from the repo folder:

> Here's a screenshot of a 5-star review we got today. Schedule posts about it on our channels.

Claude reads your strategy, checks the calendar, writes one post per relevant channel, spreads them over the coming days and creates them in Airtable as `To approve`. Approve them in Airtable, then publish with your chosen mode.

## 8. Close the loop

Set up the weekly review as a Claude routine or scheduled task. See [feedback-loop.md](feedback-loop.md).

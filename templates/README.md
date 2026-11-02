# Templates

Blank versions of the two files Claude reads before writing any post:

- `strategy.md` holds the company-wide rules: goals, OKRs, content pillars, approval policy, banned phrases, and the list of channels.
- `channels/_channel-template.md` covers one account: voice, cadence, formats, example posts. You make one copy per account.

For a filled-in version, see [`examples/brightloop/`](../examples/brightloop/).

## Set up your strategy folder

1. Pick a folder for your strategy and point `STRATEGY_DIR` in `.env` at it.
   - A local folder, e.g. `STRATEGY_DIR=./my-strategy`, works if you're the only one editing.
   - A synced Google Drive folder works better with a team. Install Google Drive for desktop and use the local path, e.g. `STRATEGY_DIR="/Users/you/Library/CloudStorage/GoogleDrive-you@company.com/Shared drives/Marketing/social-strategy"`. Teammates edit their own channel file from the Drive web UI or their own machine, and Claude picks up the change on the next run.
2. Copy the templates in:

   ```
   mkdir -p "$STRATEGY_DIR/channels"
   cp templates/strategy.md "$STRATEGY_DIR/"
   cp templates/channels/_channel-template.md "$STRATEGY_DIR/channels/"
   ```

3. For each account, copy `_channel-template.md` to `channels/<slug>.md` (e.g. `channels/acme-linkedin.md`) and fill it in. Keep `_channel-template.md` around for the next account.
4. Add a row per account to the Airtable `Channels` table. Its `Name` must match the channel name at the top of the file exactly, and `Channel file` holds the relative path, e.g. `channels/acme-linkedin.md`.

The files are plain markdown, which suits both sides. Claude reads text well, and anyone can edit text without learning a tool.

## How many channels to start with

Start with two or three: the company LinkedIn page, the founder's LinkedIn, and one more where your customers actually are. LinkedIn tends to work best for B2B, so it's the safe first pick.

Run those for a month. Once a week, check what went out and fix the channel files where Claude got the voice wrong. Then add channels one at a time. Each new account needs a filled-in file, an Upload-Post connection and a row in Airtable, and adding them all at once makes it hard to tell which file is causing bad posts.

Employees' personal accounts come last, and only for people who want it. They approve their own posts.

## Let Claude interview you

Filling in a strategy from a blank page is slow. It's faster to have Claude ask you questions and write the files from your answers. Paste this into Claude Code from the repo root:

```
I want to fill in my social media strategy files for this repo.
Read templates/strategy.md, templates/channels/_channel-template.md and
examples/brightloop/ to see what a finished set looks like.

Then interview me. Ask one question at a time, in plain language, and wait
for my answer. Start with the company, audiences and goals, then ask which
accounts I post from. For each account, ask who owns it, how it should sound,
and for 2-3 real posts from that account I liked (I'll paste them or give
you a link).

Don't invent facts, numbers or example posts. If I don't know something,
leave the [bracket] in place and move on.

When we're done, write strategy.md and one channels/<slug>.md per account
into $STRATEGY_DIR, and print the rows I need to add to the Airtable
Channels table.
```

Expect it to take 20 to 40 minutes. Have a few of your recent posts open, plus your marketing goals for the quarter if you have them written down.

## Keep them up to date

- The weekly review routine (`skills/social-calendar-review`) adds lines to the "What changed" log in `strategy.md` and the "Performance notes" section of each channel file. Read them now and then and delete the ones that are wrong.
- When a post comes out wrong, fix the file rather than the post. Editing the post fixes it once; editing the file fixes every post after it.

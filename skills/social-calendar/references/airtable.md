# Airtable reference

How the skill reads and writes the `Social Calendar` base. Table and field names are in `docs/data-model.md`.

## Three ways in

1. **`scripts/airtable_calendar.py`** (preferred). Stdlib Python, no installs. It handles paging, batching, rate limits, validation, duplicate checks and media hosting. Run any subcommand with `--help`.
2. **The Airtable MCP connector**, if the user has it connected. Good for quick reads. It works with table, field and select-choice IDs rather than names, so look them up first (list tables, then get the table schema). The rules in this file still apply: exact status strings, `YYYY-MM-DD` dates, public URLs for media, and a duplicate check before bulk writes.
3. **Raw REST with curl**, for debugging. Examples below.

All three need a personal access token with `data.records:read` and `data.records:write`. `scripts/setup_airtable.py` also needs `schema.bases:read` and `schema.bases:write`. Limit the token to the one base.

## Script cheatsheet

```bash
S=skills/social-calendar/scripts

python3 $S/airtable_calendar.py channels                      # active channels
python3 $S/airtable_calendar.py list --from today --to +14    # next two weeks
python3 $S/airtable_calendar.py list --channel "Maya X" --status "To approve"
python3 $S/airtable_calendar.py list --from -7 --to today --status Live --json
python3 $S/airtable_calendar.py check-duplicates /tmp/batch.json
python3 $S/airtable_calendar.py create /tmp/batch.json --dry-run
python3 $S/airtable_calendar.py create plan.csv --csv
python3 $S/airtable_calendar.py update recXXXX --set Status=Approved
python3 $S/airtable_calendar.py update --json /tmp/updates.json   # [{"id": ..., "fields": {...}}]
python3 $S/airtable_calendar.py attach recXXXX ./chart.png
```

Relative dates are day offsets: `today`, `+14`, `-7`. Write `--from -7` with a space, or `--from=-7`.

## Records

- One record per post. The same message on three channels is three records. The same channel on two dates is two records.
- `Scheduled for` is a date field. Send `"2026-11-12"`. The API also accepts a full ISO timestamp but the field only keeps the date.
- `PostContent` takes real newlines (`\n` in JSON). Emoji and other Unicode go through unchanged.
- `Status` must be one of the exact strings in the data model. A typo with `typecast: true` creates a new select option instead of failing, which then breaks every filter. The script validates before it writes.
- `Channel` must match a `Name` in the Channels table exactly. The script checks this and writes with `typecast: true`, so a channel that exists in Channels but not yet as an option in `Posts.Channel` gets added.
- There's no uniqueness constraint. Check for duplicates before bulk uploads (`check-duplicates`, or `create`, which runs the check and refuses to write if it finds any).

## Batching and limits

- Create and update take at most 10 records per request. The script chunks for you.
- Airtable allows 5 requests per second per base. After a 429 it wants you to wait 30 seconds. The script spaces requests about 220 ms apart and backs off on 429.
- Creates can run in parallel if you're scripting your own loop, but stay under the rate limit.
- List results come back 100 per page with an `offset` token. The script follows it.
- The free plan caps a base at 1,000 records and 1 GB of attachments (at the time of writing). Archive old `Live` and `Rejected` posts once a quarter if you're on it.

## Filters (`filterByFormula`)

Field names go in braces. Strings use single quotes. `TODAY()` and `NOW()` run in UTC, so near midnight a "today" filter can be off by a day for users far from UTC. The script loads a slightly wider window and cuts dates locally for that reason.

Approved and due today or earlier (what the daily publisher looks for):

```
AND({Status}='Approved', IS_BEFORE({Scheduled for}, DATEADD(TODAY(), 1, 'days')))
```

Approved and due exactly today:

```
AND({Status}='Approved', IS_SAME({Scheduled for}, TODAY(), 'day'))
```

The next 14 days on one channel:

```
AND(
  {Channel}='Brightloop LinkedIn',
  IS_AFTER({Scheduled for}, DATEADD(TODAY(), -1, 'days')),
  IS_BEFORE({Scheduled for}, DATEADD(TODAY(), 15, 'days'))
)
```

Live in the last 7 days (for the weekly review):

```
AND({Status}='Live', IS_AFTER({Posted at}, DATEADD(NOW(), -7, 'days')))
```

Waiting on someone:

```
OR({Status}='To approve', {Status}='Needs media')
```

Handed to Upload-Post but not confirmed yet:

```
AND({Status}='Scheduled', {Upload-Post ID}!='')
```

Posts mentioning a phrase:

```
FIND('csv export', LOWER({PostContent}))
```

With the script, pass any of these with `--formula`. It is ANDed with the other flags:

```bash
python3 $S/airtable_calendar.py list --formula "FIND('csv export', LOWER({PostContent}))"
```

## Raw REST

```bash
# list, URL-encoding the formula
curl -sG "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Posts" \
  -H "Authorization: Bearer $AIRTABLE_TOKEN" \
  --data-urlencode "filterByFormula=AND({Status}='Approved', IS_SAME({Scheduled for}, TODAY(), 'day'))" \
  --data-urlencode "sort[0][field]=Scheduled for"

# create (max 10 records)
curl -s -X POST "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Posts" \
  -H "Authorization: Bearer $AIRTABLE_TOKEN" -H "Content-Type: application/json" \
  -d '{"typecast": true, "records": [{"fields": {"Name": "Test", "Status": "Draft",
       "Scheduled for": "2026-11-12", "Channel": "Maya X", "PostContent": "Line one\nLine two"}}]}'

# update (max 10 records). PATCH changes only the fields you send.
curl -s -X PATCH "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Posts" \
  -H "Authorization: Bearer $AIRTABLE_TOKEN" -H "Content-Type: application/json" \
  -d '{"records": [{"id": "recXXXX", "fields": {"Status": "Approved"}}]}'
```

Table names with spaces need URL encoding in the path (`Social%20Posts`), or use the table ID (`tbl...`).

## Attachments (`Media`)

Airtable only accepts attachments by public URL. It downloads the file and stores its own copy. Local paths and `file://` URLs are silently dropped. The request succeeds and the field stays empty.

The write format is a list of objects:

```json
{"Media": [{"url": "https://files.catbox.moe/abc123.png", "filename": "chart.png"}]}
```

To add a file and keep the existing ones, send the existing attachments back by `id` together with the new URL. `attach` does this unless you pass `--replace`.

```json
{"Media": [{"id": "attXXXX"}, {"url": "https://files.catbox.moe/new.png"}]}
```

When you read a record, each attachment has `url`, `filename`, `type` (MIME) and `size`. Airtable's attachment URLs expire after a few hours, so publishers read them at publish time and never store them.

### Hosting local files on catbox.moe

`attach` and `create` upload local paths to catbox.moe on their own. By hand:

```bash
curl -s -F "reqtype=fileupload" -F "fileToUpload=@/path/img.png" https://catbox.moe/user/api.php
# -> https://files.catbox.moe/abc123.png
```

Then set `{"Media": [{"url": "https://files.catbox.moe/abc123.png"}]}`. Once Airtable has copied the file, the catbox link isn't needed.

Catbox files are public, and anonymous uploads can't be deleted. Don't send anything confidential there (unreleased screenshots, customer data). Use your own bucket or CDN instead and pass the URL. 0x0.st and transfer.sh were tried and didn't work with Airtable. The limit is 200 MB per file.

### Moving posts on after attaching

Posts in `Needs media` wait for a file. `attach` moves them to `To approve` when it adds media. Pass `--keep-status` to stop that, or `--status Approved` when the owner has already approved the text and asked you to finish the job.

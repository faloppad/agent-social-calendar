# Visuals

Most posts in this system don't need a designer. There are four kinds of visual, in order of how often they come up.

## 1. Screenshots (news, reviews, features)

The cheapest visual and often the best one. A customer review screenshot did better than anything else on LinkedIn in the original setup.

- News: screenshot the headline and the first paragraph, not the whole page. Crop out cookie banners and ads.
- Reviews: crop to the stars, the review text and the date. Leave out the reviewer's full name and photo if the platform allows it, or ask the user.
- Features: one screenshot of the feature in use, at a size where the text is readable on a phone. If the UI is dense, crop to the part that changed.

On macOS the user takes these with `Cmd+Shift+4` and drops them into the chat. Save the file to a known path before attaching it.

Some review sites block automated browsers. Don't try to scrape them. Ask for a screenshot.

## 2. Data cards (one number or one chart)

For text or data posts going to Instagram, or any channel file that asks for an image:

1. Write a small self-contained HTML file: one headline, one number or one chart, a source line, the brand colours and font from `strategy.md` (fall back to white background, near-black text, one accent colour).
2. Size it for the platform: 1080x1350 (4:5) for Instagram and LinkedIn feed, 1080x1080 if unsure, 1600x900 for X.
3. Render it to PNG with a headless browser, for example:
   ```bash
   npx playwright screenshot --viewport-size=1080,1350 card.html card.png
   ```
   or Chrome: `chrome --headless --screenshot=card.png --window-size=1080,1350 card.html`.
4. Look at the PNG before attaching it. Check that the text fits, numbers match the source, and nothing is cut off.

Draw charts from the data. Don't use an image model for them, because it will get the numbers wrong.

Keep a few HTML card templates in the strategy folder (`visuals/`) once you have a look you like, and reuse them so the feed looks consistent.

## 3. Event and team photos

Use the photo as it is. Light crop and straightening are fine. Don't add text on top unless the channel file says so. Check that everyone visible would be OK with it being posted. If unsure, ask.

## 4. Video clips (podcasts, talks)

Cutting clips is still a manual or separate-tool job. Each clip needs:
- A burned-in caption track (most people watch on mute).
- 9:16 for Instagram, TikTok and Shorts. LinkedIn and X take 9:16 too, and 1:1 is safer there.
- Under 90 seconds unless a channel file says otherwise.

Once clips exist as files, the skill attaches one per post and spreads them over weeks (see `post-types.md`).

## Getting files into Airtable

Airtable only ingests attachments from a public URL. `scripts/airtable_calendar.py attach <record> <file>` uploads local files to catbox.moe first and attaches the resulting URL. Catbox uploads are public and can't be deleted. Don't send anything confidential through it. Use your own bucket (S3, R2, Drive with public link) for that.

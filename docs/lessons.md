# Field notes

Things learned from running this across about 14 accounts (two companies' pages, founder profiles, co-founders and salespeople). Most of these came up as questions at the talk.

## What it's for

The goal is a steady presence, not virality. Posting regularly tells customers and partners the company is alive and shipping. That's most of what marketing has to do for a B2B software company, and this system does it in about two hours a month.

If you need to be at the cutting edge of a platform, you still need people doing manual, platform-native work. This system helps them too: a marketer or video editor makes the content, and the agent spreads it across every channel without anyone copy-pasting.

## Milk every piece of content

One talk, one podcast episode or one feature launch can feed posts for months. A podcast cut into 20 shorts, each going to several channels over three months, is a couple of hundred posts from one recording.

The best performer in the original setup was a batch of customer review screenshots, scheduled over a year. One of them, a 5-star review that opened with "the service started badly", got about 10,000 views on LinkedIn, far above the usual. Nobody predicted it. You only find these by posting consistently and looking at the numbers afterwards.

## Approvals

- People approve posts on their own profiles. Don't post as someone without their OK, especially as their employer.
- The approval step is what keeps the output from becoming AI slop. In practice approvals drift toward a quick glance, so make the channel files good enough that a glance is enough.
- When a new feature ships, every salesperson's LinkedIn can carry a post about it the same week, each in their own voice, each approved by them.

## Use AI only where it helps

Claude writes the posts and decides when they go out, based on cadence. Publishing is a plain script. A script is cheaper, faster, and does the same thing every time. The first version used a daily n8n workflow for publishing. Upload-Post's own scheduler made it redundant, so now a small script hands approved posts over and Upload-Post does the timing. The rule still applies: if a script can do it, don't spend tokens on it.

## Don't connect to the networks yourself

Building your own integrations with LinkedIn, X, Instagram and the rest means dealing with API changes, rate limits and app reviews. A service like Upload-Post keeps the connections alive for you, and your posts go out through an established app rather than a brand-new one with a single account.

## Platform risk

- Automation that looks like spam gets punished. A follow/unfollow script on Twitter (around 2013) got the account shadow-banned, and it never fully recovered.
- On LinkedIn, automated connection requests above roughly 50 a day start to get risky. Scheduled posts haven't caused visible problems, but reach varies a lot from post to post either way.
- Some sites, Trustpilot among them, block automated browsers. Take screenshots by hand. It takes five seconds.

## What's not automated yet

- **Video editing.** Cutting podcast clips is still manual or done in a separate tool.
- **Comments and replies.** Engagement is still human.
- **Metrics.** The weekly review reads metrics where a connector or export exists. LinkedIn's connector for Claude is new. Expect this part to improve.

## Airtable limits

The free plan fills up. With one record per post per channel you'll hit the cap within months. Archive old `Live` rows, or pay.

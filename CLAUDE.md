# Rumo Instagram kit — read this first

This repository builds a pool of Instagram posts for Rumo (rumopt.com) from the 60 free
grammar chapters and the 40 free graded stories: carousels in nine formats plus faceless
Reels with original music made by the kit. It checks every line against the live site and
posts ONE post a day at 18:00 UK time (every other one a Reel) through Meta's own free
Instagram API. It runs on GitHub Actions (free for a public repository); `.gitlab-ci.yml`
is the same on GitLab. Total cost: €0. No Publer, no laptop needed.

The code is finished and tested end to end against local stand-ins for rumopt.com, Meta's
Graph API and a public file host (`tests/run_offline_test.py`). Run it, don't rewrite it.

## Who you are talking to
Loenne. Dutch, not a developer, cannot check Portuguese. Short, plain English. He does
every click on GitHub and Meta himself (a robot clicking a new GitHub account got it
suspended once). Never ask him to paste a key, password or token into the chat; the key goes
only into the repository secret META_TOKEN. He pays for nothing: never propose a paid plan.

## Hard rules
1. Never write, translate, correct or "improve" Portuguese, and never edit the text in
   posts.json by hand. Every Portuguese line, explanation and story translation is a
   reference into a live page; the accuracy gate refuses anything else (a refused post is
   left out, never published).
2. English you may change: hooks, labels, questions, the 'Start here' post (rumo_formats.py:
   `brand_post`, MEANING_HOOKS, REAL_CARDS, ENGAGE, SEND). No statistics, no promises, no
   claims the site does not make.
3. Never print, log or commit the key. It lives only in the secret META_TOKEN and is sent only
   in an Authorization header (never in a URL), so errors cannot leak it.
4. If a run stops, GitHub opens an issue (and emails him) with FAILED.txt: read it to him in
   plain words and follow its WHAT TO DO. Never work around the gate.
5. If Meta's live API answers differently from rumo_meta.py, read the Instagram Platform docs
   (content publishing, resumable uploads, media insights), make the smallest change, rerun
   the offline test, then continue.

## How it runs
- `.github/workflows/rumo.yml`: runs at 17:05 and 18:05 UTC (one of them is 18:05 UK, summer or
  winter), catch-ups at 19:35 and 20:35 UTC, and Tue/Thu 11:05 + 12:05 UTC for trial Reels.
  `rumo.py daily` posts only when a slot is open (18:00-23:00 UK; trial 12:00-17:00 UK) and
  not yet filled, so extra runs do nothing. A day the runner misses entirely is skipped and
  reported in DONE.txt (never posted late the next day).
- Each post is drawn and checked against the live site just before it goes out.
- Carousel slides and Reel covers need a public address: the kit pushes them to the `media`
  branch (replaced every time, so the repository never grows) and gives Instagram the raw
  URL of that commit. Reel videos are uploaded straight from the runner (resumable upload).
  The repository must therefore be PUBLIC. The key is not in it.
- After every run the kit commits posts.json, config.json, DONE.txt, FAILED.txt back
  ("[skip ci]"). The concurrency group allows one run at a time.
- Never posts twice: before making a post it records the Instagram container in posts.json
  (`pending`, committed at once); the next run looks at Instagram (container status, and the
  last 25 captions) and finishes or adopts it.
- Weekly (any daily run 7+ days after the last): reads each post's results (reach, saves,
  shares) from Instagram, updates the mix, reads the follower count (trial Reels switch on by
  themselves at 200), decides the call-to-action test, and tops up the queue.

## Commands (Actions > Rumo Instagram > Run workflow > pick one)
daily · build · build --rerender · build --fresh · connect · launch · check · status ·
trial on · trial off. Locally (for drawing previews only): `python rumo.py setup`, then build.

## What the kit does, and why (research of 28 Oct 2026)
- Reels reach strangers best for small accounts; carousels earn saves. So every other post
  is a Reel. Reels move from the first frame, show the question within half a second, always
  have sound, and loop. Kinds: quick quiz, "3 in a row" quiz, guess the meaning, 3 texts from
  a Brazilian friend, textbook vs. real, "Can you read this?" (a story line).
- Carousels: quiz, meaning, real, traps, flip, examples, cheat, story, words, brand ('Start
  here'). Slide 2 always makes sense on its own.
- Captions: first line reads like a search, then the page's own one-line description (checked
  by the gate), an honest question, 5 specific hashtags. A send prompt only where it fits, a
  save prompt on reference posts.
- Pattern of 10: Reel, story, Reel, phrase, Reel, save, Reel, challenge, Reel, words. Launch:
  post 1 ('Start here') with `launch`, then 18:00 daily.
- Call to action: "Comment START" (Meta's comment-to-message rule in Business Suite, already
  live) or "link in bio". Split test: weeks 1 and 4 after launch "Comment START", weeks 2 and 3
  "link in bio"; after six weeks the kit keeps "Comment START" unless link-in-bio weeks
  reached at least 25% more (Reels compared with Reels, carousels with carousels).
- Learning: rates per person reached (saves + sends), last 4 weeks, posts with 100+ reach,
  3+ posts per format, formats compete only within their slot: best third x1.3, weakest x0.8.
- Trial Reels (from 200 followers): extra Reel Tue/Thu 12:00 UK, shown to non-followers first
  (`trial_params` SS_PERFORMANCE). `trial off` also stops the automatic switch.

config.json: `cta_mode` comment|bio, `keyword`, `preview_posts` (30), `exclude` (lines never
posted, refused from the next run on), `cta_test`, `cta_test_weeks`, `trial_reels`,
`trial_auto`, `instagram_username` (rumo.portuguese).

## Setup order (he clicks; you direct) — see SETUP-STEPS.txt
1. Public repository with these files; Actions enabled.
2. Meta: developer account, app (Business), Page token that never expires -> secret META_TOKEN.
3. Run workflow `connect`: T1 key + account, T2 public image address.
4. Run workflow `build`: download the `preview` artifact from the run page; he looks, plays a
   Reel with sound, approves the 'Start here' wording. Tell him once: "Two diminutive examples
   on the site are spelled cafézinho / pézinho; the usual spelling is cafezinho / pezinho. I
   left those lines out; worth asking your reviewer."
5. Before 12:00 UK: run workflow `launch` (post 1 now, a test Reel upload, launch date). Then he
   comments START on post 1 from his personal account: 'dm works' or 'no dm'. If 'no dm': set
   `"cta_mode": "bio"` in config.json (edit on GitHub, commit). If Meta only accepts '#'
   keywords: `"keyword": "#START"`.
6. Done. Daily posts start at 18:00 UK on the launch date (or the next day if launched after
   12:00). On day 3 he pins the first three posts; on day 3-4 he checks the first Reel's cover.

## Later
- "Rumo Instagram check" -> run workflow `check`, read its log; summarise: posts out, results
  per format, his numbers against the ranges it prints, the call-to-action outcome; give him
  the Supabase query it prints and read the result back (comment weeks vs link-in-bio weeks).
- Key expired / revoked (FAILED: "Meta refused the Instagram key"): he makes a new Page token
  (SETUP-STEPS.txt, part 2) and replaces the secret. Page tokens from a long-lived user token
  do not expire, but changing his Facebook password or removing the app revokes them.
- "public images" failure: the repository became private, or GitHub raw is down; make it
  public again / rerun.
- Site changed a lot: the gate stops everything; run `build --fresh`.
- New formats are a new project: ask him first.

## Files
posts.json (pool + progress; never hand-edit text) · config.json · DONE.txt / FAILED.txt
(plain-English status) · preview/ and cache/ (not committed) · rumo_meta.py (Instagram API) ·
rumo_host.py (image addresses, saving progress)

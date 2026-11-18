"""Rumo Instagram kit. Runs on a free runner (GitHub Actions or GitLab CI) and posts through
Meta's own free Instagram API. Nothing to pay.

    python rumo.py build         read the chapters and stories, check them, draw the first weeks
                                 (--rerender: redraw only; --fresh: read the site again)
    python rumo.py connect       check the Instagram key (secret META_TOKEN) and the image address
    python rumo.py launch        post 1 ('Start here') now, test a Reel upload, set the launch date
    python rumo.py daily         the scheduled run: posts at 18:00 UK (trial Reels Tue/Thu 12:00),
                                 once a week reads results and steers the mix
    python rumo.py check         report: what went out, what worked, the Supabase query
    python rumo.py trial on|off  Trial Reels twice a week (switch on by themselves at 200 followers)
    python rumo.py status        where things stand
    python rumo.py setup         (only on a laptop) install what is needed to build and preview
"""
import os
import subprocess
import sys
import time as systime
import webbrowser
from datetime import date, datetime, time as dtime, timedelta, timezone

if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or newer is needed. Install Python 3.12 from python.org and run again.")

# Everything runs inside the kit's own virtual environment (.venv), created by
# `setup`. That avoids touching the laptop's main Python and avoids pip
# refusing to install on Macs with a managed Python.
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent
_VENV = _ROOT / ".venv"
_VPY = _VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if (_VPY.exists() and _Path(sys.prefix).resolve() != _VENV.resolve()
        and os.environ.get("RUMO_NO_VENV") != "1"):
    sys.exit(subprocess.call([str(_VPY), str(_ROOT / "rumo.py"), *sys.argv[1:]]))

from rumo_common import (FAILED_FILE, ROOT, clear_failed, fail, load_state, save_state, say)  # noqa: E402

TZ_NAME = "Europe/London"
SLOT_TIME = dtime(18, 0)
TRIAL_TIME = dtime(12, 0)
TRIAL_DAYS = (1, 3)       # Tuesday and Thursday
LEARN_WINDOW_DAYS = 28    # results from the last four weeks
MIN_REACH = 100           # a post seen by fewer people says nothing yet
MAX_CYCLES = 2            # when the pool is used up, the best posts go out once more
MISS_LIMIT = 0.10         # more than 10% of posts failing the gate = something systematic
LEARN_AFTER_DAYS = 21     # results start steering the mix after three weeks


def _now(tz=None):
    """The current time. The offline test sets RUMO_NOW to move the clock forward."""
    fake = os.environ.get("RUMO_NOW")
    now = datetime.fromisoformat(fake.replace("Z", "+00:00")) if fake else datetime.now(timezone.utc)
    return now.astimezone(tz) if tz else now.astimezone(timezone.utc)


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TZ_NAME)
    except Exception:
        fail("setup", "Python cannot find the Europe/London time zone.",
             "Run: python rumo.py setup   (it installs the 'tzdata' package), then try again.")


def _cfg():
    from rumo_formats import config
    return config()


# ------------------------------------------------------------------ setup
SYNCED = ("onedrive", "my drive", "google drive", "googledrive", "dropbox", "icloud")


def _not_synced():
    """Sync tools lock files mid-save; keep the kit out of cloud folders."""
    where = str(ROOT).lower()
    hit = next((w for w in SYNCED if w in where), None)
    if hit:
        fail("setup", f"This folder is inside a synced cloud folder ({ROOT}).",
             "Move the Rumo-Instagram folder to a folder that is not synced, for example "
             "C:\\Users\\<you>\\Rumo-Instagram, open that folder in the Code tab, and run setup again.")


def cmd_setup():
    clear_failed()
    _not_synced()
    if not _VPY.exists():
        say("Creating the kit's own Python environment (.venv)...")
        r = subprocess.run([sys.executable, "-m", "venv", str(_VENV)])
        if r.returncode or not _VPY.exists():
            fail("setup", "Python could not create a virtual environment.",
                 "Install Python 3.12 from python.org (tick 'Add python.exe to PATH') and run setup again.")
    py = str(_VPY)
    say("Installing the Python packages this kit needs (about 100 MB, video tools included)...")
    r = subprocess.run([py, "-m", "pip", "install", "--upgrade", "-q",
                        "-r", str(ROOT / "requirements.txt")])
    if r.returncode:
        fail("setup", "pip could not install the packages.",
             "Check the internet connection and run: python rumo.py setup")
    say("Installing the headless browser that draws the slides (about 150 MB)...")
    r = subprocess.run([py, "-m", "playwright", "install", "chromium"])
    if r.returncode:
        probe = ("from playwright.sync_api import sync_playwright\n"
                 "with sync_playwright() as p:\n"
                 "    ok=False\n"
                 "    for ch in ('msedge','chrome'):\n"
                 "        try:\n"
                 "            p.chromium.launch(channel=ch).close(); ok=True; break\n"
                 "        except Exception: pass\n"
                 "raise SystemExit(0 if ok else 1)\n")
        if subprocess.run([py, "-c", probe]).returncode:
            fail("setup", "Playwright could not download its browser, and no Edge or Chrome was found.",
                 "Check the internet connection and run: python rumo.py setup")
        say("Playwright's own browser could not be downloaded; Edge or Chrome will be used instead.")
    probe = ("import imageio_ffmpeg, subprocess\n"
             "e = imageio_ffmpeg.get_ffmpeg_exe()\n"
             "out = subprocess.run([e, '-hide_banner', '-encoders'], capture_output=True, text=True, errors='replace').stdout\n"
             "raise SystemExit(0 if 'libx264' in out and ' aac ' in out else 1)\n")
    if subprocess.run([py, "-c", probe]).returncode:
        fail("setup", "The video tool (ffmpeg) is missing or cannot make MP4 video.",
             "Run: python rumo.py setup   again; tell Claude if it repeats.")
    r = subprocess.run([py, "-c", "from zoneinfo import ZoneInfo; ZoneInfo('Europe/London')"])
    if r.returncode:
        fail("setup", "The Europe/London time zone is missing.",
             "Run: python rumo.py setup   again; tell Claude if it repeats.")
    say("Setup done.")


# ------------------------------------------------------------------ build
def _gate_and_mark(state, only=None, fatal=True):
    """Run the gate; posts that fail are left out (status 'missed'), never published."""
    from rumo_gate import gate
    checked, missed, lines = gate(state, only=only)
    gone = len({p.get("url") for p in state["posts"] if p.get("gate") == "gone"})   # pages, not posts
    if checked and gone > 3:
        # many pages answering 404 at once is a broken site, not removed chapters: skip, don't drop
        for p in state["posts"]:
            if p.get("gate") == "gone":
                p["gate"] = "unread"
        lines = [ln.replace("GONE", "UNREAD", 1) for ln in lines]
    for p in state["posts"]:
        if p.get("gate") == "gone":
            p["gate"] = "missed"
    for p in state["posts"]:
        if only is not None and p["id"] not in only:
            continue
        if p.get("gate") == "missed" and p.get("status") not in ("scheduled", "published", "removed", "rejected"):
            p["status"] = "missed"
        elif p.get("gate") == "passed" and p.get("status") == "missed":
            p["status"] = "extracted"
    save_state(state)
    say(f"  accuracy gate: missed {len(missed)} of {checked} posts; passed {checked - len(missed)}.")
    for line in lines[:8]:
        say("   " + line)
    unread = sum(1 for ln in lines if ln.startswith("UNREAD"))
    if fatal and checked and unread > max(3, MISS_LIMIT * checked):
        fail("reading rumopt.com", "\n".join(lines[:12]),
             "Nothing was published. The site could not be read (offline, or rumopt.com down). "
             "Run the same command again later. If it says this again on the next run while "
             "rumopt.com opens fine in a browser: tell Claude (fix: python rumo.py build --fresh).")
    gone_posts = sum(1 for ln in lines if ln.startswith("GONE"))   # chapters removed on purpose
    if fatal and checked and len(missed) - unread - gone_posts > max(3, MISS_LIMIT * checked):
        fail("accuracy gate", "\n".join(lines[:40]),
             "Nothing was published. Many posts no longer match the site: the site probably changed. "
             "Tell Claude; the fix is usually: python rumo.py build --fresh")
    return missed


def _captions(state):
    from rumo_formats import caption_for
    cfg = _cfg()
    after_test = state.get("cta_decided") if cfg["cta_mode"] == "comment" else None
    for p in state["posts"]:
        if p.get("status") in ("scheduled", "published") or p.get("pending"):
            continue   # a half-posted post keeps its caption: the next run finds it on Instagram by it
        p["caption"] = caption_for(p, cfg, mode=p.get("cta_plan") or after_test)


def _upcoming(state, n):
    from rumo_formats import PLANNABLE
    return [p for p in sorted(state["posts"], key=lambda p: p.get("order", 10 ** 6))
            if p.get("status") in PLANNABLE and not p.get("pending")][:n]


def _render_upcoming(state, n):
    """Draw the next n posts in the queue; a post that cannot be drawn is replaced by the next one."""
    from rumo_formats import plan_order
    from rumo_render import render_all
    for _ in range(4):
        want = _upcoming(state, n)
        unfit = render_all(state, only={p["id"] for p in want}, log=say)
        save_state(state)
        if not unfit:
            return want
        plan_order(state, weights=state.get("weights"))
        _captions(state)
    return _upcoming(state, n)


def cmd_build(fresh=False, rerender=False):
    clear_failed()
    from rumo_extract import extract
    from rumo_formats import plan_order
    from rumo_gate import self_test
    from rumo_render import write_index

    state = load_state()
    if fresh or not state["posts"]:
        say("Reading the grammar chapters and the stories on rumopt.com...")
        try:
            state = extract(state)
        except SystemExit as e:
            fail("extract", str(e), "Tell Claude; the list of pages on the site may have changed.")
        except Exception as e:
            fail("extract", repr(e), "Check the internet connection and run the same command again. "
                 "If it repeats, tell Claude.")
        save_state(state)
    say("Accuracy gate, self-test (nine deliberately wrong posts must be rejected)...")
    problems = self_test(state)
    if problems:
        fail("gate self-test", "\n".join(problems),
             "Do not publish. Tell Claude: the checker itself is not trustworthy yet.")
    say("Accuracy gate, real run...")
    _gate_and_mark(state)
    if rerender:
        for p in state["posts"]:
            if p.get("status") in ("rendered", "unfit"):
                p["status"] = "extracted"
    for p in state["posts"]:   # an earlier plan is out of date: the daily run plans again
        if p.get("status") not in ("scheduled", "published"):
            p.pop("cta_plan", None)
    plan_order(state, weights=state.get("weights"))
    _captions(state)
    save_state(state)
    n = int(_cfg().get("preview_posts", 30))
    say(f"Drawing the first {n} posts (slides and Reels)...")
    try:
        want = _render_upcoming(state, n)
    except Exception as e:
        save_state(state)
        fail("render", repr(e), "Tell Claude the message above.")
    save_state(state)
    _report(state, want)
    idx = write_index(state, limit=n + 3)
    say(f"\nPreviews ready: {idx}")
    if not os.environ.get("RUMO_NO_BROWSER"):
        try:
            webbrowser.open(idx.resolve().as_uri())
        except Exception:
            pass


def _report(state, window):
    from collections import Counter
    from rumo_formats import PLANNABLE, rot_key
    pool = [p for p in state["posts"] if p.get("status") in PLANNABLE]
    c = Counter(rot_key(p) for p in window)
    say("  first weeks: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    say(f"  posts ready to go out in total: {len(pool)} (about {len(pool) // 7} weeks at 7 a week)")
    bad = Counter(p["status"] for p in state["posts"] if p.get("status") in ("missed", "unfit"))
    if bad:
        say("  left out: " + ", ".join(f"{k} {v}" for k, v in bad.items()))


# ------------------------------------------------------- Instagram (Meta's own API)
def _meta_fail(test, e, what=""):
    if e.token_problem:
        fail(test, f"Meta refused the Instagram key: {e.message}",
             "The key in the secret META_TOKEN has expired or was revoked. Make a new one (setup "
             "page, 'Instagram key'), replace the secret META_TOKEN with it, then run the workflow again.")
    if e.permission_problem:
        fail(test, f"The Instagram key lacks a permission: {e.message}",
             "Make the key again with ALL the permissions on the setup page ('Instagram key'), "
             "replace the secret META_TOKEN, then run the workflow again.")
    fail(test, f"{what}{e}", "Run the workflow again later. If it says this again, tell Claude.")


def _client(state, fresh=False):
    from rumo_meta import Meta, MetaError
    token = os.environ.get("META_TOKEN", "").strip()
    if not token:
        fail("Instagram key", "The runner has no Instagram key (the secret META_TOKEN is empty or missing).",
             "Add the repository secret META_TOKEN (setup page, 'Instagram key'), then run again.")
    ig = state.get("ig") or {}
    client = Meta(token, ig.get("id"))
    if ig.get("id") and not fresh:
        return client
    try:
        found = client.find_account()
    except MetaError as e:
        _meta_fail("Instagram key", e)
    if not found:
        fail("Instagram account", "The key works, but it sees no Instagram professional account linked "
             "to a Facebook Page.",
             "Make the key again and tick the Facebook Page 'Rumo - Brazilian Portuguese' and the Instagram "
             "account when Meta asks which ones to allow (setup page, 'Instagram key').")
    want = str(_cfg().get("instagram_username", "")).lstrip("@").lower()
    pick = next((f for f in found if str(f[1].get("username", "")).lower() == want), None)
    if pick is None:
        if len(found) > 1:
            fail("Instagram account", "The key sees several Instagram accounts: "
                 + ", ".join("@" + str(f[1].get("username")) for f in found),
                 f"Set \"instagram_username\" in config.json to the right one (now: {want or 'empty'}).")
        pick = found[0]
    page, acc = pick
    state["ig"] = {"id": acc["id"], "username": acc.get("username"), "page": page}
    client.ig = acc["id"]
    save_state(state)
    say(f"Instagram account: @{acc.get('username')} (Facebook Page '{page}').")
    return client


def _norm_cap(s):
    return " ".join((s or "").split())


def _already_out(client, state, post, strict=False):
    """Instagram has a post with exactly this caption that the kit has not recorded yet: a run
    that died after publishing. (Captions of different posts can look alike, so only a post
    whose id is unknown to the kit counts.) strict: if Instagram cannot be asked, stop rather
    than guess 'not there'."""
    from rumo_meta import MetaError
    try:
        rows = client.recent_media(25)
    except MetaError as e:
        if strict:
            if e.token_problem or e.permission_problem:
                _meta_fail("posting", e)
            fail("posting", f"Could not look at Instagram's recent posts: {e}",
                 "Nothing was changed. Run the workflow again later; it checks Instagram first and never "
                 "posts twice.")
        return None
    known = {p.get("ig_media") for p in state["posts"] if p.get("ig_media")}
    known |= {v.get("media") for v in state.get("slots", {}).values() if v.get("media")}
    want = _norm_cap((post.get("pending") or {}).get("caption") or post.get("caption"))
    hit = next((r for r in rows if r.get("id") not in known and _norm_cap(r.get("caption")) == want), None)
    return hit.get("id") if hit else None


def _done(state, post, slot, trial, mid):
    from rumo_host import persist
    post["status"] = "published"
    post["published_at"] = _utc_z(_now())
    post["scheduled_at"] = slot
    post["cycle"] = post.get("cycle", 0) + 1
    post["trial"] = bool(trial)
    if mid:
        post["ig_media"] = mid
    else:                      # out, but its Instagram id is unknown: no results, and never sent again
        post["ig_media"] = None
        post["no_requeue"] = True
    post.pop("pending", None)
    state.setdefault("slots", {})[slot] = {"post": post["id"], "media": mid, "trial": bool(trial)}
    save_state(state)
    if not persist(f"posted {post['id']}"):
        fail("saving progress", f"{post['id']} is on Instagram, but the repository could not be updated.",
             "Nothing is posted twice: the post is recorded as 'being posted', so the next run checks "
             "Instagram and notes it. If this repeats, tell Claude.")


def _mark_pending(state, post, container, slot, trial):
    """Written AND saved to the repository before anything is published: if this cannot be saved,
    nothing is published (the unpublished container simply expires after 24 hours)."""
    from rumo_host import persist
    post["pending"] = {"container": container, "slot": slot, "trial": bool(trial), "since": _utc_z(_now()),
                       "caption": post["caption"]}
    save_state(state)
    if not persist(f"posting {post['id']}"):
        post.pop("pending", None)
        save_state(state)
        fail("saving progress", "The repository could not be updated, so nothing was published.",
             "Run the workflow again. If this repeats, tell Claude.")


def _publish(client, state, post, slot, trial=False):
    """Make the post on Instagram. Returns None, or the MetaError that stopped it (err.made says
    whether a container was already recorded as pending)."""
    from rumo_host import host
    from rumo_meta import MetaError
    cap = post["caption"]
    label = f"{post['id']}-{post.get('cycle', 0) + 1}"
    try:
        if post.get("kind") == "reel":
            cover = host([post["cover"]], label)[post["cover"]]
            cid, uri = client.reel(cap, cover, trial="SS_PERFORMANCE" if trial else None)
            _mark_pending(state, post, cid, slot, trial)
            client.upload_video(cid, str(ROOT / post["video"]), uri)
        else:
            urls = host(post["slides_jpg"], label)
            alts = post.get("alts") or []
            kids = [client.image(urls[s], alts[i] if i < len(alts) else None, child=True)
                    for i, s in enumerate(post["slides_jpg"])]
            for k in kids:
                client.wait_ready(k, f"{post['id']} slide")
            cid = client.carousel(kids, cap)
            _mark_pending(state, post, cid, slot, trial)
        client.wait_ready(cid, post["id"])
        mid = client.publish(cid)
    except MetaError as e:
        e.made = bool(post.get("pending"))
        return e
    _done(state, post, slot, trial, mid)
    return None


def _find_published_id(client, state, post):
    """The id of a post Meta says is published: Instagram's list can lag a little, so look 3 times."""
    for attempt in range(3):
        mid = _already_out(client, state, post, strict=True)
        if mid:
            return mid
        systime.sleep(float(os.environ.get("RUMO_POLL", "10")) * 2)
    return None


def _resolve_pending(client, state, tz):
    """A run that stopped between making a post and saving that it went out: look at Instagram
    and finish it, so a post is never published twice. Anything unclear stops the run with the
    record kept, rather than guessing."""
    from rumo_meta import MetaError
    for post in [p for p in state["posts"] if p.get("pending")]:
        pend = post["pending"]
        cid, slot, trial = pend["container"], pend["slot"], pend.get("trial")
        mid = _already_out(client, state, post, strict=True)
        if mid:
            _done(state, post, slot, trial, mid)
            say(f"  {post['id']} was already on Instagram (the last run stopped before saving that); not posted twice.")
            continue
        try:
            code, _ = client.status(cid)
            if code == "IN_PROGRESS":
                client.wait_ready(cid, post["id"])
                code = "FINISHED"
        except MetaError as e:
            if e.token_problem or e.permission_problem:
                _meta_fail("posting", e)
            if not e.gone:
                fail("posting", f"{post['id']}: Instagram could not say whether it was posted: {e}",
                     "Nothing was changed. Run the workflow again later; it never posts twice.")
            code = "GONE"
        if code == "PUBLISHED":
            _done(state, post, slot, trial, _find_published_id(client, state, post))
            say(f"  {post['id']} was published by the last run; noted.")
            continue
        due = slot in {s for s, _ in _due(state, _cfg(), tz, _now())}
        if code == "FINISHED" and due:
            try:
                _done(state, post, slot, trial, client.publish(cid))
                say(f"  {post['id']}: finished what the last run started.")
                continue
            except MetaError as e:
                if e.token_problem or e.permission_problem:
                    _meta_fail("posting", e)
                if e.unclear or e.rate_limited:
                    fail("posting", f"{post['id']}: {e}", "Run the workflow again in a few minutes; "
                         "it checks Instagram first and never posts twice.")
        # ERROR / EXPIRED / gone, or made but not published and its slot has closed: back in the queue
        post.pop("pending", None)
        save_state(state)


SLOT_WINDOW = timedelta(hours=5)    # a run up to 5 hours late still posts; later, the day is skipped


def _due(state, cfg, tz, now):
    """Slots open right now: (slot in UTC 'Z', trial?)."""
    if not state.get("launch_date"):
        return []
    launch = date.fromisoformat(state["launch_date"])
    out = []
    for d in {(now.astimezone(tz) - timedelta(hours=h)).date() for h in (0, 6)}:
        if d < launch:
            continue
        s = datetime.combine(d, SLOT_TIME, tzinfo=tz)
        if s <= now < s + SLOT_WINDOW:
            out.append((_utc_z(s), False))
        if cfg.get("trial_reels") and d.weekday() in TRIAL_DAYS:
            t = datetime.combine(d, TRIAL_TIME, tzinfo=tz)
            if t <= now < t + SLOT_WINDOW:
                out.append((_utc_z(t), True))
    return sorted(out)


def _ready(post):
    return (post.get("status") in ("rendered", "requeue") and post.get("gate") in ("passed", "written")
            and ((post.get("video") and (ROOT / post["video"]).exists() and post.get("cover"))
                 or (post.get("slides_jpg") and all((ROOT / s).exists() for s in post["slides_jpg"]))))


def _prepare(state, post):
    """Draw one post and check it against the live site, just before it goes out."""
    from rumo_render import render_all
    _captions(state)
    render_all(state, only={post["id"]}, log=say)
    save_state(state)
    _gate_and_mark(state, only={post["id"]})
    return _ready(post)


def _post_slot(client, state, cfg, tz, slot, trial):
    skipped, refused = set(), 0
    for _ in range(8):
        pool = [p for p in _upcoming(state, 10 ** 6) if p["id"] not in skipped]
        if trial:
            pool = [p for p in pool if p.get("kind") == "reel"]
        if not pool:
            _top_up(state, force=True)
            pool = [p for p in _upcoming(state, 10 ** 6) if p["id"] not in skipped
                    and (not trial or p.get("kind") == "reel")]
        if not pool:
            fail("queue", "Every post has gone out (the best ones twice).", "Tell Claude: time for new posts.")
        post = pool[0]
        post["cta_plan"] = _cta_for(state, cfg, slot, tz)
        if not _prepare(state, post):
            skipped.add(post["id"])
            continue
        mid = _already_out(client, state, post)
        if mid:
            _done(state, post, slot, trial, mid)
            say(f"  {post['id']} was already on Instagram; noted, not posted twice.")
            return True
        err = _publish(client, state, post, slot, trial)
        if err is None:
            local = _parse(slot).astimezone(tz).strftime("%a %d %b %H:%M")
            say(f"  posted {post['id']} for the {local} UK slot" + (" (trial Reel)" if trial else "")
                + (" · link-in-bio week" if post.get("cta_plan") == "bio" else ""))
            return True
        if err.token_problem or err.permission_problem:
            _meta_fail("posting", err)
        if err.unclear or err.rate_limited:   # it may exist: keep the record, let the next run look
            fail("posting", f"{post['id']}: {err}",
                 "Nothing is posted twice: the next run checks Instagram first and finishes or retries it.")
        post.pop("pending", None)
        post["status"], post["rejected"] = "rejected", str(err)[:400]
        save_state(state)
        refused += 1
        say(f"  Instagram refused {post['id']}; it is left out: {str(err)[:200]}")
        if refused >= 3:
            fail("posting", f"Instagram refused three posts in a row. Last answer: {err}",
                 "Tell Claude: Meta's API may have changed (CLAUDE.md, rule 5). Nothing was posted twice.")
    note = f"The {_parse(slot).astimezone(tz).strftime('%a %d %b %H:%M')} slot stayed empty (posts left out on the way)."
    say("  " + note)
    state.setdefault("notes", []).append(note)
    save_state(state)
    return False


def _parse(ts):
    import re as _re
    t = _re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(ts).strip().replace("Z", "+00:00"))
    d = datetime.fromisoformat(t)
    if d.tzinfo is None:
        raise ValueError(f"a time without a time zone: {ts!r}")
    return d


def _utc_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cta_for(state, cfg, slot, tz):
    """The call to action of a post in this slot. Split test: weeks 1 and 4 after launch
    'Comment START', weeks 2 and 3 'link in bio' (same number of Reels on each side, and the
    account's growth cancels out); after it, the winner."""
    if cfg["cta_mode"] != "comment":
        return cfg["cta_mode"]
    launch = date.fromisoformat(state["launch_date"])
    week = (_parse(slot).astimezone(tz).date() - launch).days // 7
    n = int(cfg.get("cta_test_weeks", 4))
    if cfg.get("cta_test") and 1 <= week <= n:
        return TEST_WEEKS(n)[week]
    return state.get("cta_decided") or "comment"


def TEST_WEEKS(n):
    """Week -> call to action during the split test: ABBA ABBA ... ('comment', 'bio', 'bio', 'comment')."""
    pat = ["comment", "bio", "bio", "comment"]
    return {w: pat[(w - 1) % 4] for w in range(1, n + 1)}


def _when(p):
    t = p.get("scheduled_at") or p.get("published_at")
    return _parse(t) if t else None


def _learn(client, state, tz):
    """Read each post's results from Instagram and let them steer the mix of formats.

    Rates, not totals (saves and sends per person reached); only posts that reached at
    least 100 people; only the last four weeks; at least 3 posts per format. The best third
    of formats then get a few more turns (x1.3) and the weakest third a few fewer (x0.8):
    every format keeps coming round."""
    from rumo_formats import CATEGORY, rot_key
    from rumo_meta import MetaError
    if not state.get("launch_date"):
        return None
    cfg = _cfg()
    launch = date.fromisoformat(state["launch_date"])
    now = _now(tz)
    n, refused = 0, None
    for p in state["posts"]:
        w = _when(p)
        if p.get("status") != "published" or not p.get("ig_media") or not w:
            continue
        if not (now - timedelta(days=LEARN_WINDOW_DAYS + 14) <= w <= now - timedelta(hours=20)):
            continue   # too fresh to say anything, or too old to matter (its numbers stay as they were)
        try:
            st = client.insights(p["ig_media"])
        except MetaError as e:
            if e.token_problem:
                _meta_fail("results", e)
            refused = e
            if e.permission_problem:
                break
            continue
        if st:
            p["stats"] = st
            n += 1
    if refused is not None and not n:
        say(f"  results not available from Instagram ({refused.message}); the mix stays as planned.")
        state["results_note"] = ("Instagram gave no results (the key needs the permission "
                                 "instagram_manage_insights)" if refused.permission_problem
                                 else "Instagram gave no results this week")
        save_state(state)
        return None
    out = [p for p in state["posts"] if p.get("stats") and _when(p)]
    for p in out:   # missing numbers count as 0 in sums, but 'missing' is remembered for shares
        for k, v in list(p["stats"].items()):
            if v is None and k != "shares":
                p["stats"][k] = 0
    shares_known = any(p["stats"].get("shares") is not None for p in out)
    state["shares_known"] = shares_known
    if out and not shares_known:
        say("  Instagram gives no share counts for this account: the ranking uses saves only.")
    state["results_note"] = None if out else "no results from Instagram yet"
    recent = [p for p in out if now - timedelta(days=LEARN_WINDOW_DAYS) <= _when(p) <= now - timedelta(days=2)
              and (p["stats"].get("reach") or 0) >= MIN_REACH and not p.get("trial")]
    scores = {}
    for p in recent:
        st = p["stats"]
        scores.setdefault(rot_key(p), []).append(((st.get("saves") or 0)
                                                 + ((st.get("shares") or 0) if shares_known else 0))
                                                 / st["reach"])
    table = {k: (sum(v) / len(v), len(v)) for k, v in scores.items()}
    state["results"] = {k: {"score": round(v[0], 4), "posts": v[1]} for k, v in table.items()}
    days = (now.date() - launch).days

    def cat_of(k):
        return "reel" if k.startswith("reel:") else CATEGORY.get(k, "save")
    w, more, less = {}, [], []
    if days >= LEARN_AFTER_DAYS:
        for cat in sorted({cat_of(k) for k in table}):
            ranked = sorted([k for k, v in table.items() if v[1] >= 3 and cat_of(k) == cat],
                            key=lambda k: -table[k][0])
            if len(ranked) < 2:
                continue
            third = max(1, len(ranked) // 3)
            for k in ranked:
                w[k] = 1.0
            for k in ranked[:third]:
                w[k] = 1.3
                more.append(k)
            for k in ranked[-third:]:
                w[k] = 0.8
                less.append(k)
    if w:
        state["weights"] = w
        state["learned_at"] = now.date().isoformat()
        say("  results steer the mix now: a little more " + ", ".join(more) + "; a little less " + ", ".join(less))
    _decide_cta(state, cfg, out, launch, now, tz)
    save_state(state)
    return n


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _decide_cta(state, cfg, out, launch, now, tz):
    """After the split test: keep 'Comment START' unless link-in-bio weeks reached clearly more
    people (25% or more). Reels are compared with Reels and carousels with carousels. Decided a
    week after the test ends, so the last test week's posts have had time to collect reach."""
    weeks = int(cfg.get("cta_test_weeks", 4))
    if not cfg.get("cta_test") or cfg["cta_mode"] != "comment" or state.get("cta_decided"):
        return
    if (now.date() - launch).days < (weeks + 2) * 7:
        return
    plan = TEST_WEEKS(weeks)
    reach = {(c, k): [] for c in ("comment", "bio") for k in ("reel", "carousel")}
    for p in out:
        if p.get("trial"):
            continue
        wk = (_when(p).astimezone(tz).date() - launch).days // 7
        if wk in plan and p.get("cta_plan") == plan[wk]:
            reach[(plan[wk], "reel" if p.get("kind") == "reel" else "carousel")].append(p["stats"].get("reach") or 0)
    ratios, detail = [], {}
    for k in ("reel", "carousel"):
        c, b = reach[("comment", k)], reach[("bio", k)]
        detail[k] = {"comment_median": _median(c), "bio_median": _median(b), "comment_posts": len(c),
                     "bio_posts": len(b)}
        if len(c) >= 3 and len(b) >= 3 and _median(c) > 0:
            ratios.append(_median(b) / _median(c))
    if not ratios:
        say("  call-to-action test: no results to compare yet; deciding at a later weekly run.")
        return
    decided = "bio" if sum(ratios) / len(ratios) > 1.25 else "comment"
    state["cta_decided"] = decided
    state["cta_test_result"] = {"by_kind": detail, "bio_vs_comment": round(sum(ratios) / len(ratios), 2),
                                "decided": decided, "on": now.date().isoformat()}
    say(f"  call-to-action test done: link-in-bio weeks reached {sum(ratios) / len(ratios):.2f}x the people "
        "of 'Comment START' weeks (Reels with Reels, carousels with carousels). From now on: "
        + ("link in bio." if decided == "bio" else "Comment START."))


def _top_up(state, force=False):
    """When fewer than two weeks of new posts are left, the best posts go out once more."""
    from rumo_formats import PLANNABLE, plan_order
    pool = [p for p in state["posts"] if p.get("status") in PLANNABLE]
    if len(pool) >= 14 and not force:
        return
    old = [p for p in state["posts"] if p.get("status") == "published" and p.get("cycle", 0) < MAX_CYCLES
           and not p.get("written") and not p.get("trial") and p.get("ig_media") and not p.get("no_requeue")]

    def _rate(p):
        st = p.get("stats") or {}
        return ((st.get("saves") or 0) + (st.get("shares") or 0)) / max(1, st.get("reach") or 1)
    old.sort(key=lambda p: -_rate(p))
    for p in old[:30]:
        p["status"] = "requeue"
        p.pop("gate", None)
    plan_order(state, weights=state.get("weights"))
    _captions(state)
    save_state(state)


TRIAL_FOLLOWERS = 200   # Instagram: trial Reels need a professional account with 200+ followers


def _auto_trial(client, state, cfg):
    """Note the follower count; at 200+ switch trial Reels on by themselves."""
    from rumo_formats import save_config
    n = client.followers()
    if n is None:
        return
    state["followers"] = {"count": n, "at": _utc_z(_now())}
    if cfg.get("trial_reels") or not cfg.get("trial_auto", True) or n < TRIAL_FOLLOWERS:
        return
    cfg["trial_reels"] = True
    save_config(cfg)
    note = (f"{n} followers: trial Reels switched on by themselves (an extra Reel on Tuesdays and "
            "Thursdays at 12:00 UK, shown to non-followers first). Off: run the workflow with 'trial off'.")
    say("  " + note)
    state.setdefault("notes", []).append(note)


def _weekly(client, state, cfg, tz):
    from rumo_formats import plan_order
    say("Weekly: reading results, follower count, topping up the queue...")
    _learn(client, state, tz)
    _auto_trial(client, state, cfg)
    _top_up(state)
    plan_order(state, weights=state.get("weights"))
    _captions(state)
    state["weekly_at"] = _now(tz).date().isoformat()
    save_state(state)


def _show_and_clear_failed():
    """A stop of an earlier run is shown before it is cleared, never lost."""
    if FAILED_FILE.exists():
        say("The last run stopped with this (FAILED.txt, now cleared):\n"
            + FAILED_FILE.read_text(encoding="utf-8").strip() + "\n")
    clear_failed()


def cmd_connect():
    """Right after the key is added: does Meta accept it, which account, can Instagram read our images?"""
    _show_and_clear_failed()
    from rumo_host import host
    from rumo_meta import MetaError
    state = load_state()
    client = _client(state, fresh=True)
    try:
        prof = client.profile()
    except MetaError as e:
        _meta_fail("Instagram key", e)
    say(f"T1 passed: @{prof.get('username')}, {prof.get('followers_count')} followers, "
        f"{prof.get('media_count')} posts.")
    used, total = client.quota()
    if total:
        say(f"  posts published through the API in the last 24 h: {used} of {total}.")
    from PIL import Image
    test = ROOT / "cache" / "connect-test.jpg"
    test.parent.mkdir(exist_ok=True)
    Image.new("RGB", (64, 64), (49, 47, 42)).save(test, "JPEG")
    url = host([str(test.relative_to(ROOT)).replace("\\", "/")], "connect-test")
    say("T2 passed: images get a public address Instagram can open: " + next(iter(url.values())))
    state["connected_at"] = _utc_z(_now())
    save_state(state)
    say("Connected.")


def cmd_launch():
    """Post 1 ('Start here') now, test a Reel upload, and set the launch date."""
    _show_and_clear_failed()
    tz = _tz()
    state = load_state()
    if state.get("launch_date"):
        say(f"Already launched on {state['launch_date']}; the daily run posts from there. Nothing done.")
        return
    client = _client(state)
    _resolve_pending(client, state, tz)
    post = min(state["posts"], key=lambda p: p["order"])
    if post.get("status") != "published":
        post["cta_plan"] = _cfg()["cta_mode"]
        if not _prepare(state, post):
            fail("accuracy gate", f"{post['id']} could not be drawn or checked against the site just now.",
                 "Nothing was published. Run the workflow again in a few minutes; if it repeats, tell Claude.")
        mid = _already_out(client, state, post)
        if mid:
            _done(state, post, _utc_z(_now()), False, mid)
        else:
            err = _publish(client, state, post, _utc_z(_now()), False)
            if err is not None:
                if err.token_problem or err.permission_problem:
                    _meta_fail("T3 publish", err)
                fail("T3 publish", str(err), "Run the workflow again; it checks Instagram first and never "
                     "posts twice. If it says this again, tell Claude.")
    say(f"T3 passed: post 1 ({post['hook']}) is on Instagram. Check your phone.")
    # T4: a Reel is made and uploaded but NOT published (Meta drops unpublished ones after 24 h)
    reel = next((p for p in _upcoming(state, 30) if p.get("kind") == "reel"), None)
    if reel and _prepare(state, reel):
        from rumo_host import host
        from rumo_meta import MetaError
        try:
            cover = host([reel["cover"]], f"test-{reel['id']}")[reel["cover"]]
            cid, uri = client.reel(reel["caption"], cover)
            client.upload_video(cid, str(ROOT / reel["video"]), uri)
            client.wait_ready(cid, "test Reel")
            say("T4 passed: a Reel was uploaded and accepted by Instagram (not published; it is the next Reel).")
        except MetaError as e:
            if e.token_problem or e.permission_problem:
                _meta_fail("T4 Reel", e)
            fail("T4 Reel", f"The test Reel was refused: {e}",
                 "Post 1 is out and the launch date is NOT set yet. Tell Claude the message above.")
    now = _now(tz)
    launch = now.date() if now.hour < 12 else now.date() + timedelta(days=1)
    state["launch_date"] = launch.isoformat()
    save_state(state)
    say(f"Launched. One post a day at 18:00 UK from {launch.strftime('%a %d %b')} on; every other one a Reel.")
    _write_done(state, tz)


def cmd_daily():
    """The scheduled run: post what is due now, once a week learn and top up, write DONE.txt."""
    _show_and_clear_failed()
    tz = _tz()
    state = load_state()
    if not state.get("launch_date"):
        say("Not launched yet: nothing to post (run the workflow with 'launch' once).")
        return
    cfg = _cfg()
    now = _now()
    client = _client(state)
    _resolve_pending(client, state, tz)
    due = [(s, t) for s, t in _due(state, cfg, tz, now) if s not in state.get("slots", {})]
    if not due:
        say("Nothing due right now (posts go out at 18:00 UK; trial Reels Tue/Thu 12:00).")
    for slot, trial in due:
        _post_slot(client, state, cfg, tz, slot, trial)
    last = state.get("weekly_at")
    if not last or (now.astimezone(tz).date() - date.fromisoformat(last)).days >= 7:
        _weekly(client, state, cfg, tz)
    _write_done(state, tz)


def _skipped_days(state, tz):
    """Days since launch whose 18:00 slot passed without a post (the runner did not run in time)."""
    launch = date.fromisoformat(state["launch_date"])
    slots = state.get("slots", {})
    now = _now()
    out, d = [], launch
    while True:
        s = datetime.combine(d, SLOT_TIME, tzinfo=tz)
        if s + SLOT_WINDOW > now:
            return out
        if _utc_z(s) not in slots:
            out.append(d)
        d += timedelta(days=1)


def _write_done(state, tz):
    from rumo_formats import PLANNABLE
    cfg = _cfg()
    now = _now(tz)
    pool = sum(1 for p in state["posts"] if p.get("status") in PLANNABLE)
    week = [p for p in state["posts"] if p.get("status") == "published" and p.get("published_at")
            and _parse(p["published_at"]) > now - timedelta(days=7)]
    lines = [f"Rumo Instagram — status written {now.strftime('%a %d %b %Y %H:%M')} UK time", ""]
    ig = state.get("ig") or {}
    lines.append(f"Account: @{ig.get('username')}   Launched: {state.get('launch_date')}")
    lines.append(f"Posted in the last 7 days: {len(week)} (one a day at 18:00 UK, every other one a Reel).")
    first = date.fromisoformat(state["launch_date"]) if state.get("launch_date") else now.date()
    nxt = datetime.combine(max(now.date(), first), SLOT_TIME, tzinfo=tz)
    if _utc_z(nxt) in state.get("slots", {}) or now >= nxt + SLOT_WINDOW:
        nxt += timedelta(days=1)
    lines.append(f"Next post: {nxt.strftime('%a %d %b')} 18:00 UK.")
    if state.get("cta_decided"):
        lines.append("Call to action after the 4-week test: "
                     + ("link in bio." if state["cta_decided"] == "bio" else "Comment START."))
    elif cfg.get("cta_test") and cfg["cta_mode"] == "comment":
        lines.append("Weeks 1-4 after launch alternate 'Comment START' and 'link in bio' to compare reach.")
    if (state.get("followers") or {}).get("count") is not None:
        lines.append(f"Followers: {state['followers']['count']} ({state['followers']['at'][:10]}).")
    if cfg.get("trial_reels"):
        lines.append("Trial Reels: Tuesdays and Thursdays 12:00 UK, shown to non-followers first.")
    elif cfg.get("trial_auto", True):
        lines.append("Trial Reels switch on by themselves at 200 followers.")
    lines.append(f"Waiting in the kit: {pool} more posts (about {pool // 7} weeks).")
    if state.get("launch_date"):
        skipped = _skipped_days(state, tz)
        if skipped:
            lines.append(f"Days without a post (no run in time, or posts refused): {len(skipped)}, last "
                         f"{skipped[-1].strftime('%a %d %b')}.")
    rej = [p for p in state["posts"] if p.get("status") == "rejected"]
    if rej:
        lines.append(f"Refused by Instagram and left out: {len(rej)} (others took their days).")
    if state.get("results_note"):
        lines.append("Results: " + state["results_note"] + ".")
    for note in (state.get("notes") or [])[-3:]:
        lines.append("Note: " + note)
    state["notes"] = []
    lines += ["", "Runs by itself every day. If a run fails, GitHub emails you; FAILED.txt says what to do."]
    done = ROOT / "DONE.txt"
    old = done.read_text(encoding="utf-8").split("\n", 1)[-1] if done.exists() else None
    new = "\n".join(lines) + "\n"
    if old != new.split("\n", 1)[-1]:    # only the time changed: leave it (no commit for nothing)
        done.write_text(new, encoding="utf-8")
    save_state(state)


# Rough working ranges for a brand-new faceless education account (no reliable public
# benchmark exists; these come from large general studies, see the setup page).
BENCH = [
    ("Median reach per Reel", "200–1,000", "500–3,000", "under 100 again and again"),
    ("Saves per 1,000 reached (carousels)", "10–30", "15–40", "under 5"),
    ("Sends per 1,000 reached", "3–10", "5–15", "under 2"),
    ("Followers", "30–200", "300–1,000+", "under 20 at day 30"),
]


def cmd_check():
    _show_and_clear_failed()
    tz = _tz()
    state = load_state()
    client = _client(state)
    now = _now()
    out30 = [p for p in state["posts"] if p.get("status") == "published" and p.get("published_at")
             and _parse(p["published_at"]) >= now - timedelta(days=30)]
    say(f"Published in the last 30 days: {len(out30)} posts.")
    n = client.followers()
    if n is not None:
        state["followers"] = {"count": n, "at": _utc_z(_now())}
        cfg = _cfg()
        say(f"Followers: {n}." + (" Trial Reels switch on by themselves at 200 (weekly run)."
                                   if not cfg.get("trial_reels") and cfg.get("trial_auto", True)
                                   and n < TRIAL_FOLLOWERS else ""))
    _learn(client, state, tz)
    res = state.get("results") or {}
    if res:
        what = "saves + sends" if state.get("shares_known") else "saves"
        say(f"\nResults per format, last 4 weeks ({what} per 100 people reached; posts that reached 100+):")
        for k, v in sorted(res.items(), key=lambda kv: -kv[1]["score"]):
            say(f"  {k:14s} {100 * v['score']:5.1f}   ({v['posts']} posts)")
    out = [p for p in state["posts"] if p.get("stats") and _when(p) and _when(p) >= now - timedelta(days=28)]
    reels = [p["stats"].get("reach") or 0 for p in out if p.get("kind") == "reel"]
    cars = [p["stats"] for p in out if p.get("kind") != "reel"]
    allr = sum(p["stats"].get("reach") or 0 for p in out) or 0
    mine = [f"{_median(reels):.0f}" if reels else "–",
            f"{1000 * sum(c.get('saves') or 0 for c in cars) / max(1, sum(c.get('reach') or 0 for c in cars)):.1f}"
            if cars else "–",
            (f"{1000 * sum(p['stats'].get('shares') or 0 for p in out) / max(1, allr):.1f}"
             if out and state.get("shares_known") else "not reported"),
            str(n) if n is not None else "–"]
    say("\nLast 4 weeks against rough ranges for a new account (estimates, not data):")
    say(f"  {'':38s} {'yours':>10s}   {'day 30 healthy':>15s}   {'day 90 healthy':>15s}   red flag")
    for (name, d30, d90, red), m in zip(BENCH, mine):
        say(f"  {name:38s} {m:>10s}   {d30:>15s}   {d90:>15s}   {red}")
    say("  Reach growing but few taps on /start: fix the profile, bio and call to action, not the posts.")
    say("  Reach flat under about 300: the hooks and the Reels need work.")
    best = sorted([p for p in state["posts"] if p.get("stats")], key=lambda p: -(p["stats"].get("reach") or 0))[:5]
    if best:
        say("\nMost reached:")
        for p in best:
            st = p["stats"]
            say(f"  {int(st.get('reach') or 0):6d} reach  {int(st.get('saves') or 0):3d} saves  "
                f"{int(st.get('shares') or 0):3d} sends  {p['id']}")
    t = state.get("cta_test_result")
    if t:
        parts = [f"{k}s: comment weeks median {v['comment_median']:.0f} ({v['comment_posts']} posts), "
                 f"bio weeks {v['bio_median']:.0f} ({v['bio_posts']})" for k, v in t["by_kind"].items()]
        say("\nCall-to-action test (median reach): " + "; ".join(parts)
            + f". Kept: {'link in bio' if t['decided'] == 'bio' else 'Comment START'}.")
    launch = state.get("launch_date")
    if launch:
        cfg = _cfg()
        plan = ""
        if cfg.get("cta_test") and cfg["cta_mode"] == "comment":
            tw = TEST_WEEKS(int(cfg.get("cta_test_weeks", 4)))
            plan = "; test weeks: " + ", ".join(f"week {w} {'Comment START' if v == 'comment' else 'link in bio'}"
                                                for w, v in tw.items())
        say("\nRun this in Supabase > SQL Editor and paste the result back to Claude "
            f"(Instagram visitors per week after launch, week 0 = launch week{plan}):\n")
        say(f"select (at::date - date '{launch}') / 7 as week_after_launch, name,\n"
            "       count(distinct session) as people\n"
            "from stats_events\n"
            "where (ref ilike '%instagram%' or (meta->>'ad')::boolean)\n"
            f"  and at >= '{launch}'\n"
            "group by 1, 2 order by 1, 2;")
    save_state(state)


def cmd_trial(arg):
    from rumo_formats import config, save_config
    clear_failed()
    cfg = config()
    known = (load_state().get("followers") or {}).get("count")
    if arg != "off" and known is not None and known < TRIAL_FOLLOWERS and "--force" not in sys.argv:
        say(f"Not switched on: Instagram last counted {known} followers, and it offers trial Reels "
            f"from {TRIAL_FOLLOWERS}. The weekly run switches them on by itself at 200.")
        return
    cfg["trial_reels"] = arg != "off"
    if arg == "off":
        cfg["trial_auto"] = False   # and the weekly run does not switch them back on
    save_config(cfg)
    say("Trial Reels on: an extra Reel on Tuesdays and Thursdays at 12:00 UK, shown to non-followers first."
        if cfg["trial_reels"] else "Trial Reels off.")


def cmd_status():
    state = load_state()
    from collections import Counter
    c = Counter(p.get("status", "?") for p in state["posts"])
    say(f"{len(state['posts'])} posts: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    ig = state.get("ig") or {}
    if ig:
        say(f"Instagram account: @{ig.get('username')} (Page '{ig.get('page')}')")
    if state.get("launch_date"):
        say(f"Launch date: {state['launch_date']}")
        slots = sorted(state.get("slots", {}).items())[-3:]
        for s, v in slots:
            say(f"  {s}: {v.get('post')}")


COMMANDS = {"setup": cmd_setup, "build": cmd_build, "connect": cmd_connect, "launch": cmd_launch,
            "daily": cmd_daily, "check": cmd_check, "status": cmd_status}
LOCKED = ("build", "connect", "launch", "daily", "check", "trial")


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return ctypes.get_last_error() == 5
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _lock_or_stop():
    """One run at a time (the runner also allows only one; this guards a laptop)."""
    lock = ROOT / ".run.lock"
    try:
        if lock.exists() and _pid_alive(lock.read_text(encoding="utf-8").strip()) \
                and datetime.now().timestamp() - lock.stat().st_mtime < 3 * 3600:
            say("\nNOT STARTED: another run of the kit is still busy. Wait until it has finished.")
            sys.exit(2)
    except OSError:
        pass
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def main(argv):
    if len(argv) < 2 or (argv[1] not in COMMANDS and argv[1] != "trial"):
        print(__doc__)
        sys.exit(1)
    name = argv[1]
    arg = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else None
    run = {"build": lambda: cmd_build(fresh="--fresh" in argv, rerender="--rerender" in argv),
           "trial": lambda: cmd_trial(arg or "on")}.get(name) or COMMANDS[name]
    from rumo_host import persist
    lock = _lock_or_stop() if name in LOCKED else None
    try:
        run()
    finally:
        if lock:
            lock.unlink(missing_ok=True)
        if name in LOCKED:
            persist(f"{name} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except SystemExit:
        raise
    except Exception:
        import traceback
        try:
            fail("unexpected error", traceback.format_exc()[-1800:],
                 "Run the workflow again. If it stops here again, tell Claude and show this file.")
        finally:
            try:
                from rumo_host import persist
                persist("unexpected error")
            except Exception:
                pass

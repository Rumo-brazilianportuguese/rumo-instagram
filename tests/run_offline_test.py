"""End-to-end offline test of the kit, against local stand-ins for rumopt.com, Meta's Instagram
Graph API and a public file host. Run:  python tests/run_offline_test.py

It copies the kit into a temporary folder, so your real posts.json and previews are never
touched. It takes 15-25 minutes (it draws real slides and real Reels). The clock is moved
forward with RUMO_NOW to run five weeks of daily posting, the weekly learning, the
call-to-action test, trial Reels and the failure cases.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
_VENV = KIT / ".venv"
_VPY = _VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if _VPY.exists() and Path(sys.prefix).resolve() != _VENV.resolve() and os.environ.get("RUMO_NO_VENV") != "1":
    sys.exit(subprocess.call([str(_VPY), str(Path(__file__).resolve()), *sys.argv[1:]]))
sys.path.insert(0, str(HERE))
import mock_servers as ms  # noqa: E402

RESULTS = []
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SKIP = ("tests", "posts.json", "preview", "cache", "config.json", "FAILED.txt", "DONE.txt",
        "__pycache__", ".venv", ".run.lock", "posts.tmp", ".git")


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({str(detail)[:600]})" if detail and not cond else ""),
          flush=True)


def probe_video(path):
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = "ffmpeg"
    r = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    err = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
    return {"dur": dur, "h264": "Video: h264" in err, "size": "1080x1920" in err, "aac": "Audio: aac" in err}


def main():
    site = ms.start(ms.Site)
    graph = ms.start(ms.Graph)
    ms.GS.port = graph.server_port
    work = Path(tempfile.mkdtemp(prefix="rumo-kit-test-"))
    hostdir = Path(tempfile.mkdtemp(prefix="rumo-host-"))
    files = ms.file_server(hostdir)
    for f in KIT.iterdir():
        if f.name in SKIP:
            continue
        if f.is_dir():
            shutil.copytree(f, work / f.name)
        else:
            shutil.copy2(f, work / f.name)
    env = dict(os.environ,
               RUMO_SITE=f"http://127.0.0.1:{site.server_port}",
               META_BASE=f"http://127.0.0.1:{graph.server_port}/v25.0",
               META_RUPLOAD=f"http://127.0.0.1:{graph.server_port}/rupload/v25.0",
               META_TOKEN=ms.TOKEN, RUMO_HOST="dir", RUMO_HOST_DIR=str(hostdir),
               RUMO_HOST_URL=f"http://127.0.0.1:{files.server_port}",
               RUMO_POLL="0.05", PYTHONIOENCODING="utf-8", RUMO_REEL_FPS="8", RUMO_NO_BROWSER="1",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    for k in ("GITHUB_ACTIONS", "GITLAB_CI", "RUMO_RAW_BASE", "RUMO_NOW"):
        env.pop(k, None)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"   # in-process calls too
    N = 12   # posts drawn by 'build' in this test (30 for real), to keep the test quick
    (work / "config.json").write_text(json.dumps({"preview_posts": N}), encoding="utf-8")

    py = str(_VPY) if _VPY.exists() else sys.executable

    def run(*args, expect=0, now=None, quiet=False, extra=None):
        e = dict(env, **(extra or {}))
        if now:
            e["RUMO_NOW"] = now if isinstance(now, str) else now.astimezone(timezone.utc).isoformat()
        r = subprocess.run([py, "rumo.py", *args], cwd=work, env=e,
                           capture_output=True, text=True, encoding="utf-8")
        out = r.stdout + r.stderr
        if r.returncode != expect and not quiet:
            print(out[-3000:])
        return r.returncode, out

    def load():
        return json.loads((work / "posts.json").read_text(encoding="utf-8"))

    def dump(st):
        (work / "posts.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

    sys.path.insert(0, str(work))
    from rumo_formats import CATEGORY, SAVE, SEND, refs_of, rot_key  # noqa: E402

    # ------------------------------------------------------------------ 1. build
    code, out = run("build")
    check("build exits cleanly", code == 0, out[-500:])
    state = load()
    posts = state["posts"]
    by_order = sorted(posts, key=lambda p: p["order"])
    fmts = {p["format"] for p in posts}
    check("a pool of months of posts (300+)", len(posts) >= 300, len(posts))
    check("every format present", {"brand", "quiz", "meaning", "real", "traps", "flip", "examples", "cheat",
                                    "story", "words", "reel"} <= fmts, fmts)
    check("all six Reel kinds present (incl. the longer 3-in-a-row Reels)",
          {p.get("reel_kind") for p in posts if p["format"] == "reel"}
          >= {"meaning", "quiz", "real", "story", "quiz3", "meaning3"})
    check("launch order: start-here, quiz, meaning",
          [p["format"] for p in by_order[:3]] == ["brand", "quiz", "meaning"], [p["format"] for p in by_order[:3]])
    check("post 3 is the strongest phrase card", by_order[2]["hook"].startswith("You'll hear"), by_order[2]["hook"])
    plan = [p for p in by_order if p["status"] in ("extracted", "rendered")]
    week = [p["format"] for p in plan[3:3 + 40]]
    check("every other post is a Reel", week.count("reel") == 20 and week[0] == "reel", week)
    check("the same format never twice in a row (first 80)",
          all(rot_key(plan[i]) != rot_key(plan[i + 1]) for i in range(79)),
          [rot_key(p) for p in plan[:80]])
    check("self-test rejected all nine poisoned posts", out.count("rejected, as it should be") == 9, out[:1500])
    check("gate: 0 missed", re.search(r"missed 0 of \d+ posts", out) is not None, out[-800:])
    window = plan[:N]
    check(f"first {N} posts drawn", all(p["status"] == "rendered" for p in window),
          [(p["id"], p["status"]) for p in window if p["status"] != "rendered"])
    check("nothing left out as unfit", not [p for p in posts if p["status"] == "unfit"],
          [(p["id"], p.get("unfit")) for p in posts if p["status"] == "unfit"][:5])
    cars = [p for p in window if p["kind"] == "carousel"]
    reels = [p for p in window if p["kind"] == "reel"]
    check("4 to 10 slides per carousel", all(4 <= len(p["slides_jpg"]) <= 10 for p in cars),
          [len(p["slides_jpg"]) for p in cars])
    check("alt text for every slide", all(len(p["alts"]) == len(p["slides_jpg"]) and all(p["alts"]) for p in cars))
    from PIL import Image  # noqa: E402
    with Image.open(work / cars[0]["slides_jpg"][0]) as im:   # closed at once: Windows can't delete open files
        size, fmt = im.size, im.format
    check("slides are 1080x1350 JPEG", size == (1080, 1350) and fmt == "JPEG", (size, fmt))
    v = probe_video(work / reels[0]["video"])
    check("Reels are 1080x1920 H.264 with AAC sound", v["h264"] and v["size"] and v["aac"], v)
    durs = [(p["reel_kind"], probe_video(work / p["video"])["dur"]) for p in reels]
    check("Reels last 8 to 13 seconds; 3-in-a-row Reels 17 to 24",
          {k for k, d in durs} >= {"quiz", "quiz3"}
          and all((17 <= d <= 24) if k in ("quiz3", "meaning3") else (8 <= d <= 13) for k, d in durs), durs)
    from rumo_reels import REEL_CSS, scene_html  # noqa: E402
    r0 = next(p for p in reels if p["reel_kind"] == "quiz")
    h0 = scene_html(r0, "", {"cta_mode": "comment", "keyword": "START"}, "comment")[0]
    check("Reels move from the first frame and fade back to the start (loop)",
          'class="blob b1"' in h0 and "infinite alternate" in h0 and "animation:enter" in h0
          and "fadeOut 0.45s" in h0 and "spin90" in REEL_CSS, h0[:300])
    try:
        import imageio_ffmpeg
        fexe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        fexe = "ffmpeg"
    vid = work / reels[0]["video"]
    a_png, b_png = work / "cache" / "loop-a.png", work / "cache" / "loop-b.png"
    subprocess.run([fexe, "-v", "error", "-y", "-i", str(vid), "-vf", "select=eq(n\\,0)", "-vsync", "0",
                    "-frames:v", "1", str(a_png)])
    subprocess.run([fexe, "-v", "error", "-y", "-sseof", "-0.2", "-i", str(vid), "-update", "1", "-vsync", "0",
                    str(b_png)])
    from PIL import ImageChops  # noqa: E402
    try:
        with Image.open(a_png) as ia, Image.open(b_png) as ib:
            dif = ImageChops.difference(ia.convert("L"), ib.convert("L"))
        hist = dif.histogram()
        mean = sum(i * c for i, c in enumerate(hist)) / max(1, sum(hist))
    except Exception as e:
        mean = repr(e)
    check("a Reel's last frame matches its first (clean loop)", isinstance(mean, float) and mean < 3, mean)
    with Image.open(work / reels[0]["cover"]) as cov:
        csize = cov.size
    check("Reel covers are 1080x1920", csize == (1080, 1920), csize)
    caps = [p["caption"] for p in plan[:120]]
    check("captions: 5 hashtags, the keyword, no price",
          all(c.count("#") == 5 and "Comment START" in c and "€" not in c and "$" not in c for c in caps),
          next((c for c in caps if c.count("#") != 5 or "Comment START" not in c), ""))
    plan120 = plan[:120]
    check("a send prompt only where it fits, a save prompt on reference posts",
          all((SEND[rot_key(p)] in p["caption"]) if rot_key(p) in SEND
              else ((SAVE in p["caption"]) if p["format"] in ("examples", "cheat", "words", "story") else True)
              for p in plan120))
    check("no generic 'send them this' line on every post",
          not any("Learning with someone? Send them this" in a for p in cars for a in p.get("alts", [])))
    abouts = [p for p in plan120 if p["slides"][0].get("about")]
    check("captions carry the page's own one-line description",
          len(abouts) >= 100 and all(p["slides"][0]["about"]["text"] in p["caption"] for p in abouts),
          len(abouts))
    check("no broad hashtags", not any("#languagelearning" in c for c in caps))
    check("hashtags rotate", len({c.rsplit("\n", 1)[-1] for c in caps}) >= 6)
    st_caps = [p["caption"] for p in plan[:120] if p["format"] in ("story", "words")]
    check("story captions say the stories are free to read", st_caps and all("free to read" in c for c in st_caps))
    check("excluded spellings never appear",
          not any("cafézinho" in r["text"] or "pézinho" in r["text"] for p in posts for r in refs_of(p))
          and any(p.get("slug") == "b2-diminutivos" for p in posts))
    quiz = next(p for p in posts if p["format"] == "quiz")
    qs = [s for s in quiz["slides"] if s["kind"] == "question"]
    check("quiz questions each have exactly one blank", all(q["q"]["text"].count("___") == 1 for q in qs))
    story = next(p for p in posts if p["format"] == "story")
    en = [l["en"]["text"] for s in story["slides"] if s["kind"] == "story" for l in s["lines"]]
    check("story translations shown without their word notes", en and all(" = " not in e for e in en), en[:3])
    idx = (work / "preview" / "index.html").read_text(encoding="utf-8")
    check("preview shows slides and Reels", "<video" in idx and ".jpg" in idx)

    # ------------------------------------------------------------- 1b. rerender
    code, out = run("build", "--rerender")
    check(f"build --rerender redraws the first {N}", code == 0 and out.count("  rendered ") == N, out[-300:])

    # ------------------------------------------------------- 1c. CTA fallback
    (work / "config.json").write_text(json.dumps({"preview_posts": N, "cta_mode": "bio"}), encoding="utf-8")
    code, out = run("build")
    st = load()
    win = [p for p in sorted(st["posts"], key=lambda p: p["order"]) if p["status"] == "rendered"][:N]
    check("cta_mode bio: captions and slides switch without --rerender",
          code == 0 and out.count("  rendered ") == N
          and all("Link in bio" in p["caption"] and "Comment START" not in p["caption"] and p["cta"] == "bio"
                  for p in win), out[-300:])
    (work / "config.json").write_text(json.dumps({"preview_posts": N}), encoding="utf-8")
    code, out = run("build")
    check("back to comment mode", code == 0 and out.count("  rendered ") == N)

    # ------------------------------------------- 2. hand-edited Portuguese
    saved = (work / "posts.json").read_text(encoding="utf-8")
    s2 = json.loads(saved)
    victim_post = sorted([p for p in s2["posts"] if p["status"] == "rendered" and not p.get("written")],
                         key=lambda p: p["order"])[3]
    victim = next(r for r in refs_of(victim_post) if r.get("role") == "pt")
    victim["text"] = victim["text"].replace("é", "e", 1) if "é" in victim["text"] else victim["text"] + "!"
    dump(s2)
    code, out = run("build")
    st = load()
    vp = next(p for p in st["posts"] if p["id"] == victim_post["id"])
    check("a hand-edited post is refused and left out", code == 0 and vp["status"] == "missed", (code, vp["status"]))
    s4 = json.loads(saved)
    pair_post = next(p for p in sorted(s4["posts"], key=lambda p: p["order"])
                     if p["status"] == "rendered" and p["format"] == "meaning")
    cha = [x for x in pair_post["slides"] if x["kind"] == "chat_a"]
    cha[0]["en"], cha[1]["en"] = cha[1]["en"], cha[0]["en"]   # real English lines, but swapped
    dump(s4)
    code, out = run("build")
    st = load()
    check("a Portuguese line shown with the English of another line is refused",
          code == 0 and next(p for p in st["posts"] if p["id"] == pair_post["id"])["status"] == "missed",
          out[-300:])
    s3 = json.loads(saved)
    for p in [p for p in s3["posts"] if not p.get("written")][:60]:
        r = next((r for r in refs_of(p) if r.get("role") == "pt"), None)
        if r:
            r["text"] += "!"
    dump(s3)
    code, out = run("build", expect=2)
    check("many mismatches stop everything (site changed)", code == 2 and (work / "FAILED.txt").exists(),
          out[-300:])
    (work / "posts.json").write_text(saved, encoding="utf-8")
    code, out = run("build")
    check("clean again after restoring", code == 0)

    # ------------------------------------------- 2b. exclude a line later on
    st = load()
    ex_post = sorted([p for p in st["posts"] if p["status"] == "rendered" and not p.get("written")],
                     key=lambda p: p["order"])[5]
    ex_line = next(r["text"] for r in refs_of(ex_post) if r.get("role") == "pt")
    (work / "config.json").write_text(json.dumps({"preview_posts": N, "exclude": [ex_line]}), encoding="utf-8")
    code, out = run("build")
    st = load()
    check("a line added to 'exclude' later is refused by the gate (no --fresh needed)",
          code == 0 and next(p for p in st["posts"] if p["id"] == ex_post["id"])["status"] == "missed", out[-300:])
    (work / "config.json").write_text(json.dumps({"preview_posts": N}), encoding="utf-8")
    code, out = run("build")

    # ------------------------------------------------------------ 3. connect
    from zoneinfo import ZoneInfo  # noqa: E402
    tz = ZoneInfo("Europe/London")
    code, out = run("connect", expect=2, extra={"META_TOKEN": ""})
    check("no key: plain explanation, nothing else happens", code == 2 and "META_TOKEN" in out, out[-300:])
    code, out = run("connect", expect=2, extra={"META_TOKEN": "WRONG"})
    check("a wrong key: 'Meta refused the Instagram key'", code == 2 and "refused the Instagram key" in out,
          out[-300:])
    check("the key never appears in any output", "WRONG" not in out and ms.TOKEN not in out)
    ms.GS.me_kind = "user"
    code, out = run("connect")
    check("a user key: the Page and its Instagram account are found through the Page list",
          code == 0 and "@rumo.portuguese" in out, out[-300:])
    ms.GS.me_kind = "page"
    code, out = run("connect")
    check("connect finds @rumo.portuguese behind the Facebook Page and checks the image address",
          code == 0 and "@rumo.portuguese" in out and "T1 passed" in out and "T2 passed" in out, out[-400:])

    # -------------------------------------------------------------- 4. launch
    def uk(d, h, m=10):
        return datetime.combine(d, dtime(h, m), tzinfo=tz)

    L = date(2027, 3, 15)            # a Monday; the UK clocks go forward on 28 March 2027
    code, out = run("daily", now=uk(L, 18))
    check("before launch the daily run posts nothing", code == 0 and "Not launched yet" in out and not ms.GS.media,
          out[-300:])
    ms.GS.lose_publish_once = True
    code, out = run("launch", expect=2, now=uk(L, 9))
    check("post 1: a lost answer stops the launch without retrying", code == 2 and len(ms.GS.media) == 1, out[-400:])
    code, out = run("launch", now=uk(L, 9, 20))
    check("post 1: the rerun finds it on Instagram instead of posting again",
          code == 0 and len(ms.GS.media) == 1 and "T3 passed" in out, out[-600:])
    check("a Reel is uploaded and checked (not published) at launch", "T4 passed" in out and len(ms.GS.media) == 1
          and any(c["kind"] == "REELS" and c.get("uploaded") for c in ms.GS.containers.values()), out[-300:])
    st = load()
    check("launch date set to launch day (launched before 12:00)", st.get("launch_date") == L.isoformat(),
          st.get("launch_date"))
    code, out = run("launch", now=uk(L, 10))
    check("launch twice does nothing", code == 0 and "Already launched" in out and len(ms.GS.media) == 1)
    check("post 1 is the 'Start here' carousel with alt text on every slide",
          ms.GS.media[0]["type"] == "FEED" and not ms.GS.errors, ms.GS.errors[:3])

    # ---------------------------------------------------- 5. five weeks of daily runs
    code, out = run("daily", now=uk(L, 11))
    check("outside 18:00-23:00 UK the daily run posts nothing", code == 0 and "Nothing due" in out
          and len(ms.GS.media) == 1, out[-300:])
    slow = []
    for d in range(0, 35):
        day = L + timedelta(days=d)
        code, out = run("daily", now=uk(day, 18))
        if code != 0:
            slow.append((day.isoformat(), out[-500:]))
        if d == 0:
            code2, out2 = run("daily", now=uk(day, 19))
            check("a second run in the same evening posts nothing", code2 == 0 and "Nothing due" in out2
                  and len(ms.GS.media) == 2, out2[-300:])
    check("35 daily runs all succeed", not slow, slow[:2])
    st = load()
    pub = sorted([p for p in st["posts"] if p.get("status") == "published" and not p.get("written")],
                 key=lambda p: p["scheduled_at"])
    slots = st.get("slots", {})
    check("one post per day for 35 days, none twice", len(ms.GS.media) == 36 and len(slots) == 36
          and len({v["media"] for v in slots.values()}) == 36
          and len({v["post"] for v in slots.values()}) == 36, (len(ms.GS.media), len(slots)))
    check("posts with look-alike captions are all really posted (never mistaken for one another)",
          len({p["ig_media"] for p in pub}) == len(pub), [p["id"] for p in pub][:5])
    kinds = [p["kind"] for p in pub]
    check("every other post is a Reel (after the launch trio)", kinds[2:].count("reel") in (16, 17)
          and all(kinds[i] != kinds[i + 1] for i in range(2, len(kinds) - 1)), kinds)
    check("UK clock change: 18:00 UK is 18:00 UTC in winter and 17:00 UTC in summer",
          "2027-03-27T18:00:00Z" in slots and "2027-03-28T17:00:00Z" in slots, sorted(slots)[10:15])
    def week_of(p):
        return (date.fromisoformat(p["scheduled_at"][:10]) - L).days // 7
    wk = {}
    for p in pub:
        wk.setdefault(week_of(p), set()).add("bio" if "Link in bio" in p["caption"] else
                                             "comment" if "Comment START" in p["caption"] else "?")
    check("split test: weeks 1 and 4 say 'Comment START', weeks 2 and 3 'link in bio'",
          wk.get(1) == {"comment"} and wk.get(2) == {"bio"} and wk.get(3) == {"bio"} and wk.get(4) == {"comment"},
          wk)
    reels_c = sum(1 for p in pub if p["kind"] == "reel" and week_of(p) in (1, 4))
    reels_b = sum(1 for p in pub if p["kind"] == "reel" and week_of(p) in (2, 3))
    check("the test is fair: the same number of Reels in comment weeks and bio weeks", reels_c == reels_b,
          (reels_c, reels_b))
    reels_sent = [m for m in ms.GS.media if m["type"] == "REELS"]
    check("Reels go out as Reels with our cover, a named sound and shared to the grid",
          reels_sent and all(m["f"].get("cover_url") and m["f"].get("audio_name") and m["f"].get("share_to_feed") == "true"
                             for m in reels_sent))
    check("the mock saw no malformed request", not ms.GS.errors, ms.GS.errors[:3])
    st = load()
    check("results are read once a week; formats compete only with formats in the same slot",
          st.get("weights") and all(
              {v for k, v in st["weights"].items() if (k.startswith("reel:") and c == "reel")
               or (not k.startswith("reel:") and CATEGORY.get(k, "save") == c)} >= {1.3, 0.8}
              for c in {("reel" if k.startswith("reel:") else CATEGORY.get(k, "save")) for k in st["weights"]}),
          st.get("weights"))
    done = (work / "DONE.txt").read_text(encoding="utf-8")
    check("DONE.txt says what went out and what comes next", "Posted in the last 7 days: 7" in done
          and "Next post:" in done, done)

    # ------------------------------------------------------ 6. trial Reels
    code, out = run("trial", "on")
    check("'trial on' below 200 known followers explains instead", "Not switched on" in out
          and not json.loads((work / "config.json").read_text()).get("trial_reels"), out[-300:])
    ms.GS.followers = 250
    d35 = L + timedelta(days=35)
    code, out = run("daily", now=uk(d35, 18))
    check("at 200+ followers the weekly run switches trial Reels on by itself",
          code == 0 and json.loads((work / "config.json").read_text()).get("trial_reels") is True, out[-400:])
    n0 = len(ms.GS.media)
    code, out = run("daily", now=uk(d35 + timedelta(days=1), 12))   # Tuesday 12:10
    trials = [m for m in ms.GS.media[n0:] if m.get("trial")]
    check("Trial Reels: an extra Reel on Tuesday 12:00 UK, shown to non-followers first",
          code == 0 and len(trials) == 1 and trials[0]["trial"] == "SS_PERFORMANCE" and trials[0]["type"] == "REELS",
          out[-400:])
    code, out = run("daily", now=uk(d35 + timedelta(days=1), 18))
    check("the normal 18:00 post still goes out that day", code == 0 and len(ms.GS.media) == n0 + 2, out[-300:])
    code, out = run("trial", "off")
    cfg = json.loads((work / "config.json").read_text())
    check("'trial off' also stops the automatic switch", cfg.get("trial_reels") is False and cfg.get("trial_auto") is False)

    # ------------------------------------------------------ 7. failures
    d = d35 + timedelta(days=2)
    n0 = len(ms.GS.media)
    ms.GS.lose_publish_once = True
    code, out = run("daily", expect=2, now=uk(d, 18))
    check("a lost answer from Instagram stops the run (no blind retry)", code == 2 and len(ms.GS.media) == n0 + 1,
          out[-300:])
    code, out = run("daily", now=uk(d, 18, 40))
    check("the next run finds the post on Instagram and never posts it twice",
          code == 0 and len(ms.GS.media) == n0 + 1 and "not posted twice" in out, out[-400:])
    d += timedelta(days=1)
    ms.GS.fail_publish_once = True
    code, out = run("daily", expect=2, now=uk(d, 18))
    check("a failed publish (nothing made) stops the run", code == 2 and len(ms.GS.media) == n0 + 1, out[-300:])
    code, out = run("daily", now=uk(d, 18, 40))
    check("the next run finishes the half-made post", code == 0 and len(ms.GS.media) == n0 + 2
          and "finished what the last run started" in out, out[-400:])
    d += timedelta(days=1)
    ms.GS.fail_publish_once = True
    code, out = run("daily", expect=2, now=uk(d, 18))
    ms.GS.media_list_down = True
    code, out = run("daily", expect=2, now=uk(d, 18, 30))
    st = load()
    check("if Instagram cannot be asked, the half-made post's record is kept and nothing is guessed",
          code == 2 and any(p.get("pending") for p in st["posts"]) and len(ms.GS.media) == n0 + 2, out[-300:])
    ms.GS.media_list_down = False
    code, out = run("daily", now=uk(d, 18, 50))
    check("...and the next run finishes it once", code == 0 and len(ms.GS.media) == n0 + 3, out[-300:])
    d += timedelta(days=1)
    ms.GS.unclear_publish_once = True
    code, out = run("daily", expect=2, now=uk(d, 18))
    st = load()
    check("an 'unknown error' on publishing is never taken as a refusal",
          code == 2 and not any(p["status"] == "rejected" for p in st["posts"])
          and any(p.get("pending") for p in st["posts"]), out[-300:])
    code, out = run("daily", now=uk(d, 18, 30))
    check("...the next run finds that post on Instagram (no second post that day)",
          code == 0 and len(ms.GS.media) == n0 + 4 and "not posted twice" in out, out[-300:])
    n0 += 2
    d += timedelta(days=1)
    ms.GS.reject_next = 1
    code, out = run("daily", now=uk(d, 18))
    st = load()
    check("a post Instagram refuses is left out and the next post takes its day",
          code == 0 and len(ms.GS.media) == n0 + 3 and sum(1 for p in st["posts"] if p["status"] == "rejected") == 1,
          out[-400:])
    d += timedelta(days=1)
    ms.GS.reject_next = 5
    code, out = run("daily", expect=2, now=uk(d, 18))
    check("three refusals in a row stop with a plain explanation", code == 2 and "three posts in a row" in out,
          out[-300:])
    ms.GS.reject_next = 0
    d += timedelta(days=1)
    ms.GS.token_dead = True
    code, out = run("daily", expect=2, now=uk(d, 18))
    check("an expired key: 'Meta refused the Instagram key' and what to do",
          code == 2 and "refused the Instagram key" in out and "META_TOKEN" in (work / "FAILED.txt").read_text(),
          out[-300:])
    ms.GS.token_dead = False
    d += timedelta(days=1)
    code, out = run("daily", now=uk(d, 18))
    done = (work / "DONE.txt").read_text(encoding="utf-8")
    check("days without a post are reported in DONE.txt", code == 0 and "Days without a post" in done
          and "The last run stopped with this" in out, done)
    n1 = len(ms.GS.media)
    code, out = run("daily", now=uk(d, 23, 30))
    check("after 23:00 UK the day's slot is closed", code == 0 and len(ms.GS.media) == n1 and "Nothing due" in out)

    # ----------------------------------------------------- 8. check, CTA decision, no insights
    code, out = run("check", now=uk(d + timedelta(days=1), 9))
    st = load()
    check("check prints results per format and the Supabase query by week after launch",
          code == 0 and "Results per format" in out and "week_after_launch" in out and "Followers: 250" in out,
          out[-600:])
    check("after the 4 test weeks the kit keeps one call to action", st.get("cta_decided") in ("comment", "bio"),
          st.get("cta_test_result"))
    check("carousels: a metric Instagram does not give is dropped, the rest still read",
          any(p.get("stats", {}).get("reach") for p in st["posts"] if p.get("kind") == "carousel"
              and p.get("status") == "published"))
    ms.GS.insights = False
    code, out = run("check", now=uk(d + timedelta(days=1), 10))
    check("no insights permission: check explains and carries on", code == 0 and "results not available" in out,
          out[-300:])
    ms.GS.insights = True

    # ----------------------------------------------------- 9. in-process checks
    import rumo  # noqa: E402
    cfg = {"trial_reels": False}
    stx = {"launch_date": "2027-03-01"}
    due = lambda t: rumo._due(stx, cfg, tz, t)  # noqa: E731
    check("winter: 17:05 UTC is too early, 18:05 UTC posts the 18:00 slot",
          due(datetime(2027, 3, 26, 17, 5, tzinfo=timezone.utc)) == []
          and due(datetime(2027, 3, 26, 18, 5, tzinfo=timezone.utc)) == [("2027-03-26T18:00:00Z", False)])
    check("summer: 17:05 UTC posts the 18:00 UK slot",
          due(datetime(2027, 3, 29, 17, 5, tzinfo=timezone.utc)) == [("2027-03-29T17:00:00Z", False)])
    from rumo_render import mark_word  # noqa: E402
    check("answer highlight never lands inside another word",
          mark_word("O café é forte.", "é") == "O café <mark>é</mark> forte."
          and mark_word("Vou parar para comer.", "para") == "Vou parar <mark>para</mark> comer.",
          mark_word("O café é forte.", "é"))
    import rumo_gate, rumo_extract  # noqa: E402
    src = (HERE / "fixtures" / "b2-giria.html").read_text(encoding="utf-8")
    st = load()
    gp = [p for p in st["posts"] if "b2-giria" in (p.get("url") or "") and p.get("topic")
          and p.get("status") not in ("missed", "unfit")]
    renamed = rumo_extract.parse_page(src.replace("<h1>Gíria &amp; expressões", "<h1>Gírias &amp; expressões"))
    same = rumo_extract.parse_page(src)
    check("a chapter renamed on the site stops posts whose caption names the old title",
          gp and all(rumo_gate.check_post(p, same) == [] for p in gp)
          and all(rumo_gate.check_post(p, renamed) for p in gp)
          and any(any("title changed" in m for m in rumo_gate.check_post(p, renamed)) for p in gp),
          [(p["id"], rumo_gate.check_post(p, renamed)[:1]) for p in gp[:4]])
    st = load()
    from rumo_formats import PLANNABLE  # noqa: E402
    for p in [p for p in st["posts"] if p.get("status") in PLANNABLE][5:]:
        p["status"] = "missed"
    rumo._top_up(st)
    req = [p for p in st["posts"] if p.get("status") == "requeue"]
    check("when the queue runs low, the best posts go out once more (never trial Reels)",
          req and not any(p.get("trial") for p in req), len(req))

    # ------------------------------------------- 10. the runner: git hosting + saving progress
    gw = Path(tempfile.mkdtemp(prefix="rumo-git-"))
    bare = Path(tempfile.mkdtemp(prefix="rumo-bare-")) / "r.git"
    for f in work.iterdir():
        if f.name in ("preview", "cache", "__pycache__", ".run.lock"):
            continue
        (shutil.copytree if f.is_dir() else shutil.copy2)(f, gw / f.name)
    g = lambda *a, cwd=gw: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)  # noqa: E731
    g("init", "-q", "--bare", str(bare), cwd=bare.parent)
    g("init", "-q", "-b", "main")
    g("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "kit")
    g("remote", "add", "origin", str(bare))
    g("push", "-q", "origin", "main")
    from http.server import BaseHTTPRequestHandler  # noqa: E402

    class Raw(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            m = re.fullmatch(r"/raw/([0-9a-f]{40})/(.+)", self.path)
            r = subprocess.run(["git", "--git-dir", str(bare), "show", f"{m.group(1)}:{m.group(2)}"],
                               capture_output=True) if m else None
            if not r or r.returncode:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(r.stdout)
    raw = ms.start(Raw)
    genv = dict(env, GITHUB_ACTIONS="true", GITHUB_REF_NAME="main",
                RUMO_RAW_BASE=f"http://127.0.0.1:{raw.server_port}/raw/{{sha}}/{{path}}")
    genv.pop("RUMO_HOST")
    r = subprocess.run([py, "rumo.py", "connect"], cwd=gw, env=genv, capture_output=True, text=True,
                       encoding="utf-8")
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "-1", "--format=%s", "main"],
                         capture_output=True, text=True).stdout
    media = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "media"],
                           capture_output=True, text=True).stdout
    saved = subprocess.run(["git", "--git-dir", str(bare), "show", "main:posts.json"],
                           capture_output=True, text=True, encoding="utf-8").stdout
    check("on the runner: slides go to the 'media' branch and Instagram can open them",
          r.returncode == 0 and "T2 passed" in r.stdout and "m/connect-test/connect-test.jpg" in media,
          (r.stdout + r.stderr)[-500:])
    check("on the runner: progress is committed back with [skip ci] (never starts another run)",
          "[skip ci]" in log and '"connected_at"' in saved, log)
    other = Path(tempfile.mkdtemp(prefix="rumo-other-"))
    g("clone", "-q", "-b", "main", str(bare), str(other / "c"), cwd=other)
    (other / "c" / "posts.json").write_text('{"edited": "elsewhere"}', encoding="utf-8")
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "hand edit", cwd=other / "c")
    g("push", "-q", "origin", "main", cwd=other / "c")
    st = json.loads((gw / "posts.json").read_text(encoding="utf-8"))
    st["touched"] = 1
    (gw / "posts.json").write_text(json.dumps(st), encoding="utf-8")
    r = subprocess.run([py, "rumo.py", "status"], cwd=gw, env=genv, capture_output=True, text=True, encoding="utf-8")
    sys.path.insert(0, str(gw))
    r = subprocess.run([py, "-c", "import rumo_host; print(rumo_host.persist('test'))"], cwd=gw, env=genv,
                       capture_output=True, text=True, encoding="utf-8")
    remote = subprocess.run(["git", "--git-dir", str(bare), "show", "main:posts.json"],
                            capture_output=True, text=True, encoding="utf-8").stdout
    check("a clash with a hand edit is given up cleanly: no half-merged file is ever pushed",
          r.stdout.strip().endswith("False") and "<<<<<<<" not in remote and json.loads(remote)
          and not (gw / ".git" / "rebase-merge").exists(), (r.stdout + r.stderr)[-300:])
    ignored = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main"],
                             capture_output=True, text=True).stdout
    check("previews, cache and locks are never committed",
          not any(x.startswith(("preview/", "cache/", ".run.lock")) for x in ignored.splitlines()), ignored[:300])

    # ----------------------------------------------------------- 11. crash
    (work / "posts.json").write_text("{not json", encoding="utf-8")
    code, out = run("daily", expect=2, now=uk(d, 18))
    failed = (work / "FAILED.txt").read_text(encoding="utf-8") if (work / "FAILED.txt").exists() else ""
    check("a crash writes FAILED.txt (never a silent traceback)", code == 2 and "STOPPED AT" in failed, out[-400:])

    print("\n%d checks, %d failed" % (len(RESULTS), sum(1 for r in RESULTS if not r[1])))
    print("Test folder:", work)
    return 0 if all(r[1] for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

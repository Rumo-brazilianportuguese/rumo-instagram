"""The accuracy gate.

For every post, every reference (Portuguese line, English explanation or
translation, label, quiz sentence, story sentence) is re-derived from the LIVE
page: same card, row and cell, or same story sentence id; same language role;
same derivation. Quiz answers are re-derived from the card the sentence sits
in. One mismatch and the post is refused.
"""
import copy

from rumo_common import say
from rumo_extract import fetch_page, parse_page
from rumo_formats import DUELS, config, derive, excluded, live_text, refs_of, topic_of


def _check_ref(r, page):
    live = live_text(page, r)
    if live is None:
        where = r.get("sid") or f"{r['card']}/{r['row']}/{r['cell']}"
        return f"{where}: not found on the page"
    if "sid" in r:
        src = live
        if r.get("role") != ("pt" if r["field"] == "pt" else "en"):
            return f"{r['sid']}: language role differs"
    elif isinstance(r["card"], int) or str(r["card"]).isdigit():
        card = page["cards"][int(r["card"])]
        if card["heading"] != r.get("heading"):
            return f"card {r['card']}: heading differs"
        if r["row"] is None:
            src = live
        else:
            if live["role"] != r.get("role"):
                return f"card {r['card']} row {r['row']}: language role differs"
            src = live["text"]
    else:
        src = live
    want = derive(src, r["op"], r["arg"])
    if want != r["text"]:
        return f"text differs: {r['text']!r} vs page {want!r}"
    if not r["text"] or r["text"].startswith("⁇"):
        return f"empty or broken derivation: {r['text']!r}"
    if "rich" in r and isinstance(live, dict) and r["rich"] != live.get("rich"):
        return f"emphasis differs: {r['rich']!r} vs page {live.get('rich')!r}"
    if r["op"] in ("whole", "seg") and r.get("field") != "en" and r["text"] not in page["alltext"]:
        return f"text not found anywhere on the page: {r['text']!r}"
    return None


def _quiz_parts(post):
    """Every answered quiz item in a post: carousel answer slides, Reel scenes, streak items."""
    for s in post["slides"]:
        if "answer_card" in s:
            yield s
        for it in s.get("items") or []:
            if "answer_card" in it:
                yield it


def _check_quiz(post, page):
    spec = DUELS.get(post.get("slug"))
    misses = []
    for s in _quiz_parts(post):
        if not spec:
            return ["quiz from a page that is not a known duel"]
        heading = s["full"].get("heading", "")
        answer = next((v for k, v in spec["cards"].items() if heading.startswith(k)), None)
        if answer is None or answer != s["answer"]:
            misses.append(f"quiz answer {s['answer']!r} does not match the card {heading!r}")
        if s["word"]["text"].lower() not in [t.lower() for t in spec["tokens"][s["answer"]]]:
            misses.append(f"quiz word {s['word']['text']!r} is not a form of {s['answer']}")
    for s in post["slides"]:
        qs = [s.get("q")] if s.get("kind") in ("question", "reel_quiz") else []
        qs += [it.get("q") for it in s.get("items") or [] if "answer_card" in it]
        for q in qs:
            if q is not None and q["text"].count("___") != 1:
                misses.append("quiz sentence must contain exactly one blank")
    return misses


PAIR_KEYS = ("pt", "en", "gloss", "q", "full", "word", "why", "left", "right", "label")


def _loc(r):
    return ("sid", r["sid"]) if "sid" in r else ("cell", r.get("card"), r.get("row"))


def _check_pairs(post):
    """Lines shown together must come from the same place: a Portuguese line and its English
    from the same row or story sentence, a quiz blank and its answer from the same example."""
    misses = []

    def walk(x):
        if isinstance(x, dict):
            refs = {k: v for k, v in x.items() if k in PAIR_KEYS and isinstance(v, dict) and "op" in v}
            if len(refs) >= 2:
                locs = {_loc(v) for v in refs.values()}
                if len(locs) != 1:
                    misses.append(f"lines shown together come from different places: {sorted(refs)}")
                segs = {v["arg"].get("i") for v in refs.values() if "i" in v.get("arg", {})
                        and v["op"] in ("blank", "blankans", "seg")}
                if len(segs) > 1:
                    misses.append("quiz sentence and answer come from different examples")
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(post["slides"])
    # a carousel quiz: question n and answer n are the same sentence
    qs = {s["n"]: s["q"] for s in post["slides"] if s.get("kind") == "question"}
    for s in post["slides"]:
        if s.get("kind") == "answer" and s["n"] in qs:
            q = qs[s["n"]]
            if _loc(q) != _loc(s["full"]) or q["arg"].get("i") != s["full"]["arg"].get("i"):
                misses.append(f"question {s['n']} and answer {s['n']} are different sentences")
    return misses


def check_post(post: dict, page: dict) -> list:
    misses = []
    if post.get("written"):
        return misses
    refs = refs_of(post)
    if not refs:
        return ["post has no references to the page"]
    for r in refs:
        if r["url"] != post["url"]:
            misses.append("reference points at another page")
            continue
        m = _check_ref(r, page)
        if m:
            misses.append(m)
    misses += _check_quiz(post, page)
    misses += _check_pairs(post)
    misses += _check_topic(post, page)
    return misses


def _check_topic(post, page):
    """The caption's first line names the chapter or story: it must still match the live page."""
    t = post.get("topic")
    if not t:
        return []
    live = {r["text"] for r in refs_of(post)}
    if page.get("title"):
        live.add(topic_of(page))
    if t not in live:
        return [f"chapter/story title changed on the site: {t!r}"]
    # stored copies of the title elsewhere in the post must match it too
    f, hook, sub = post.get("format"), post.get("hook", ""), post.get("sub", "")
    if f == "traps" and not hook.startswith(t + ":"):
        return ["the cover title no longer matches the chapter title"]
    if f in ("story", "examples") and hook != t:
        return ["the cover title no longer matches the chapter/story title"]
    if f == "examples":
        head = ((post.get("slides") or [{}])[0].get("head") or {}).get("text")
        if head is None or sub != head:
            return ["the cover subtitle no longer matches the card heading"]
    return []


def gate(state: dict, refresh: bool = True, only=None) -> tuple:
    """Check posts against the live pages. Returns (checked, missed_ids, report_lines).

    Posts already scheduled or published are not re-checked (they were checked
    before upload). `only` limits the check to some post ids.
    """
    pages = {}
    cfg = config()
    checked, missed, lines = 0, [], []
    for post in state["posts"]:
        if only is not None and post["id"] not in only:
            continue
        if post.get("written"):
            post["gate"] = "written"
            continue
        if post.get("status") in ("scheduled", "published", "removed", "rejected") and only is None:
            continue   # booked/out, or left out for good: never brought back by a re-check
        if post["url"] not in pages:
            try:
                pages[post["url"]] = parse_page(fetch_page(post["url"], refresh=refresh))
            except Exception as e:  # page gone or unreachable
                pages[post["url"]] = e
        page = pages[post["url"]]
        checked += 1
        if isinstance(page, Exception):
            m = [f"page could not be read: {page}"]
        elif excluded(post, cfg):
            m = ["contains a line listed under 'exclude' in config.json"]
        else:
            m = check_post(post, page)
        if isinstance(page, Exception) and ("HTTP 404" in str(page) or "HTTP 410" in str(page)):
            # the page is gone from the site (removed or renamed): its posts are left out for good
            missed.append(post["id"])
            lines.append(f"GONE {post['id']}: page no longer on the site ({post['url']})")
            post["gate"] = "gone"   # left out for good, unless half the site is gone (see rumo.py)
        elif isinstance(page, Exception):
            # a hiccup of the site is not a mismatch: the post is skipped this run, not left out
            missed.append(post["id"])
            lines.append(f"UNREAD {post['id']}: " + m[0][:200])
            post["gate"] = "unread"
        elif m:
            missed.append(post["id"])
            lines.append(f"MISS {post['id']}: " + "; ".join(m[:6]))
            post["gate"] = "missed"
        else:
            post["gate"] = "passed"
    return checked, missed, lines


# --------------------------------------------------------------- self-test
ACCENTS = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")


def _poisons(posts):
    """Deliberately wrong posts built from real ones. Every one must be rejected."""
    out = {}
    for post in posts:
        refs = refs_of(post)
        if "a_swapped" not in out:
            pts = [r for r in refs if r.get("role") == "pt" and "sid" not in r]
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    if pts[i]["text"] != pts[j]["text"] and pts[i]["row"] != pts[j]["row"]:
                        p = copy.deepcopy(post)
                        rr = [r for r in refs_of(p) if r.get("role") == "pt" and "sid" not in r]
                        rr[i]["text"], rr[j]["text"] = rr[j]["text"], rr[i]["text"]
                        out["a_swapped"] = p
                        break
                if "a_swapped" in out:
                    break
        if "b_accent" not in out:
            for i, r in enumerate(refs):
                if r.get("role") == "pt" and r["text"].translate(ACCENTS) != r["text"]:
                    p = copy.deepcopy(post)
                    t = refs_of(p)[i]
                    ch = next(c for c in t["text"] if c.translate(ACCENTS) != c)
                    t["text"] = t["text"].replace(ch, ch.translate(ACCENTS), 1)
                    out["b_accent"] = p
                    break
        if "c_word" not in out:
            for i, r in enumerate(refs):
                if r.get("role") == "pt" and r["text"].startswith("✅"):
                    p = copy.deepcopy(post)
                    t = refs_of(p)[i]
                    t["text"] = t["text"] + "s"
                    if "rich" in t:
                        t["rich"] = t["rich"] + "s"
                    out["c_word"] = p
                    break
        if "d_quiz" not in out and post["format"] == "quiz":
            p = copy.deepcopy(post)
            ans = next(s for s in p["slides"] if s["kind"] == "answer")
            a, b = DUELS[p["slug"]]["pair"]
            ans["answer"] = b if ans["answer"] == a else a
            out["d_quiz"] = p
        if "e_story_en" not in out:
            for i, r in enumerate(refs):
                if "sid" in r and r["field"] == "en" and " " in r["text"]:
                    p = copy.deepcopy(post)
                    t = refs_of(p)[i]
                    w = t["text"].split(" ")
                    t["text"] = " ".join(w[1:] + w[:1])   # same words, wrong order
                    out["e_story_en"] = p
                    break
        if "f_story_swap" not in out:
            sp = [r for r in refs if "sid" in r and r["field"] == "pt"]
            for i in range(len(sp) - 1):
                if sp[i]["sid"] != sp[i + 1]["sid"] and sp[i]["text"] != sp[i + 1]["text"]:
                    p = copy.deepcopy(post)
                    rr = [r for r in refs_of(p) if "sid" in r and r["field"] == "pt"]
                    rr[i]["text"], rr[i + 1]["text"] = rr[i + 1]["text"], rr[i]["text"]
                    out["f_story_swap"] = p
                    break
        if "i_pair" not in out:
            holders = []

            def find(x):
                if isinstance(x, dict):
                    if isinstance(x.get("pt"), dict) and isinstance(x.get("en"), dict) and "op" in x["en"]:
                        holders.append(x)
                    for v in x.values():
                        find(v)
                elif isinstance(x, list):
                    for v in x:
                        find(v)
            p = copy.deepcopy(post)
            find(p["slides"])
            for a in range(len(holders)):
                for b in range(a + 1, len(holders)):
                    if _loc(holders[a]["en"]) != _loc(holders[b]["en"]):
                        holders[a]["en"], holders[b]["en"] = holders[b]["en"], holders[a]["en"]
                        out["i_pair"] = p
                        break
                if "i_pair" in out:
                    break
        if "h_streak" not in out and post.get("reel_kind") == "quiz3":
            p = copy.deepcopy(post)
            it = p["slides"][0]["items"][1]
            a, b = DUELS[p["slug"]]["pair"]
            it["answer"] = b if it["answer"] == a else a
            out["h_streak"] = p
        if "g_reel_quiz" not in out and post.get("reel_kind") == "quiz":
            p = copy.deepcopy(post)
            sc = p["slides"][0]
            a, b = DUELS[p["slug"]]["pair"]
            sc["answer"] = b if sc["answer"] == a else a
            out["g_reel_quiz"] = p
    return out


POISONS = ("a_swapped", "b_accent", "c_word", "d_quiz", "e_story_en", "f_story_swap", "g_reel_quiz",
           "h_streak", "i_pair")


def self_test(state: dict) -> list:
    """Check the checker. Posts are rebuilt fresh from a few live pages (so a post that was
    edited by hand in posts.json cannot spoil the test): each fresh post must pass, and each
    deliberately poisoned copy must be rejected."""
    from rumo_formats import GRAMMAR_BUILDERS, REEL_BUILDERS, STORY_BUILDERS
    problems = []
    stored = [p for p in state["posts"] if not p.get("written") and p.get("url")]
    pages = {}

    def page_of(url):
        if url not in pages:
            pages[url] = parse_page(fetch_page(url))
        return pages[url]

    wanted = []
    for test in (lambda p: p["format"] == "quiz", lambda p: p["format"] == "traps",
                 lambda p: p["format"] == "story", lambda p: p.get("reel_kind") == "quiz"):
        p = next((p for p in stored if test(p)), None)
        if p and p["url"] not in wanted:
            wanted.append(p["url"])
    real = []
    for url in wanted:
        page = page_of(url)
        slug = url.rstrip("/").split("/")[-1].replace(".html", "")
        builders = STORY_BUILDERS if page["kind"] == "story" else GRAMMAR_BUILDERS + REEL_BUILDERS
        for b in builders:
            real += b(slug, url, page)
    for f in ("quiz", "story", "reel"):
        c = next((p for p in real if p["format"] == f), None)
        if c is None:
            problems.append(f"could not build a fresh {f} post for the control test")
        elif check_post(c, page_of(c["url"])):
            problems.append(f"control post {c['id']} should pass but did not: {check_post(c, page_of(c['url']))[:2]}")
    poisons = _poisons(real)
    for name in POISONS:
        bad = poisons.get(name)
        if bad is None:
            problems.append(f"could not build poisoned test {name}")
            continue
        if not check_post(bad, page_of(bad["url"])):
            problems.append(f"poisoned test {name} on {bad['id']} was NOT rejected")
        else:
            say(f"  self-test {name}: rejected, as it should be")
    return problems

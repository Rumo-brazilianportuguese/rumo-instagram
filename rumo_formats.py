"""Post formats, the posting order and the captions.

Every Portuguese string and every English explanation or translation on a
slide or in a Reel is a *reference* into a live page: page URL plus card / row /
cell (grammar chapters) or sentence id (stories), and a derivation (the whole
text, one " · " segment, one side of an arrow, a gloss, the verb blanked out
for a quiz...). The gate re-reads the live page, re-runs the same derivation,
and refuses the post if a single character differs.

The only text written here is English framing: hooks, labels, questions and
calls to action. None of it states a grammar rule, a statistic or a promise
that is not on the site.
"""
import json
import re

from rumo_common import LEVEL_ORDER, ROOT, norm

SEP = " · "      # separates examples on the site
ARROW = "→"
CHECK = "✅"

CONFIG_FILE = ROOT / "config.json"
DEFAULT_CONFIG = {
    # "comment": slides and captions say "Comment START" (Meta comment-to-message rule live)
    # "bio":     slides and captions say "Link in bio" (fallback if the rule is not live)
    "cta_mode": "comment",
    "keyword": "START",
    # Posts drawn by 'build' for you to look at first (about four weeks).
    "preview_posts": 30,
    # Lines that must never be posted (a post containing one is left out).
    # cafézinho / pézinho: the diminutives page spells them with an accent; the
    # usual spelling is cafezinho / pezinho. Left out until the page is checked.
    "exclude": ["cafézinho", "pézinho"],
    # The Instagram account the key must post to (the key may see more than one).
    "instagram_username": "rumo.portuguese",
    # The first 4 weeks after launch alternate "Comment START" weeks and "link in bio" weeks,
    # to see on this account whether the comment ask costs reach. The kit then keeps the winner.
    "cta_test": True,
    "cta_test_weeks": 4,
    # Trial Reels (shown to non-followers first). Instagram offers them from 200 followers;
    # with trial_auto the weekly run switches them on by itself when Instagram reports 200+
    # followers. By hand: python rumo.py trial on / trial off (off also stops the automatic switch).
    "trial_reels": False,
    "trial_auto": True,
}


def config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
    return cfg


def save_config(cfg: dict) -> None:
    keep = {k: v for k, v in cfg.items()}
    CONFIG_FILE.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------ derivations
_GLOSS = re.compile(r"\s*\(([^()]*? = [^()]*)\)")


def _segs(t):
    return [s.strip() for s in t.split(SEP)]


def token_re(tokens):
    alt = "|".join(sorted((re.escape(t) for t in tokens), key=len, reverse=True))
    return re.compile(r"(?<![\wÀ-ɏ])(" + alt + r")(?![\wÀ-ɏ])", re.I)


def derive(text: str, op: str, arg: dict) -> str:
    """The single derivation function, used when building AND when checking."""
    t = norm(text)
    if op in ("whole", "heading"):
        return t
    if op == "h1topic":
        return t.split(" — ")[0].strip()
    if op == "h1tag":
        parts = t.split(" — ", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    if op == "headshort":
        return t.split(" — ")[0].strip()
    if op == "subhook":  # the part of the chapter subtitle after "level XX."
        m = re.search(r"level (?:A1|A2|B1|B2)\.\s*(.+)$", t)
        return m.group(1).strip() if m else ""
    if op == "storysub":  # the part of a story subtitle after "level XX · "
        m = re.search(r"level (?:A1|A2|B1|B2) · (.+)$", t)
        return m.group(1).strip() if m else ""
    if op == "gloss":    # the i-th "(word = meaning)" note in a story translation
        found = _GLOSS.findall(t)
        i = arg.get("i", 0)
        return found[i].strip() if i < len(found) else "⁇no gloss"
    if op == "nogloss":  # the translation without its "(word = meaning)" notes
        return re.sub(r"\s+", " ", _GLOSS.sub("", t)).strip()
    segs = _segs(t)
    i = arg.get("i", 0)
    if i >= len(segs):
        return "⁇missing segment"
    seg = segs[i]
    if op == "seg":
        return seg
    if op == "arrow":
        parts = [p.strip() for p in seg.split(ARROW)]
        if len(parts) != 2:
            return "⁇no arrow"
        return parts[arg["side"]]
    if op in ("blank", "blankans"):
        m = token_re(arg["tokens"]).search(seg)
        if not m:
            return "⁇no token"
        if op == "blankans":
            return m.group(0)
        return seg[:m.start()] + "___" + seg[m.end():]
    raise ValueError(op)


def glosses(en_text):
    return [g.strip() for g in _GLOSS.findall(norm(en_text))]


def ref(url, page, card, row, cell, op="whole", **arg):
    """A reference into a grammar chapter (card/row/cell, or the h1/subtitle)."""
    if card == "h1":
        src = page["title"]
    elif card == "sub":
        src = page["sub"]
    elif row is None:
        src = page["cards"][card]["heading"]
    else:
        src = page["cards"][card]["rows"][row][cell]["text"]
    r = {"url": url, "card": card, "row": row, "cell": cell, "op": op, "arg": arg,
         "text": derive(src, op, arg)}
    if isinstance(card, int):
        r["heading"] = page["cards"][card]["heading"]
        if row is not None:
            c = page["cards"][card]["rows"][row][cell]
            r["role"] = c["role"]
            if op == "whole":
                r["rich"] = c["rich"]  # the page's own bold emphasis, checked by the gate
    return r


def sref(url, page, sid, field, op="whole", **arg):
    """A reference into a story: sentence id, Portuguese text or its English data-tr."""
    src = page["sents"][sid][field]
    return {"url": url, "sid": sid, "field": field, "op": op, "arg": arg,
            "role": "pt" if field == "pt" else "en", "text": derive(src, op, arg)}


def live_text(page, r):
    """The live text a reference points at (None if it is gone)."""
    if "sid" in r:
        s = page.get("sents", {}).get(r["sid"])
        return None if s is None else s.get(r["field"])
    if r["card"] == "h1":
        return page["title"]
    if r["card"] == "sub":
        return page["sub"]
    card = page["cards"].get(int(r["card"]))
    if card is None:
        return None
    if r["row"] is None:
        return card["heading"]
    cells = card["rows"].get(r["row"])
    if cells is None or r["cell"] >= len(cells):
        return None
    return cells[r["cell"]]


def refs_of(post):
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "op" in x and "url" in x and "text" in x:
                out.append(x)
            else:
                for v in x.values():
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(post["slides"])
    return out


def excluded(post, cfg):
    bad = [x for x in cfg.get("exclude", []) if x]
    return any(b in r["text"] for r in refs_of(post) for b in bad)


# ------------------------------------------------------------ helpers
def _cards(page, prefix):
    p = prefix.lower()
    return [(ci, c) for ci, c in page["cards"].items() if c["heading"].lower().startswith(p)]


def _pt_en_rows(card):
    """Rows laid out as [Portuguese cell, English cell]."""
    return [k for k, cells in card["rows"].items()
            if len(cells) == 2 and cells[0]["role"] == "pt" and cells[1]["role"] == "en"
            and cells[0]["text"] and cells[1]["text"]]


def _en_pt_rows(card):
    return [k for k, cells in card["rows"].items()
            if len(cells) == 2 and cells[0]["role"] == "en" and cells[1]["role"] == "pt"
            and cells[0]["text"] and cells[1]["text"]]


def topic_of(page):
    return page["title"].split(" — ")[0].strip()


def _post(fmt, series, slug, url, page, hook, sub, slides, theme, extra=None, kind="carousel"):
    return {
        "id": f"{fmt}-{slug}" + (f"-{extra}" if extra else ""),
        "format": fmt, "kind": kind, "series": series, "theme": theme,
        "slug": slug, "url": url, "level": page["level"],
        "chapter": page.get("chapter") or 0, "story": page.get("story"),
        "topic": topic_of(page), "hook": hook, "sub": sub, "slides": slides,
        "status": "extracted",
    }


# ------------------------------------------------------------ grammar data
# Quiz duels: the card a sentence sits in decides the answer.
DUELS = {
    "ser-estar": {
        "pair": ("SER", "ESTAR"),
        "cards": {"When to use SER": "SER", "When to use ESTAR": "ESTAR"},
        "tokens": {"SER": ["sou", "é", "somos", "são"],
                   "ESTAR": ["estou", "está", "estamos", "estão"]},
        "skip_labels": ["personality"],   # ser and estar can both be right there
    },
    "por-para": {
        "pair": ("POR", "PARA"),
        "cards": {"PARA — forward": "PARA", "POR — through": "POR"},
        "tokens": {"POR": ["por"], "PARA": ["para"]},
        "skip_labels": [],
    },
}

# Phrase pages: rows of [Portuguese phrase | English meaning].
MEANING_CARDS = {
    "spoken": ["The social sound kit", "a gente"],
    "b2-giria": ["The safe core", "The idiom engine", "The intensity dial"],
}
MEANING_HOOKS = {
    "The social sound kit": ("You'll hear these in Brazil every day", "Guess what they mean, then swipe."),
    "a gente": ("a gente: the “we” you'll actually hear", "Guess the meaning, then swipe."),
    "The safe core": ("Brazilian slang, decoded", "Guess the meaning, then swipe."),
    "The idiom engine": ("Brazilian idioms, taken literally", "Guess the meaning, then swipe."),
    "The intensity dial": ("How good is it? Say it like a Brazilian", "Guess the meaning, then swipe."),
}

# Two registers of the same thing, split by an arrow on the site.
REAL_CARDS = {
    ("spoken", "The great shortcuts"): {
        "hook": "Textbook Portuguese vs. what Brazilians say",
        "sub": "Same words, the way you'll actually hear them.",
        "labels": ("Textbook", "What you'll hear"),
    },
    ("b2-giria", "Register safety"): {
        "hook": "Texting friends vs. writing to your boss",
        "sub": "The same message in two registers.",
        "labels": None,  # taken verbatim from the English cell: "friends → chefia / e-mail"
    },
}

# Cards used by a dedicated format, or not suited to posts.
EXAMPLE_SKIP = ("what this is about", "exceptions", "the classic traps", "the flip test",
                "practise this chapter")


def quiz_items(slug, url, page):
    spec = DUELS.get(slug)
    if not spec:
        return {}
    a_lbl, b_lbl = spec["pair"]
    other = {a_lbl: b_lbl, b_lbl: a_lbl}
    items = {a_lbl: [], b_lbl: []}
    for heading, answer in spec["cards"].items():
        for ci, card in _cards(page, heading):
            for key in _en_pt_rows(card):
                label_cell, pt_cell = card["rows"][key]
                if any(s in label_cell["text"].lower() for s in spec["skip_labels"]):
                    continue
                for i, seg in enumerate(_segs(pt_cell["text"])):
                    if not token_re(spec["tokens"][answer]).search(seg):
                        continue
                    if token_re(spec["tokens"][other[answer]]).search(seg):
                        continue  # both verbs in one sentence: not a fair question
                    items[answer].append({
                        "q": ref(url, page, ci, key, 1, "blank", i=i, tokens=spec["tokens"][answer]),
                        "full": ref(url, page, ci, key, 1, "seg", i=i),
                        "word": ref(url, page, ci, key, 1, "blankans", i=i, tokens=spec["tokens"][answer]),
                        "why": ref(url, page, ci, key, 0, "whole"),
                        "answer": answer, "answer_card": card["heading"],
                        "key": f"{ci}-{key}-{i}",
                    })
    return items


def build_quiz(slug, url, page):
    spec = DUELS.get(slug)
    if not spec:
        return []
    a_lbl, b_lbl = spec["pair"]
    items = quiz_items(slug, url, page)
    posts = []
    n = min(len(items[a_lbl]), len(items[b_lbl])) // 2
    for k in range(n):
        qs = [items[a_lbl][2 * k], items[b_lbl][2 * k], items[b_lbl][2 * k + 1], items[a_lbl][2 * k + 1]]
        if k % 2:
            qs = [qs[1], qs[0], qs[3], qs[2]]
        slides = [{"kind": "cover", "chips": [a_lbl, b_lbl]}]
        for qn, q in enumerate(qs, 1):
            slides.append({"kind": "question", "n": qn, "of": len(qs), "q": q["q"],
                           "options": [a_lbl, b_lbl]})
            slides.append({"kind": "answer", "n": qn, "full": q["full"], "word": q["word"],
                           "why": q["why"], "answer": q["answer"], "answer_card": q["answer_card"],
                           "slug": slug})
        slides.append({"kind": "cta"})
        p = _post("quiz", f"{a_lbl.title()} or {b_lbl.title()}?", slug, url, page,
                  f"{a_lbl.title()} or {b_lbl.lower()}? Can you get all 4?",
                  f"Round {k + 1}. Pick one, then swipe for the answer.",
                  slides, "night", extra=str(k + 1))
        p["rank"] = k
        posts.append(p)
    return posts


def _meaning_rows(page):
    for rank, prefix in enumerate(MEANING_CARDS.get(page.get("_slug"), [])):
        for ci, card in _cards(page, prefix):
            yield rank, prefix, ci, card, _pt_en_rows(card)


def build_meaning(slug, url, page):
    out = []
    page["_slug"] = slug
    for rank, prefix, ci, card, keys in _meaning_rows(page):
        hook, sub = MEANING_HOOKS.get(prefix, (f"{card['heading']}: guess the meaning",
                                               "Guess the meaning, then swipe."))
        for k in range(0, len(keys) - 1, 3):
            part = keys[k:k + 3]
            if len(part) < 2:
                continue
            slides = [{"kind": "cover", "bubble": ref(url, page, ci, part[0], 0, "whole")}]
            for key in part:
                slides.append({"kind": "chat_q", "pt": ref(url, page, ci, key, 0, "whole")})
                slides.append({"kind": "chat_a", "pt": ref(url, page, ci, key, 0, "whole"),
                               "en": ref(url, page, ci, key, 1, "whole")})
            slides.append({"kind": "cta"})
            part_sub = sub if k == 0 else f"Part {k // 3 + 1}. {sub}"
            post = _post("meaning", "Guess the meaning", slug, url, page, hook, part_sub,
                         slides, "tropic", extra=f"{ci}-{k // 3 + 1}")
            post["rank"] = rank * 10 + k // 3  # the strongest card goes first
            out.append(post)
    return out


def _real_pairs(slug, url, page):
    for (s, prefix), spec in REAL_CARDS.items():
        if s != slug:
            continue
        for ci, card in _cards(page, prefix):
            for key in _pt_en_rows(card):
                pt, en = card["rows"][key]
                for i, seg in enumerate(_segs(pt["text"])):
                    if seg.count(ARROW) != 1:
                        continue
                    pair = {"left": ref(url, page, ci, key, 0, "arrow", i=i, side=0),
                            "right": ref(url, page, ci, key, 0, "arrow", i=i, side=1)}
                    sl = {"pairs": [pair]}
                    if spec["labels"]:
                        sl["labels"] = list(spec["labels"])
                        sl["example"] = ref(url, page, ci, key, 1, "whole")
                    else:
                        if en["text"].count(ARROW) != 1:
                            continue
                        sl["label_refs"] = [ref(url, page, ci, key, 1, "arrow", i=0, side=0),
                                            ref(url, page, ci, key, 1, "arrow", i=0, side=1)]
                    yield spec, ci, key, i, sl


def build_real(slug, url, page):
    out = {}
    for spec, ci, key, i, sl in _real_pairs(slug, url, page):
        post = out.get(ci)
        if post is None:
            post = out[ci] = _post("real", "Textbook vs. real", slug, url, page, spec["hook"],
                                   spec["sub"], [{"kind": "cover"}], "sun", extra=str(ci))
        post["slides"].append(dict(sl, kind="real"))
    res = []
    for post in out.values():
        if len(post["slides"]) < 3:
            continue
        post["slides"] = post["slides"][:9]
        post["slides"].append({"kind": "cta"})
        res.append(post)
    return res


def build_traps(slug, url, page):
    out = []
    for ci, card in _cards(page, "The classic traps"):
        keys = [k for k in _pt_en_rows(card) if card["rows"][k][0]["text"].startswith(CHECK)]
        if len(keys) < 2:
            continue
        slides = [{"kind": "cover", "count": len(keys[:6]), "topic": ref(url, page, "h1", None, None, "h1topic")}]
        for n, key in enumerate(keys[:6], 1):
            slides.append({"kind": "trap", "n": n, "of": len(keys[:6]), "pt": ref(url, page, ci, key, 0, "whole"),
                           "en": ref(url, page, ci, key, 1, "whole")})
        slides.append({"kind": "cta"})
        topic = topic_of(page)
        out.append(_post("traps", "The classic traps", slug, url, page,
                         f"{topic}: {len(keys[:6])} classic traps",
                         "The right way to say each one, with the reason.", slides, "rumo"))
    return out


def build_flip(slug, url, page):
    out = []
    for ci, card in _cards(page, "The flip test"):
        keys = _pt_en_rows(card)
        pairs = [keys[i:i + 2] for i in range(0, len(keys) - 1, 2)][:4]
        if not pairs:
            continue
        slides = [{"kind": "cover", "topic": ref(url, page, "h1", None, None, "h1topic")}]
        for a, b in pairs:
            slides.append({"kind": "flip",
                           "a": {"pt": ref(url, page, ci, a, 0, "whole"), "en": ref(url, page, ci, a, 1, "whole")},
                           "b": {"pt": ref(url, page, ci, b, 0, "whole"), "en": ref(url, page, ci, b, 1, "whole")}})
        slides.append({"kind": "cta"})
        out.append(_post("flip", "One word, two meanings", slug, url, page,
                         "Same sentence. One word changes the meaning.",
                         topic_of(page), slides, "sun"))
    return out


def _dedicated(slug, heading):
    h = heading.lower()
    if h.startswith(EXAMPLE_SKIP):
        return True
    for prefix in MEANING_CARDS.get(slug, []):
        if h.startswith(prefix.lower()):
            return True
    for (s, prefix) in REAL_CARDS:
        if s == slug and h.startswith(prefix.lower()):
            return True
    return False


def build_examples(slug, url, page):
    """One post per example table: [Portuguese example | what it does / means]."""
    out = []
    rank = 0
    for ci, card in page["cards"].items():
        if _dedicated(slug, card["heading"]):
            continue
        keys = _pt_en_rows(card)
        if len(keys) < 3:
            continue
        head = ref(url, page, ci, None, None, "headshort")
        slides = [{"kind": "cover", "head": head,
                   "topic": ref(url, page, "h1", None, None, "h1topic"),
                   "subhook": ref(url, page, "sub", None, None, "subhook")}]
        for key in keys[:6]:
            slides.append({"kind": "example", "head": head,
                           "pt": ref(url, page, ci, key, 0, "whole"),
                           "en": ref(url, page, ci, key, 1, "whole")})
        slides.append({"kind": "cta"})
        p = _post("examples", "Say it like a Brazilian", slug, url, page,
                  topic_of(page), head["text"], slides, "coral", extra=str(ci))
        p["rank"] = rank
        rank += 1
        out.append(p)
    return out


def build_cheat(slug, url, page):
    """A one-chapter cheat sheet: the 'When to use' style tables, redesigned."""
    blocks = []
    for ci, card in page["cards"].items():
        h = card["heading"].lower()
        if any(x in h for x in ("classic trap", "flip test", "exceptions", "what this is about")):
            continue
        keys = _en_pt_rows(card)[:4]
        if len(keys) >= 2:
            blocks.append((ci, card, keys))
    if len(blocks) < 2:
        return []
    slides = [{"kind": "cover", "topic": ref(url, page, "h1", None, None, "h1topic")}]
    for ci, card, keys in blocks[:4]:
        slides.append({"kind": "cheat", "heading": ref(url, page, ci, None, None, "heading"),
                       "rows": [{"label": ref(url, page, ci, k, 0, "whole"),
                                 "pt": ref(url, page, ci, k, 1, "whole")} for k in keys]})
    slides.append({"kind": "cta"})
    return [_post("cheat", "Cheat sheet", slug, url, page, f"{topic_of(page)}: the cheat sheet",
                  "Save this for later.", slides, "rumo")]


# ------------------------------------------------------------ stories
STORY_MAX_SLIDES = 7      # content slides per story post
STORY_SLIDE_CHARS = 110   # Portuguese characters per slide before a new slide starts
STORY_PARTS = 2           # posts per story (part 1, part 2)


def _story_title(url, page):
    return ref(url, page, "h1", None, None, "whole")


def _story_line(url, page, sid):
    s = page["sents"][sid]
    line = {"pt": sref(url, page, sid, "pt", "whole"),
            "en": sref(url, page, sid, "en", "nogloss")}
    gl = glosses(s["en"])
    if gl:
        line["gloss"] = sref(url, page, sid, "en", "gloss", i=0)
    return line


def build_story(slug, url, page):
    """The story itself, a few sentences per slide: Portuguese, English underneath."""
    paras = {}
    for sid in page["sent_order"]:
        paras.setdefault(page["sents"][sid]["para"], []).append(sid)
    slides_of_para = []
    for pi in sorted(paras):
        slides, cur, chars = [], [], 0
        for sid in paras[pi]:
            n = len(page["sents"][sid]["pt"])
            if n > 260:          # too long for a slide: stop the paragraph here
                break
            if cur and (chars + n > STORY_SLIDE_CHARS or len(cur) == 3):
                slides.append(cur)
                cur, chars = [], 0
            cur.append(sid)
            chars += n
        if cur:
            slides.append(cur)
        if slides:
            slides_of_para.append(slides)
    parts, cur = [], []
    for slides in slides_of_para:
        if cur and len(cur) + len(slides) > STORY_MAX_SLIDES:
            parts.append(cur)
            cur = []
        cur += slides[:STORY_MAX_SLIDES]
        if len(cur) >= STORY_MAX_SLIDES:
            parts.append(cur[:STORY_MAX_SLIDES])
            cur = []
        if len(parts) >= STORY_PARTS:
            break
    if cur and len(parts) < STORY_PARTS:
        parts.append(cur)
    out = []
    title = _story_title(url, page)
    for k, part in enumerate(parts[:STORY_PARTS], 1):
        if len(part) < 2:
            continue
        slides = [{"kind": "story_cover", "title": title, "part": k}]
        for group in part:
            slides.append({"kind": "story", "lines": [_story_line(url, page, sid) for sid in group]})
        slides.append({"kind": "cta", "story": True})
        p = _post("story", f"Story {page['story']} of 40", slug, url, page,
                  title["text"], f"Part {k}. Read the Portuguese first, then check the English.",
                  slides, "paper", extra=f"part{k}")
        p["topic"] = title["text"]
        p["part"] = k
        p["rank"] = k
        out.append(p)
    return out


def build_words(slug, url, page):
    """Words the story itself explains: '(tímida = shy)' notes in its translation."""
    found = []
    for sid in page["sent_order"]:
        s = page["sents"][sid]
        for j, g in enumerate(glosses(s["en"])):
            if " = " in g and len(g) <= 80 and len(s["pt"]) <= 140:
                found.append((sid, j))
    out = []
    title = _story_title(url, page)
    chunks = [found[i:i + 5] for i in range(0, len(found), 5)]
    for k, chunk in enumerate(chunks[:3], 1):
        if len(chunk) < 3:
            continue
        slides = [{"kind": "words_cover", "title": title, "count": len(chunk)}]
        for sid, j in chunk:
            slides.append({"kind": "word", "gloss": sref(url, page, sid, "en", "gloss", i=j),
                           "pt": sref(url, page, sid, "pt", "whole"),
                           "en": sref(url, page, sid, "en", "nogloss")})
        slides.append({"kind": "cta", "story": True})
        p = _post("words", "Words from the story", slug, url, page,
                  f"{len(chunk)} words from a Portuguese story",
                  f"Story {page['story']} of 40 · level {page['level']}", slides, "sky", extra=str(k))
        p["topic"] = title["text"]
        p["rank"] = k
        out.append(p)
    return out


# ------------------------------------------------------------ Reels
REEL_THEMES = {"meaning": "tropic", "quiz": "night", "real": "sun", "story": "paper",
               "quiz3": "night", "meaning3": "tropic"}


def _reel(kind, slug, url, page, key, scene, hook, extra_topic=None):
    p = _post("reel", {"meaning": "Guess the meaning", "quiz": "Quick quiz", "real": "Textbook vs. real",
                       "story": f"Story {page.get('story')} of 40", "quiz3": "3 in a row",
                       "meaning3": "Guess the meaning"}[kind],
              slug, url, page, hook, "", [dict(scene, kind=f"reel_{kind}")], REEL_THEMES[kind],
              extra=f"{kind}-{key}", kind="reel")
    p["id"] = f"reel-{kind}-{slug}-{key}"
    p["reel_kind"] = kind
    if extra_topic:
        p["topic"] = extra_topic
    return p


def build_reels_grammar(slug, url, page):
    out = []
    page["_slug"] = slug
    for rank, prefix, ci, card, keys in _meaning_rows(page):
        hook = "Guess the meaning before the answer pops up."
        for n, key in enumerate(keys):
            p = _reel("meaning", slug, url, page, f"{ci}-{key}",
                      {"pt": ref(url, page, ci, key, 0, "whole"), "en": ref(url, page, ci, key, 1, "whole")},
                      hook)
            p["rank"] = rank * 10 + n
            out.append(p)
        for g in range(0, len(keys) - 2, 3):   # 3 in a row: a longer Reel (about 20 s)
            trio = keys[g:g + 3]
            p = _reel("meaning3", slug, url, page, f"{ci}-{g // 3 + 1}",
                      {"items": [{"pt": ref(url, page, ci, key, 0, "whole"),
                                  "en": ref(url, page, ci, key, 1, "whole")} for key in trio]},
                      "3 texts from a Brazilian friend. Do you get them?")
            p["rank"] = rank * 10 + g // 3
            out.append(p)
    items = quiz_items(slug, url, page)
    if items:
        a_lbl, b_lbl = DUELS[slug]["pair"]
        seq = [x for pair in zip(items[a_lbl], items[b_lbl]) for x in pair]
        for n, q in enumerate(seq):
            p = _reel("quiz", slug, url, page, q["key"],
                      {"q": q["q"], "full": q["full"], "word": q["word"], "why": q["why"],
                       "answer": q["answer"], "answer_card": q["answer_card"], "options": [a_lbl, b_lbl],
                       "slug": slug},
                      f"{a_lbl.title()} or {b_lbl.lower()}? You have three seconds.")
            p["rank"] = n
            out.append(p)
        qitems = [{"q": q["q"], "full": q["full"], "word": q["word"], "why": q["why"], "answer": q["answer"],
                   "answer_card": q["answer_card"], "options": [a_lbl, b_lbl]} for q in seq]
        for g in range(0, len(qitems) - 2, 3):
            p = _reel("quiz3", slug, url, page, str(g // 3 + 1), {"items": qitems[g:g + 3], "slug": slug},
                      f"3 in a row: {a_lbl.title()} or {b_lbl.lower()}?")
            p["rank"] = g // 3
            out.append(p)
    for n, (spec, ci, key, i, sl) in enumerate(_real_pairs(slug, url, page)):
        p = _reel("real", slug, url, page, f"{ci}-{key}-{i}", sl, spec["hook"])
        p["rank"] = n
        out.append(p)
    return out


def build_reels_story(slug, url, page):
    with_gloss, plain = [], []
    for sid in page["sent_order"]:
        s = page["sents"][sid]
        words = len(s["pt"].split())
        if len(s["pt"]) > 95 or words < 3 or words > 14:
            continue
        (with_gloss if glosses(s["en"]) else plain).append(sid)
    pick = with_gloss[:2]
    if len(pick) < 2:
        pick += [x for x in plain if len(x) and len(page["sents"][x]["pt"].split()) >= 5][:2 - len(pick)]
    out = []
    title = _story_title(url, page)
    for n, sid in enumerate(pick):
        scene = _story_line(url, page, sid)
        scene["title"] = title
        p = _reel("story", slug, url, page, sid, scene, "Can you read this?", extra_topic=title["text"])
        p["rank"] = n
        out.append(p)
    return out


GRAMMAR_BUILDERS = [build_quiz, build_meaning, build_real, build_traps, build_flip,
                    build_examples, build_cheat]
STORY_BUILDERS = [build_story, build_words, build_reels_story]
REEL_BUILDERS = [build_reels_grammar]


def brand_post():
    """The pinned 'Start here' post. English only, written for Rumo: approve the wording."""
    slides = [
        {"kind": "brand_cover"},
        {"kind": "brand", "big": "Brazilian Portuguese for English speakers.",
         "small": "Rumo is a complete course, A1 to B2. Lessons 1–8 are free, all the way to the A1 exam."},
        {"kind": "brand", "big": "Built by a learner, for learners.",
         "small": "Rumo was made by a Dutch learner who found textbooks too slow."},
        {"kind": "brand", "big": "What you'll find here",
         "small": "Quizzes, slang, idioms, short stories and the classic traps. "
                  "Every Portuguese line comes straight from the course."},
        {"kind": "cta"},
    ]
    return {"id": "brand-start-here", "format": "brand", "kind": "carousel", "series": "Start here",
            "theme": "rumo", "slug": None, "url": None, "level": "A1", "chapter": 0, "story": None,
            "topic": "Rumo", "hook": "Learning Brazilian Portuguese? Start here.",
            "sub": "What this account is, and the free way in.",
            "slides": slides, "status": "extracted", "written": True}


# ------------------------------------------------------------ posting order
# One slot a day, every other one a Reel (PATTERN). A slot draws from its category; within
# a category the formats take turns (weighted by results once there are some).
CATEGORY = {"quiz": "challenge", "traps": "challenge", "flip": "challenge",
            "meaning": "phrase", "real": "phrase",
            "examples": "save", "cheat": "save",
            "story": "story", "words": "words", "reel": "reel", "brand": "brand"}
PATTERN = ["reel", "story", "reel", "phrase", "reel", "save", "reel", "challenge", "reel", "words"]
FALLBACK = {"challenge": ["phrase", "save", "story"], "phrase": ["challenge", "save", "words"],
            "save": ["challenge", "phrase", "story"], "story": ["words", "save"],
            "words": ["story", "save"], "reel": ["reel"]}
ROT_ORDER = ["quiz", "traps", "flip", "meaning", "real", "examples", "cheat", "story", "words",
             "reel:quiz", "reel:story", "reel:meaning", "reel:quiz3", "reel:real", "reel:meaning3"]
PLANNABLE = ("extracted", "rendered", "requeue")


def rot_key(p):
    return f"reel:{p['reel_kind']}" if p.get("kind") == "reel" else p["format"]


def _src_key(p):
    return (LEVEL_ORDER.get(p.get("level"), 9), p.get("story") or 0, p.get("chapter") or 0, p.get("slug") or "")


def _spread(posts):
    """Take turns between source pages so the same chapter or story never comes twice in a row."""
    groups = {}
    for p in sorted(posts, key=lambda p: (_src_key(p), p.get("rank", 0), p["id"])):
        groups.setdefault(p.get("slug"), []).append(p)
    order = sorted(groups, key=lambda s: _src_key(groups[s][0]))
    out = []
    while any(groups[s] for s in order):
        for s in order:
            if groups[s]:
                out.append(groups[s].pop(0))
    return out


def plan_order(state, weights=None):
    """Give every post that is not booked yet its place in the queue.

    Booked and published posts keep their place. The rest follow the weekly
    pattern; `weights` (from the results of earlier posts) make the strongest
    formats come round more often. Without weights every format takes turns.
    """
    weights = weights or {}
    posts = state["posts"]
    fixed = [p for p in posts if p.get("status") in ("scheduled", "published")]
    todo = [p for p in posts if p.get("status") in PLANNABLE and p not in fixed]
    seq = []
    pools = {}
    for p in todo:
        pools.setdefault(CATEGORY.get(p["format"], "save"), {}).setdefault(rot_key(p), []).append(p)
    for cat in pools:
        for k in pools[cat]:
            pools[cat][k] = _spread(pools[cat][k])
    credit = {}

    def take(cat, avoid=None):
        avail = [k for k in ROT_ORDER if pools.get(cat, {}).get(k)]
        if avoid in avail and len(avail) > 1:
            avail.remove(avoid)
        if not avail:
            return None
        tot = sum(weights.get(k, 1.0) for k in avail)
        for k in avail:
            credit[k] = credit.get(k, 0.0) + weights.get(k, 1.0)
        best = max(avail, key=lambda k: (credit[k], -ROT_ORDER.index(k)))
        credit[best] -= tot
        return pools[cat][best].pop(0)

    main = [p for p in fixed if not p.get("trial")]   # trial Reels sit outside the daily pattern
    n_fixed = len(main)
    if not [p for p in main if not p.get("written")]:
        # Nothing but (perhaps) the 'Start here' post has gone out: the launch trio comes first.
        for cat, fmt in (("brand", "brand"), ("challenge", "quiz"), ("phrase", "meaning")):
            lst = pools.get(cat, {}).get(fmt)
            if lst:
                seq.append(lst.pop(0))
        n_fixed = len(main) + len(seq)
    slot = max(0, n_fixed - 3)
    prev = rot_key(seq[-1]) if seq else (rot_key(max(main, key=lambda p: p.get("order", 0))) if main else None)
    while True:
        cat = PATTERN[slot % len(PATTERN)]
        got = None
        for c in [cat] + FALLBACK.get(cat, []):
            got = take(c, avoid=prev)
            if got:
                break
        if not got:   # every pool that this slot may use is empty: try anything left
            for c in list(pools):
                got = take(c, avoid=prev)
                if got:
                    break
        if not got:
            break
        seq.append(got)
        prev = rot_key(got)
        slot += 1
    start = max([p.get("order", 0) for p in fixed] or [0])
    for i, p in enumerate(seq, 1):
        p["order"] = start + i
    rest = [p for p in posts if p not in fixed and p not in seq]
    for i, p in enumerate(rest, len(seq) + start + 1):
        p["order"] = i   # missed / unfit posts: kept on record at the end
    state["posts"] = sorted(posts, key=lambda p: p.get("order", 10 ** 6))
    return state


# ------------------------------------------------------------ captions
CAPTION_FORMAT = {
    "quiz": "4-question quiz", "meaning": "guess the meaning", "traps": "the classic traps",
    "real": "textbook vs. real", "flip": "one word, two meanings", "cheat": "cheat sheet",
}
ENGAGE = {
    "quiz": "How many did you get right? Tell us in the comments.",
    "meaning": "How many did you know? Tell us in the comments.",
    "real": "Which one had you heard before?",
    "traps": "Which one used to catch you out?",
    "flip": "Did you know this one?",
    "examples": "Which one will you use first?",
    "story": "How much did you understand before reading the English?",
    "words": "Which word was new to you?",
    "reel:meaning": "Did you know it before the answer came up?",
    "reel:quiz": "Did you get it before the answer?",
    "reel:quiz3": "How many of the 3 did you get?",
    "reel:meaning3": "How many of the 3 did you get?",
    "reel:story": "Could you read it before the English came in?",
    "reel:real": "Had you heard this one?",
}
# A send prompt only where sending is natural, written for the situation (sends to
# non-followers are what Instagram weighs most); a save prompt for reference posts.
SEND = {
    "quiz": "Send this to your study buddy and compare scores.",
    "reel:quiz": "Send this to your study buddy and compare scores.",
    "reel:quiz3": "Send this to your study buddy and compare scores.",
    "meaning": "Know someone learning Portuguese? Send them this one.",
    "reel:meaning": "Know someone learning Portuguese? Send them this one.",
    "reel:meaning3": "Know someone learning Portuguese? Send them this one.",
    "real": "Send this to someone who learned from a textbook.",
    "reel:real": "Send this to someone who learned from a textbook.",
    "flip": "Send this to someone who mixes these up.",
    "traps": "Send this to someone who mixes these up.",
}
SAVE = "Save this for your next study session."
SAVE_FORMATS = ("examples", "cheat", "words", "story")
BASE_TAGS = ["#brazilianportuguese", "#learnportuguese"]
TAG_POOLS = {   # specific tags only (broad ones such as #languagelearning are left out)
    "grammar": ["#portuguesegrammar", "#portuguesebrasileiro", "#studyportuguese", "#learnbrazilianportuguese"],
    "phrase": ["#brazilianslang", "#portuguesebrasileiro", "#portuguesephrases", "#learnbrazilianportuguese"],
    "story": ["#portuguesereading", "#gradedreader", "#portuguesebrasileiro", "#learnbrazilianportuguese"],
    "brand": ["#portuguesebrasileiro", "#learnbrazilianportuguese", "#portuguesegrammar"],
}


def send_line(p):
    """The send (or save) prompt for this post, or None."""
    k = rot_key(p)
    if k in SEND:
        return SEND[k]
    if p["format"] in SAVE_FORMATS:
        return SAVE
    return None


def add_about(post, page, url):
    """Attach the page's own one-line description (checked by the gate) to a post."""
    if not post.get("slides") or page is None:
        return post
    if page.get("kind") == "story":
        r = ref(url, page, "sub", None, None, "storysub")
    else:
        r = ref(url, page, "sub", None, None, "subhook")
    if r["text"] and not r["text"].startswith("⁇"):
        post["slides"][0]["about"] = r
    return post


def _tag_pool(p):
    if p["format"] == "brand":
        return "brand"
    if p["format"] in ("story", "words") or p.get("reel_kind") == "story":
        return "story"
    if p["format"] in ("meaning", "real") or p.get("reel_kind") in ("meaning", "real", "meaning3"):
        return "phrase"
    return "grammar"


def hashtags(p, cfg=None):
    pool = TAG_POOLS[_tag_pool(p)]
    n = p.get("order", 0)
    # Instagram allows 5 hashtags; a '#START'-style keyword in the call to action counts as one
    k = 2 if cfg and str(cfg.get("keyword", "")).startswith("#") and cfg.get("cta_mode") == "comment" else 3
    picks = [pool[(n + i) % len(pool)] for i in range(k)]
    return " ".join(BASE_TAGS + picks)


def cta_line(cfg, network="instagram", mode=None):
    mode = mode or cfg["cta_mode"]
    if network == "tiktok":
        return "Free 60-second start: rumopt.com/start (8 words, 4 questions, no sign-up)."
    if mode == "comment":
        return (f"Want the free 60-second start? Comment {cfg['keyword']} and we'll DM you the link: "
                f"8 words, 4 questions, no sign-up. Or tap the link in bio.")
    return "Free 60-second start: 8 words, 4 questions, no sign-up. Link in bio."


def first_line(p):
    f = p["format"]
    if f == "brand":
        return "Learn Brazilian Portuguese — start here"
    if f == "story":
        return f"{p['topic']} — a short {p['level']} story in Brazilian Portuguese, part {p.get('part', 1)}"
    if f == "words":
        return f"{p['hook']}: “{p['topic']}” ({p['level']})"
    if f == "examples":
        return f"{p['topic']} in Brazilian Portuguese — {p['sub']}"
    if f == "reel":
        k = p["reel_kind"]
        if k == "story":
            art = "an" if str(p["level"]).startswith("A") else "a"
            return f"Can you read this? A line from “{p['topic']}”, {art} {p['level']} story in Brazilian Portuguese"
        return f"{p['topic']} in Brazilian Portuguese — " + {
            "meaning": "guess the meaning", "quiz": "quick quiz", "real": "textbook vs. real",
            "quiz3": "3-question quiz", "meaning3": "guess the meaning"}[k]
    return f"{p['topic']} in Brazilian Portuguese — {CAPTION_FORMAT[f]}"


def caption_for(p, cfg, network="instagram", mode=None):
    """Keyword-first first line (reads like a search), what the post is, the page's own
    one-line description, an honest question, a send or save prompt, the call to action."""
    parts = [first_line(p)]
    if p["format"] == "reel":
        parts.append(p["hook"])
    elif p["format"] == "examples":
        parts.append(p["slides"][0]["subhook"]["text"] or p["sub"])
    elif p["format"] in ("story", "words"):
        parts.append(p["sub"])
    else:
        parts.append((p["hook"] + " " + p["sub"]).strip())
    about = (p["slides"][0].get("about") or {}).get("text") if p.get("slides") else None
    if about and about not in parts[-1]:
        if p["format"] in ("story", "words") or p.get("reel_kind") == "story":
            parts.append(f"In this story: {about}")
        else:
            parts.append(about)
    q = ENGAGE.get(rot_key(p))
    if q:
        parts.append(q)
    parts.append(send_line(p))
    if p["format"] in ("story", "words") or p.get("reel_kind") == "story":
        parts.append("All 40 stories are free to read on rumopt.com.")
    parts.append(cta_line(cfg, network, mode or p.get("cta_plan")))
    parts.append(hashtags(p, cfg))
    return "\n\n".join(x for x in parts if x)

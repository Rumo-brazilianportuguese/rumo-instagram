"""Read the free grammar chapters and the 40 graded stories, and turn them into
a pool of post plans.

Every string stored here is copied from the page. Nothing is written,
translated or corrected. The gate (rumo_gate.py) re-reads the live pages
and refuses anything that does not match.
"""
import html as htmllib
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from rumo_common import CACHE_DIR, SITE, http_get, norm, say, site_url

SKIP_HEADINGS = ("all 60 grammar chapters", "all 40 portuguese short stories")
MIN_GRAMMAR = 50     # the site has 60; fewer means the sitemap is broken
MIN_STORIES = 30     # the site has 40


# ---------------------------------------------------------------- parsing
def _rich(node) -> str:
    """Cell text as safe HTML that keeps only <b> emphasis."""
    out = []

    def walk(n):
        if isinstance(n, NavigableString):
            out.append(htmllib.escape(str(n), quote=False))
        elif isinstance(n, Tag):
            if n.name in ("b", "strong"):
                out.append("<b>")
                for c in n.children:
                    walk(c)
                out.append("</b>")
            elif n.name == "br":
                out.append(" ")
            else:
                for c in n.children:
                    walk(c)

    walk(node)
    s = "".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("<b> ", " <b>").replace(" </b>", "</b> ")
    return re.sub(r"\s+", " ", s).strip()


def _plain(rich: str) -> str:
    return norm(re.sub(r"<[^>]+>", "", rich))


def parse_page(page_html: str) -> dict:
    """Parse a grammar chapter or a story page.

    Card, row and sentence numbers come from document order and ids, so the
    gate can find exactly the same text again on the live page.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    for b in soup.find_all("button"):
        b.decompose()
    # A line break is a space; inline tags such as <b> are NOT (get_text(" ")
    # would turn "foo<b>bar</b>" into "foo bar").
    for br in soup.find_all("br"):
        br.replace_with(" ")
    lesson = ""
    lb = soup.select_one("header h1 .lbadge")
    if lb:
        lesson = norm(lb.get_text(""))
        lb.decompose()

    def text_of(sel):
        el = soup.select_one(sel)
        return norm(el.get_text("")) if el else ""

    badge = text_of("header .badge")
    m = re.search(r"CHAPTER\s+(\d+)\s+OF\s+(\d+)", badge, re.I)
    ms = re.search(r"STORY\s+(\d+)\s+OF\s+(\d+)", badge, re.I)
    lv = re.search(r"\b(A1|A2|B1|B2)\b", badge)
    page = {
        "badge": badge,
        "kind": "story" if soup.select_one("#story-text") else "grammar",
        "chapter": int(m.group(1)) if m else None,
        "story": int(ms.group(1)) if ms else None,
        "level": lv.group(1) if lv else None,
        "title": text_of("header h1"),
        "lesson": lesson,
        "sub": text_of("header .sub"),
        "cards": {},
        "sents": {},
        "sent_order": [],
        # Whole visible text, used by the gate as a second, independent check.
        "alltext": norm(soup.get_text("")),
    }
    story = soup.select_one("#story-text")
    if story:
        for pi, para in enumerate(story.find_all("p", recursive=False)):
            for sp in para.select("span.sent"):
                sid = sp.get("id")
                if not sid:
                    continue
                page["sents"][sid] = {"pt": norm(sp.get_text("")), "en": norm(sp.get("data-tr", "")),
                                      "para": pi}
                page["sent_order"].append(sid)
        return page
    main = soup.select_one("main") or soup
    for ci, card in enumerate(main.select("div.card")):
        classes = card.get("class") or []
        h3 = card.find("h3")
        heading = norm(h3.get_text("")) if h3 else ""
        if "cta" in classes or heading.lower().startswith(SKIP_HEADINGS):
            continue
        rows = {}
        for ri, tr in enumerate(card.select("table tr")):
            cells = []
            for td in tr.find_all(["td", "th"], recursive=False):
                rich = _rich(td)
                text = norm(td.get_text(""))
                if _plain(rich) != text:
                    rich = htmllib.escape(text, quote=False)
                role = "pt" if "pt" in (td.get("class") or []) else "en"
                cells.append({"role": role, "text": text, "rich": rich})
            if cells:
                rows[f"t{ri}"] = cells
        for ri, cr in enumerate(card.select("div.conjrow")):
            cells = []
            for sp in cr.find_all("span", recursive=False):
                text = norm(sp.get_text(""))
                role = "pt" if "pt" in (sp.get("class") or []) else "en"
                cells.append({"role": role, "text": text,
                              "rich": htmllib.escape(text, quote=False)})
            if cells:
                rows[f"c{ri}"] = cells
        page["cards"][ci] = {"heading": heading, "rows": rows}
    return page


# ------------------------------------------------------------------ sources
def _sitemap():
    r = http_get(SITE + "/sitemap.xml")
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)


def grammar_urls(locs=None):
    return [l for l in (locs or _sitemap()) if "/Grammar/" in l]


def story_urls(locs=None):
    return [l for l in (locs or _sitemap()) if "/Stories/" in l]


def slug_of(loc: str) -> str:
    return loc.rstrip("/").split("/")[-1].replace(".html", "")


def fetch_page(loc: str, refresh: bool = False) -> str:
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"{slug_of(loc)}.html"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8")
    text = http_get(site_url(loc)).text
    f.write_text(text, encoding="utf-8")
    return text


# ------------------------------------------------------------------ main
def extract(state: dict) -> dict:
    """Build the pool of posts from the grammar chapters and the stories.

    Safe to rerun after the site changes: posts that are already scheduled or
    published keep their record; everything else is rebuilt from the live pages.
    """
    from rumo_formats import (GRAMMAR_BUILDERS, REEL_BUILDERS, STORY_BUILDERS, add_about, brand_post,
                              config, excluded, plan_order)

    cfg = config()
    locs = _sitemap()
    g_urls, s_urls = grammar_urls(locs), story_urls(locs)
    say(f"Sitemap: {len(g_urls)} grammar chapters (expected 60), {len(s_urls)} stories (expected 40).")
    if len(g_urls) < MIN_GRAMMAR:
        raise SystemExit(f"EXPECTED 60 grammar chapters, found {len(g_urls)}")
    if len(s_urls) < MIN_STORIES:
        raise SystemExit(f"EXPECTED 40 stories, found {len(s_urls)}")
    posts = []
    for n, loc in enumerate(g_urls, 1):
        slug = slug_of(loc)
        page = parse_page(fetch_page(loc, refresh=True))
        made = []
        for build in GRAMMAR_BUILDERS + REEL_BUILDERS:
            made += build(slug, loc, page)
        posts += [add_about(p, page, loc) for p in made]
    for n, loc in enumerate(s_urls, 1):
        slug = slug_of(loc)
        page = parse_page(fetch_page(loc, refresh=True))
        if page["kind"] != "story" or not page["sents"]:
            say(f"  story page without sentences, skipped: {slug}")
            continue
        for build in STORY_BUILDERS:
            posts += [add_about(p, page, loc) for p in build(slug, loc, page)]
    before = len(posts)
    posts = [p for p in posts if not excluded(p, cfg)]
    if before != len(posts):
        say(f"  left out {before - len(posts)} posts that contain a line listed under 'exclude' in config.json")
    seen, uniq = set(), []
    for p in posts:
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)
    posts = [brand_post()] + uniq

    old = {p["id"]: p for p in state.get("posts", [])}
    merged = []
    def held(o):   # out of our hands, or half-posted (the next run finishes it): keep exactly as it is
        return o.get("status") in ("scheduled", "published", "removed", "rejected") or o.get("pending")

    for p in posts:
        o = old.get(p["id"])
        if o and held(o):
            merged.append(o)
            continue
        if o:
            for k in ("stats", "cycle", "published_at", "ig_media"):
                if k in o:
                    p[k] = o[k]
        merged.append(p)
    for pid, o in old.items():   # a post whose source disappeared stays on record
        if held(o) and pid not in seen and pid != "brand-start-here":
            o["orphan"] = True
            merged.append(o)
    state["posts"] = merged
    plan_order(state, weights=state.get("weights"))
    counts = {}
    for p in state["posts"]:
        counts[p["format"]] = counts.get(p["format"], 0) + 1
    say("  pool: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        + f"  (total {len(state['posts'])})")
    if len(state["posts"]) < 60:
        raise SystemExit(f"Only {len(state['posts'])} posts could be built (need at least 60).")
    return state

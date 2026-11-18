"""Draw the carousel slides (1080 x 1350 JPEG) and the Reels (1080 x 1920 MP4)
with a headless browser.

Design: one palette per series so each series is recognisable at a glance;
Bricolage Grotesque for headlines, Fraunces for the Portuguese, Inter for the
English (all SIL Open Font Licence, bundled in assets/fonts). Text is never
cut: a slide that does not fit is shrunk in steps; if it still does not fit,
the post is left out (status 'unfit') and the next post takes its place.
"""
import base64
import html as htmllib
import re
import shutil
import time

from rumo_common import PREVIEW_DIR, ROOT, say
from rumo_formats import CHECK, config, send_line

W, H = 1080, 1350
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
SCALES = (1.0, 0.9, 0.8, 0.72, 0.64)

THEMES = {
    # series            bg        fg        soft      accent    on-accent  alt       card      line
    "night":  dict(bg="#102A43", fg="#F0F4F8", soft="#9FB3C8", acc="#F7B32B", on="#102A43",
                   alt="#2EC4B6", card="#183A5E", line="#2A4D73"),
    "tropic": dict(bg="#0B3D2E", fg="#FFF8EC", soft="#A9CBB8", acc="#FFC93C", on="#0B3D2E",
                   alt="#FF6B4A", card="#13513D", line="#1F6A51"),
    "sun":    dict(bg="#FFF6E5", fg="#14213D", soft="#5B6478", acc="#00875A", on="#FFFFFF",
                   alt="#E5484D", card="#FFFFFF", line="#EADFCB", hi="#FFD23F"),
    "rumo":   dict(bg="#3C6A4C", fg="#FFF8EC", soft="#D3E3D7", acc="#FFC93C", on="#24412E",
                   alt="#FF8A65", card="#33603F", line="#55836A"),
    "paper":  dict(bg="#F7F1E3", fg="#1F1A14", soft="#6B5E4B", acc="#C2410C", on="#FFFFFF",
                   alt="#0F766E", card="#FFFDF7", line="#E4D7BD", hi="#FCD34D"),
    "sky":    dict(bg="#EAF2FF", fg="#0F1B3D", soft="#4A5A80", acc="#2F5BEA", on="#FFFFFF",
                   alt="#F97316", card="#FFFFFF", line="#C9D8F5", hi="#FFE066"),
    "coral":  dict(bg="#2B1B3D", fg="#FFF4EC", soft="#CDB8D6", acc="#FF8A5B", on="#2B1B3D",
                   alt="#7DD3FC", card="#3A2752", line="#523E6E"),
}


def _theme_css():
    out = []
    for name, t in THEMES.items():
        hi = t.get("hi", t["acc"])
        out.append(f".t-{name}{{--bg:{t['bg']};--fg:{t['fg']};--soft:{t['soft']};--acc:{t['acc']};"
                   f"--on:{t['on']};--alt:{t['alt']};--card:{t['card']};--line:{t['line']};--hi:{hi}}}")
    return "\n".join(out)


def font_face():
    faces = [("Bricolage", "BricolageGrotesque.ttf", "200 800"),
             ("Fraunces", "Fraunces.ttf", "100 900"),
             ("Inter", "Inter.ttf", "100 900")]
    css = []
    for fam, f, w in faces:
        p = FONTS / f
        if p.exists():
            css.append(f"@font-face{{font-family:'{fam}';font-weight:{w};"
                       f"src:url('{p.resolve().as_uri()}') format('truetype');}}")
    return "".join(css)


def mark_uri():
    svg = (ASSETS / "mark.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()


BASE_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;overflow:hidden;background:#000}
#root{--s:1}
.slide{width:1080px;height:1350px;position:relative;overflow:hidden;display:flex;flex-direction:column;
  padding:84px 92px 70px;background:var(--bg);color:var(--fg);
  font-family:'Inter','Segoe UI',system-ui,sans-serif;font-optical-sizing:auto}
.deco{position:absolute;pointer-events:none}
.deco.diamond{width:820px;height:820px;right:-330px;top:150px;border:44px solid var(--acc);opacity:.12;transform:rotate(45deg);border-radius:60px}
.top{display:flex;align-items:center;gap:16px;position:relative;z-index:1}
.pill{font-family:'Bricolage',sans-serif;font-weight:700;font-size:30px;letter-spacing:.09em;text-transform:uppercase;
  background:var(--acc);color:var(--on);padding:12px 24px 13px;border-radius:999px;white-space:nowrap}
.lvl{font-family:'Bricolage',sans-serif;font-weight:700;font-size:30px;letter-spacing:.06em;color:var(--soft);
  border:3px solid var(--line);padding:9px 18px;border-radius:999px}
.body{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:center;gap:calc(40px*var(--s));
  position:relative;z-index:1}
.foot{display:flex;align-items:center;gap:16px;position:relative;z-index:1;font-family:'Bricolage',sans-serif;
  font-weight:700;font-size:34px;color:var(--fg)}
.foot img{width:54px;height:54px;border-radius:12px}
.bar{flex:1;display:flex;gap:8px;margin-left:24px}
.bar i{flex:1;height:8px;border-radius:4px;background:var(--line)}
.bar i.on{background:var(--acc)}
.hook{font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(124px*var(--s));line-height:1.0;
  letter-spacing:-.025em;text-wrap:balance}
.hook.mid{font-size:calc(104px*var(--s))}
.hook.sm{font-size:calc(88px*var(--s))}
.sub{font-size:calc(46px*var(--s));line-height:1.32;color:var(--soft);max-width:860px;text-wrap:pretty}
.swipe{align-self:flex-end;font-family:'Bricolage',sans-serif;font-weight:800;font-size:38px;background:var(--fg);
  color:var(--bg);padding:16px 30px;border-radius:999px;position:relative;z-index:1}
.label{font-family:'Bricolage',sans-serif;font-weight:700;font-size:calc(32px*var(--s));letter-spacing:.11em;
  text-transform:uppercase;color:var(--acc)}
.pt{font-family:'Fraunces',Georgia,serif;font-weight:600;font-size:calc(92px*var(--s));line-height:1.1;
  letter-spacing:-.01em;text-wrap:balance;font-variation-settings:"WONK" 0,"SOFT" 30;
  font-feature-settings:"ss01" 0,"ss02" 0,"dlig" 0}
.pt b{font-weight:800;color:var(--acc)}
.ans .pt b,.bubble .pt b,.flipcard .pt b{color:inherit}
.pt .ln{display:block}
.pt.l{font-size:calc(108px*var(--s))}
.pt.m{font-size:calc(76px*var(--s))}
.pt.s{font-size:calc(62px*var(--s))}
.pt .gl,.gl{font-family:'Inter',sans-serif;font-weight:400;font-size:.5em;color:var(--soft);letter-spacing:0}
.en{font-size:calc(48px*var(--s));line-height:1.34;color:var(--soft);text-wrap:pretty}
.en.fg{color:var(--fg)}
.en.s{font-size:calc(38px*var(--s))}
.blank{display:inline-block;min-width:3.1em;border-bottom:.11em solid var(--acc);height:.8em;vertical-align:baseline}
.opts{display:flex;gap:28px}
.opt{flex:1;text-align:center;font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(76px*var(--s));
  padding:calc(30px*var(--s)) 10px;border:5px solid var(--fg);border-radius:30px}
.hint{font-family:'Bricolage',sans-serif;font-weight:700;font-size:34px;color:var(--soft)}
.ans{background:var(--acc);color:var(--on);border-radius:44px;padding:calc(56px*var(--s)) calc(60px*var(--s));
  display:flex;flex-direction:column;gap:calc(26px*var(--s))}
.ans .verdict{font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(64px*var(--s));letter-spacing:.02em}
.ans .pt mark{background:none;color:inherit;text-decoration:underline;text-decoration-thickness:.09em;text-underline-offset:.12em}
.ans .en{color:var(--on);opacity:.85}
.chips{display:flex;gap:26px;flex-wrap:wrap}
.chip{font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(84px*var(--s));padding:18px 40px;border-radius:26px;
  background:var(--card);border:4px solid var(--line)}
.chip.a{background:var(--acc);color:var(--on);border-color:var(--acc)}
.chathead{display:flex;align-items:center;gap:20px;font-size:36px;color:var(--soft)}
.chathead .av{width:72px;height:72px;border-radius:50%;background:var(--acc);color:var(--on);display:grid;place-items:center;
  font-family:'Bricolage',sans-serif;font-weight:800;font-size:38px}
.bubble{align-self:flex-start;max-width:900px;background:#FFFFFF;color:#13241C;border-radius:46px 46px 46px 14px;
  padding:calc(38px*var(--s)) calc(48px*var(--s))}
.bubble .pt{font-size:calc(84px*var(--s))}
.bubble .gl{color:#5B6B63}
.reply{align-self:flex-end;max-width:900px;background:var(--acc);color:var(--on);border-radius:46px 46px 14px 46px;
  padding:calc(34px*var(--s)) calc(46px*var(--s));font-size:calc(50px*var(--s));line-height:1.3;font-weight:500}
.time{font-size:26px;color:#7A8A82;margin-top:10px;font-family:'Inter',sans-serif}
.typing{display:flex;gap:14px;padding:12px 6px}
.typing i{width:22px;height:22px;border-radius:50%;background:#9AB0A5}
.panel{border-radius:40px;padding:calc(40px*var(--s)) calc(48px*var(--s));display:flex;flex-direction:column;gap:14px}
.panel.muted{background:transparent;border:4px dashed var(--line)}
.panel.muted .pt{color:var(--soft)}
.panel.bright{background:var(--card);border:5px solid var(--acc)}
.panel.bright .pt{color:var(--fg)}
.down{font-family:'Bricolage',sans-serif;font-weight:800;font-size:64px;color:var(--acc);text-align:center;line-height:1}
.pairs{display:flex;flex-direction:column;gap:calc(26px*var(--s))}
.tick{width:calc(120px*var(--s));height:calc(120px*var(--s));border-radius:50%;background:var(--acc);position:relative;flex:none}
.tick::after{content:"";position:absolute;left:36%;top:19%;width:24%;height:46%;border:solid var(--on);
  border-width:0 calc(14px*var(--s)) calc(14px*var(--s)) 0;transform:rotate(45deg)}
.big-num{font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(300px*var(--s));line-height:.85;color:var(--acc)}
.flipcard{background:var(--card);border-radius:36px;padding:calc(36px*var(--s)) calc(44px*var(--s));display:flex;flex-direction:column;gap:12px;
  border:4px solid var(--line)}
.flipcard mark,.mk{background:var(--hi);color:#14213D;padding:0 .12em;border-radius:.12em}
.vs{font-family:'Bricolage',sans-serif;font-weight:800;font-size:44px;color:var(--soft);text-align:center}
.cheat{display:flex;flex-direction:column;gap:calc(22px*var(--s))}
.cheat .row{display:flex;flex-direction:column;gap:6px;padding-top:calc(20px*var(--s));border-top:3px solid var(--line)}
.cheat .lab{font-family:'Bricolage',sans-serif;font-weight:700;font-size:calc(32px*var(--s));letter-spacing:.06em;color:var(--acc);text-transform:uppercase}
.cheat .pt{font-size:calc(64px*var(--s))}
.ctab{display:flex;flex-direction:column;gap:calc(34px*var(--s))}
.kw{display:inline-block;background:var(--acc);color:var(--on);font-family:'Bricolage',sans-serif;font-weight:800;
  padding:4px 26px 10px;border-radius:22px}
.small{font-size:calc(38px*var(--s));color:var(--soft);line-height:1.35}
.send{font-family:'Bricolage',sans-serif;font-weight:700;font-size:calc(40px*var(--s));color:var(--fg);
  border:4px solid var(--line);border-radius:999px;padding:16px 30px;align-self:flex-start}
.brandmark{width:220px;height:220px;border-radius:48px}
.lines{display:flex;flex-direction:column;gap:calc(44px*var(--s))}
.line{display:flex;flex-direction:column;gap:calc(12px*var(--s))}
.line .pt{font-size:calc(66px*var(--s));line-height:1.14;text-wrap:pretty}
.line .en{font-size:calc(38px*var(--s));line-height:1.3}
.glo{align-self:flex-start;font-family:'Inter',sans-serif;font-weight:600;font-size:calc(30px*var(--s));color:var(--fg);
  background:var(--hi);padding:6px 18px;border-radius:12px}
.story-title{font-family:'Fraunces',Georgia,serif;font-weight:700;font-size:calc(116px*var(--s));line-height:1.02;
  letter-spacing:-.02em;color:var(--fg);text-wrap:balance;font-variation-settings:"WONK" 1,"SOFT" 60}
.page-edge{position:absolute;left:0;top:0;bottom:0;width:26px;background:var(--acc);opacity:.85}
.wordbig{font-family:'Fraunces',Georgia,serif;font-weight:700;font-size:calc(118px*var(--s));line-height:1.02;color:var(--acc);
  letter-spacing:-.02em;font-variation-settings:"WONK" 1,"SOFT" 50}
.wordeq{font-family:'Inter',sans-serif;font-weight:500;font-size:calc(52px*var(--s));line-height:1.25;color:var(--fg)}
.ctx{background:var(--card);border:4px solid var(--line);border-radius:36px;padding:calc(34px*var(--s)) calc(42px*var(--s));
  display:flex;flex-direction:column;gap:calc(12px*var(--s))}
.ctx .pt{font-size:calc(58px*var(--s))}
.ctx .en{font-size:calc(38px*var(--s))}
"""


def esc(s):
    return htmllib.escape(s or "", quote=False)


def _gloss(t):
    return re.sub(r"\s*\(([^()<>]*)\)\s*$", r' <span class="gl">(\1)</span>', t)


def pt_html(text, rich=None):
    """Portuguese text: strip a leading ✅, one line per " · " example, a bracketed
    English gloss set lighter. `rich` (the page's own <b> emphasis, checked by the
    gate) is used when it matches the text."""
    src = rich if rich and re.sub(r"<[^>]+>", "", rich) == esc(text) else esc(text)
    if src.startswith(CHECK):
        src = src[len(CHECK):].strip()
    src = src.replace("___", '<span class="blank"></span>')
    parts = [p.strip() for p in src.split(" · ") if p.strip()]
    if len(parts) > 1:
        return "".join(f'<span class="ln">{_gloss(p)}</span>' for p in parts)
    return _gloss(src)


def mark_word(sentence, word, cls=None):
    """Highlight `word` as a whole word (never inside another word: 'é' in 'café')."""
    from rumo_formats import token_re
    m = token_re([word]).search(sentence) if word else None
    if not m:
        return esc(sentence)
    tag = f'<mark class="{cls}">' if cls else "<mark>"
    return esc(sentence[:m.start()]) + tag + esc(m.group(0)) + "</mark>" + esc(sentence[m.end():])


def gloss_parts(g):
    """'tímida = shy' -> ('tímida', 'shy'). Only for display; the text is the page's."""
    if g.count(" = ") == 1 and ";" not in g:
        a, b = g.split(" = ")
        return a.strip(), b.strip()
    return None, g


def word_in_sentence(word, sentence):
    """The glossed word as it appears in the sentence (drops a leading article)."""
    if not word:
        return None
    from rumo_formats import token_re
    for w in (word, re.sub(r"^(o|a|os|as|um|uma)\s+", "", word, flags=re.I)):
        w = w.rstrip("?!.")
        if w and token_re([w]).search(sentence):
            return w
    return None


def diff_marks(a, b):
    ta, tb = a.split(" "), b.split(" ")
    sb, sa = set(tb), set(ta)
    ma = " ".join(f"<mark>{esc(w)}</mark>" if w not in sb else esc(w) for w in ta)
    mb = " ".join(f"<mark>{esc(w)}</mark>" if w not in sa else esc(w) for w in tb)
    return ma, mb


def _frame(post, i, n, inner, mark, deco="", top=None):
    theme = post["theme"]
    if top is None:
        top = f'<span class="pill">{esc(post["series"])}</span><span class="lvl">{esc(post["level"] or "")}</span>'
    bars = "".join(f'<i class="{"on" if k <= i else ""}"></i>' for k in range(1, n + 1))
    return (f'<div class="slide t-{theme}">{deco}<div class="top">{top}</div>'
            f'<div class="body">{inner}</div>'
            f'<div class="foot"><img src="{mark}" alt=""><span>rumo</span><div class="bar">{bars}</div></div></div>')


def _cover(post, s):
    f = post["format"]
    proof = ""
    hook = f'<div class="hook">{esc(post["hook"])}</div><div class="sub">{esc(post["sub"])}</div>'
    if f == "quiz":
        a, b = s["chips"]
        proof = f'<div class="chips"><span class="chip a">{esc(a)}</span><span class="chip">{esc(b)}</span></div>'
    elif f == "meaning":
        proof = ('<div class="chathead"><span class="av">BR</span><span>Your Brazilian friend</span></div>'
                 '<div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div>')
    elif f == "traps":
        proof = f'<div style="display:flex;align-items:center;gap:36px"><span class="tick"></span><span class="big-num">{s["count"]}</span></div>'
    elif f == "real":
        first = next((x for x in post["slides"] if x["kind"] == "real"), None)
        if first:
            p = first["pairs"][0]
            proof = (f'<div class="pt m" style="color:var(--soft)">{pt_html(p["left"]["text"])} '
                     f'<span style="color:var(--acc)">→</span> '
                     f'<span style="color:var(--fg)">{pt_html(p["right"]["text"])}</span></div>')
    elif f == "flip":
        proof = '<div class="chips"><span class="chip">1 word</span><span class="chip a">2 meanings</span></div>'
    elif f == "cheat":
        proof = '<div class="label">Save this</div>'
    elif f == "examples":
        hook = (f'<div class="label">{esc(s["head"]["text"])}</div>'
                f'<div class="hook">{esc(s["topic"]["text"])}</div>'
                f'<div class="sub">{esc(s["subhook"]["text"])}</div>')
    return f'{hook}{proof}<span class="swipe">Swipe →</span>'


def _cta(post, cfg, mode=None, story=False):
    mode = mode or cfg["cta_mode"]
    if mode == "comment":
        ask = (f'<div class="hook mid">Comment <span class="kw">{esc(cfg["keyword"])}</span></div>'
               '<div class="en fg">and we\'ll DM you the free 60-second start.</div>')
        small = "8 words · 4 questions · no sign-up · or tap the link in bio"
    elif mode == "url":   # TikTok: no comment-to-DM, and no clickable bio link before 1,000 followers
        ask = ('<div class="hook mid" style="font-size:calc(88px*var(--s))">rumopt.com/start</div>'
               '<div class="en fg">the free 60-second start.</div>')
        small = "8 words · 4 questions · no sign-up"
    else:
        ask = ('<div class="hook mid">Link in bio</div>'
               '<div class="en fg">for the free 60-second start.</div>')
        small = "8 words · 4 questions · no sign-up · rumopt.com"
    extra = '<div class="small">All 40 stories are free to read on rumopt.com</div>' if story else ""
    line = send_line(post) if post.get("format") != "brand" else None
    send = f'<div class="send">{esc(line)}{" ↗" if line and line.startswith(("Send", "Know")) else ""}</div>' \
        if line else ""
    return ('<div class="ctab"><div class="label">Try Brazilian Portuguese free</div>'
            f'{ask}<div class="small">{small}</div>{extra}{send}</div>')


def _line_html(line, show_gloss=True):
    g = ""
    if show_gloss and line.get("gloss"):
        g = f'<span class="glo">{esc(line["gloss"]["text"])}</span>'
    return (f'<div class="line"><div class="pt">{esc(line["pt"]["text"])}</div>'
            f'<div class="en">{esc(line["en"]["text"])}</div>{g}</div>')


def slides_html(post, mark, cfg, cta_mode=None):
    out = []
    n = len(post["slides"])
    for i, s in enumerate(post["slides"], 1):
        k = s["kind"]
        deco = ""
        top = None
        if k == "cover":
            inner, deco = _cover(post, s), '<div class="deco diamond"></div>'
        elif k == "question":
            inner = (f'<div class="label">Question {s["n"]} of {s["of"]}</div>'
                     f'<div class="pt l">{pt_html(s["q"]["text"])}</div>'
                     f'<div class="opts">' + "".join(f'<span class="opt">{esc(o)}</span>' for o in s["options"])
                     + '</div><div class="hint">Answer on the next slide →</div>')
        elif k == "answer":
            inner = (f'<div class="label">Answer {s["n"]}</div><div class="ans">'
                     f'<div class="verdict">✓ {esc(s["answer"])}</div>'
                     f'<div class="pt">{mark_word(s["full"]["text"], s["word"]["text"])}</div>'
                     f'<div class="en">{esc(s["why"]["text"])}</div></div>')
        elif k == "chat_q":
            inner = ('<div class="chathead"><span class="av">BR</span><span>Your Brazilian friend</span></div>'
                     f'<div class="bubble"><div class="pt">{pt_html(s["pt"]["text"])}</div>'
                     '<div class="time">18:04</div></div>'
                     '<div class="hint">What does it mean? Swipe →</div>')
        elif k == "chat_a":
            inner = ('<div class="chathead"><span class="av">BR</span><span>Your Brazilian friend</span></div>'
                     f'<div class="bubble"><div class="pt">{pt_html(s["pt"]["text"])}</div>'
                     '<div class="time">18:04</div></div>'
                     f'<div class="reply">{esc(s["en"]["text"])}</div>')
        elif k == "real":
            if s.get("labels"):
                la, lb = s["labels"]
            else:
                la, lb = s["label_refs"][0]["text"], s["label_refs"][1]["text"]
            pairs = []
            for p in s["pairs"]:
                pairs.append(f'<div class="panel muted"><div class="label" style="color:var(--soft)">{esc(la)}</div>'
                             f'<div class="pt m">{pt_html(p["left"]["text"])}</div></div>'
                             '<div class="down">↓</div>'
                             f'<div class="panel bright"><div class="label">{esc(lb)}</div>'
                             f'<div class="pt">{pt_html(p["right"]["text"])}</div></div>')
            ex = f'<div class="en">{esc(s["example"]["text"])}</div>' if s.get("example") else ""
            inner = '<div class="pairs">' + "".join(pairs) + "</div>" + ex
        elif k == "trap":
            inner = (f'<div class="label">Say it like this · {s.get("n", 1)} of {s.get("of", 1)}</div>'
                     '<div style="display:flex;gap:34px;align-items:flex-start"><span class="tick"></span>'
                     f'<div class="pt">{pt_html(s["pt"]["text"], s["pt"].get("rich"))}</div></div>'
                     f'<div class="en">{esc(s["en"]["text"])}</div>')
        elif k == "flip":
            ma, mb = diff_marks(s["a"]["pt"]["text"], s["b"]["pt"]["text"])
            inner = ('<div class="label">Same sentence, one word different</div>'
                     f'<div class="flipcard"><div class="pt">{ma}</div><div class="en">{esc(s["a"]["en"]["text"])}</div></div>'
                     '<div class="vs">vs.</div>'
                     f'<div class="flipcard"><div class="pt">{mb}</div><div class="en">{esc(s["b"]["en"]["text"])}</div></div>')
        elif k == "cheat":
            rows = "".join(f'<div class="row"><div class="lab">{esc(r["label"]["text"])}</div>'
                           f'<div class="pt">{pt_html(r["pt"]["text"])}</div></div>' for r in s["rows"])
            inner = f'<div class="label">{esc(s["heading"]["text"])}</div><div class="cheat">{rows}</div>'
        elif k == "example":
            inner = (f'<div class="label">{esc(s["head"]["text"])}</div>'
                     f'<div class="pt">{pt_html(s["pt"]["text"], s["pt"].get("rich"))}</div>'
                     f'<div class="en fg">{esc(s["en"]["text"])}</div>')
        elif k == "story_cover":
            deco = '<div class="page-edge"></div>'
            inner = (f'<div class="label">Part {s["part"]} · a short story in Portuguese</div>'
                     f'<div class="story-title">{esc(s["title"]["text"])}</div>'
                     '<div class="sub">Read the Portuguese first. The English is underneath.</div>'
                     '<span class="swipe">Swipe to read →</span>')
        elif k == "story":
            deco = '<div class="page-edge"></div>'
            first = i == 2   # the slide Instagram may show again on its own: say what this is
            lab = '<div class="label">Read it in Portuguese · the English is underneath</div>' if first else ""
            inner = lab + '<div class="lines">' + "".join(_line_html(l) for l in s["lines"]) + "</div>"
        elif k == "words_cover":
            deco = '<div class="deco diamond"></div>'
            inner = (f'<div class="hook sm">{esc(post["hook"])}</div>'
                     f'<div class="story-title" style="color:var(--acc)">{esc(s["title"]["text"])}</div>'
                     f'<div class="sub">{esc(post["sub"])}</div><span class="swipe">Swipe →</span>')
        elif k == "word":
            a, b = gloss_parts(s["gloss"]["text"])
            big = (f'<div class="wordbig">{esc(a)}</div><div class="wordeq">= {esc(b)}</div>' if a
                   else f'<div class="wordeq">{esc(b)}</div>')
            w = word_in_sentence(a, s["pt"]["text"])
            pt = mark_word(s["pt"]["text"], w, "mk") if w else esc(s["pt"]["text"])
            inner = (f'<div class="label">From the story</div>{big}'
                     f'<div class="ctx"><div class="pt">{pt}</div><div class="en">{esc(s["en"]["text"])}</div></div>')
        elif k == "brand_cover":
            deco = '<div class="deco diamond"></div>'
            inner = (f'<img class="brandmark" src="{mark}" alt="">'
                     f'<div class="hook">{esc(post["hook"])}</div><div class="sub">{esc(post["sub"])}</div>'
                     '<span class="swipe">Swipe →</span>')
        elif k == "brand":
            inner = f'<div class="hook mid">{esc(s["big"])}</div><div class="en fg">{esc(s["small"])}</div>'
        elif k == "cta":
            deco = '<div class="deco diamond"></div>'
            inner = _cta(post, cfg, cta_mode, story=s.get("story"))
        else:
            raise ValueError(k)
        out.append(_frame(post, i, n, inner, mark, deco, top))
    return out


FIT_JS = """() => {
  const sl = document.querySelector('.slide');
  const b = sl.querySelector('.body');
  if (b.scrollHeight > b.clientHeight + 1) return 'tall';
  const box = sl.getBoundingClientRect();
  for (const el of sl.querySelectorAll('.body *, .top *')) {
    if (el.closest('.deco')) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    if (r.right > box.right - 60 || r.left < box.left + 60) return 'wide';
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow !== 'visible') return 'clip';
  }
  return 'ok';
}"""


def launch(pw):
    errors = []
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return pw.chromium.launch(**kw)
        except Exception as e:
            errors.append(f"{kw or 'chromium'}: {str(e).splitlines()[0]}")
    raise RuntimeError("No browser to draw the slides with. " + " | ".join(errors))


def base_page(tmpdir, css_extra="", w=W, h=H, name="base.html"):
    css = font_face() + BASE_CSS.replace("width:1080px;height:1350px;overflow:hidden;background:#000",
                                         f"width:{w}px;height:{h}px;overflow:hidden;background:#000") \
        + _theme_css() + css_extra
    f = tmpdir / name
    f.write_text(f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head>"
                 "<body><div id='root'></div></body></html>", encoding="utf-8")
    return f


def _render_carousel(page, post, folder, mark, cfg, cta_mode=None, only_last=False):
    htmls = slides_html(post, mark, cfg, cta_mode)
    paths, alts = [], []
    for idx, h in enumerate(htmls, 1):
        if only_last and idx != len(htmls):
            continue
        verdict = None
        for s in SCALES:
            page.evaluate("([h, s]) => { const r = document.getElementById('root');"
                          " r.style.setProperty('--s', s); r.innerHTML = h; }", [h, s])
            page.evaluate("document.fonts.ready")
            verdict = page.evaluate(FIT_JS)
            if verdict == "ok":
                break
        if verdict != "ok":
            return None, f"slide {idx} does not fit ({verdict})"
        name = f"{idx:02d}" + {"bio": "-bio", "url": "-tt"}.get(cta_mode, "") + ".jpg"
        out = folder / name
        page.screenshot(path=str(out), type="jpeg", quality=90,
                        clip={"x": 0, "y": 0, "width": W, "height": H})
        paths.append(str(out.relative_to(ROOT)).replace("\\", "/"))
        alts.append(page.evaluate("document.querySelector('.body').innerText").replace("\n", " ")[:900])
    return (paths, alts), None


def render_all(state, only=None, log=say):
    """Draw every post in `only` (ids) that is not drawn yet. Returns the ids left out as unfit."""
    from playwright.sync_api import sync_playwright

    from rumo_reels import ReelRenderer

    cfg = config()
    mark = mark_uri()
    PREVIEW_DIR.mkdir(exist_ok=True)
    tmp = ROOT / "cache"
    tmp.mkdir(exist_ok=True)
    unfit = []
    todo = [p for p in state["posts"] if (only is None or p["id"] in only)]

    after_test = state.get("cta_decided") if cfg["cta_mode"] == "comment" else None

    def mode_of(p):
        return p.get("cta_plan") or after_test or cfg["cta_mode"]

    def done(p):
        if p.get("cta") != mode_of(p):   # drawn with the other call to action: draw again
            return False
        if p.get("kind") == "reel":
            ok = p.get("video") and (ROOT / p["video"]).exists()
            if cfg.get("tiktok"):
                ok = ok and p.get("tt_video") and (ROOT / p["tt_video"]).exists()
            return ok
        ok = p.get("slides_jpg") and all((ROOT / s).exists() for s in p["slides_jpg"])
        if cfg.get("tiktok"):
            ok = ok and p.get("tt_slides_jpg") and all((ROOT / s).exists() for s in p["tt_slides_jpg"])
        return ok

    todo = [p for p in todo if p.get("status") not in ("scheduled", "published", "missed", "unfit")
            and not (p.get("status") == "rendered" and done(p))]
    if not todo:
        return unfit
    base = base_page(tmp)
    with sync_playwright() as pw:
        browser = launch(pw)
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(base.resolve().as_uri())
        page.evaluate("document.fonts.ready")
        reels = None
        for post in todo:
            folder = PREVIEW_DIR / f"{post['order']:03d}-{post['id']}"
            # earlier drawings of this post under an older queue number: remove (preview/ stays small)
            if PREVIEW_DIR.exists():
                pat = re.compile(r"\d{3,}-" + re.escape(post["id"]) + r"(-\d+)?")
                for old in PREVIEW_DIR.iterdir():
                    if old.is_dir() and old != folder and pat.fullmatch(old.name):
                        shutil.rmtree(old, ignore_errors=True)
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            if folder.exists():   # Windows: a file is still open (a Reel playing in a preview tab)
                folder = folder.with_name(f"{folder.name}-{int(time.time())}")
            folder.mkdir(parents=True)
            if post.get("kind") == "reel":
                if reels is None:
                    reels = ReelRenderer(browser, tmp, mark, cfg)
                err = reels.render(post, folder, mode=mode_of(post), log=log)
                if err:
                    post["status"], post["unfit"] = "unfit", err
                    unfit.append(post["id"])
                    log(f"  left out {post['id']}: {err}")
                    continue
                post["status"], post["cta"] = "rendered", mode_of(post)
                post.pop("media", None)      # redrawn: an earlier upload is out of date
                post.pop("tt_media", None)
                log(f"  rendered {post['order']:03d} {post['id']}: Reel {post['duration']:.1f}s")
                continue
            res, err = _render_carousel(page, post, folder, mark, cfg, cta_mode=mode_of(post))
            if err:
                post["status"], post["unfit"] = "unfit", err
                unfit.append(post["id"])
                log(f"  left out {post['id']}: {err}")
                continue
            post["slides_jpg"], post["alts"] = res
            if cfg.get("tiktok"):
                res2, err2 = _render_carousel(page, post, folder, mark, cfg, cta_mode="url", only_last=True)
                if err2:
                    post["status"], post["unfit"] = "unfit", "TikTok " + err2
                    unfit.append(post["id"])
                    continue
                post["tt_slides_jpg"] = post["slides_jpg"][:-1] + res2[0]
            post["status"], post["cta"] = "rendered", mode_of(post)
            post.pop("media", None)          # redrawn: an earlier upload is out of date
            post.pop("tt_media", None)
            log(f"  rendered {post['order']:03d} {post['id']}: {len(post['slides_jpg'])} slides")
        browser.close()
    return unfit


def write_index(state, limit=None):
    cards = []
    shown = [p for p in state["posts"] if p.get("slides_jpg") or p.get("video")]
    shown.sort(key=lambda p: p.get("order", 0))
    for p in shown[:limit]:
        if p.get("kind") == "reel":
            media = (f'<video controls preload="none" poster="../{p["cover"]}" src="../{p["video"]}"></video>'
                     f'<img loading="lazy" src="../{p["cover"]}" alt="">')
        else:
            media = "".join(f'<img loading="lazy" src="../{s}" alt="">' for s in p.get("slides_jpg", []))
        cap = esc(p.get("caption", "")).replace("\n", "<br>")
        flag = (' <b style="color:#b3261e">· English written for Rumo — approve the wording</b>'
                if p.get("written") else "")
        when = p.get("scheduled_at") or ""
        cards.append(f'<section><h2>{p["order"]:03d} · {esc(p["format"] if p.get("kind") != "reel" else "Reel · " + p["reel_kind"])}'
                     f' · {esc(p["level"] or "")} · {esc(p["hook"])}{flag} <small>{esc(when)}</small></h2>'
                     f'<div class="strip">{media}</div><p>{cap}</p></section>')
    html = ("<!doctype html><meta charset='utf-8'><title>Rumo posts preview</title><style>"
            "body{font-family:Inter,'Segoe UI',sans-serif;background:#f4f1ea;color:#1c1e1b;margin:0;padding:24px}"
            "h1{margin:0 0 8px}section{margin:28px 0;padding-top:16px;border-top:1px solid #ddd}"
            "h2{font-size:17px;margin:0 0 10px}h2 small{color:#888;font-weight:400}"
            ".strip{display:flex;gap:10px;overflow-x:auto}"
            ".strip img{height:320px;border-radius:6px}.strip video{height:420px;border-radius:6px;background:#000}"
            "p{font-size:14px;color:#555;max-width:72ch}</style>"
            f"<h1>Rumo — the first {len(shown[:limit])} posts</h1>"
            "<p>Judge the look. Every Portuguese line, every explanation and every story translation has been "
            "matched word for word against rumopt.com. Posts marked in red contain English written for Rumo. "
            "Reels play with sound.</p>"
            + "".join(cards))
    out = PREVIEW_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out

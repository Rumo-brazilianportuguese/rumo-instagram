"""Draw the Reels: 1080 x 1920, 9 to 21 seconds, with original music.

Every frame is drawn by the same headless browser as the slides: the scene is
built once with CSS animations, the animations are paused, and the clock is
moved frame by frame (30 frames a second), so the video is exactly the same
every time and never drops a frame. Frames go straight into ffmpeg (bundled by
the imageio-ffmpeg package), together with the music from rumo_music.py.

Design rules (from Instagram's own ranking notes): something moves from the
very first frame (the content flies in over a slowly moving background), the
question is on screen within half a second, the sound is always on, and the
end fades back to the opening background so the Reel loops cleanly. The cover
(the thumbnail on the grid) is the frame just after the opening, so it shows
the whole question. Instagram covers the top and bottom of a Reel with its own
buttons and the caption, so all text stays inside the middle band.
"""
import base64
import os
import subprocess
import tempfile

from rumo_common import ROOT
from rumo_music import make_track
from rumo_render import base_page, esc, mark_word, pt_html

RW, RH = 1080, 1920
FPS = int(os.environ.get("RUMO_REEL_FPS", "30"))
OUTRO = 0.45

REEL_CSS = r"""
.reel{width:1080px;height:1920px;position:relative;overflow:hidden;background:var(--bg);color:var(--fg);
  font-family:'Inter','Segoe UI',system-ui,sans-serif}
.bgfx{position:absolute;inset:0;overflow:hidden}
.blob{position:absolute;width:980px;height:980px;border-radius:50%;
  background:radial-gradient(circle at center, var(--acc) 0%, transparent 66%);opacity:.20}
.blob.b1{left:-360px;top:180px}
.blob.b2{right:-420px;top:980px;
  background:radial-gradient(circle at center, var(--alt) 0%, transparent 66%);opacity:.16}
.reel .deco.diamond{width:900px;height:900px;right:-420px;top:520px;border:48px solid var(--acc);opacity:.10;
  border-radius:70px;position:absolute;transform:rotate(45deg)}
.fgl{position:absolute;inset:0}
.rtop{position:absolute;left:84px;right:160px;top:310px;display:flex;align-items:center;gap:16px}
.rtop img{width:58px;height:58px;border-radius:13px}
.rtop .rb{font-family:'Bricolage',sans-serif;font-weight:800;font-size:40px;margin-right:10px}
.rbody{position:absolute;left:84px;right:160px;top:420px;height:1080px;display:flex;flex-direction:column;
  justify-content:center;gap:calc(46px*var(--s))}
.rhook{font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(96px*var(--s));line-height:1.0;letter-spacing:-.02em;text-wrap:balance}
.rpt{font-family:'Fraunces',Georgia,serif;font-weight:600;font-size:calc(100px*var(--s));line-height:1.1;letter-spacing:-.01em;
  text-wrap:balance;font-variation-settings:"WONK" 0,"SOFT" 30}
.rpt b{font-weight:800;color:var(--acc)}
.rpt.l{font-size:calc(120px*var(--s))}
.ren{font-size:calc(52px*var(--s));line-height:1.3;color:var(--fg);text-wrap:pretty}
.rsoft{font-size:calc(40px*var(--s));line-height:1.3;color:var(--soft)}
.cd{display:flex;align-items:center;gap:26px;height:110px}
.cd .track{flex:1;height:16px;border-radius:8px;background:var(--line);overflow:hidden}
.cd .fill{height:100%;background:var(--acc);transform-origin:left center}
.cd .nums{position:relative;width:110px;height:110px}
.cd .nums span{position:absolute;inset:0;display:grid;place-items:center;font-family:'Bricolage',sans-serif;
  font-weight:800;font-size:96px;color:var(--acc)}
.rbubble{align-self:flex-start;max-width:100%;background:#FFFFFF;color:#13241C;border-radius:52px 52px 52px 16px;
  padding:calc(42px*var(--s)) calc(52px*var(--s))}
.rbubble .rpt{font-size:calc(92px*var(--s))}
.rbubble .rpt.l{font-size:calc(112px*var(--s))}
.rbubble .rpt.xl{font-size:calc(150px*var(--s))}
.rbubble .gl{color:#5B6B63}
.rreply{align-self:flex-end;max-width:100%;background:var(--acc);color:var(--on);border-radius:52px 52px 16px 52px;
  padding:calc(38px*var(--s)) calc(50px*var(--s));font-size:calc(56px*var(--s));line-height:1.28;font-weight:600}
.rtyping{align-self:flex-end;display:flex;gap:16px;background:var(--card);padding:28px 36px;border-radius:40px}
.rtyping i{width:24px;height:24px;border-radius:50%;background:var(--soft)}
.ropts{display:flex;gap:28px}
.ropt{flex:1;text-align:center;font-family:'Bricolage',sans-serif;font-weight:800;font-size:calc(84px*var(--s));
  padding:calc(30px*var(--s)) 10px;border:6px solid var(--fg);border-radius:34px}
.stack{display:grid}
.stack > *{grid-area:1/1}
.blk{display:flex;flex-direction:column;gap:calc(40px*var(--s))}
.rpt mark{background:none;color:var(--acc);text-decoration:underline;text-decoration-thickness:.08em;text-underline-offset:.12em}
.rpt .blank{display:inline-block;min-width:3em;border-bottom:.1em solid var(--acc);height:.8em}
.why{background:var(--card);border-radius:36px;padding:calc(34px*var(--s)) calc(42px*var(--s));font-size:calc(46px*var(--s));
  line-height:1.3;color:var(--fg)}
.rpanel{border-radius:44px;padding:calc(40px*var(--s)) calc(50px*var(--s));display:flex;flex-direction:column;gap:16px;position:relative}
.rpanel.muted{border:5px dashed var(--line)}
.rpanel.muted .rpt{color:var(--soft)}
.rpanel.bright{background:var(--card);border:6px solid var(--acc)}
.rlabel{font-family:'Bricolage',sans-serif;font-weight:700;font-size:calc(34px*var(--s));letter-spacing:.11em;text-transform:uppercase;color:var(--acc)}
.struck{position:relative;display:inline-block}
.strike{position:absolute;left:-6px;right:-6px;top:52%;height:.09em;border-radius:.05em;background:var(--alt);transform-origin:left center}
.w{display:inline}
.rglo{align-self:flex-start;font-weight:700;font-size:calc(42px*var(--s));color:#1F1A14;background:var(--hi);padding:10px 24px;border-radius:16px}
.dots{display:flex;gap:16px;align-items:center}
.dots i{width:64px;height:14px;border-radius:7px;background:var(--line)}
.rctacard{position:absolute;left:60px;right:140px;top:860px;background:var(--fg);color:var(--bg);border-radius:52px;
  padding:56px 60px;display:flex;flex-direction:column;gap:22px;box-shadow:0 30px 80px rgba(0,0,0,.25)}
.rctacard .t1{font-family:'Bricolage',sans-serif;font-weight:700;font-size:34px;letter-spacing:.11em;text-transform:uppercase;opacity:.75}
.rctacard .t2{font-family:'Bricolage',sans-serif;font-weight:800;font-size:96px;line-height:1}
.rctacard .t2.url{font-size:84px;letter-spacing:-.01em}
.rctacard .kw{display:inline-block;background:var(--acc);color:var(--on);padding:2px 26px 10px;border-radius:24px}
.rctacard .t3{font-size:46px;line-height:1.3}
.rctacard .t4{font-size:36px;opacity:.7}
@keyframes drift1{from{transform:translate(0,0) scale(1)}to{transform:translate(160px,120px) scale(1.12)}}
@keyframes drift2{from{transform:translate(0,0) scale(1.05)}to{transform:translate(-170px,-150px) scale(.95)}}
@keyframes spin90{from{transform:rotate(45deg)}to{transform:rotate(135deg)}}
@keyframes enter{from{opacity:0;transform:translateY(70px) scale(.96)}to{opacity:1;transform:none}}
@keyframes pop{0%{opacity:0;transform:scale(.86)}70%{opacity:1;transform:scale(1.03)}100%{opacity:1;transform:scale(1)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(40px)}to{opacity:1;transform:none}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes fadeOut{from{opacity:1}to{opacity:0}}
@keyframes slideIn{from{opacity:0;transform:translateX(140px)}to{opacity:1;transform:none}}
@keyframes slideOut{from{opacity:1;transform:none}to{opacity:0;transform:translateX(-140px)}}
@keyframes blip{0%{opacity:0}12%{opacity:1}88%{opacity:1}100%{opacity:0}}
@keyframes num{0%{opacity:0;transform:scale(1.5)}12%{opacity:1;transform:scale(1)}82%{opacity:1}100%{opacity:0}}
@keyframes shrink{from{transform:scaleX(1)}to{transform:scaleX(0)}}
@keyframes strike{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes kara{0%{color:inherit}25%{color:var(--acc)}75%{color:var(--acc)}100%{color:inherit}}
@keyframes dim{from{opacity:1}to{opacity:.22}}
@keyframes slideUp{from{transform:translateY(1200px)}to{transform:none}}
@keyframes win{to{background:var(--acc);color:var(--on);border-color:var(--acc)}}
@keyframes lose{to{opacity:.3}}
@keyframes dotOn{to{background:var(--acc)}}
"""

# Measured with every animation removed, so each element sits where it ends up.
FIT_JS = """() => {
  document.getAnimations().forEach(a => a.cancel());
  const b = document.querySelector('.rbody');
  if (b.scrollHeight > b.clientHeight + 1) return 'tall';
  const box = b.getBoundingClientRect();
  for (const el of b.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    if (r.right > box.right + 2 || r.left < box.left - 2) return 'wide';
  }
  return 'ok';
}"""

SETUP_JS = """() => new Promise(res => requestAnimationFrame(() => {
  const anims = document.getAnimations();
  anims.forEach(a => a.pause());
  window.__anims = anims;
  window.__setT = t => { for (const a of window.__anims) a.currentTime = t; };
  window.__setT(0);
  res(anims.map(a => { const t = a.effect.getComputedTiming();
      const end = (t.activeDuration === Infinity) ? 1e12 : (t.delay || 0) + (t.activeDuration || 0);
      return [t.delay || 0, end]; }));
}))"""


def A(name, dur, delay, ease="ease-out", fill="both"):
    return f"animation:{name} {dur}s {ease} {delay}s {fill}"


def AA(*parts):
    """Several animations on one element: [(name, dur, delay, ease, fill), ...]."""
    return "animation:" + ", ".join(f"{n} {d}s {e} {t}s {f}" for n, d, t, e, f in parts)


def _in(i, base=0.0):
    """The opening: everything flies in within the first second, one element after the other."""
    return A("enter", 0.45, base + 0.08 * i, "cubic-bezier(.2,.8,.2,1)")


def _countdown(t0, beats=3):
    nums = "".join(f'<span style="{A("num", 1.0, t0 + i, "linear")}">{beats - i}</span>' for i in range(beats))
    show = AA(("fadeIn", 0.3, max(0.0, t0 - 0.35), "linear", "both"),
              ("fadeOut", 0.2, t0 + beats, "linear", "forwards"))
    return (f'<div class="cd" style="{show}">'
            f'<div class="track"><div class="fill" style="{A("shrink", beats, t0, "linear")}"></div></div>'
            f'<div class="nums">{nums}</div></div>')


def _cta_card(cfg, mode, t, story=False):
    if mode == "comment":
        big = f'<div class="t2">Comment <span class="kw">{esc(cfg["keyword"])}</span></div>'
        line = "and we'll DM you the free 60-second start."
        small = "8 words · 4 questions · no sign-up · or tap the link in bio"
    elif mode == "url":   # TikTok: no comment-to-DM, and no bio link before 1,000 followers
        big = '<div class="t2 url">rumopt.com/start</div>'
        line = "the free 60-second start."
        small = "8 words · 4 questions · no sign-up"
    else:
        big = '<div class="t2">Link in bio</div>'
        line = "for the free 60-second start."
        small = "8 words · 4 questions · no sign-up"
    extra = '<div class="t4">All 40 stories are free to read on rumopt.com</div>' if story else ""
    return (f'<div class="rctacard" style="{A("slideUp", 0.45, t, "cubic-bezier(.2,.8,.2,1)")}">'
            f'<div class="t1">Try Brazilian Portuguese free</div>{big}'
            f'<div class="t3">{line}</div><div class="t4">{small}</div>{extra}</div>')


def _size(text):
    n = len(text)
    return " xl" if n <= 14 else (" l" if n <= 28 else "")


def _quiz_block(q, t0, reveal, idx=None, of=None, enter=None, leave=None):
    a, b = q["options"]
    win = a if q["answer"] == a else b
    opts = "".join(f'<span class="ropt" style="{A("win" if o == win else "lose", 0.3, reveal)}">{esc(o)}</span>'
                   for o in q["options"])
    label = f'<div class="rlabel">Question {idx} of {of}</div>' if idx else ""
    style = ""
    anims = []
    if enter is not None:
        anims.append(("slideIn", 0.4, enter, "cubic-bezier(.2,.8,.2,1)", "both"))
    if leave is not None:
        anims.append(("slideOut", 0.35, leave, "ease-in", "forwards"))
    if anims:
        style = f' style="{AA(*anims)}"'
    return (f'<div class="blk"{style}>{label}'
            f'<div class="stack"><div class="rpt" style="{A("fadeOut", 0.25, reveal, "linear")}">'
            f'{pt_html(q["q"]["text"])}</div>'
            f'<div class="rpt" style="{A("fadeIn", 0.25, reveal, "linear")}">'
            f'{mark_word(q["full"]["text"], q["word"]["text"])}</div></div>'
            f'<div class="ropts">{opts}</div>' + _countdown(t0) +
            f'<div class="why" style="{A("fadeUp", 0.4, reveal + 0.4)}">{esc(q["why"]["text"])}</div></div>')


def _chat_block(m, t0, reveal, enter=None, leave=None):
    anims = []
    if enter is not None:
        anims.append(("slideIn", 0.4, enter, "cubic-bezier(.2,.8,.2,1)", "both"))
    if leave is not None:
        anims.append(("slideOut", 0.35, leave, "ease-in", "forwards"))
    style = f' style="{AA(*anims)}"' if anims else ""
    return (f'<div class="blk"{style}>'
            '<div class="chathead"><span class="av">BR</span><span>Your Brazilian friend</span></div>'
            f'<div class="rbubble"><div class="rpt{_size(m["pt"]["text"])}">{pt_html(m["pt"]["text"])}</div></div>'
            + _countdown(t0) +
            f'<div class="stack"><div class="rtyping" style="{A("blip", 0.5, reveal - 0.5, "linear")}">'
            '<i></i><i></i><i></i></div>'
            f'<div class="rreply" style="{A("pop", 0.35, reveal)}">{esc(m["en"]["text"])}</div></div></div>')


def _dots(starts):
    return ('<div class="dots">' + "".join(f'<i style="{A("dotOn", 0.25, t, "linear")}"></i>' for t in starts)
            + "</div>")


def scene_html(post, mark, cfg, mode):
    """Return (html, duration_s, sound events, cover_time_s)."""
    s = post["slides"][0]
    k = post["reel_kind"]
    ev = []
    cover_t = 0.75
    if k == "meaning":
        cd, reveal = 0.7, 3.7
        body = (f'<div class="rhook" style="{_in(0)}">What does it mean?</div>'
                f'<div class="chathead" style="{_in(1)}"><span class="av">BR</span><span>Your Brazilian friend</span></div>'
                f'<div class="rbubble" style="{A("pop", 0.4, 0.2)}"><div class="rpt{_size(s["pt"]["text"])}">'
                f'{pt_html(s["pt"]["text"])}</div></div>'
                + _countdown(cd) +
                f'<div class="stack"><div class="rtyping" style="{A("blip", 0.5, reveal - 0.5, "linear")}">'
                '<i></i><i></i><i></i></div>'
                f'<div class="rreply" style="{A("pop", 0.35, reveal)}">{esc(s["en"]["text"])}</div></div>')
        ev += [(cd, "tick"), (cd + 1, "tick"), (cd + 2, "tick"), (reveal, "chime")]
        cta, dur = reveal + 3.3, reveal + 6.5
    elif k == "quiz":
        cd, reveal = 0.7, 3.7
        a, b = s["options"]
        win = a if s["answer"] == a else b
        opts = "".join(
            f'<span class="ropt" style="{AA(("enter", 0.45, 0.24 + 0.08 * n, "cubic-bezier(.2,.8,.2,1)", "both"), ("win" if o == win else "lose", 0.3, reveal, "ease-out", "forwards"))}">{esc(o)}</span>'
            for n, o in enumerate(s["options"]))
        body = (f'<div class="rhook" style="{_in(0)}">{esc(post["hook"].split("?")[0] + "?")}</div>'
                f'<div class="stack" style="{_in(1)}"><div class="rpt" style="{A("fadeOut", 0.25, reveal, "linear")}">'
                f'{pt_html(s["q"]["text"])}</div>'
                f'<div class="rpt" style="{A("fadeIn", 0.25, reveal, "linear")}">'
                f'{mark_word(s["full"]["text"], s["word"]["text"])}</div></div>'
                f'<div class="ropts">{opts}</div>' + _countdown(cd) +
                f'<div class="why" style="{A("fadeUp", 0.4, reveal + 0.5)}">{esc(s["why"]["text"])}</div>')
        ev += [(cd, "tick"), (cd + 1, "tick"), (cd + 2, "tick"), (reveal, "chime")]
        cta, dur = reveal + 4.1, reveal + 7.3
    elif k == "quiz3":
        qs = s["items"]
        starts, blocks = [], []
        for i, q in enumerate(qs):
            t = 0.15 + i * 6.2
            starts.append(t)
            reveal = t + 3.5
            blocks.append(_quiz_block(q, t + 0.5, reveal, i + 1, len(qs),
                                      enter=(t if i else None), leave=(t + 5.85 if i < len(qs) - 1 else None)))
            ev += [(t + 0.5, "tick"), (t + 1.5, "tick"), (t + 2.5, "tick"), (reveal, "chime")]
        a, b = qs[0]["options"]
        body = (f'<div class="rhook" style="{_in(0)}">3 in a row: {esc(a.title())} or {esc(b.lower())}?</div>'
                f'<div style="{_in(1)}">{_dots(starts)}</div>'
                f'<div class="stack" style="{_in(2)}">{"".join(blocks)}</div>')
        cta, dur = reveal + 2.6, reveal + 5.8
    elif k == "meaning3":
        ms = s["items"]
        starts, blocks = [], []
        for i, m in enumerate(ms):
            t = 0.15 + i * 6.0
            starts.append(t)
            reveal = t + 3.5
            blocks.append(_chat_block(m, t + 0.5, reveal, enter=(t if i else None),
                                      leave=(t + 5.65 if i < len(ms) - 1 else None)))
            ev += [(t + 0.5, "tick"), (t + 1.5, "tick"), (t + 2.5, "tick"), (reveal, "chime")]
        body = (f'<div class="rhook" style="{_in(0)}">3 texts from a Brazilian friend. Do you get them?</div>'
                f'<div style="{_in(1)}">{_dots(starts)}</div>'
                f'<div class="stack" style="{_in(2)}">{"".join(blocks)}</div>')
        cta, dur = reveal + 2.6, reveal + 5.8
    elif k == "real":
        if s.get("labels"):
            la, lb = s["labels"]
        else:
            la, lb = s["label_refs"][0]["text"], s["label_refs"][1]["text"]
        p = s["pairs"][0]
        reveal = 2.1
        ex = (f'<div class="rsoft" style="{A("fadeUp", 0.4, reveal + 0.6)}">{esc(s["example"]["text"])}</div>'
              if s.get("example") else "")
        body = (f'<div class="rhook" style="{_in(0)}">{esc(post["hook"])}</div>'
                f'<div class="rpanel muted" style="{_in(1)}"><div class="rlabel" style="color:var(--soft)">{esc(la)}</div>'
                f'<div class="rpt"><span class="struck">{pt_html(p["left"]["text"])}'
                f'<i class="strike" style="{A("strike", 0.35, 1.3)}"></i></span></div></div>'
                f'<div class="rpanel bright" style="{A("pop", 0.35, reveal)}"><div class="rlabel">{esc(lb)}</div>'
                f'<div class="rpt">{pt_html(p["right"]["text"])}</div></div>' + ex)
        ev += [(1.3, "tick"), (reveal, "chime")]
        cta, dur = reveal + 4.0, reveal + 7.2
    elif k == "story":
        words = s["pt"]["text"].split(" ")
        t0, per = 0.9, 0.32
        spans = " ".join(f'<span class="w" style="{A("kara", per * 1.6, t0 + i * per, "linear")}">{esc(w)}</span>'
                         for i, w in enumerate(words))
        reveal = t0 + per * len(words) + 0.4
        g = ""
        if s.get("gloss"):
            g = f'<span class="rglo" style="{A("fadeUp", 0.4, reveal + 0.5)}">{esc(s["gloss"]["text"])}</span>'
        body = (f'<div class="rhook" style="{_in(0)}">Can you read this?</div>'
                f'<div class="rsoft" style="{_in(1)}">From “{esc(s["title"]["text"])}”</div>'
                f'<div class="rpt{" l" if len(s["pt"]["text"]) <= 34 else ""}" style="{_in(2)}">{spans}</div>'
                f'<div class="ren" style="{A("fadeUp", 0.4, reveal)}">{esc(s["en"]["text"])}</div>' + g)
        ev.append((reveal, "chime"))
        cta, dur = reveal + 3.6, reveal + 6.8
        cover_t = 0.85
    else:
        raise ValueError(k)
    top = (f'<div class="rtop" style="{A("fadeIn", 0.3, 0)}"><img src="{mark}" alt=""><span class="rb">rumo</span>'
           f'<span class="pill">{esc(post["series"])}</span><span class="lvl">{esc(post["level"] or "")}</span></div>')
    half = round(dur / 2, 3)
    html = (f'<div class="reel t-{post["theme"]}"><div class="bgfx">'
            f'<div class="blob b1" style="animation:drift1 {half}s ease-in-out 0s infinite alternate"></div>'
            f'<div class="blob b2" style="animation:drift2 {half}s ease-in-out 0s infinite alternate"></div>'
            f'<div class="deco diamond" style="animation:spin90 {round(dur, 3)}s linear 0s infinite"></div></div>'
            f'<div class="fgl" style="{A("fadeOut", OUTRO, dur - OUTRO - 0.1, "linear", "forwards")}">{top}'
            f'<div class="rbody" style="{A("dim", 0.35, cta, "ease-out", "forwards")}">{body}</div>'
            + _cta_card(cfg, mode, cta, story=(k == "story")) + "</div></div>")
    return html, dur, ev, cover_t


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


class ReelRenderer:
    def __init__(self, browser, tmpdir, mark, cfg):
        self.mark, self.cfg, self.tmp = mark, cfg, tmpdir
        base = base_page(tmpdir, REEL_CSS, RW, RH, name="reel-base.html")
        self.page = browser.new_page(viewport={"width": RW, "height": RH}, device_scale_factor=1)
        self.page.goto(base.resolve().as_uri())
        self.page.evaluate("document.fonts.ready")
        self.ffmpeg = ffmpeg_exe()
        self.cdp = None

    def _shot(self, t_ms):
        self.page.evaluate("t => window.__setT(t)", t_ms)
        try:   # Chromium's own capture: a little faster than page.screenshot
            if self.cdp is None:
                self.cdp = self.page.context.new_cdp_session(self.page)
            r = self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92,
                                                         "clip": {"x": 0, "y": 0, "width": RW, "height": RH,
                                                                  "scale": 1}})
            return base64.b64decode(r["data"])
        except Exception:
            self.cdp = False
            return self.page.screenshot(type="jpeg", quality=92, clip={"x": 0, "y": 0, "width": RW, "height": RH})

    def _video(self, post, folder, mode, name, log):
        from rumo_render import SCALES
        html = dur = ev = cover_t = None
        put = ("([h, s]) => { const r = document.getElementById('root');"
               " r.style.setProperty('--s', s); r.innerHTML = h; }")
        for sc in SCALES:
            html, dur, ev, cover_t = scene_html(post, self.mark, self.cfg, mode)
            self.page.evaluate(put, [html, sc])
            self.page.evaluate("document.fonts.ready")
            if self.page.evaluate(FIT_JS) == "ok":
                break
        else:
            return None, "the Reel text does not fit"
        self.page.evaluate(put, [html, sc])   # fresh animations (the fit check removed them)
        self.page.evaluate("document.fonts.ready")
        spans = self.page.evaluate(SETUP_JS)
        wav = self.tmp / f"{post['id']}.wav"
        make_track(dur, post["id"], ev, wav)
        out = folder / name
        cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
               "-c:v", "mjpeg", "-i", "-", "-i", str(wav),
               "-vf", "scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-profile:v", "high",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
               "-shortest", "-movflags", "+faststart", str(out)]
        # no console window on Windows (the weekly run has none; a window closed by hand kills ffmpeg)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        errf = tempfile.TemporaryFile()   # a file, not a pipe: a full pipe would freeze ffmpeg
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf, creationflags=flags)
        n = int(round(dur * FPS))
        last, prev_t, shots = None, -1.0, 0
        fg = [(a, b) for a, b in spans if b < 1e11]      # the content's own movements
        bg = len(fg) < len(spans)                        # the slowly drifting background
        try:
            for i in range(n):
                t = i * 1000.0 / FPS
                moving = any(a <= t and b >= prev_t for a, b in fg)
                # The background drifts slowly: while only it moves, half the frames are enough.
                if last is None or moving or (bg and i % 2 == 0):
                    last = self._shot(t)
                    shots += 1
                proc.stdin.write(last)
                prev_t = t
            proc.stdin.close()
        except OSError:   # BrokenPipeError, or EINVAL on Windows when ffmpeg died
            pass
        proc.wait()
        errf.seek(0)
        err = errf.read().decode("utf-8", "replace")
        errf.close()
        cover = self._shot(cover_t * 1000.0)
        try:
            wav.unlink()
        except OSError:
            pass
        if proc.returncode != 0 or not out.exists():
            return None, f"ffmpeg failed: {err[-300:]}"
        return (out, cover, dur, shots), None

    def render(self, post, folder, mode=None, log=print):
        mode = mode or self.cfg["cta_mode"]
        res, err = self._video(post, folder, mode, "reel.mp4", log)
        if err:
            return err
        out, cover, dur, shots = res
        cov = folder / "cover.jpg"
        cov.write_bytes(cover)
        post["video"] = str(out.relative_to(ROOT)).replace("\\", "/")
        post["cover"] = str(cov.relative_to(ROOT)).replace("\\", "/")
        post["duration"] = round(dur, 2)
        if self.cfg.get("tiktok"):
            res2, err2 = self._video(post, folder, "url", "reel-tiktok.mp4", log)
            if err2:
                return "TikTok " + err2
            post["tt_video"] = str(res2[0].relative_to(ROOT)).replace("\\", "/")
        return None

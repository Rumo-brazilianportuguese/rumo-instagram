"""Local stand-ins for rumopt.com, Meta's Instagram Graph API and a public file host, for
offline testing.

The site copy serves 60 chapter URLs built from five real chapter pages
(ser-estar, por-para, spoken, b2-giria, b2-diminutivos) and 40 story URLs
built from the real story 1 page, and mimics Netlify's redirect of
/Grammar/x.html to /grammar/x. The Graph mock follows Meta's documented request shapes
(image / carousel / resumable Reel containers, status, media_publish, insights) and records
anything that does not match them in GS.errors. It downloads every image_url and cover_url
the way Instagram does, so a private or broken address fails here too.
"""
import hashlib
import itertools
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIX = Path(__file__).parent / "fixtures"
REAL = ["ser-estar", "por-para", "spoken", "b2-giria", "b2-diminutivos"]
PAGES = {k: (FIX / f"{k}.html").read_text(encoding="utf-8") for k in REAL}
SLUGS = REAL + [f"ch{n:02d}" for n in range(6, 61)]
STORY = (FIX / "story-01.html").read_text(encoding="utf-8")
STORY_SLUGS = [f"licao-{n:02d}-story-{n}" for n in range(1, 41)]


def page_for(slug):
    if slug in PAGES:
        return PAGES[slug]
    n = int(slug[2:])
    base = "ser-estar" if n % 2 else "por-para"
    html = PAGES[base]
    # give every copy its own chapter number and level, as on the real site
    level = ["A1", "A2", "B1", "B2"][(n - 1) // 15]
    html = re.sub(r"CHAPTER \d+ OF 60 · (A1|A2|B1|B2)", f"CHAPTER {n} OF 60 · {level}", html, count=1)
    return html


def story_for(slug):
    n = int(slug.split("-")[1])
    level = ["A1", "A2", "B1", "B2"][min(3, (n - 1) // 10)]
    html = STORY.replace("STORY 1 OF 40 · A1", f"STORY {n} OF 40 · {level}", 1)
    html = html.replace('<span class="lbadge">Lição 1</span>', f'<span class="lbadge">Lição {n}</span>', 1)
    return html


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/sitemap.xml":
            locs = "".join(f"<url><loc>https://rumopt.com/Grammar/{s}.html</loc></url>" for s in SLUGS)
            locs += "".join(f"<url><loc>https://rumopt.com/Stories/{s}.html</loc></url>" for s in STORY_SLUGS)
            locs += "<url><loc>https://rumopt.com/Lessons/PT-L01-x.html</loc></url>"
            return self._send(200, f"<urlset>{locs}</urlset>".encode(), "application/xml")
        m = re.fullmatch(r"/Grammar/([a-z0-9-]+)\.html", path)
        if m:
            return self._send(301, headers={"Location": f"/grammar/{m.group(1)}"})
        m = re.fullmatch(r"/grammar/([a-z0-9-]+)", path)
        if m and m.group(1) in SLUGS:
            return self._send(200, page_for(m.group(1)).encode("utf-8"))
        m = re.fullmatch(r"/Stories/([a-z0-9-]+)\.html", path)
        if m and m.group(1) in STORY_SLUGS:
            return self._send(200, story_for(m.group(1)).encode("utf-8"))
        return self._send(404, b"not found")


class GraphState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.containers = {}
        self.media = []                 # newest last
        self.ids = itertools.count(1000)
        self.errors = []
        self.followers = 120
        self.insights = True            # False: the key lacks instagram_manage_insights
        self.lose_publish_once = False  # media_publish: make the post, then answer 502
        self.fail_publish_once = False  # media_publish: answer 502 WITHOUT making the post
        self.reject_next = 0            # media_publish: refuse the next n posts (code 9004)
        self.token_dead = False         # every call: code 190 (expired)
        self.me_kind = "page"           # the key is a Page token ('page') or a user token ('user')
        self.unclear_publish_once = False   # media_publish: make the post, answer 400 code 1 (unknown error)
        self.media_list_down = False    # GET /ig1/media answers 500
        self.port = None


GS = GraphState()
TOKEN = "TESTTOKEN"
V = "/v25.0"


def _stats(seed):
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    reach = 80 + h % 900
    return {"reach": reach, "likes": h % 50, "comments": h % 7, "shares": (h >> 3) % 15,
            "saved": (h >> 7) % 25, "views": reach * 2}


def _fetch_jpeg(url):
    """Download an address the way Instagram does (no login); JPEG only."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            body = r.read()
            return body[:3] == b"\xff\xd8\xff"
    except Exception:
        return False


class Graph(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, http=400, msg="error", sub=None):
        e = {"message": msg, "type": "OAuthException", "code": code}
        if sub:
            e["error_subcode"] = sub
        return self._json(http, {"error": e})

    def _auth(self, scheme="Bearer"):
        if GS.token_dead:
            self._err(190, 400, "Error validating access token: Session has expired.", 463)
            return False
        if self.headers.get("Authorization") != f"{scheme} {TOKEN}":
            self._err(190, 400, "Invalid OAuth access token - Cannot parse access token")
            return False
        if "access_token=" in self.path:
            GS.errors.append("token sent in a URL")
        return True

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        return raw, {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self._auth():
            return
        if u.path == f"{V}/me":
            return self._json(200, {"id": "p1", "name": "Rumo - Brazilian Portuguese"} if GS.me_kind == "page"
                              else {"id": "u1", "name": "Dylan De Roode"})
        if u.path == f"{V}/p1":
            return self._json(200, {"id": "p1", "name": "Rumo - Brazilian Portuguese",
                                    "instagram_business_account": {"id": "ig1", "username": "rumo.portuguese"}})
        if u.path == f"{V}/u1":
            return self._err(100, 400, "(#100) Tried accessing nonexisting field (instagram_business_account) "
                                       "on node type (User)")
        if u.path == f"{V}/me/accounts":
            if GS.me_kind == "page":
                return self._err(100, 400, "(#100) Tried accessing nonexisting field (accounts) on node type (Page)")
            return self._json(200, {"data": [
                {"name": "Other page", "id": "p0"},
                {"name": "Rumo - Brazilian Portuguese", "id": "p1",
                 "instagram_business_account": {"id": "ig1", "username": "rumo.portuguese"}}]})
        if u.path == f"{V}/ig1":
            return self._json(200, {"id": "ig1", "username": "rumo.portuguese",
                                    "followers_count": GS.followers, "media_count": len(GS.media)})
        if u.path == f"{V}/ig1/content_publishing_limit":
            day = sum(1 for m in GS.media)
            return self._json(200, {"data": [{"quota_usage": day, "config": {"quota_total": 100}}]})
        if u.path == f"{V}/ig1/media":
            if GS.media_list_down:
                return self._json(500, {"error": {"message": "An unknown error occurred", "code": 1,
                                                  "is_transient": True}})
            rows = [{"id": m["id"], "caption": m["caption"], "timestamp": m["timestamp"],
                     "media_product_type": m["type"]} for m in reversed(GS.media)]
            return self._json(200, {"data": rows[:int(q.get("limit", 25))]})
        m = re.fullmatch(V + r"/(\w+)/insights", u.path)
        if m:
            if not GS.insights:
                return self._err(10, 403, "(#10) Application does not have permission for this action")
            med = next((x for x in GS.media if x["id"] == m.group(1)), None)
            if med is None:
                return self._err(100, 400, "Unsupported get request")
            want = q.get("metric", "").split(",")
            if med["type"] == "FEED" and "views" in want:
                # Meta's real wording names every valid metric, so the kit cannot pick the bad one out
                return self._err(100, 400, "(#100) metric[5] must be one of the following values: reach, "
                                           "saved, shares, likes, comments, total_interactions")
            st = _stats(med["caption"])
            return self._json(200, {"data": [{"name": k, "period": "lifetime", "values": [{"value": st[k]}]}
                                             for k in want if k in st]})
        m = re.fullmatch(V + r"/(\w+)", u.path)
        if m and m.group(1) in GS.containers:
            c = GS.containers[m.group(1)]
            c["polls"] += 1
            code = c["status"]
            if code == "IN_PROGRESS" and c.get("uploaded") and c["polls"] >= 2:
                c["status"] = code = "FINISHED"
            return self._json(200, {"status_code": code, "status": code, "id": m.group(1)})
        if m:
            return self._err(100, 400, "Unsupported get request. Object does not exist")
        return self._err(100, 404, "unknown path " + u.path)

    def do_POST(self):
        u = urlparse(self.path)
        rm = re.fullmatch(r"/rupload" + V + r"/(\w+)", u.path)
        if rm:
            if not self._auth("OAuth"):
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            c = GS.containers.get(rm.group(1))
            if c is None or c["kind"] != "REELS":
                return self._json(400, {"debug_info": {"message": "unknown container"}})
            if self.headers.get("offset") != "0" or self.headers.get("file_size") != str(len(body)):
                GS.errors.append("rupload headers wrong")
                return self._json(400, {"debug_info": {"message": "bad offset/file_size"}})
            if body[4:8] != b"ftyp":
                GS.errors.append("rupload body is not an MP4")
                return self._json(400, {"debug_info": {"message": "not a video"}})
            c["uploaded"] = len(body)
            return self._json(200, {"success": True, "message": "Upload successful."})
        if not self._auth():
            return
        raw, f = self._form()
        if u.path == f"{V}/ig1/media":
            known = {"image_url", "is_carousel_item", "alt_text", "caption", "media_type", "children",
                     "upload_type", "cover_url", "share_to_feed", "audio_name", "trial_params"}
            bad = set(f) - known
            if bad:
                GS.errors.append(f"unknown parameters {bad}")
                return self._err(100, 400, f"(#100) Invalid parameter {sorted(bad)}")
            cid = str(next(GS.ids))
            mt = f.get("media_type")
            if mt is None:
                if not f.get("image_url") or not _fetch_jpeg(f["image_url"]):
                    GS.errors.append("image_url not a public JPEG")
                    return self._err(9004, 400, "(#9004) Only photo or video can be accepted as media type.", 2207052)
                if len(f.get("alt_text", "")) > 1000:
                    GS.errors.append("alt_text too long")
                GS.containers[cid] = {"kind": "IMAGE", "status": "FINISHED", "polls": 0, "f": f}
                return self._json(200, {"id": cid})
            if mt == "CAROUSEL":
                kids = (f.get("children") or "").split(",")
                if not 2 <= len(kids) <= 10 or any(GS.containers.get(k, {}).get("kind") != "IMAGE"
                                                   or GS.containers[k]["f"].get("is_carousel_item") != "true"
                                                   for k in kids):
                    GS.errors.append(f"bad carousel children {kids}")
                    return self._err(100, 400, "(#100) children invalid")
                cap = f.get("caption", "")
                if len(cap) > 2200 or cap.count("#") > 30:
                    GS.errors.append("caption too long / too many hashtags")
                if not all(GS.containers[k]["f"].get("alt_text") for k in kids):
                    GS.errors.append("carousel slide without alt text")
                GS.containers[cid] = {"kind": "CAROUSEL", "status": "IN_PROGRESS", "uploaded": 1, "polls": 0,
                                      "f": f}
                return self._json(200, {"id": cid})
            if mt == "REELS":
                if f.get("upload_type") != "resumable" or not f.get("audio_name") or not f.get("caption") \
                        or (f.get("share_to_feed") != "true") == ("trial_params" not in f):
                    GS.errors.append(f"reel container fields {sorted(f)}")
                if f.get("cover_url") and not _fetch_jpeg(f["cover_url"]):
                    GS.errors.append("cover_url not a public JPEG")
                    return self._err(9004, 400, "(#9004) cover_url could not be fetched", 2207052)
                if "trial_params" in f:
                    try:
                        tp = json.loads(f["trial_params"])
                        assert tp.get("graduation_strategy") in ("MANUAL", "SS_PERFORMANCE")
                    except Exception:
                        GS.errors.append("trial_params malformed")
                GS.containers[cid] = {"kind": "REELS", "status": "IN_PROGRESS", "polls": 0, "f": f}
                return self._json(200, {"id": cid,
                                        "uri": f"http://127.0.0.1:{GS.port}/rupload{V}/{cid}"})
            GS.errors.append(f"media_type {mt}")
            return self._err(100, 400, "(#100) bad media_type")
        if u.path == f"{V}/ig1/media_publish":
            cid = f.get("creation_id")
            c = GS.containers.get(cid)
            if c is None:
                return self._err(100, 400, "(#100) creation_id invalid")
            if c["status"] == "PUBLISHED":
                GS.errors.append("a container published twice")
                return self._err(100, 400, "(#100) already published")
            if c["status"] != "FINISHED":
                GS.errors.append("published before FINISHED")
                return self._err(9007, 400, "(#9007) Media ID is not available", 2207027)
            if GS.fail_publish_once:
                GS.fail_publish_once = False
                return self._json(502, {"error": {"message": "Bad gateway", "code": 2, "is_transient": True}})
            if GS.reject_next:
                GS.reject_next -= 1
                c["status"] = "ERROR"
                return self._err(9004, 400, "(#9004) The media could not be fetched / is not supported", 2207026)
            c["status"] = "PUBLISHED"
            mid = "m" + cid
            from datetime import datetime, timezone
            GS.media.append({"id": mid, "caption": c["f"].get("caption", ""),
                             "timestamp": datetime.now(timezone.utc).isoformat(),
                             "type": "REELS" if c["kind"] == "REELS" else "FEED",
                             "trial": json.loads(c["f"]["trial_params"])["graduation_strategy"]
                             if "trial_params" in c["f"] else None, "f": c["f"]})
            if GS.unclear_publish_once:
                GS.unclear_publish_once = False
                return self._err(1, 400, "An unknown error occurred")
            if GS.lose_publish_once:
                GS.lose_publish_once = False
                return self._json(502, {"error": {"message": "Bad gateway", "code": 2}})
            return self._json(200, {"id": mid})
        return self._err(100, 404, "unknown path " + u.path)


def file_server(folder):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    return start(partial(Quiet, directory=str(folder)))


def start(handler, port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

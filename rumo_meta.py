"""Instagram posting through Meta's own Graph API (free; checked against Meta's docs, 7 Nov 2026).

Instagram API with Facebook Login. The token (META_TOKEN, a Page or system-user token with
instagram_basic, instagram_content_publish, instagram_manage_insights, pages_show_list,
pages_read_engagement) is sent only in the Authorization header, never in a URL, so it can
never appear in an error message or a log.

POST /{ig}/media  image_url, is_carousel_item, alt_text             -> {id}   (JPEG, public URL)
POST /{ig}/media  media_type=CAROUSEL, children=id,id,.., caption   -> {id}   (up to 10)
POST /{ig}/media  media_type=REELS, upload_type=resumable, caption, cover_url, share_to_feed,
                  audio_name, trial_params={"graduation_strategy": ...} -> {id, uri}
POST rupload.facebook.com/ig-api-upload/<ver>/<id>  headers offset, file_size; body = the file
GET  /{container}?fields=status_code,status    FINISHED | IN_PROGRESS | ERROR | EXPIRED | PUBLISHED
POST /{ig}/media_publish creation_id=..        -> {id}   (containers expire after 24 h)
GET  /{ig}/media?fields=id,caption,timestamp,media_product_type,permalink
GET  /{media}/insights?metric=reach,saved,shares,likes,comments,views
GET  /{ig}?fields=username,followers_count
Limits: 100 API-published posts per 24 h; the kit makes 1-2 a day.
"""
import json
import os
import time

import requests

VERSION = os.environ.get("META_VERSION", "v25.0")
BASE = os.environ.get("META_BASE", f"https://graph.facebook.com/{VERSION}").rstrip("/")
RUPLOAD = os.environ.get("META_RUPLOAD", f"https://rupload.facebook.com/ig-api-upload/{VERSION}").rstrip("/")
POLL = float(os.environ.get("RUMO_POLL", "5"))
READY_TIMEOUT = float(os.environ.get("RUMO_READY_TIMEOUT", "900"))


class MetaError(Exception):
    def __init__(self, status, body, what):
        self.status, self.what = status, what
        err = body.get("error") if isinstance(body, dict) else None
        self.code = (err or {}).get("code")
        self.subcode = (err or {}).get("error_subcode")
        self.transient = bool((err or {}).get("is_transient"))
        self.message = (err or {}).get("error_user_msg") or (err or {}).get("message") or str(body)[:300]
        super().__init__(f"{what}: HTTP {status}: {self.message} (code {self.code}"
                         + (f"/{self.subcode}" if self.subcode else "") + ")")

    @property
    def token_problem(self):
        return self.code == 190 or self.status == 401

    @property
    def permission_problem(self):
        return self.code in (10, 200, 3) or (isinstance(self.code, int) and 200 <= self.code <= 299)

    @property
    def unclear(self):
        """The request may or may not have done its work (a post may exist): never assume either."""
        return self.status == 0 or self.status >= 500 or self.transient or self.code in (1, 2, -1, -2)

    @property
    def gone(self):
        """The object does not exist (a container Meta never made, or one long expired)."""
        return self.code == 100 and self.subcode in (None, 33) and "not exist" in (self.message or "")

    @property
    def rate_limited(self):
        return self.code in (4, 17, 32, 613, 9) or self.status == 429


class Meta:
    def __init__(self, token, ig_id=None):
        if not token:
            raise MetaError(0, {"error": {"message": "META_TOKEN is empty", "code": 190}}, "token")
        self._token = token
        self.ig = ig_id

    # ------------------------------------------------------------ plumbing
    def _h(self, extra=None):
        h = {"Authorization": f"Bearer {self._token}"}
        h.update(extra or {})
        return h

    def _req(self, method, path, what, safe=True, base=None, timeout=120, **kw):
        """safe=False for calls that create or publish: never retried after the request may
        have reached Meta (a timeout or a 5xx), because the post could already exist."""
        url = (base or BASE) + path
        headers = self._h(kw.pop("headers", None))
        last = None
        for attempt in range(5):
            try:
                r = requests.request(method, url, headers=headers, timeout=timeout, **kw)
            except requests.RequestException as e:
                last = MetaError(0, {"error": {"message": type(e).__name__}}, what)   # no URL, no token
                if not safe:
                    raise last
                time.sleep(3 * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError:
                body = {"error": {"message": r.text[:300]}}
            if r.status_code < 400 and not (isinstance(body, dict) and "error" in body):
                return body
            err = MetaError(r.status_code, body, what)
            if err.rate_limited:
                last = err
                if not safe:
                    raise err   # refused before anything was made; the caller decides
                time.sleep(30 * (attempt + 1))
                continue
            if safe and (r.status_code >= 500 or err.transient):
                last = err
                time.sleep(5 * (attempt + 1))
                continue
            raise err
        raise last

    # ------------------------------------------------------------ account
    def find_account(self):
        """The Instagram professional account behind the token's Facebook Page(s).
        A Page token: 'me' is the Page itself. A user or system-user token: 'me/accounts' lists Pages."""
        fields = "name,instagram_business_account{id,username}"
        me = self._req("GET", "/me", "read the key's owner", params={"fields": "id,name"})
        try:
            page = self._req("GET", f"/{me['id']}", "read the Page", params={"fields": fields})
            if page.get("instagram_business_account"):
                return [(page.get("name"), page["instagram_business_account"])]
        except MetaError as e:
            if e.token_problem:
                raise
        data = self._req("GET", "/me/accounts", "list Facebook Pages", params={"fields": fields, "limit": 50})
        return [(p.get("name"), p["instagram_business_account"]) for p in data.get("data", [])
                if isinstance(p, dict) and p.get("instagram_business_account")]

    def profile(self):
        return self._req("GET", f"/{self.ig}", "read the Instagram account",
                         params={"fields": "id,username,followers_count,media_count"})

    def followers(self):
        try:
            v = self.profile().get("followers_count")
            return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None
        except (MetaError, ValueError, TypeError):
            return None

    def quota(self):
        try:
            d = self._req("GET", f"/{self.ig}/content_publishing_limit", "publishing limit",
                          params={"fields": "quota_usage,config"})
            row = (d.get("data") or [{}])[0]
            return row.get("quota_usage"), (row.get("config") or {}).get("quota_total")
        except MetaError:
            return None, None

    # ------------------------------------------------------------ containers
    def image(self, url, alt=None, child=False, caption=None):
        data = {"image_url": url}
        if child:
            data["is_carousel_item"] = "true"
        if alt:
            data["alt_text"] = alt[:1000]
        if caption:
            data["caption"] = caption
        try:
            return self._req("POST", f"/{self.ig}/media", "create image container", safe=False, data=data)["id"]
        except MetaError as e:   # a 400 makes nothing; if alt text is the problem, post without it
            if e.code == 100 and "alt_text" in (e.message or "") and "alt_text" in data:
                data.pop("alt_text")
                return self._req("POST", f"/{self.ig}/media", "create image container", safe=False,
                                 data=data)["id"]
            raise

    def carousel(self, children, caption):
        return self._req("POST", f"/{self.ig}/media", "create carousel container", safe=False,
                         data={"media_type": "CAROUSEL", "children": ",".join(children),
                               "caption": caption})["id"]

    def reel(self, caption, cover_url=None, trial=None, audio_name="Rumo - original music"):
        data = {"media_type": "REELS", "upload_type": "resumable", "caption": caption, "audio_name": audio_name}
        if not trial:            # a trial Reel is shown to non-followers first: not shared to the grid
            data["share_to_feed"] = "true"
        if cover_url:
            data["cover_url"] = cover_url
        if trial:
            data["trial_params"] = json.dumps({"graduation_strategy": trial})
        d = self._req("POST", f"/{self.ig}/media", "create Reel container", safe=False, data=data)
        return d["id"], d.get("uri")

    def upload_video(self, container, path, uri=None):
        """Resumable upload of a local file. Safe to repeat: Meta resumes from `offset`."""
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            blob = f.read()
        url = uri or f"{RUPLOAD}/{container}"
        last = None
        for attempt in range(4):
            try:
                r = requests.post(url, data=blob, timeout=900,
                                  headers={"Authorization": f"OAuth {self._token}", "offset": "0",
                                           "file_size": str(size)})
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code < 400 and (body.get("success") is not False):
                    return body
                last = MetaError(r.status_code, body or {"error": {"message": r.text[:300]}}, "upload the Reel video")
                if r.status_code < 500:
                    raise last
            except requests.RequestException as e:
                last = MetaError(0, {"error": {"message": type(e).__name__}}, "upload the Reel video")
            time.sleep(10 * (attempt + 1))
        raise last

    def status(self, container):
        d = self._req("GET", f"/{container}", "container status", params={"fields": "status_code,status"})
        return str(d.get("status_code") or "").upper(), d.get("status")

    def wait_ready(self, container, what):
        t0 = time.time()
        while True:
            code, detail = self.status(container)
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise MetaError(400, {"error": {"message": f"{code}: {detail}"}}, what)
            if code == "PUBLISHED":
                return
            if time.time() - t0 > READY_TIMEOUT:
                raise MetaError(0, {"error": {"message": f"still {code or 'processing'} after "
                                                         f"{READY_TIMEOUT:.0f}s"}}, what)
            time.sleep(POLL)

    def publish(self, container):
        return self._req("POST", f"/{self.ig}/media_publish", "publish", safe=False,
                         data={"creation_id": container})["id"]

    # ------------------------------------------------------------ reading back
    def recent_media(self, limit=25):
        d = self._req("GET", f"/{self.ig}/media", "list recent posts",
                      params={"fields": "id,caption,timestamp,media_product_type,permalink", "limit": limit})
        return d.get("data", [])

    def insights(self, media_id):
        """Lifetime numbers of one post: reach, saves, shares, likes, comments, views (None = not given).
        If Meta refuses the set (code 100: a metric not offered for this kind of post), each metric
        is asked on its own and the refused ones are left out."""
        want = ["reach", "saved", "shares", "likes", "comments", "views"]

        def ask(metrics):
            d = self._req("GET", f"/{media_id}/insights", "post results", params={"metric": ",".join(metrics)})
            got = {}
            for row in d.get("data", []):
                vals = row.get("values") or []
                v = vals[0].get("value") if vals else (row.get("total_value") or {}).get("value")
                got[row.get("name")] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
            return got
        try:
            out = ask(want)
        except MetaError as e:
            if e.code != 100:
                raise
            out = {}
            for m in want:
                try:
                    out.update(ask([m]))
                except MetaError as e2:
                    if e2.code != 100:
                        raise
        return {"reach": out.get("reach"), "saves": out.get("saved"), "shares": out.get("shares"),
                "likes": out.get("likes"), "comments": out.get("comments"), "views": out.get("views")}

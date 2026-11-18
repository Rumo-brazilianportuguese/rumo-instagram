"""Public addresses for slides and Reel covers, and saving the kit's progress, on a free runner
(GitHub Actions or GitLab CI).

Instagram's API takes images only from a public address (JPEG). The kit puts each post's files
on a separate branch, `media`, which is replaced every time (so the repository never grows),
and hands Instagram the raw address of that exact commit. The repository must be public.
Reel videos are uploaded straight from the runner, so they never need an address.

After a run, posts.json, config.json, DONE.txt and FAILED.txt are committed back, so the next
run knows what went out. Commits say [skip ci] so they never start another run.
"""
import os
import re
import shutil
import subprocess
import time
from urllib.parse import quote

from rumo_common import ROOT, fail, say

BOT = {"GIT_AUTHOR_NAME": "Rumo kit", "GIT_AUTHOR_EMAIL": "rumo-kit@users.noreply.github.com",
       "GIT_COMMITTER_NAME": "Rumo kit", "GIT_COMMITTER_EMAIL": "rumo-kit@users.noreply.github.com"}


def ci():
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github"
    if os.environ.get("GITLAB_CI") == "true":
        return "gitlab"
    return None


def scrub(text):
    """Never let a credential inside a git URL reach a log, FAILED.txt or an issue."""
    return re.sub(r"://[^/@\s]+@", "://***@", text or "")


def _git(*args, env=None, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, errors="replace",
                       env=dict(os.environ, **BOT, **(env or {})))
    if check and r.returncode:
        raise RuntimeError(f"git {args[0]} failed: {scrub((r.stderr or r.stdout).strip()[-400:])}")
    return r.stdout.strip()


def raw_url(sha, path):
    tpl = os.environ.get("RUMO_RAW_BASE")
    if tpl:
        return tpl.format(sha=sha, path=quote(path))
    if ci() == "github":
        return f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/{quote(path)}"
    if ci() == "gitlab":
        return f"{os.environ['CI_SERVER_URL']}/{os.environ['CI_PROJECT_PATH']}/-/raw/{sha}/{quote(path)}"
    raise RuntimeError("no runner")


def _push_media(files, label):
    """One commit holding only these files, force-pushed as branch `media`."""
    idx = ROOT / ".git" / "rumo-media-index"
    env = {"GIT_INDEX_FILE": str(idx)}
    _git("read-tree", "--empty", env=env)
    dests = {}
    for f in files:
        blob = _git("hash-object", "-w", str(ROOT / f))
        dest = f"m/{label}/{os.path.basename(f)}"
        _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{dest}", env=env)
        dests[f] = dest
    tree = _git("write-tree", env=env)
    commit = _git("commit-tree", tree, "-m", f"media for {label} [skip ci]")
    idx.unlink(missing_ok=True)
    for attempt in range(3):
        r = subprocess.run(["git", "push", "--force", "origin", f"{commit}:refs/heads/media"], cwd=ROOT,
                           capture_output=True, text=True, errors="replace", env=dict(os.environ, **BOT))
        if r.returncode == 0:
            return {f: raw_url(commit, d) for f, d in dests.items()}
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"git push of the media branch failed: {scrub((r.stderr or r.stdout).strip()[-400:])}")


def _copy_dir(files, label):
    """Tests: copy into a folder that a local web server shows."""
    base = os.environ["RUMO_HOST_DIR"]
    out = {}
    for f in files:
        dest = os.path.join(base, "m", label, os.path.basename(f))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(ROOT / f, dest)
        out[f] = os.environ["RUMO_HOST_URL"].rstrip("/") + f"/m/{quote(label)}/{quote(os.path.basename(f))}"
    return out


def host(files, label):
    """files: paths relative to the kit folder. Returns {path: public URL}; checks that a
    stranger (Instagram) can actually open the first one before anything is posted."""
    import requests
    mode = os.environ.get("RUMO_HOST") or ("git" if ci() else "")
    try:
        if mode == "dir":
            urls = _copy_dir(files, label)
        elif mode == "git":
            urls = _push_media(files, label)
        else:
            fail("public images", "Carousel slides need a public web address, and this computer has none.",
                 "Posting runs on the free runner (GitHub or GitLab), not on this computer. "
                 "Use the runner's 'Run workflow' button instead.")
    except RuntimeError as e:
        fail("public images", str(e), "Run the workflow again. If it repeats, tell Claude.")
    first = urls[files[0]]
    last = None
    for attempt in range(12):            # a fresh push can take a few seconds to be served
        try:
            r = requests.get(first, timeout=30)      # no login: exactly what Instagram sees
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ("image/" in ctype or ctype.startswith("application/octet")):
                return urls
            last = f"HTTP {r.status_code} {ctype}"
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(5)
    fail("public images", f"Instagram could not open the slide's address ({last}).",
         "The repository must be PUBLIC (Settings > General > Danger zone > Change visibility > Public). "
         "Your Instagram key is not in it: it is in the runner's locked secret store. Then run again.")


def persist(msg):
    """Commit the kit's progress back to the repository (runner only). Returns False if it
    could not be saved. Only one run writes at a time (the workflow's concurrency group, and
    every run starts from the latest commit), so a rejected push means someone edited the
    repository meanwhile: the kit then rebases once, and if that conflicts it gives up cleanly
    (never commits a half-merged file)."""
    if not ci():
        return True
    branch = os.environ.get("GITHUB_REF_NAME") or os.environ.get("CI_COMMIT_BRANCH") \
        or os.environ.get("CI_DEFAULT_BRANCH") or "main"
    try:
        if (ROOT / ".git" / "rebase-merge").exists() or (ROOT / ".git" / "rebase-apply").exists():
            _git("rebase", "--abort", check=False)
        _git("add", "-A")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
            _git("commit", "-m", f"{msg} [skip ci]")
        for attempt in range(3):
            r = subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=ROOT,
                               capture_output=True, text=True, errors="replace", env=dict(os.environ, **BOT))
            if r.returncode == 0:
                return True
            p = subprocess.run(["git", "pull", "--rebase", "origin", branch], cwd=ROOT, capture_output=True,
                               text=True, errors="replace", env=dict(os.environ, **BOT))
            if p.returncode != 0:
                _git("rebase", "--abort", check=False)
                say("WARNING: progress could not be saved (the repository was changed meanwhile and the "
                    "changes clash): " + scrub((p.stderr or p.stdout)[-300:]))
                return False
            time.sleep(5 * (attempt + 1))
        say("WARNING: progress could not be saved to the repository: " + scrub((r.stderr or "")[-300:]))
        return False
    except RuntimeError as e:
        say(f"WARNING: progress could not be saved to the repository: {e}")
        return False

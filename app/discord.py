"""Discord side of ChatVoice: cloud calls, !link claims, activity reporting, and webhook posts."""
import json
import re
import threading
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Signal

from .platforms import youtube_id

LINK_RX = re.compile(r"^!link\s+([A-Za-z0-9]{4}-[A-Za-z0-9]{4})\s*$", re.I)
UA = "ChatVoice/0.2 (+desktop app)"


class Bridge(QObject):
    done = Signal(str, object)      # tag, result dict


def run_bg(bridge, tag, fn):
    """Run a blocking call in a thread and deliver its result to the UI thread."""
    def work():
        try:
            res = fn()
        except Exception as e:
            res = {"error": str(e)[:120]}
        bridge.done.emit(tag, res)
    threading.Thread(target=work, daemon=True).start()


def _http(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": "HTTP %d" % e.code}
    except Exception as e:
        return {"error": "Cannot reach server (%s)" % str(e)[:60]}


class Cloud:
    def __init__(self, settings):
        self.s = settings

    @property
    def base(self):
        return self.s.get("cloud_url").strip().rstrip("/")

    @property
    def configured(self):
        return bool(self.base and self.s.get("cloud_token").strip())

    def call(self, method, path, body=None):
        if not self.configured:
            return {"error": "Enter the cloud address and server key first"}
        return _http(method, self.base + path,
                     {"Authorization": "Bearer " + self.s.get("cloud_token").strip(),
                      "Content-Type": "application/json", "User-Agent": UA}, body if method != "GET" else None)


def post_webhook(url, content="", embed=None):
    """Post either simple content or a Discord embed to a webhook."""
    url = (url or "").strip()
    if not re.match(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/", url):
        return {"error": "That does not look like a Discord webhook link"}
    payload = {
        "username": "ChatVoice",
        "allowed_mentions": {"parse": []},
    }
    if content:
        payload["content"] = content[:1900]
    if embed:
        payload["embeds"] = [embed]
    res = _http("POST", url, {"Content-Type": "application/json", "User-Agent": UA}, payload)
    return res


def normalize_youtube_url(value):
    """Return a normal YouTube watch URL when the input is a video/live URL or 11-char ID."""
    value = (value or "").strip()
    if not value:
        return ""
    vid = youtube_id(value)
    return "https://www.youtube.com/watch?v=%s" % vid if vid else value


def post_live_announcement(url, message, youtube_link):
    """Post a rich live announcement with a clickable YouTube embed and custom message."""
    link = normalize_youtube_url(youtube_link)
    if not link:
        return {"error": "Enter a YouTube live link or video ID first"}
    msg = (message or "I'm live! Come hang out").strip()
    embed = {
        "title": "🔴 LIVE NOW",
        "description": msg[:4096],
        "url": link,
        "color": 0xFF0000,
        "fields": [
            {"name": "Watch on YouTube", "value": "[▶ Open the live stream](%s)" % link, "inline": False}
        ],
        "footer": {"text": "ChatVoice • Live announcement"},
    }
    return post_webhook(url, embed=embed)


class LinkManager(QObject):
    """Handles '!link CODE' in chat. Counts linked viewers locally and asks the cloud for a role
    only when a viewer reaches a threshold (so almost nothing is written to the free cloud storage)."""
    notice = Signal(str)

    def __init__(self, settings, cloud, bridge, counts_path=None):
        super().__init__()
        self.s, self.cloud, self.bridge = settings, cloud, bridge
        self.linked = set()
        self.counts_path = counts_path
        self.counts = {}
        self.retry_at = {}
        self.inflight = set()
        self.dirty = False
        self._load()
        bridge.done.connect(self.on_done)

    def _load(self):
        try:
            with open(self.counts_path, encoding="utf-8") as f:
                self.counts = json.load(f)
        except Exception:
            self.counts = {}

    def save(self):
        if not self.dirty or not self.counts_path:
            return
        try:
            with open(self.counts_path, "w", encoding="utf-8") as f:
                json.dump(self.counts, f)
            self.dirty = False
        except Exception:
            pass

    flush = save

    def handle(self, m, now=None):
        """Count activity / detect link codes. Returns True if the message was a link attempt."""
        if not self.cloud.configured or not m.uid or m.platform in ("test", "tip"):
            return False
        mt = LINK_RX.match(m.text.strip())
        if mt and m.kind == "chat":
            code, name, plat, uid = mt.group(1).upper(), m.author, m.platform, m.uid
            run_bg(self.bridge, "claim|%s|%s" % (name, plat),
                   lambda: self.cloud.call("POST", "/api/claim", {"code": code, "platform": plat, "uid": uid, "name": name}))
            return True
        key = "%s:%s" % (m.platform, m.uid)
        if key in self.linked:
            c = self.counts.setdefault(key, {"msgs": 0, "paid": 0, "regular": False, "supporter": False})
            c["msgs"] += 1
            if m.kind == "super":
                c["paid"] += 1
            self.dirty = True
            self._check(key, c, time.time() if now is None else now)
        return False

    def _check(self, key, c, now):
        want = []
        if self.s.get("role_regular") and not c["regular"] and c["msgs"] >= int(self.s.get("regular_msgs")):
            want.append("regular")
        if self.s.get("role_supporter") and not c["supporter"] and c["paid"] >= 1:
            want.append("supporter")
        for role in want:
            if (key, role) in self.inflight or now < self.retry_at.get((key, role), 0):
                continue
            self.inflight.add((key, role))
            plat, uid = key.split(":", 1)
            run_bg(self.bridge, "grant|%s|%s" % (key, role),
                   lambda plat=plat, uid=uid, role=role: self.cloud.call("POST", "/api/grant", {"platform": plat, "uid": uid, "role": role}))

    def refresh(self):
        if self.cloud.configured:
            run_bg(self.bridge, "links", lambda: self.cloud.call("GET", "/api/links"))

    def on_done(self, tag, res):
        if tag == "links":
            if "keys" in res:
                self.linked = set(res["keys"])
        elif tag.startswith("claim|"):
            _, name, plat = tag.split("|", 2)
            if res.get("ok"):
                self.linked.add(res["key"])
                extra = "" if res.get("roleGranted") else " (no Verified role given - check Discord page)"
                self.notice.emit("Linked %s (%s) to Discord user %s%s" % (name, plat, res.get("discordName", "?"), extra))
            else:
                self.notice.emit("Link failed for %s: %s" % (name, res.get("error", "unknown error")))
        elif tag.startswith("grant|"):
            _, key, role = tag.split("|", 2)
            self.inflight.discard((key, role))
            if res.get("ok"):
                self.counts.setdefault(key, {"msgs": 0, "paid": 0, "regular": False, "supporter": False})[role] = True
                self.dirty = True
                self.save()
                self.notice.emit("Gave the %s role to %s" % (role, key.split(":", 1)[0] + " viewer"))
            else:
                self.retry_at[(key, role)] = time.time() + 600
                hint = " - move the ChatVoice role above it in Discord" if res.get("status") == 403 else ""
                self.notice.emit("Could not give the %s role (%s)%s" % (role, res.get("error") or res.get("status"), hint))

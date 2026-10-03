"""Update check and one-click update, using GitHub Releases (free, no server of our own)."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

from .version import VERSION

GH_API = "https://api.github.com"
DL_PREFIX = "https://github.com/{repo}/releases/download/"


def parse_version(v):
    nums = [int(x) for x in re.findall(r"\d+", v or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


class Updater(QObject):
    found = Signal(object)        # {"version", "page", "asset", "digest", "notes"}
    message = Signal(str)
    status = Signal(str)          # manual check: nothing to install, or the check failed
    progress = Signal(str)
    quit_now = Signal()
    _evt = Signal(str, object)    # from worker threads

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.frozen = bool(getattr(sys, "frozen", False))      # only the installed app can replace itself
        self.busy = False
        self._evt.connect(self._on_evt)

    # ----- check -----
    def check(self, manual=False):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._check, args=(manual,), daemon=True).start()

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "ChatVoice-updater", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def _check(self, manual):
        repo = self.s.get("update_repo").strip()
        try:
            d = self._fetch("%s/repos/%s/releases/latest" % (GH_API, repo))
            self.s.set("update_last", int(time.time()))
            tag = d.get("tag_name", "")
            if parse_version(tag) <= parse_version(VERSION):
                if manual:
                    self._evt.emit("status", "There is not any update at all. Wait for the devs to update the app.")
                return
            asset = next((a for a in d.get("assets", []) if a.get("name", "").lower().endswith("setup.exe")), None)
            self._evt.emit("found", {"version": tag.lstrip("v"), "page": d.get("html_url", ""),
                                     "asset": asset.get("browser_download_url", "") if asset else "",
                                     "digest": (asset or {}).get("digest", ""), "notes": (d.get("body") or "")[:300]})
        except Exception as e:
            if manual:
                self._evt.emit("status", "Could not check for updates (%s)" % str(e)[:60])
        finally:
            self._evt.emit("idle", None)

    # ----- install -----
    def install(self, info):
        asset = info.get("asset", "")
        if not asset.startswith(DL_PREFIX.format(repo=self.s.get("update_repo").strip())):
            self.message.emit("The update file is not from your GitHub repository, so it was not downloaded.")
            return
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._download, args=(info,), daemon=True).start()

    def _download(self, info):
        path = os.path.join(tempfile.gettempdir(), "ChatVoice-Setup-%s.exe" % info["version"])
        try:
            req = urllib.request.Request(info["asset"], headers={"User-Agent": "ChatVoice-updater"})
            sha, done = hashlib.sha256(), 0
            with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if total:
                        self._evt.emit("progress", "Downloading update... %d%%" % (done * 100 // total))
            want = (info.get("digest") or "").lower()
            if want.startswith("sha256:") and want[7:] != sha.hexdigest():
                os.remove(path)
                self._evt.emit("note", "The downloaded update did not match GitHub's checksum, so it was discarded.")
                return
            self._evt.emit("ready", path)
        except Exception as e:
            self._evt.emit("note", "Update download failed (%s)" % str(e)[:60])
        finally:
            self._evt.emit("idle", None)

    def launch(self, path):
        flags = 0x00000008 if sys.platform == "win32" else 0        # DETACHED_PROCESS
        subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True, creationflags=flags)

    def _on_evt(self, kind, data):
        if kind == "found":
            self.found.emit(data)
        elif kind == "note" and data:
            self.message.emit(data)
        elif kind == "status" and data:
            self.status.emit(data)
        elif kind == "progress":
            self.progress.emit(data)
        elif kind == "idle":
            self.busy = False
        elif kind == "ready":
            self.progress.emit("Installing update...")
            self.launch(data)
            self.quit_now.emit()

"""ChatVoice main window. Animations only run on interaction, so idle CPU stays near zero."""
import html
import os
import sys
import time

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QStackedWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from . import hinglish
from .discord import Bridge, Cloud, LinkManager
from .discord_page import DiscordPage
from .overlay import Overlay
from .overlay_ui import OverlayPage
from .payments import TipPoller
from .payments_page import PaymentsPage
from .ytmod import GoogleAuth, YtModerator
from .ytmod_page import YtModPage
from .models import Message
from .moderation import Moderator
from .platforms import Hub, KickSource, TwitchSource, YouTubeSource
from .settings import Settings, data_dir
from .speech import VOICES, Speaker
from .theme import DEFAULT_THEME, FX, THEMES, build_qss
from .updater import Updater
from .version import CREATOR, STAGE, VERSION, label

COLORS = {"youtube": "#ff4d4d", "twitch": "#9146ff", "kick": "#53fc18", "test": "#00d4ff", "tip": "#ffd24d"}
TAGS = {"youtube": "YT", "twitch": "TW", "kick": "KICK", "test": "TEST", "tip": "TIP"}
PAGES = ("Connect", "Live chat", "Voice", "Moderation", "Discord", "Payments", "YouTube mod", "OBS overlays")
ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def esc(s):
    return html.escape(s or "")


def labeled(text, widget, hint=""):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lab = QLabel(text)
    lab.setMinimumWidth(190)
    lay.addWidget(lab)
    lay.addWidget(widget, 1)
    if hint:
        h = QLabel(hint)
        h.setObjectName("hint")
        lay.addWidget(h)
    return w


class PlatformCard(QFrame):
    def __init__(self, key, title, placeholder, source, settings, extra=None):
        super().__init__()
        self.setObjectName("card")
        self.key, self.source, self.s = key, source, settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        head = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:#4a5168; font-size:16px;")
        name = QLabel(title)
        name.setStyleSheet("font-size:15px; font-weight:600;")
        head.addWidget(self.dot)
        head.addWidget(name)
        head.addStretch(1)
        self.status = QLabel("Not connected")
        self.status.setObjectName("sub")
        head.addWidget(self.status)
        lay.addLayout(head)
        row = QHBoxLayout()
        self.edit = QLineEdit(settings.get(key))
        self.edit.setPlaceholderText(placeholder)
        row.addWidget(self.edit, 1)
        self.btn = QPushButton("Connect")
        self.btn.setObjectName("primary")
        self.btn.setMinimumWidth(110)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.extra = None
        if extra:
            self.extra = QLineEdit(settings.get(extra[0]))
            self.extra.setPlaceholderText(extra[1])
            lay.addWidget(self.extra)
        self.btn.clicked.connect(self.toggle)
        self.edit.returnPressed.connect(self.toggle)

    def args(self):
        self.s.set(self.key, self.edit.text().strip())
        if self.extra is not None:
            self.s.set("kick_room", self.extra.text().strip())
            return (self.edit.text().strip(), self.extra.text().strip())
        return (self.edit.text().strip(),)

    def toggle(self):
        if self.source.running:
            self.source.stop()
            self.status.setText("Stopping...")
        else:
            self.source.start(*self.args())

    def set_status(self, text, ok):
        self.status.setText(text)
        self.dot.setStyleSheet("color:%s; font-size:16px;" % ("#3ddc84" if ok else "#ffb020" if "..." in text else "#4a5168"))
        running = self.source.running
        self.btn.setText("Disconnect" if running else "Connect")
        self.btn.setObjectName("stop" if running else "primary")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("ChatVoice (%s) \u2014 by %s" % (STAGE, CREATOR))
        self.resize(1000, 660)
        self.setMinimumSize(860, 620)
        self.s = Settings()
        self.hub = Hub()
        self.speaker = Speaker(self.s)
        self.words_path = os.path.join(data_dir(), "hinglish_words.txt")
        self.blocked_path = os.path.join(data_dir(), "blocked_words.txt")
        hinglish.load_words(self.words_path)
        hinglish.on_unknown = self._unknown_word
        self.mod = Moderator(self.s, self.blocked_path)
        self.connected = set()
        self._anims = []
        self._anim_targets = []
        self.fx = FX()
        self.fx.enabled = not bool(self.s.get("lite_mode"))
        self.bridge = Bridge()
        self.cloud = Cloud(self.s)
        self.links = LinkManager(self.s, self.cloud, self.bridge, os.path.join(data_dir(), "counts.json"))
        self.discord = DiscordPage(self.s, self.cloud, self.bridge, self.links)
        self.poller = TipPoller(self.s, self.cloud, self.bridge)
        self.payments = PaymentsPage(self.s, self.cloud, self.bridge, self.poller)
        self.gauth = GoogleAuth(self.s)
        self.ytmod = YtModerator(self.s, self.gauth, self.bridge)
        self.ytpage = YtModPage(self.s, self.gauth, self.bridge, self.ytmod)
        self.overlay = Overlay(self.s, os.path.join(ROOT, "assets", "fonts"), self._overlay_cfg)
        self.overlay.start()
        self.ovpage = OverlayPage(self.s, self.overlay)
        self.updater = Updater(self.s)
        self.pending_update = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(26, 20, 26, 20)
        right.addLayout(self._build_topbar())
        self.banner = self._build_banner()
        right.addWidget(self.banner)
        self.stack = QStackedWidget()
        for page in (self._page_connect(), self._page_feed(), self._page_voice(), self._page_mod(), self.discord, self.payments, self.ytpage, self.ovpage):
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)

        self.hub.message.connect(self.on_message)
        self.hub.status.connect(self.on_status)
        self.speaker.note.connect(lambda t: self.feed.append("<span style='color:#ffb020'>%s</span>" % esc(t)))
        self.links.notice.connect(lambda t: self.feed.append("<span style='color:#7c9cff'>Discord: %s</span>" % esc(t)))
        self.sync = QTimer(self)                      # report activity to Discord once a minute
        self.sync.timeout.connect(self.links.save)
        self.sync.start(60000)
        self.relink = QTimer(self)                    # refresh the list of linked viewers every 5 minutes
        self.relink.timeout.connect(self.links.refresh)
        self.relink.start(300000)
        QTimer.singleShot(2000, self.links.refresh)
        self.poller.tip.connect(self.on_tip)
        self.poller.notice.connect(lambda t: self.feed.append("<span style='color:#ffd24d'>%s</span>" % esc(t)))
        self.ytmod.notice.connect(lambda t: self.feed.append("<span style='color:#ff8a5c'>YouTube mod: %s</span>" % esc(t)))
        QTimer.singleShot(2500, self.poller.apply)
        self.updater.found.connect(self._update_found)
        self.updater.status.connect(self._update_status)
        self.updater.message.connect(lambda t: self.feed.append("<span style='color:#7cf0c0'>Update: %s</span>" % esc(t)))
        self.updater.progress.connect(self.banner_text.setText)
        self.updater.quit_now.connect(lambda: QTimer.singleShot(400, QApplication.quit))
        QTimer.singleShot(6000, self._auto_update)
        for b in self.findChildren(QPushButton):
            if b.objectName() != "nav":
                self.fx.attach(b)
        self.apply_theme(self.s.get("theme"))
        self.goto(0)

    # ---------- layout ----------
    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(190)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 18, 0, 18)
        self.logo = QLabel("🎙  ChatVoice")
        self.logo.setObjectName("logo")
        lay.addWidget(self.logo)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, name in enumerate(PAGES):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            lay.addWidget(b)
        self.nav.idClicked.connect(self.goto)
        lay.addStretch(1)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 0, 16, 6)
        bl.setSpacing(6)
        theme = QComboBox()
        theme.addItems(list(THEMES))
        theme.setCurrentText(self.s.get("theme") if self.s.get("theme") in THEMES else DEFAULT_THEME)
        theme.currentTextChanged.connect(self.apply_theme)
        lab = QLabel("Theme")
        lab.setObjectName("hint")
        bl.addWidget(lab)
        bl.addWidget(theme)
        lite = QCheckBox("Lite mode")
        lite.setToolTip("Turns off glow and fade animations. Use it on slow PCs or while gaming.")
        lite.setChecked(bool(self.s.get("lite_mode")))
        lite.toggled.connect(self._lite)
        bl.addWidget(lite)
        upd = QPushButton("Check for updates")
        upd.clicked.connect(lambda: self.updater.check(True))
        bl.addWidget(upd)
        lay.addWidget(box)
        ver = QLabel(label())
        ver.setObjectName("hint")
        ver.setContentsMargins(16, 0, 0, 0)
        by = QLabel("by <b>%s</b>" % CREATOR)
        by.setObjectName("hint")
        by.setContentsMargins(16, 0, 0, 0)
        lay.addWidget(ver)
        lay.addWidget(by)
        return side

    def _build_banner(self):
        b = QFrame()
        b.setObjectName("banner")
        lay = QHBoxLayout(b)
        lay.setContentsMargins(16, 8, 12, 8)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        lay.addWidget(self.banner_text, 1)
        self.upd_btn = QPushButton("Update now")
        self.upd_btn.setObjectName("primary")
        self.upd_btn.clicked.connect(self._update_now)
        later = QPushButton("Later")
        later.clicked.connect(b.hide)
        lay.addWidget(self.upd_btn)
        lay.addWidget(later)
        b.hide()
        return b

    def _update_found(self, info):
        self.pending_update = info
        self.banner_text.setText("A new version is available: %s (you have %s)" % (info["version"], VERSION))
        self.upd_btn.setEnabled(True)
        self.upd_btn.show()
        self.banner.show()

    def _update_status(self, text):
        self.pending_update = None
        self.banner_text.setText(text)
        self.upd_btn.hide()
        self.banner.show()

    def _update_now(self):
        info = self.pending_update
        if not info:
            return
        if not info.get("asset"):
            self.feed.append("<span style='color:#7cf0c0'>Update: No installer file is attached to this release yet.</span>")
            return
        self.banner_text.setText("Downloading update...")
        self.upd_btn.setEnabled(False)
        self.updater.install(info)

    def _auto_update(self):
        if self.s.get("auto_update_check") and time.time() - float(self.s.get("update_last") or 0) > 20 * 3600:
            self.updater.check(False)

    def _overlay_cfg(self):
        t = THEMES.get(self.s.get("theme"), THEMES[DEFAULT_THEME])
        return {"colors": {"a1": t["a1"], "a2": t["a2"], "a3": t["a3"]}, "sound": bool(self.s.get("ov_sound")),
                "seconds": int(self.s.get("ov_seconds")), "showMessage": bool(self.s.get("ov_show_message")),
                "chatSeconds": int(self.s.get("ov_chat_seconds")), "maxLines": 8}

    def _build_topbar(self):
        bar = QHBoxLayout()
        self.title = QLabel("Connect")
        self.title.setObjectName("title")
        bar.addWidget(self.title)
        self.live = QLabel("● LIVE")
        self.live.setObjectName("live")
        self.live_fx = QGraphicsOpacityEffect(self.live)
        self.live.setGraphicsEffect(self.live_fx)
        self.live.hide()
        self.pulse = QPropertyAnimation(self.live_fx, b"opacity", self)
        self.pulse.setDuration(1600)
        self.pulse.setKeyValueAt(0, 1.0)
        self.pulse.setKeyValueAt(0.5, 0.35)
        self.pulse.setKeyValueAt(1, 1.0)
        self.pulse.setLoopCount(-1)
        bar.addWidget(self.live)
        bar.addStretch(1)
        self.mute_btn = QPushButton("🔇  Mute")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setChecked(bool(self.s.get("muted")))
        self.mute_btn.toggled.connect(self._mute)
        skip = QPushButton("⏭  Skip")
        skip.clicked.connect(self.speaker.skip)
        test = QPushButton("▶  Test voice")
        test.clicked.connect(self.test_voice)
        for b in (self.mute_btn, skip, test):
            bar.addWidget(b)
        return bar

    def _page_connect(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(14)
        intro = QLabel("Paste your stream details and press Connect. No passwords or API keys needed.")
        intro.setObjectName("sub")
        lay.addWidget(intro)
        self.cards = {
            "youtube": PlatformCard("youtube", "YouTube Live", "Live stream link or video ID", YouTubeSource(self.hub), self.s),
            "twitch": PlatformCard("twitch", "Twitch", "Channel name", TwitchSource(self.hub), self.s),
            "kick": PlatformCard("kick", "Kick", "Channel name", KickSource(self.hub), self.s,
                                 extra=("kick_room", "Chatroom ID (only if the lookup fails)")),
        }
        for c in self.cards.values():
            lay.addWidget(c)
        lay.addStretch(1)
        return page

    def _page_feed(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        self.feed = QTextEdit()
        self.feed.setReadOnly(True)
        self.feed.document().setMaximumBlockCount(300)
        self.feed.setPlaceholderText("Chat messages appear here. Grey lines were skipped by moderation.")
        lay.addWidget(self.feed)
        return page

    def _bind_check(self, text, key):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.s.get(key)))
        cb.toggled.connect(lambda v: self.s.set(key, v))
        return cb

    def _bind_slider(self, key, lo, hi):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(int(self.s.get(key)))
        sl.valueChanged.connect(lambda v: self.s.set(key, v))
        return sl

    def _bind_spin(self, key, lo, hi, suffix=""):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(suffix)
        sp.setValue(int(self.s.get(key)))
        sp.valueChanged.connect(lambda v: self.s.set(key, v))
        return sp

    def _voice_combo(self, key):
        cb = QComboBox()
        for name, vid in VOICES:
            cb.addItem(name, vid)
        cb.setCurrentIndex(max(0, cb.findData(self.s.get(key))))
        cb.currentIndexChanged.connect(lambda _: self.s.set(key, cb.currentData()))
        return cb

    def _page_voice(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        eng = QComboBox()
        eng.addItem("Neural voices (online, best quality)", "neural")
        eng.addItem("Windows voices (offline)", "windows")
        eng.setCurrentIndex(max(0, eng.findData(self.s.get("engine"))))
        eng.currentIndexChanged.connect(lambda _: self.s.set("engine", eng.currentData()))
        lay.addWidget(labeled("Voice engine", eng))
        lay.addWidget(labeled("Hindi (Devanagari) voice", self._voice_combo("hi_voice")))
        lay.addWidget(labeled("Hinglish / English voice", self._voice_combo("en_voice")))
        lay.addWidget(self._bind_check("Different voice for each viewer", "per_viewer"))
        lay.addWidget(labeled("Speed", self._bind_slider("rate", -5, 5)))
        lay.addWidget(labeled("Volume", self._bind_slider("volume", 0, 100)))
        lay.addWidget(self._bind_check("Say the viewer's name first", "read_name"))
        lay.addWidget(self._bind_check("Read Super Chats / Bits (paid messages are never dropped)", "read_super"))
        lay.addWidget(labeled("Max queued messages", self._bind_spin("queue_max", 1, 20),
                              "older ones are dropped when chat is fast"))
        row = QHBoxLayout()
        b1 = QPushButton("Edit Hinglish word list")
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.words_path)))
        b2 = QPushButton("Reload word list")
        b2.clicked.connect(lambda: self.feed.append("<span style='color:#8a93a8'>Loaded %d short-form words</span>"
                                                      % hinglish.load_words(self.words_path)))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return page

    def _page_mod(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        note = QLabel("These filters decide what gets read aloud. Skipped messages stay visible in grey on the Live chat page.")
        note.setObjectName("sub")
        note.setWordWrap(True)
        lay.addWidget(note)
        for text, key in (("Skip messages with links", "skip_links"), ("Skip !commands", "skip_cmds"),
                          ("Ignore known bots (Nightbot, StreamElements, ...)", "ignore_bots"),
                          ("Only read moderators and the streamer", "mods_only")):
            lay.addWidget(self._bind_check(text, key))
        lay.addWidget(labeled("Max message length", self._bind_spin("max_len", 20, 500, " chars")))
        lay.addWidget(labeled("Ignore repeats for", self._bind_spin("dedupe_secs", 0, 120, " s")))
        lay.addWidget(labeled("Same viewer cooldown", self._bind_spin("user_cooldown", 0, 60, " s")))
        lay.addWidget(QLabel("Blocked words (one per line, never read aloud, also blocks paid messages)"))
        self.blocked_edit = QPlainTextEdit()
        try:
            with open(self.blocked_path, encoding="utf-8") as f:
                self.blocked_edit.setPlainText(f.read())
        except Exception:
            pass
        lay.addWidget(self.blocked_edit, 1)
        save = QPushButton("Save blocked words")
        save.setObjectName("primary")
        save.clicked.connect(self._save_blocked)
        lay.addWidget(save, 0, Qt.AlignLeft)
        return page

    # ---------- behaviour ----------
    def apply_theme(self, name):
        if name not in THEMES:
            name = DEFAULT_THEME
        t = THEMES[name]
        self.s.set("theme", name)
        self.setStyleSheet(build_qss(name))
        self.logo.setText('<span style="color:%s">🎙 Chat</span><span style="color:%s">Voice</span>' % (t["a3"], t["a2"]))
        self.fx.recolor(t["a1"])

    def _lite(self, on):
        self.s.set("lite_mode", on)
        self.fx.set_enabled(not on)
        if on:
            self.pulse.stop()
            self.live_fx.setOpacity(1.0)
        elif self.connected:
            self.pulse.start()

    def _end_anim(self):
        for g in self._anims:
            g.stop()
        for w in self._anim_targets:
            w.setGraphicsEffect(None)
        self._anims, self._anim_targets = [], []

    def goto(self, i):
        self._end_anim()
        self.nav.button(i).setChecked(True)
        self.title.setText(PAGES[i])
        page = self.stack.widget(i)
        self.stack.setCurrentIndex(i)
        if self.s.get("lite_mode"):
            return
        group = QParallelAnimationGroup(self)
        targets = [page]
        fx = QGraphicsOpacityEffect(page)
        fx.setOpacity(0.0)
        page.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity")
        a.setDuration(160)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(a)
        group.finished.connect(self._end_anim)
        self._anims, self._anim_targets = [group], targets
        group.start()

    def _mute(self, v):
        self.s.set("muted", v)
        if v:
            self.speaker.clear()

    def _save_blocked(self):
        try:
            with open(self.blocked_path, "w", encoding="utf-8") as f:
                f.write(self.blocked_edit.toPlainText())
            self.mod.reload_blocked()
            self.feed.append("<span style='color:#8a93a8'>Blocked words saved (%d)</span>" % len(self.mod.blocked))
        except Exception as e:
            self.feed.append("<span style='color:#ff5470'>Could not save: %s</span>" % esc(str(e)))

    def _unknown_word(self, w):
        self.feed.append("<span style='color:#8a93a8'>new short word '%s' - add it in Voice > Edit word list</span>" % esc(w))

    def on_status(self, platform, text, ok):
        card = self.cards.get(platform)
        if card:
            card.set_status(text, ok)
        (self.connected.add if ok else self.connected.discard)(platform)
        if ok:
            self.discord.auto_announce()
        if self.connected and self.live.isHidden():
            self.live.show()
            self.pulse.start()
        elif not self.connected and not self.live.isHidden():
            self.pulse.stop()
            self.live.hide()

    def on_message(self, m):
        is_link = self.links.handle(m)
        ok, reason = self.mod.check(m)
        if is_link:
            ok, reason = False, "link code (processing)"
        elif not ok and m.platform == "youtube" and not m.mod:
            self.ytmod.flag(m, reason)
        color = COLORS.get(m.platform, "#8a93a8")
        amt = " <span style='color:#ffd24d'>[%s]</span>" % esc(m.amount) if m.amount else ""
        tag = "<span style='color:%s'><b>%s</b></span>" % (color, TAGS.get(m.platform, "?"))
        if ok:
            self.feed.append("%s <b>%s</b>%s: %s" % (tag, esc(m.author), amt, esc(m.text)))
            self.speaker.say(m.author, m.text, m.amount if m.kind == "super" else "")
            if m.platform != "tip":
                self.overlay.push("chat", {"platform": m.platform, "name": m.author, "text": m.text})
            if m.kind == "super":
                self.overlay.push("alert", {"platform": m.platform, "name": m.author, "amount": m.amount, "message": m.text})
            if m.kind == "super":
                self.discord.post_paid(m)
        else:
            self.feed.append("<span style='color:#5d667d'>%s %s: %s <i>(skipped: %s)</i></span>"
                             % (TAGS.get(m.platform, "?"), esc(m.author), esc(m.text), reason))

    def on_tip(self, ev):
        msg, note = (ev.get("message") or "").strip(), ""
        if msg and self.mod._blocked_hit(msg):
            msg, note = "", "message hidden: blocked word"
        elif msg and ev.get("currency") == "INR" and float(ev.get("value") or 0) < int(self.s.get("tip_min")):
            msg, note = "", "message not read: below the minimum amount"
        self.on_message(Message("tip", ev.get("name") or "Someone", msg, "super", ev.get("display", "")))
        if note:
            self.feed.append("<span style='color:#5d667d'>%s</span>" % esc(note))

    def test_voice(self):
        for m in (Message("test", "Test", "bhai kya krra hoga, nhi pta yr, bht mast stream h lol"),
                  Message("test", "Test", "नमस्ते दोस्तों, चैट रीडर चालू है।")):
            self.on_message(m)
        self.goto(1)

    def closeEvent(self, e):
        self.links.save()
        self.overlay.stop()
        for c in self.cards.values():
            c.source.stop()
        self.speaker.clear()
        super().closeEvent(e)

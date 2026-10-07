"""The Discord page of ChatVoice: connect the bot, create viewer roles/invites, link page, announcements."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from .discord import normalize_youtube_url, post_live_announcement, post_webhook, run_bg
from .theme import DEFAULT_THEME, THEMES
from .ui_kit import FormScrollArea, bind_switch, field_row, hrow, option_switch_row, section_card

NICE = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}


class DiscordPage(FormScrollArea):
    def __init__(self, settings, cloud, bridge, links):
        super().__init__()
        self.s, self.cloud, self.bridge, self.links = settings, cloud, bridge, links
        self._announced = False
        inner = QWidget()
        inner.setObjectName("page")
        self.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 8, 12, 12)
        lay.setSpacing(14)
        accent = THEMES.get(self.s.get("theme"), THEMES[DEFAULT_THEME])["a1"]

        c, cl = section_card(
            "Connect your Discord server",
            "Paste the cloud address, press Add bot, pick your server, then paste the server key shown afterwards.",
        )
        self.url = QLineEdit(self.s.get("cloud_url"))
        self.url.setPlaceholderText("https://chatvoice-cloud.something.workers.dev")
        self.url.editingFinished.connect(lambda: self.s.set("cloud_url", self.url.text().strip()))
        self.key = QLineEdit(self.s.get("cloud_token"))
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Server key")
        self.key.editingFinished.connect(lambda: self.s.set("cloud_token", self.key.text().strip()))
        add = QPushButton("Add bot to my server")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.open_setup)
        test = QPushButton("Test connection")
        test.setObjectName("primary")
        test.setCursor(Qt.PointingHandCursor)
        test.clicked.connect(self.test)
        self.status = QLabel("Not connected")
        self.status.setObjectName("sub")
        cl.addWidget(self.url)
        cl.addWidget(self.key)
        cl.addWidget(hrow(add, test, self.status))
        lay.addWidget(c)

        c, cl = section_card(
            "Viewer invite roles",
            "ChatVoice can create the viewer role and a never-expiring, unlimited Discord invite for each platform. "
            "Choose a channel or leave it on Automatic, then click Create role + invite.",
        )
        self.inv_channel = QComboBox()
        self.inv_channel.addItem("Automatic channel", "")
        load_channels = QPushButton("Load channels")
        load_channels.clicked.connect(self.load_channels)
        self.inv_edits, self.inv_boxes, self.inv_create = {}, {}, {}
        cl.addWidget(hrow(QLabel("Invite channel"), self.inv_channel, load_channels))
        for src in ("youtube", "twitch", "kick"):
            e = QLineEdit(self.s.get("inv_" + src))
            e.setPlaceholderText("https://discord.gg/...")
            e.editingFinished.connect(lambda k=src, w=e: self.s.set("inv_" + k, w.text().strip()))
            cb = QComboBox()
            cb.addItem("(no role)", "")
            button = QPushButton("Create role + invite")
            button.clicked.connect(lambda _checked=False, k=src: self.create_invite(k))
            lab = QLabel(NICE[src])
            lab.setObjectName("settingName")
            lab.setMinimumWidth(72)
            self.inv_edits[src], self.inv_boxes[src], self.inv_create[src] = e, cb, button
            cl.addWidget(hrow(lab, e, cb, button))
        save_inv = QPushButton("Save invite rules")
        save_inv.setObjectName("primary")
        save_inv.clicked.connect(self.save_invites)
        chk = QPushButton("Check now")
        chk.clicked.connect(self.check_invites)
        self.istatus = QLabel("")
        self.istatus.setObjectName("sub")
        self.istatus.setWordWrap(True)
        cl.addWidget(hrow(save_inv, chk))
        cl.addWidget(self.istatus)
        lay.addWidget(c)

        c, cl = section_card(
            "Chat-activity roles",
            "Viewers who link their account get Verified. Active chatters become Regular. Paid messages grant Supporter. "
            "The ChatVoice role must sit above these roles in Discord.",
        )
        self.boxes = {}
        for key, label in (("role_verified", "Verified (after linking)"), ("role_regular", "Regular (after N messages)"),
                           ("role_supporter", "Supporter (after a paid message)")):
            cb = QComboBox()
            cb.addItem("(none)", "")
            self.boxes[key] = cb
            lab = QLabel(label)
            lab.setObjectName("settingName")
            lab.setMinimumWidth(210)
            if key == "role_regular":
                self.n = QSpinBox()
                self.n.setRange(1, 100000)
                self.n.setValue(int(self.s.get("regular_msgs")))
                cl.addWidget(hrow(lab, cb, self.n, QLabel("messages")))
            else:
                cl.addWidget(hrow(lab, cb))
        load = QPushButton("Load my roles")
        load.clicked.connect(self.load_roles)
        save = QPushButton("Save rules")
        save.setObjectName("primary")
        save.clicked.connect(self.save_rules)
        self.rstatus = QLabel("")
        self.rstatus.setObjectName("sub")
        cl.addWidget(hrow(load, save, self.rstatus))
        lay.addWidget(c)

        c, cl = section_card(
            "Link page for chat-activity roles",
            "Share this link in Discord and your stream description. Viewers log in with Discord, get a code, "
            "and type !link CODE in their stream chat.",
        )
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.link.text()))
        cl.addWidget(hrow(self.link, copy))
        lay.addWidget(c)
        self.update_link()

        c, cl = section_card(
            "Live announcements",
            "Posts a Discord embed with your custom message and a clickable YouTube live link.",
        )
        self.hook = QLineEdit(self.s.get("webhook_url"))
        self.hook.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.hook.editingFinished.connect(lambda: self.s.set("webhook_url", self.hook.text().strip()))
        self.yt = QLineEdit(self.s.get("youtube"))
        self.yt.setPlaceholderText("https://youtube.com/watch?v=... or a video ID")
        self.yt.editingFinished.connect(lambda: self.s.set("youtube", self.yt.text().strip()))
        self.text = QLineEdit(self.s.get("announce_text"))
        self.text.setPlaceholderText("I'm live! Come hang out")
        self.text.editingFinished.connect(lambda: self.s.set("announce_text", self.text.text()))
        cl.addWidget(field_row("Webhook URL", "Where live announcements are posted.", self.hook))
        cl.addWidget(field_row("YouTube live link", "The YouTube URL used as the embed link.", self.yt))
        cl.addWidget(field_row("Custom message", "Shown as the main embed description.", self.text))
        cl.addWidget(option_switch_row(
            "Announce automatically when YouTube connects",
            "Posts the embed when the YouTube chat connects.",
            bind_switch(self.s, "announce_auto", accent),
        ))
        cl.addWidget(option_switch_row(
            "Post Super Chats / Bits to Discord",
            "Forwards paid messages to the same webhook.",
            bind_switch(self.s, "post_super", accent),
        ))
        now = QPushButton("Announce now")
        now.clicked.connect(self.announce_now)
        self.hstatus = QLabel("")
        self.hstatus.setObjectName("sub")
        cl.addWidget(hrow(now, self.hstatus))
        lay.addWidget(c)
        lay.addStretch(1)
        bridge.done.connect(self.on_done)

    # ----- actions -----
    def open_setup(self):
        base = self.url.text().strip().rstrip("/")
        self.s.set("cloud_url", base)
        if base:
            QDesktopServices.openUrl(QUrl(base + "/setup"))
        else:
            self.status.setText("Enter the cloud address first")

    def _save_conn(self):
        self.s.set("cloud_url", self.url.text().strip())
        self.s.set("cloud_token", self.key.text().strip())

    def test(self):
        self._save_conn()
        self.status.setText("Checking bot and server...")
        run_bg(self.bridge, "ui:test", lambda: self.cloud.call("GET", "/api/config"))

    def load_channels(self):
        self._save_conn()
        self.istatus.setText("Loading channels...")
        run_bg(self.bridge, "ui:channels", lambda: self.cloud.call("GET", "/api/channels"))

    def create_invite(self, src):
        self._save_conn()
        self.istatus.setText("Creating %s role and invite..." % NICE[src])
        channel_id = self.inv_channel.currentData() or ""
        run_bg(self.bridge, "ui:create_inv:%s" % src,
               lambda src=src, channel_id=channel_id: self.cloud.call("POST", "/api/invite-setup",
                                                                       {"platform": src, "channelId": channel_id}))

    def load_roles(self):
        self._save_conn()
        self.rstatus.setText("Loading...")
        run_bg(self.bridge, "ui:roles", lambda: self.cloud.call("GET", "/api/roles"))

    def save_rules(self):
        self._save_conn()
        cfg = {"verifiedRole": self.boxes["role_verified"].currentData() or "",
               "regularRole": self.boxes["role_regular"].currentData() or "",
               "supporterRole": self.boxes["role_supporter"].currentData() or "",
               "regularMsgs": self.n.value()}
        for k, b in self.boxes.items():
            self.s.set(k, b.currentData() or "")
        self.s.set("regular_msgs", self.n.value())
        self.rstatus.setText("Saving...")
        run_bg(self.bridge, "ui:save", lambda: self.cloud.call("PUT", "/api/config", cfg))

    def save_invites(self):
        self._save_conn()
        rules = []
        for src, e in self.inv_edits.items():
            code, role = e.text().strip(), self.inv_boxes[src].currentData() or ""
            self.s.set("inv_role_" + src, role)
            if code:
                if not role:
                    self.istatus.setText("Pick a role for the %s invite first, or use 'Create role + invite'." % NICE[src])
                    return
                rules.append({"code": code, "role": role, "label": NICE[src]})
        self.istatus.setText("Saving...")
        run_bg(self.bridge, "ui:inv", lambda: self.cloud.call("PUT", "/api/config", {"inviteRules": rules}))

    def check_invites(self):
        self._save_conn()
        self.istatus.setText("Checking...")
        run_bg(self.bridge, "ui:invcheck", lambda: self.cloud.call("POST", "/api/invites/check", {}))

    def announce_now(self):
        self.s.set("webhook_url", self.hook.text().strip())
        self.s.set("youtube", self.yt.text().strip())
        self.s.set("announce_text", self.text.text())
        self.hstatus.setText("Sending embed...")
        url, txt, yt = self.s.get("webhook_url"), self.s.get("announce_text"), self.s.get("youtube")
        run_bg(self.bridge, "ui:hook", lambda: post_live_announcement(url, txt, yt))

    def auto_announce(self, platform=None):
        if platform and platform != "youtube":
            return
        yt = self.s.get("youtube") or ""
        if self.s.get("announce_auto") and self.s.get("webhook_url") and yt and not self._announced:
            self._announced = True
            self.announce_now()

    def reset_announce(self):
        self._announced = False

    def post_paid(self, m):
        if self.s.get("post_super") and self.s.get("webhook_url"):
            where = "" if m.platform == "tip" else " on " + m.platform
            txt = "💎 **%s** sent **%s**%s%s" % (m.author, m.amount, where, (": " + m.text[:300]) if m.text else "")
            run_bg(self.bridge, "ui:hookpaid", lambda: post_webhook(self.s.get("webhook_url"), txt))

    def update_link(self):
        gid, base = self.s.get("guild_id"), self.s.get("cloud_url").strip().rstrip("/")
        self.link.setText("%s/link/%s" % (base, gid) if gid and base else "Connect your server first (step 1)")

    def _fill_roles(self, roles):
        for src, cb in self.inv_boxes.items():
            saved = self.s.get("inv_role_" + src)
            cb.clear()
            cb.addItem("(no role)", "")
            for r in roles:
                cb.addItem(r["name"], r["id"])
            cb.setCurrentIndex(max(0, cb.findData(saved)))
        for key, cb in self.boxes.items():
            saved = self.s.get(key)
            cb.clear()
            cb.addItem("(none)", "")
            for r in roles:
                cb.addItem(r["name"], r["id"])
            cb.setCurrentIndex(max(0, cb.findData(saved)))

    def on_done(self, tag, res):
        if not tag.startswith("ui:"):
            return
        err = res.get("error")
        if tag == "ui:test":
            if err:
                self.status.setText(err)
                return
            self.s.set("guild_id", res["guildId"])
            self.s.set("guild_name", res["guildName"])
            cfg = res.get("config", {})
            for k, name in (("role_verified", "verifiedRole"), ("role_regular", "regularRole"), ("role_supporter", "supporterRole")):
                if name in cfg:
                    self.s.set(k, cfg[name])
            for rule in cfg.get("inviteRules", []) or []:
                src = str(rule.get("label", "")).lower()
                if src in self.inv_edits:
                    self.inv_edits[src].setText("https://discord.gg/" + rule["code"])
                    self.s.set("inv_" + src, "https://discord.gg/" + rule["code"])
                    self.s.set("inv_role_" + src, rule["role"])
            if cfg.get("regularMsgs"):
                self.n.setValue(int(cfg["regularMsgs"]))
            self.status.setText("Connected to %s • checking bot..." % res["guildName"])
            self.update_link()
            self.links.refresh()
            self.load_roles()
            run_bg(self.bridge, "ui:bot", lambda: self.cloud.call("GET", "/api/bot-status"))
        elif tag == "ui:bot":
            if err:
                self.status.setText("Server connected • %s" % err)
            else:
                self.status.setText("Connected to %s • Bot ready" % self.s.get("guild_name"))
        elif tag == "ui:channels":
            if err:
                self.istatus.setText(err)
                return
            current = self.inv_channel.currentData() or ""
            self.inv_channel.blockSignals(True)
            self.inv_channel.clear()
            self.inv_channel.addItem("Automatic channel", "")
            for c in res.get("channels", []):
                self.inv_channel.addItem("#" + c["name"], c["id"])
            idx = self.inv_channel.findData(current)
            self.inv_channel.setCurrentIndex(max(0, idx))
            self.inv_channel.blockSignals(False)
            self.istatus.setText("%d invite channels loaded" % len(res.get("channels", [])))
        elif tag.startswith("ui:create_inv:"):
            src = tag.split(":", 2)[2]
            if err:
                self.istatus.setText(err)
                return
            self.inv_edits[src].setText(res.get("inviteUrl", ""))
            self.s.set("inv_" + src, res.get("inviteUrl", ""))
            role = res.get("role") or {}
            self.s.set("inv_role_" + src, role.get("id", ""))
            if role.get("id"):
                cb = self.inv_boxes[src]
                idx = cb.findData(role["id"])
                if idx < 0:
                    cb.addItem(role.get("name", NICE[src] + " Viewer"), role["id"])
                    idx = cb.findData(role["id"])
                cb.setCurrentIndex(idx)
            status = "Reused" if res.get("reused") else "Created"
            self.istatus.setText("%s %s Viewer role + invite: %s" % (status, NICE[src], res.get("inviteUrl", "")))
            self.load_roles()
        elif tag == "ui:roles":
            if err:
                self.rstatus.setText(err)
            else:
                self._fill_roles(res["roles"])
                self.rstatus.setText("%d roles loaded" % len(res["roles"]))
        elif tag == "ui:save":
            self.rstatus.setText(err or "Rules saved")
        elif tag == "ui:inv":
            self.istatus.setText(err or "Saved. ChatVoice's cloud checks for new members every 2 minutes.")
        elif tag == "ui:invcheck":
            if err or res.get("error"):
                self.istatus.setText(err or res["error"])
                return
            lines = []
            for r in res.get("rules", []):
                lines.append("%s: %s" % (r["label"], "invite found, used %d times so far" % r["uses"] if r.get("found")
                                         else "invite NOT found - create it in Discord or fix the link"))
            lines += res.get("notes", [])
            if res.get("assigned"):
                lines.append("Gave roles to %d new member(s)." % len(res["assigned"]))
            self.istatus.setText("\n".join(lines) or "Nothing new")
        elif tag == "ui:hook":
            self.hstatus.setText(err or "Sent")

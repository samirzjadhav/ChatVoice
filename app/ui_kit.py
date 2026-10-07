"""Shared section cards, toggles, and form rows for settings pages."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

FORM_SCROLL_AREAS = []


class Switch(QCheckBox):
    """Sliding on/off control; saves like a checkbox."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._knob = 0.0
        self._accent = QColor("#7c5cff")
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._slide)

    def knob(self):
        return self._knob

    def setKnob(self, value):
        self._knob = value
        self.update()

    knob = Property(float, knob, setKnob)

    def set_accent(self, color):
        self._accent = QColor(color)
        self.update()

    def setChecked(self, on):
        self.blockSignals(True)
        super().setChecked(on)
        self.blockSignals(False)
        self._knob = 1.0 if on else 0.0
        self.update()

    def _slide(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent if self.isChecked() else QColor(255, 255, 255, 36))
        painter.drawRoundedRect(0, 2, 40, 18, 9, 9)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(int(2 + self._knob * 18), 4, 14, 14)


class FormScrollArea(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        FORM_SCROLL_AREAS.append(self)


class TwoColumnBoard(QWidget):
    """Two-column card grid on wide pages, one column when narrow."""

    def __init__(self, breakpoint=760):
        super().__init__()
        self._breakpoint = breakpoint
        self._wide = None
        self._pairs = []
        self._full = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

    def set_cards(self, pairs, full=None):
        self._pairs = pairs
        self._full = full
        self._arrange(self.width() >= self._breakpoint)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(self.width() >= self._breakpoint)

    def _arrange(self, wide):
        if wide == self._wide:
            return
        self._wide = wide
        while self._grid.count():
            self._grid.takeAt(0)
        if wide:
            for index, (left, right) in enumerate(self._pairs):
                self._grid.addWidget(left, index, 0)
                self._grid.addWidget(right, index, 1)
            if self._full is not None:
                self._grid.addWidget(self._full, len(self._pairs), 0, 1, 2)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
        else:
            row = 0
            for left, right in self._pairs:
                self._grid.addWidget(left, row, 0)
                self._grid.addWidget(right, row + 1, 0)
                row += 2
            if self._full is not None:
                self._grid.addWidget(self._full, row, 0)
            self._grid.setColumnStretch(0, 1)


def section_card(title, description, object_name="tile"):
    card = QFrame()
    card.setObjectName(object_name)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("pageTitle")
    note = QLabel(description)
    note.setObjectName("pageNote")
    note.setWordWrap(True)
    lay.addWidget(head)
    lay.addWidget(note)
    return card, lay


def field_row(title, note, widget):
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(2)
    name = QLabel(title)
    name.setObjectName("settingName")
    detail = QLabel(note)
    detail.setObjectName("settingNote")
    detail.setWordWrap(True)
    if widget.maximumWidth() > 1000:
        widget.setMaximumWidth(420)
    lay.addWidget(name)
    lay.addWidget(detail)
    lay.addWidget(widget)
    return wrap


def option_switch_row(title, note, switch):
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 6, 0, 6)
    text = QVBoxLayout()
    text.setSpacing(1)
    name = QLabel(title)
    name.setObjectName("settingName")
    name.setWordWrap(True)
    detail = QLabel(note)
    detail.setObjectName("settingNote")
    detail.setWordWrap(True)
    text.addWidget(name)
    text.addWidget(detail)
    lay.addLayout(text, 1)
    lay.addWidget(switch, 0, Qt.AlignTop)
    return row


def bind_switch(settings, key, accent):
    switch = Switch()
    switch.set_accent(accent)
    switch.setChecked(bool(settings.get(key)))
    switch.toggled.connect(lambda on, k=key: settings.set(k, on))
    return switch


def meter_row(title, note, slider, fmt):
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 6, 0, 2)
    lay.setSpacing(4)
    top = QHBoxLayout()
    name = QLabel(title)
    name.setObjectName("settingName")
    value = QLabel(fmt(slider.value()))
    value.setObjectName("settingValue")
    top.addWidget(name)
    top.addStretch(1)
    top.addWidget(value)
    detail = QLabel(note)
    detail.setObjectName("settingNote")
    detail.setWordWrap(True)
    slider.valueChanged.connect(lambda v, f=fmt, lab=value: lab.setText(f(v)))
    lay.addLayout(top)
    lay.addWidget(detail)
    lay.addWidget(slider)
    return wrap


def hrow(*widgets):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x in widgets:
        if x is None:
            continue
        stretch = 1 if x.__class__.__name__ in ("QLineEdit", "QComboBox", "QPlainTextEdit") else 0
        lay.addWidget(x, stretch)
    return w

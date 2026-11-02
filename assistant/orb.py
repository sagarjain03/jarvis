"""Jarvis orb: a glowing, audio-reactive orb that floats above the desktop.

Controlled through stdin by orb_client.py, one JSON message per line:
  {"cmd": "state", "state": "listening"|"thinking"|"speaking"}  (also shows it)
  {"cmd": "level", "value": 0..1}        live microphone loudness
  {"cmd": "speak", "env": [...], "fps": 30}  loudness envelope of the reply
  {"cmd": "caption", "text": "..."}
  {"cmd": "hide"} / {"cmd": "quit"}
The window closes by itself if stdin closes (Jarvis exited).

Preview frames without a window:  python orb.py --preview OUT_DIR
"""

from __future__ import annotations

import json
import math
import random
import sys
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontMetrics, QGuiApplication, QImage, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

W, H = 440, 460
CENTER = QPointF(W / 2, 200)
BASE_R = 72

# (core, mid, edge) colours per state.
PALETTES = {
    "listening": [(150, 245, 255), (0, 200, 255), (70, 90, 255)],
    "thinking": [(255, 170, 250), (175, 80, 255), (255, 50, 160)],
    "speaking": [(200, 255, 240), (0, 230, 200), (255, 190, 70)],
}


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


class OrbModel:
    """Animation state, advanced once per frame and drawn by ``paint``."""

    def __init__(self) -> None:
        self.t = 0.0
        self.state = "listening"
        self.colors = [list(c) for c in PALETTES["listening"]]
        self.level = 0.0
        self.target_level = 0.0
        self.spin = 0.0
        self.visible = 0.0  # 0 hidden .. 1 fully shown
        self.show_target = 0.0
        self.caption = ""
        self.env: list[float] = []
        self.env_fps = 30
        self.env_start = 0.0
        rnd = random.Random(7)
        self.particles = [
            (rnd.uniform(0, math.tau), rnd.uniform(1.25, 2.1), rnd.uniform(0.15, 0.55)
             * rnd.choice((-1, 1)), rnd.uniform(0.8, 2.4), rnd.uniform(0, math.tau))
            for _ in range(80)
        ]

    def handle(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "state":
            self.state = msg.get("state", "listening")
            self.show_target = 1.0
            if self.state != "speaking":
                self.env = []
        elif cmd == "level":
            self.target_level = max(0.0, min(1.0, float(msg.get("value", 0))))
        elif cmd == "speak":
            self.state = "speaking"
            self.show_target = 1.0
            self.env = [float(v) for v in msg.get("env", [])]
            self.env_fps = int(msg.get("fps", 30)) or 30
            self.env_start = time.monotonic()
        elif cmd == "caption":
            self.caption = str(msg.get("text", ""))
        elif cmd == "hide":
            self.show_target = 0.0
            self.target_level = 0.0

    def step(self, dt: float) -> None:
        self.t += dt
        if self.env:
            i = int((time.monotonic() - self.env_start) * self.env_fps)
            self.target_level = self.env[i] if i < len(self.env) else 0.0
        elif self.state == "thinking":
            self.target_level = 0.25 + 0.15 * math.sin(self.t * 4)
        self.level = _lerp(self.level, self.target_level, min(1.0, dt * 14))
        speed = {"thinking": 2.6, "speaking": 1.3}.get(self.state, 0.8)
        self.spin += dt * speed
        for c, target in zip(self.colors, PALETTES.get(self.state, PALETTES["listening"])):
            for j in range(3):
                c[j] = _lerp(c[j], target[j], min(1.0, dt * 4))
        self.visible = _lerp(self.visible, self.show_target, min(1.0, dt * 6))
        if abs(self.visible - self.show_target) < 0.002:
            self.visible = self.show_target

    # -- drawing --------------------------------------------------------------

    def _color(self, i: int, alpha: float) -> QColor:
        r, g, b = self.colors[i]
        return QColor(int(r), int(g), int(b), max(0, min(255, int(alpha))))

    def paint(self, p: QPainter) -> None:
        v = self.visible
        if v <= 0.001:
            return
        p.setRenderHint(QPainter.Antialiasing)
        ease = 1 - (1 - v) ** 3
        R = BASE_R * (0.55 + 0.45 * ease) * (1 + 0.10 * self.level)
        t, lvl = self.t, self.level
        p.save()
        p.setOpacity(v)

        # 1. Soft outer aura.
        aura = QRadialGradient(CENTER, R * 2.6)
        aura.setColorAt(0.0, self._color(1, 110 + 90 * lvl))
        aura.setColorAt(0.35, self._color(2, 45 + 40 * lvl))
        aura.setColorAt(1.0, self._color(2, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(aura)
        p.drawEllipse(CENTER, R * 2.6, R * 2.6)

        # 2. Orbit rings with comet tails (behind the core).
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        self._rings(p, R, front=False)

        # 3a. Deep glass body so the orb has depth on light wallpapers too.
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        body = QRadialGradient(CENTER + QPointF(R * 0.15, R * 0.2), R * 1.05)
        body.setColorAt(0.0, QColor(20, 28, 70, 225))
        body.setColorAt(0.8, QColor(8, 12, 35, 235))
        body.setColorAt(1.0, self._color(2, 120))
        p.setBrush(body)
        p.drawEllipse(CENTER, R * 0.98, R * 0.98)
        p.setCompositionMode(QPainter.CompositionMode_Plus)

        # 3. Plasma: three wobbling blobs blended additively.
        amp = 0.035 + 0.13 * lvl + (0.05 if self.state == "thinking" else 0.0)
        for k in range(3):
            path = QPainterPath()
            n = 120
            for i in range(n + 1):
                a = math.tau * i / n
                wob = (0.5 * math.sin(3 * a + t * (1.1 + 0.3 * k) + k * 2.1)
                       + 0.3 * math.sin(5 * a - t * (1.6 + 0.2 * k) + k)
                       + 0.2 * math.sin(7 * a + t * 2.3 - k))
                r = R * (0.9 - 0.06 * k + amp * wob)
                pt = QPointF(CENTER.x() + r * math.cos(a), CENTER.y() + r * math.sin(a))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            off = QPointF(math.cos(t * 0.7 + k * 2.1), math.sin(t * 0.9 + k * 2.1)) * (R * 0.18)
            g = QRadialGradient(CENTER + off, R)
            g.setColorAt(0.0, self._color(0, 95))
            g.setColorAt(0.5, self._color((k + 1) % 3, 105))
            g.setColorAt(1.0, self._color(2, 20))
            p.setBrush(g)
            p.drawPath(path)

        # 4. White-hot core, breathing with the voice.
        core_r = R * (0.36 + 0.22 * lvl)
        core = QRadialGradient(CENTER, core_r)
        core.setColorAt(0.0, QColor(255, 255, 255, int(150 + 80 * lvl)))
        core.setColorAt(0.45, self._color(0, 90))
        core.setColorAt(1.0, self._color(1, 0))
        p.setBrush(core)
        p.drawEllipse(CENTER, core_r, core_r)

        # 5. Particles.
        for a0, rad, speed, size, phase in self.particles:
            a = a0 + self.spin * speed * 2
            rr = R * (rad + 0.35 * lvl * math.sin(phase + t * 3))
            x = CENTER.x() + rr * math.cos(a)
            y = CENTER.y() + rr * math.sin(a) * 0.92
            tw = 0.5 + 0.5 * math.sin(t * 3 + phase)
            p.setBrush(self._color(0, 60 + 170 * tw))
            p.drawEllipse(QPointF(x, y), size * (0.7 + 0.6 * lvl), size * (0.7 + 0.6 * lvl))

        self._rings(p, R, front=True)

        # 6. Glass highlight.
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        hl_c = CENTER + QPointF(-R * 0.32, -R * 0.38)
        hl = QRadialGradient(hl_c, R * 0.42)
        hl.setColorAt(0.0, QColor(255, 255, 255, 70))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(hl_c, R * 0.42, R * 0.3)

        self._caption(p)
        p.restore()

    def _rings(self, p: QPainter, R: float, front: bool) -> None:
        """Tilted elliptical rings; only the near (front) or far half is drawn."""
        for i, (scale, tilt, speed, width) in enumerate(
            ((1.38, 0.30, 1.0, 2.2), (1.6, 0.48, -0.7, 1.6), (1.85, 0.22, 0.45, 1.2))
        ):
            p.save()
            p.translate(CENTER)
            p.rotate(-18 + 28 * i + 6 * math.sin(self.t * 0.4 + i))
            p.scale(1.0, tilt)
            rr = R * scale
            head = math.degrees(self.spin * speed * 1.4) % 360
            cg = QConicalGradient(QPointF(0, 0), head)
            cg.setColorAt(0.0, self._color(0, 230))
            cg.setColorAt(0.25, self._color(1, 90))
            cg.setColorAt(0.7, self._color(2, 10))
            cg.setColorAt(1.0, self._color(0, 230))
            pen = QPen(QBrush(cg), width * (1 + self.level) / max(tilt, 0.3))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            # Qt angles: 0 = 3 o'clock, counter-clockwise; front half is the bottom.
            start, span = (180 * 16, 180 * 16) if front else (0, 180 * 16)
            p.drawArc(QRectF(-rr, -rr, 2 * rr, 2 * rr), start, span)
            p.restore()
        p.setPen(Qt.NoPen)

    def _caption(self, p: QPainter) -> None:
        if not self.caption:
            return
        label = {"listening": "Listening…", "thinking": "Thinking…", "speaking": ""}.get(self.state, "")
        font = QFont("Segoe UI", 11)
        p.setFont(font)
        area = QRectF(30, H - 115, W - 60, 105)
        flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
        int_flags = Qt.AlignHCenter.value | Qt.AlignTop.value | Qt.TextWordWrap.value
        text = self.caption if not label else f"{label}\n{self.caption}"
        box = QRectF(QFontMetrics(font).boundingRect(area.toRect(), int_flags, text))
        box.adjust(-14, -7, 14, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 12, 30, 150))  # readable on any wallpaper
        p.drawRoundedRect(box, 12, 12)
        p.setPen(QColor(235, 250, 255, 240))
        p.drawText(area, flags, text)


class _Bridge(QObject):
    message = Signal(dict)


class OrbWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.model = OrbModel()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(W, H)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - W // 2, screen.bottom() - H + 10)
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def on_message(self, msg: dict) -> None:
        if msg.get("cmd") == "quit":
            QApplication.quit()
            return
        self.model.handle(msg)
        if self.model.show_target > 0 and not self.isVisible():
            self.show()

    def _tick(self) -> None:
        now = time.monotonic()
        self.model.step(min(0.05, now - self._last))
        self._last = now
        if self.model.visible == 0 and self.model.show_target == 0 and self.isVisible():
            self.hide()
            self.model.caption = ""
        elif self.isVisible():
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self.model.paint(p)
        p.end()


def _read_stdin(bridge: _Bridge) -> None:
    for line in sys.stdin:
        try:
            bridge.message.emit(json.loads(line))
        except json.JSONDecodeError:
            continue
    bridge.message.emit({"cmd": "quit"})  # Jarvis went away


def preview(out_dir: str) -> None:
    """Render one frame per state (on dark and light backdrops) to PNG files."""
    from pathlib import Path

    QGuiApplication(sys.argv)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for state, level, caption in (
        ("listening", 0.35, "What's the weather in Indore?"),
        ("thinking", 0.0, "What's the weather in Indore?"),
        ("speaking", 0.85, "It's sunny and 24 degrees in Indore, Master."),
    ):
        for bg_name, bg in (("dark", QColor(18, 20, 28)), ("light", QColor(235, 238, 242))):
            m = OrbModel()
            m.handle({"cmd": "state", "state": state})
            m.handle({"cmd": "caption", "text": caption})
            m.handle({"cmd": "level", "value": level})
            for _ in range(90):  # 1.5 s of animation so colours and fade settle
                m.step(1 / 60)
            if state == "speaking":
                m.target_level = m.level = level
            # Paint on transparency like the real window, then lay it over a backdrop.
            layer = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
            layer.fill(Qt.transparent)
            p = QPainter(layer)
            m.paint(p)
            p.end()
            img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
            img.fill(bg)
            p = QPainter(img)
            p.drawImage(0, 0, layer)
            p.end()
            img.save(str(Path(out_dir) / f"orb_{state}_{bg_name}.png"))


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
        return
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = OrbWindow()
    bridge = _Bridge()
    bridge.message.connect(window.on_message)
    threading.Thread(target=_read_stdin, args=(bridge,), daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

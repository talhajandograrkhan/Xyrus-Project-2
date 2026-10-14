"""
Xyrus android head for the HUD centre.

This replaces the old photoreal wireframe face with a completely different
design: a clean, hand-built **android / robot head** drawn entirely from vector
shapes. Nothing is scanned or meshed any more.

Structure (front view, all sizes in head-half-heights)
-------------------------------------------------------
* **Shell**     - armoured helmet with a flat crown, squared cheeks and a
                  tapered chin plate; segmented **neck** underneath.
* **Ears**      - two side sensor pods with a glowing ring. They pulse with the
                  voice and shrink on the side the head turns away from.
* **Visor**     - dark eye band across the face.
* **Eyes**      - glowing LED irises with a pupil that follows the gaze, plus a
                  specular dot. Lids close for blinks and when asleep.
* **Brows**     - two light-bars that lift when it speaks and slant down when
                  it is thinking.
* **Nose**      - a small sensor bridge.
* **Mouth**     - a lip-shaped slot with teeth strip and tongue glow. Its
                  height follows the jaw (viseme openness) and its width
                  follows lip spread / rounding (viseme wideness).
* **Cheek vents** - three LED slats on each side that light up with loudness.
* **Forehead gem** - state / energy indicator.

The public interface is unchanged (`HoloAvatar`, `step()`, `paint()`,
`glance()`, `style`, `SPAN`), so `ui_new.py` and `main.py` work as before.
Lip-sync, blinking, gaze, brows and the state behaviour (thinking, listening,
sleeping) all come from the same animation code as before - only the body it
drives is new.

Software rendered with QPainter: no OpenGL, no numpy mesh, no extra files.
`core/avatar_mesh.py` and `core/face_model.obj` are no longer used.
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QLinearGradient, QPainter,
                         QPainterPath, QPen, QRadialGradient)

# Timing constants (seconds) - unchanged from the previous avatar so the mouth
# keeps its measured behaviour at 20 / 30 / 60 fps.
_TAU_OPEN = 0.022     # jaw dropping toward a vowel
_TAU_SHUT = 0.012     # lips closing on a consonant, mid-word
_TAU_REST = 0.055     # settling back to rest after speech ends
_TAU_SHAPE = 0.018    # viseme openness following the schedule
_MIC_FLOOR = 0.14     # microphone path level floor
_CLOSE_FRAC = 0.10    # -20 dB below this voice's loud level == closure


def _rate(dt: float, tau: float) -> float:
    """Frame-rate independent lerp factor for time constant `tau`."""
    return 1.0 - math.exp(-dt / tau)


def _c(col: QColor, a: float) -> QColor:
    """Copy of `col` at alpha `a` (0-255, clamped)."""
    q = QColor(col)
    q.setAlpha(int(max(0.0, min(255.0, a))))
    return q


def _blend(bg: QColor, col: QColor, a: float) -> QColor:
    """`col` at alpha `a` pre-mixed onto `bg`, returned fully opaque."""
    f = max(0.0, min(1.0, a / 255.0))
    return QColor(int(bg.red() + (col.red() - bg.red()) * f),
                  int(bg.green() + (col.green() - bg.green()) * f),
                  int(bg.blue() + (col.blue() - bg.blue()) * f))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


class HoloAvatar:
    """Animated android head. One instance per HUD canvas.

    Lifecycle:
        av = HoloAvatar()
        av.step(dt, amp, speaking=..., muted=...)          # once per tick
        av.paint(painter, cx, cy, r, primary, accent, bg)  # once per frame
    """

    # Kept for compatibility with callers that flip it; the android head is
    # always solid.
    shaded = True

    def __init__(self) -> None:
        # Crown (-1.0) down to the bottom of the neck (+1.55), in
        # head-half-heights. Callers size the head to the room they have.
        self.SPAN = 2.55

        self.style = "face"
        self._t = 0.0
        self._sway = 0.0           # integrated sway phase - see step()
        self._yaw = 0.0
        self._pitch = 0.0
        self._mouth = 0.0          # 0..1 smoothed jaw opening
        self._glow = 0.0           # 0..1 smoothed overall energy
        self._scan = -1.6          # vertical position of the energy sweep
        self._blink = 0.0          # 0 = open, 1 = shut
        self._blink_at = 3.0

        # expression
        self._amp_slow = 0.0
        self._expr = 0.0
        self._expr_tgt = 0.0
        self._expr_at = 0.0
        self._brow = 0.0           # smoothed brow lift, -0.4 .. 1.2
        self._emph = 0.0           # syllable emphasis, drives the head nod
        self._gaze = [0.0, 0.0]
        self._gaze_tgt = [0.0, 0.0]
        self._gaze_at = 0.0

        # state expression
        self._gaze_bias = [0.0, 0.0]
        self._bias_tgt = [0.0, 0.0]
        self._bias_at = 0.0
        self._lids = 1.0           # 1 = wide, 0 = shut; low while asleep
        self._brow_bias = 0.0
        self._glance = None        # (dx, dy, until_t) - a deliberate look

        # viseme
        self._v_open = 1.0
        self._v_wide = 0.0
        self._wide = 0.0           # smoothed lip spread, -1 round .. +1 spread
        self._v_peak = 0.18

    # -- animation (unchanged logic) ------------------------------------------

    def _mouth_step(self, dt: float, amp: float, live: bool,
                    v_open: float | None, v_level: float | None) -> None:
        """One increment of the jaw. Called once per viseme frame while JARVIS
        speaks, once per rendered frame otherwise."""
        if v_open is None:
            shape = 1.0
        else:
            self._v_open += (v_open - self._v_open) * _rate(dt, _TAU_SHAPE)
            shape = self._v_open

        if v_level is None:
            gated = max(0.0, (amp - _MIC_FLOOR) / (1.0 - _MIC_FLOOR))
            drive = (gated ** 0.6) * (shape ** 0.75)
        else:
            # Speech RMS spends most of its time well below full scale, so the
            # raw value alone would only ever half-open the jaw. Normalise it
            # against a running estimate of this voice's own loud level rather
            # than a constant: it then reads the same whether the user has the
            # volume low or the model happens to be speaking softly.
            self._v_peak = max(v_level, self._v_peak - dt * 0.55)
            ref = max(0.18, self._v_peak)
            # The floor is a fraction of this voice's own loud level, not a
            # fixed number, so it means the same thing at any volume and in any
            # language. A stop consonant drops 20 dB or more below the vowels
            # around it, which is this ratio — so a real closure lands at
            # exactly zero rather than at some small positive value the curve
            # would otherwise lift back up. That lift is what kept the mouth
            # from ever quite shutting between words.
            q = (v_level - _CLOSE_FRAC * ref) / (ref * (1.0 - _CLOSE_FRAC))
            drive = max(0.0, min(1.0, q)) ** 0.85 * (shape ** 0.75)

        target = min(1.0, drive) if live else 0.0
        if target > self._mouth:
            tau = _TAU_OPEN
        elif live:
            tau = _TAU_SHUT      # mid-word: a consonant, and it must shut now
        else:
            tau = _TAU_REST      # speech is over; settle, don't snap
        self._mouth += (target - self._mouth) * _rate(dt, tau)
        if self._mouth < 0.002:
            self._mouth = 0.0

    def step(self, dt: float, amp: float, speaking: bool = False,
             muted: bool = False, state: str = "",
             v_open: float | None = None, v_wide: float = 0.0,
             v_level: float | None = None,
             v_seq: list | None = None, v_hop: float = 0.02) -> None:
        """Advance the animation.

        `amp` is the 0..1 display audio level. `v_open` / `v_wide` / `v_level`
        are the viseme schedule's shape and true level for this instant; passing
        None falls back to loudness-only articulation, which is what the
        microphone path uses. `v_seq` is every schedule frame the last rendered
        frame spanned, so no closure is lost when the paint rate drops.
        """
        dt = max(0.001, min(0.10, float(dt)))
        self._t += dt
        t = self._t
        amp = max(0.0, min(1.0, float(amp)))
        live = speaking and not muted

        # Idle sway. The phase is *integrated* rather than taken as
        # sin(t * rate * speed): multiplying absolute time by a speed that
        # changes when JARVIS starts or stops talking jumps the phase by
        # t * rate * delta, which after a minute of uptime is several radians
        # and visibly teleports the head the instant a sentence ends.
        speed = (1.0 if not muted else 0.55) * (1.25 if live else 1.0)
        self._sway += dt * speed
        s = self._sway
        self._yaw = 0.26 * math.sin(s * 0.31) + 0.09 * math.sin(s * 0.73 + 1.3)
        self._pitch = (0.060 * math.sin(s * 0.23 + 0.7)
                       + 0.024 * math.sin(s * 0.61))

        # Mouth. Which level is driving it matters more than any rate here.
        #
        # `v_level` is this 20 ms frame's own RMS, taken from the very audio
        # about to be heard, so its silences are real silences. `amp` is the
        # waveform display's level, and that one is a *peak hold*: it keeps the
        # loudest value it has seen and decays gently, on purpose, so the bars
        # do not stutter between audio chunks. Driving a mouth from a peak hold
        # is why the gaps between words never closed — the hold spans exactly
        # the consonant it was supposed to reveal. So the schedule drives the
        # jaw whenever there is one, and `amp` is left to the microphone path,
        # which has nothing better.
        # Advance the mouth once per *schedule* frame rather than once per
        # rendered frame. A bilabial closure lasts around 40 ms — two frames of
        # a 50 Hz schedule — and the HUD throttles its paint to 30 fps and to 20
        # when idle. Point-sampling at 20 fps steps 50 ms at a time, so a whole
        # closure can fall between two samples and simply never be seen; that is
        # information loss no smoothing constant can recover. Sub-stepping costs
        # a few float operations per frame and makes the mouth identical at 20,
        # 30 and 60 fps.
        # An empty list is meaningful and is not the same as None: it says a
        # schedule is playing but this tick landed inside a frame already
        # spoken. The mouth's clock is the schedule's, so the right thing then
        # is to do nothing. Re-stepping the same frame — which is what a
        # truthiness test here would do — advances the jaw twice for one 20 ms
        # of audio, and at 60 fps that alone made the mouth behave differently
        # than at 20.
        if v_seq is not None:
            for lv, op, _wd in v_seq:
                self._mouth_step(v_hop, amp, live, op, lv)
        else:
            self._mouth_step(dt, amp, live, v_open, v_level)

        # Syllable emphasis. Applied unconditionally: `_emph` decays to zero on
        # its own once the mouth closes, whereas gating it on `live` deleted the
        # whole offset in a single frame and snapped the head at sentence end.
        self._emph += (self._mouth - self._emph) * _rate(
            dt, 0.055 if self._mouth > self._emph else 0.32)
        self._pitch -= self._emph * 0.028
        self._yaw += 0.018 * math.sin(t * 1.7) * self._emph

        # Loudness envelope, deliberately lazier than the mouth: brows track the
        # shape of a phrase, not individual syllables.
        env = amp if live else 0.0
        self._amp_slow += (env - self._amp_slow) * _rate(
            dt, 0.16 if env > self._amp_slow else 0.36)

        if live:
            if t >= self._expr_at:
                self._expr_tgt = random.uniform(-0.35, 1.0)
                self._expr_at = t + 1.1 + 2.0 * random.random()
        else:
            self._expr_tgt = 0.0
            self._expr_at = t + 0.8
        self._expr += (self._expr_tgt - self._expr) * 0.075

        brow_t = 0.55 * self._amp_slow + 0.60 * self._expr + self._brow_bias
        self._brow += (max(-0.4, min(1.2, brow_t)) - self._brow) * 0.20

        # ── what the state does to the face ─────────────────────────────────
        st = (state or "").upper()
        thinking = st in ("THINKING", "PROCESSING")
        asleep = st in ("SLEEPING", "STANDBY", "OFFLINE")

        if thinking:
            # People look away to think, and hold it. The direction re-rolls
            # slowly so it reads as thought rather than as scanning.
            if t >= self._bias_at:
                self._bias_tgt = [random.choice((-1.0, 1.0)) * random.uniform(0.45, 0.8),
                                  random.uniform(0.25, 0.55)]
                self._bias_at = t + 1.4 + 1.6 * random.random()
            brow_bias, lid_tgt = -0.28, 0.94
        elif asleep:
            self._bias_tgt = [0.0, -0.25]
            brow_bias, lid_tgt = -0.05, 0.22
        else:
            # LISTENING / idle / speaking: eyes come back to the user.
            self._bias_tgt = [0.0, 0.0]
            self._bias_at = 0.0
            brow_bias = 0.10 if st == "LISTENING" else 0.0
            lid_tgt = 1.0

        for i in (0, 1):
            self._gaze_bias[i] += (self._bias_tgt[i] - self._gaze_bias[i]) * 0.06
        self._lids += (lid_tgt - self._lids) * 0.08
        self._brow_bias += (brow_bias - self._brow_bias) * 0.06

        # Gaze: saccades are near-instant jumps between fixations, and they get
        # more frequent when there is something to say. While thinking they slow
        # right down — a darting eye reads as nervous, not thoughtful.
        if t >= self._gaze_at:
            reach = 0.9 if live else (0.35 if thinking else 0.55)
            self._gaze_tgt = [random.uniform(-1.0, 1.0) * reach,
                              random.uniform(-1.0, 1.0) * reach * 0.55]
            if live:
                self._gaze_at = t + 0.55 + 1.7 * random.random()
            elif thinking:
                self._gaze_at = t + 1.8 + 2.4 * random.random()
            else:
                self._gaze_at = t + 1.3 + 2.8 * random.random()

        # A deliberate glance (something appeared on screen) overrides the
        # wandering for a moment, then hands control back.
        if self._glance is not None:
            gx, gy, until = self._glance
            if t < until:
                self._gaze_tgt = [gx, gy]
            else:
                self._glance = None

        for i, b in enumerate(self._gaze_bias):
            tgt = max(-1.0, min(1.0, self._gaze_tgt[i] + b))
            self._gaze[i] += (tgt - self._gaze[i]) * 0.30

        # Lips lead the jaw slightly in real speech, so they track a touch
        # faster; they also relax to neutral the moment the voice stops.
        wide_t = v_wide if (live and v_open is not None) else 0.0
        self._wide += (max(-1.0, min(1.0, wide_t)) - self._wide) * _rate(dt, 0.030)

        self._glow += ((0.0 if muted else amp) - self._glow) * (
            0.35 if (0.0 if muted else amp) > self._glow else 0.10)

        self._scan += dt * (0.55 + 1.5 * self._glow)
        if self._scan > 1.35:
            self._scan = -1.75

        if self._blink > 0.0:
            self._blink = max(0.0, self._blink - dt * 8.5)
        elif t >= self._blink_at:
            # Concentration suppresses blinking; a sleeping face has no need of
            # it at all, since the lids are already down.
            if asleep:
                self._blink_at = t + 6.0
            else:
                self._blink = 1.0
                gap = 5.5 if thinking else 3.4
                self._blink_at = t + gap + 3.1 * random.random()

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Look deliberately somewhere for `hold` seconds, then wander again.

        Used when something appears on screen: a face that looks at what just
        showed up tells the user it landed, without a word being spoken.
        """
        self._glance = (max(-1.0, min(1.0, float(dx))),
                        max(-1.0, min(1.0, float(dy))),
                        self._t + max(0.1, float(hold)))


    # -- rendering ------------------------------------------------------------

    @staticmethod
    def _shell_path(r: float, k: float = 1.0) -> QPainterPath:
        """Helmet outline: flat crown, square cheeks, tapered chin plate.
        `k` shrinks it about the centre for the inner bevel line."""
        def P(x, y):
            return QPointF(x * r * k, y * r * k)
        s = QPainterPath()
        s.moveTo(P(-0.52, -1.00))
        s.lineTo(P(0.52, -1.00))
        s.cubicTo(P(0.74, -1.00), P(0.86, -0.82), P(0.86, -0.58))
        s.lineTo(P(0.86, 0.20))
        s.cubicTo(P(0.86, 0.52), P(0.74, 0.80), P(0.52, 0.93))
        s.cubicTo(P(0.46, 0.97), P(0.40, 1.00), P(0.32, 1.00))
        s.lineTo(P(-0.32, 1.00))
        s.cubicTo(P(-0.40, 1.00), P(-0.46, 0.97), P(-0.52, 0.93))
        s.cubicTo(P(-0.74, 0.80), P(-0.86, 0.52), P(-0.86, 0.20))
        s.lineTo(P(-0.86, -0.58))
        s.cubicTo(P(-0.86, -0.82), P(-0.74, -1.00), P(-0.52, -1.00))
        s.closeSubpath()
        return s

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor | None = None) -> None:
        """Draw the avatar with its head centre at (cx, cy).

        `r` is the head's half-height in pixels - the caller owns the layout.
        """
        if bg is None:
            bg = QColor(0, 0, 0)
        amp = self._glow
        cartoon = self.style == "cartoon"
        black = QColor(0, 0, 0)
        white = QColor(255, 255, 255)

        p.save()
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # -- aura (drawn in screen space, behind everything) ----------------
            ar = r * 2.1
            grad = QRadialGradient(cx, cy, ar)
            grad.setColorAt(0.00, _c(primary, 50 + 70 * amp))
            grad.setColorAt(0.30, _c(primary, 26 + 56 * amp))
            grad.setColorAt(0.65, _c(primary, 10 + 26 * amp))
            grad.setColorAt(1.00, _c(primary, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawEllipse(QRectF(cx - ar, cy - ar, ar * 2, ar * 2))

            # -- head pose -----------------------------------------------------
            breathe = math.sin(self._sway * 0.9) * 0.012 * r
            p.translate(cx + self._yaw * r * 0.55,
                        cy + self._pitch * r * 1.1 + breathe)
            p.rotate(math.degrees(self._yaw) * 0.22)

            def P(x, y):
                return QPointF(x * r, y * r)

            pen_w = max(1.2, r * 0.018)
            rim = _c(primary, 215)
            dark = _blend(bg, black, 200)
            visor_fill = _blend(bg, black, 222)

            self._paint_neck(p, r, primary, bg, black, pen_w)
            self._paint_ears(p, r, primary, accent, bg, amp, pen_w)

            # -- shell ---------------------------------------------------------
            shell = self._shell_path(r)
            g = QLinearGradient(0, -r, 0, r)
            g.setColorAt(0.0, _blend(bg, primary, 98))
            g.setColorAt(0.5, _blend(bg, primary, 60))
            g.setColorAt(1.0, _blend(bg, primary, 36))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawPath(shell)

            # side light: bright on the left, falling into shade on the right
            side = QLinearGradient(-0.86 * r, 0, 0.86 * r, 0)
            side.setColorAt(0.0, _c(white, 46))
            side.setColorAt(0.45, _c(white, 0))
            side.setColorAt(1.0, _c(black, 64))
            p.setBrush(QBrush(side))
            p.drawPath(shell)

            # energy sweep, clipped to the shell
            p.save()
            p.setClipPath(shell)
            sy = self._scan * r
            band = QLinearGradient(0, sy - 0.16 * r, 0, sy + 0.16 * r)
            band.setColorAt(0.0, _c(accent, 0))
            band.setColorAt(0.5, _c(accent, 34 + 40 * amp))
            band.setColorAt(1.0, _c(accent, 0))
            p.setBrush(QBrush(band))
            p.drawRect(QRectF(-r, sy - 0.16 * r, 2 * r, 0.32 * r))
            p.restore()

            # outline + inner bevel
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(rim, pen_w * 1.25))
            p.drawPath(shell)
            p.setPen(QPen(_c(primary, 70), pen_w * 0.8))
            p.drawPath(self._shell_path(r, 0.93))

            # crown vent lines + forehead gem
            p.setPen(QPen(_c(primary, 120), pen_w, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            for i, w in enumerate((0.34, 0.22, 0.10)):
                yy = -0.93 + i * 0.04
                p.drawLine(P(-w, yy), P(w, yy))
            gem = QPainterPath()
            gy = -0.72
            gs = 0.055 + 0.015 * amp
            gem.moveTo(P(0, gy - gs * 1.4))
            gem.lineTo(P(gs, gy))
            gem.lineTo(P(0, gy + gs * 1.4))
            gem.lineTo(P(-gs, gy))
            gem.closeSubpath()
            p.setPen(QPen(_c(accent, 220), pen_w * 0.8))
            p.setBrush(QBrush(_c(accent, 90 + 150 * amp)))
            p.drawPath(gem)

            self._paint_eyes(p, r, primary, accent, visor_fill, amp, cartoon, pen_w)
            self._paint_brows(p, r, primary, pen_w, cartoon)

            # nose sensor bridge
            p.setPen(QPen(_c(primary, 105), pen_w, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            nose = QPainterPath()
            nose.moveTo(P(0.0, -0.01))
            nose.lineTo(P(0.0, 0.20))
            nose.moveTo(P(-0.07, 0.24))
            nose.lineTo(P(0.0, 0.205))
            nose.lineTo(P(0.07, 0.24))
            p.drawPath(nose)

            self._paint_vents(p, r, primary, accent, amp, pen_w)
            self._paint_mouth(p, r, primary, accent, bg, dark, pen_w)
        finally:
            p.restore()

    def _paint_neck(self, p, r, primary, bg, black, pen_w) -> None:
        """Segmented neck that fades into the background at the bottom."""
        def P(x, y):
            return QPointF(x * r, y * r)
        neck = QPainterPath()
        neck.moveTo(P(-0.27, 0.90))
        neck.lineTo(P(0.27, 0.90))
        neck.lineTo(P(0.36, 1.60))
        neck.lineTo(P(-0.36, 1.60))
        neck.closeSubpath()
        g = QLinearGradient(0, 0.9 * r, 0, 1.6 * r)
        g.setColorAt(0.0, _blend(bg, primary, 50))
        g.setColorAt(1.0, _c(_blend(bg, primary, 20), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(neck)
        for i, yy in enumerate((1.08, 1.24, 1.40)):
            half = 0.285 + (yy - 0.90) * 0.13
            p.setPen(QPen(_c(primary, 110 - i * 30), pen_w))
            p.drawLine(P(-half, yy), P(half, yy))
        p.setPen(QPen(_c(primary, 90), pen_w))
        p.drawLine(P(-0.27, 0.90), P(-0.36, 1.45))
        p.drawLine(P(0.27, 0.90), P(0.36, 1.45))

    def _paint_ears(self, p, r, primary, accent, bg, amp, pen_w) -> None:
        """Side sensor pods. The ear on the far side of a head turn shrinks."""
        for side in (-1, 1):
            turn = _clamp(side * self._yaw / 0.4, 0.0, 1.0)
            wf = 1.0 - 0.55 * turn
            x0 = side * 0.84 * r
            w = 0.17 * r * wf
            top, bot = -0.30 * r, 0.30 * r
            pod = QPainterPath()
            rect = QRectF(min(x0, x0 + side * w), top, w, bot - top)
            pod.addRoundedRect(rect, 0.07 * r, 0.07 * r)
            p.setPen(QPen(_c(primary, 200), pen_w))
            p.setBrush(QBrush(_blend(bg, primary, 52)))
            p.drawPath(pod)
            # glowing ring: the ear "listens", so it brightens with the level
            ex = x0 + side * 0.085 * r * wf
            er_x = 0.055 * r * wf
            er_y = 0.11 * r
            p.setPen(QPen(_c(accent, 120 + 120 * amp), pen_w * 1.2))
            p.setBrush(QBrush(_c(accent, 24 + 70 * amp)))
            p.drawEllipse(QPointF(ex, 0.0), er_x, er_y)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_c(accent, 170 + 80 * amp)))
            p.drawEllipse(QPointF(ex, 0.0), er_x * 0.35, er_y * 0.22)

    def _paint_eyes(self, p, r, primary, accent, visor_fill, amp,
                    cartoon, pen_w) -> None:
        """Visor band with two LED eyes that track the gaze and blink."""
        def P(x, y):
            return QPointF(x * r, y * r)
        vy0, vy1 = (-0.56, 0.02) if cartoon else (-0.50, -0.04)
        visor = QPainterPath()
        visor.addRoundedRect(QRectF(-0.72 * r, vy0 * r, 1.44 * r, (vy1 - vy0) * r),
                             0.20 * r, 0.20 * r)
        p.setPen(QPen(_c(primary, 170), pen_w))
        p.setBrush(QBrush(visor_fill))
        p.drawPath(visor)

        ey = (vy0 + vy1) * 0.5
        esc = 1.22 if cartoon else 1.0
        rx = 0.175 * r * esc
        ry_full = 0.115 * r * esc
        wake = 0.30 + 0.70 * _clamp(self._lids)
        openness = _clamp(self._lids * (1.0 - self._blink)
                          * (1.0 + 0.16 * max(0.0, self._brow)), 0.0, 1.15)
        ry = max(0.012 * r, ry_full * openness)
        gx, gy = self._gaze

        for side in (-1, 1):
            ecx = side * 0.38 * r
            ecy = ey * r
            eye = QPainterPath()
            eye.addEllipse(QPointF(ecx, ecy), rx, ry)
            # glow halo
            halo = QRadialGradient(ecx, ecy, rx * 1.9)
            halo.setColorAt(0.0, _c(accent, (60 + 70 * amp) * wake))
            halo.setColorAt(1.0, _c(accent, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(ecx, ecy), rx * 1.9, rx * 1.9)
            # iris
            iris = QRadialGradient(ecx + gx * rx * 0.2, ecy + gy * ry * 0.2, rx)
            iris.setColorAt(0.0, _c(accent, 255 * wake))
            iris.setColorAt(0.65, _c(accent, 200 * wake))
            iris.setColorAt(1.0, _c(accent, 110 * wake))
            p.setBrush(QBrush(iris))
            p.drawPath(eye)
            # pupil + specular, clipped to the visible eye
            p.save()
            p.setClipPath(eye)
            px = ecx + gx * rx * 0.46
            py = ecy + gy * max(ry, 0.05 * r) * 0.55
            pr = rx * 0.40
            p.setBrush(QBrush(_blend(visor_fill, QColor(0, 0, 0), 255)))
            p.drawEllipse(QPointF(px, py), pr, pr * 1.05)
            p.setBrush(QBrush(QColor(255, 255, 255, int(235 * wake))))
            p.drawEllipse(QPointF(px - pr * 0.38, py - pr * 0.42),
                          pr * 0.28, pr * 0.28)
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c(accent, 230 * wake), pen_w * 0.9))
            p.drawPath(eye)

    def _paint_brows(self, p, r, primary, pen_w, cartoon) -> None:
        """Light-bar brows. Lift when speaking, slant inward when thinking."""
        def P(x, y):
            return QPointF(x * r, y * r)
        b = self._brow
        base = -0.66 if not cartoon else -0.72
        lift = -b * 0.10
        slant = _clamp(-b, 0.0, 0.5) * 0.09 - _clamp(b, 0.0, 1.2) * 0.02
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 225), max(2.0, r * 0.045),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for side in (-1, 1):
            outer = P(side * 0.62, base + lift)
            inner = P(side * 0.16, base + lift + slant)
            p.drawLine(inner, outer)

    def _paint_vents(self, p, r, primary, accent, amp, pen_w) -> None:
        """Three LED slats per cheek that light up from the bottom with loudness."""
        def P(x, y):
            return QPointF(x * r, y * r)
        for side in (-1, 1):
            for i in range(3):
                lit = _clamp(amp * 1.5 - (2 - i) * 0.22)
                a = 55 + 190 * lit
                col = accent if lit > 0.15 else primary
                p.setPen(QPen(_c(col, a), max(1.5, r * 0.030),
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                yy = 0.22 + i * 0.075
                p.drawLine(P(side * 0.55, yy), P(side * 0.74 - side * i * 0.03, yy))

    def _paint_mouth(self, p, r, primary, accent, bg, dark, pen_w) -> None:
        """Lip slot. Height = jaw opening, width = lip spread / rounding."""
        def P(x, y):
            return QPointF(x * r, y * r)
        m = _clamp(self._mouth)
        wide = max(-1.0, min(1.0, self._wide))
        mw = 0.30 * (1.0 + 0.30 * wide) * (1.0 - 0.10 * m)
        y0 = 0.50
        h = 0.012 + 0.205 * m

        mouth = QPainterPath()
        mouth.moveTo(P(-mw, y0))
        mouth.quadTo(P(0.0, y0 - 0.055), P(mw, y0))          # upper lip
        mouth.quadTo(P(0.0, y0 + 2.0 * h + 0.020), P(-mw, y0))  # lower lip
        mouth.closeSubpath()

        # chin crease: the jaw plate line follows the jaw down
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 85), pen_w, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        cy_ = y0 + h + 0.20
        crease = QPainterPath()
        crease.moveTo(P(-0.30, cy_ - 0.02))
        crease.quadTo(P(0.0, cy_ + 0.035), P(0.30, cy_ - 0.02))
        p.drawPath(crease)

        # glow behind the lips
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 40 + 60 * m), max(3.0, r * 0.07),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(mouth)

        # cavity
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dark))
        p.drawPath(mouth)

        if m > 0.06:
            p.save()
            p.setClipPath(mouth)
            # upper teeth strip
            teeth = _blend(QColor(255, 255, 255), primary, 55)
            th = 0.035 + 0.05 * m
            p.setBrush(QBrush(teeth))
            p.drawRoundedRect(QRectF(-mw * r, (y0 - 0.03) * r, 2 * mw * r, th * r),
                              0.012 * r, 0.012 * r)
            # tongue glow on the lower lip
            p.setBrush(QBrush(_c(accent, 110 + 90 * m)))
            p.drawEllipse(P(0.0, y0 + 2.0 * h * 0.62), mw * r * 0.58,
                          max(0.01, h * 0.55) * r)
            p.restore()

        # lip line on top
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(primary, 235), max(1.6, r * 0.026),
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(mouth)

"""
Expressive Xyrus robot avatar for the HUD.

A friendly metallic robot inspired by the supplied expression model sheet.
It is drawn live with QPainter, preserving Xyrus lip-sync, blinking, gaze,
state animation and public HoloAvatar API. No raster sprite is required.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient


def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _rate(dt, tau):
    return 1.0 - math.exp(-max(0.0, dt) / max(0.001, tau))


def _alpha(c, a):
    q = QColor(c)
    q.setAlpha(int(_clamp(a, 0, 255)))
    return q


def _mix(a, b, t):
    t = _clamp(t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class HoloAvatar:
    """Animated expressive robot. Public API intentionally matches the old avatar."""

    shaded = True

    def __init__(self):
        self.SPAN = 2.62
        self.style = "face"
        self._t = 0.0
        self._yaw = self._pitch = 0.0
        self._gaze = [0.0, 0.0]
        self._gaze_tgt = [0.0, 0.0]
        self._gaze_at = 0.0
        self._glance = None
        self._mouth = 0.0
        self._wide = 0.15
        self._v_open = 1.0
        self._glow = 0.0
        self._blink = 0.0
        self._blink_at = 2.4
        self._brow = 0.0
        self._emotion = "neutral"
        self._lids = 1.0
        self._emph = 0.0

    def glance(self, dx, dy, hold=1.1):
        self._glance = (_clamp(float(dx), -1, 1), _clamp(float(dy), -1, 1),
                        self._t + max(0.1, float(hold)))

    def _mouth_step(self, dt, amp, speaking, v_open=None, v_level=None):
        if v_open is not None:
            self._v_open += (float(v_open) - self._v_open) * _rate(dt, 0.018)
        shape = self._v_open if v_open is not None else 1.0
        level = float(v_level) if v_level is not None else float(amp)
        target = _clamp((level ** 0.55) * shape * 1.65) if speaking else 0.0
        tau = 0.020 if target > self._mouth else 0.050
        self._mouth += (target - self._mouth) * _rate(dt, tau)

    def step(self, dt, amp, speaking=False, muted=False, state="",
             v_open=None, v_wide=None, v_level=None, v_seq=None, v_hop=0.02, **_):
        dt = _clamp(float(dt or 0.016), 0.001, 0.12)
        self._t += dt
        st = str(state or "").upper()
        live = bool(speaking and not muted)

        if st in ("SLEEPING", "STANDBY", "OFFLINE"):
            self._emotion, self._lids = "sleep", 0.05
        elif st in ("THINKING", "PROCESSING"):
            self._emotion, self._lids = "thinking", 0.78
        elif st in ("ERROR", "FAILED"):
            self._emotion, self._lids = "sad", 0.72
        elif st in ("LISTENING", "AWAKE"):
            self._emotion, self._lids = "curious", 1.0
        elif live:
            self._emotion, self._lids = "happy", 1.0
        else:
            self._emotion, self._lids = "neutral", 1.0

        if v_seq is not None:
            for lv, op, wd in v_seq:
                self._mouth_step(v_hop, amp, live, op, lv)
                if wd is not None:
                    self._wide += (_clamp(float(wd), -1, 1) - self._wide) * _rate(v_hop, .025)
        else:
            self._mouth_step(dt, amp, live, v_open, v_level)
            if v_wide is not None:
                self._wide += (_clamp(float(v_wide), -1, 1) - self._wide) * _rate(dt, .025)
        self._emph += (self._mouth - self._emph) * _rate(dt, .075)
        self._glow += (_clamp(float(amp) * 2.0 + (0.18 if live else 0)) - self._glow) * _rate(dt, .09)
        self._brow += (((0.35 if live else 0.0) + self._emph * .35) - self._brow) * _rate(dt, .11)

        if self._t >= self._blink_at and self._emotion != "sleep":
            phase = self._t - self._blink_at
            self._blink = math.sin(min(1.0, phase / .16) * math.pi) if phase < .16 else 0.0
            if phase >= .16:
                self._blink_at = self._t + random.uniform(2.1, 4.8)
        elif self._emotion == "sleep":
            self._blink = 1.0
        else:
            self._blink = max(0.0, self._blink - dt * 8)

        if self._glance and self._t < self._glance[2]:
            self._gaze_tgt = [self._glance[0], self._glance[1]]
        else:
            self._glance = None
            if self._t >= self._gaze_at:
                if self._emotion == "thinking":
                    self._gaze_tgt = [random.uniform(.25, .65), random.uniform(-.65, -.2)]
                else:
                    self._gaze_tgt = [random.uniform(-.35, .35), random.uniform(-.22, .20)]
                self._gaze_at = self._t + random.uniform(1.2, 3.2)
        for i in (0, 1):
            self._gaze[i] += (self._gaze_tgt[i] - self._gaze[i]) * _rate(dt, .18)
        self._yaw += ((self._gaze[0] * .08) - self._yaw) * _rate(dt, .30)
        nod = (-self._emph * .045 if live else math.sin(self._t * .75) * .012)
        self._pitch += (nod - self._pitch) * _rate(dt, .22)

    @staticmethod
    def _head_path(r):
        p = QPainterPath()
        p.moveTo(-.60*r, -.92*r)
        p.cubicTo(-.84*r, -.80*r, -.91*r, -.45*r, -.87*r, .15*r)
        p.cubicTo(-.83*r, .66*r, -.60*r, .94*r, -.28*r, 1.00*r)
        p.cubicTo(-.08*r, 1.04*r, .08*r, 1.04*r, .28*r, 1.00*r)
        p.cubicTo(.60*r, .94*r, .83*r, .66*r, .87*r, .15*r)
        p.cubicTo(.91*r, -.45*r, .84*r, -.80*r, .60*r, -.92*r)
        p.cubicTo(.24*r, -1.02*r, -.24*r, -1.02*r, -.60*r, -.92*r)
        p.closeSubpath()
        return p

    def paint(self, p, cx, cy, r, primary, accent, bg=None):
        bg = QColor(bg or QColor(4, 14, 25))
        cyan = QColor(accent)
        blue = QColor(primary)
        white = QColor(225, 252, 255)
        dark = QColor(5, 17, 32)
        silver = QColor(124, 147, 174)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        aura = QRadialGradient(cx, cy, 2.0*r)
        aura.setColorAt(0, _alpha(cyan, 35 + self._glow*55))
        aura.setColorAt(.55, _alpha(blue, 18 + self._glow*25))
        aura.setColorAt(1, _alpha(cyan, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(aura)
        p.drawEllipse(QPointF(cx, cy), 2*r, 2*r)

        p.translate(cx + self._yaw*r*.55, cy + self._pitch*r + math.sin(self._t*.8)*r*.008)
        p.rotate(math.degrees(self._yaw)*.20)
        pen = max(1.2, r*.018)

        # shoulders / chest bust
        chest = QPainterPath(); chest.moveTo(-1.08*r, 1.58*r)
        chest.cubicTo(-.98*r, 1.22*r, -.61*r, 1.12*r, -.36*r, 1.10*r)
        chest.lineTo(.36*r, 1.10*r); chest.cubicTo(.61*r, 1.12*r, .98*r, 1.22*r, 1.08*r, 1.58*r)
        chest.closeSubpath()
        cg = QLinearGradient(0, 1.08*r, 0, 1.65*r); cg.setColorAt(0, QColor(30,50,76)); cg.setColorAt(1, QColor(8,20,38))
        p.setPen(QPen(_alpha(cyan, 160), pen)); p.setBrush(cg); p.drawPath(chest)
        p.setBrush(QColor(9,24,43)); p.drawRoundedRect(QRectF(-.23*r,.88*r,.46*r,.42*r), .08*r,.08*r)
        for y in (.94,1.04,1.14):
            p.setPen(QPen(_alpha(cyan, 80), pen)); p.drawLine(QPointF(-.18*r,y*r), QPointF(.18*r,y*r))
        core = QRadialGradient(0,1.40*r,.19*r); core.setColorAt(0,white); core.setColorAt(.35,cyan); core.setColorAt(1,_alpha(cyan,0))
        p.setPen(QPen(_alpha(cyan,190),pen)); p.setBrush(core); p.drawEllipse(QPointF(0,1.40*r),.18*r,.18*r)

        # ears
        for s in (-1,1):
            ex=s*.91*r
            p.setPen(QPen(_alpha(cyan,210),pen)); p.setBrush(QColor(20,43,67)); p.drawRoundedRect(QRectF(ex-s*.02*r-.14*r,-.39*r,.28*r,.58*r),.12*r,.12*r)
            p.setBrush(QColor(5,22,39)); p.drawEllipse(QPointF(ex,.0),.11*r,.19*r)
            p.setPen(QPen(_alpha(cyan,160+self._glow*90),pen*1.2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(QPointF(ex,0),.07*r,.13*r)

        shell=self._head_path(r)
        sg=QLinearGradient(-.6*r,-r,.7*r,r); sg.setColorAt(0,QColor(169,188,210)); sg.setColorAt(.25,QColor(64,89,119)); sg.setColorAt(.58,QColor(22,43,69)); sg.setColorAt(1,QColor(74,91,116))
        p.setPen(QPen(_alpha(cyan,210),pen*1.15)); p.setBrush(sg); p.drawPath(shell)
        # helmet cap and seams
        cap=QPainterPath(); cap.moveTo(-.59*r,-.90*r); cap.quadTo(0,-1.08*r,.59*r,-.90*r); cap.lineTo(.47*r,-.70*r); cap.quadTo(0,-.83*r,-.47*r,-.70*r); cap.closeSubpath()
        p.setBrush(QColor(13,34,61)); p.setPen(QPen(_alpha(blue,190),pen)); p.drawPath(cap)
        p.setPen(QPen(_alpha(cyan,150),pen)); p.drawLine(QPointF(-.47*r,-.70*r),QPointF(-.20*r,-.66*r)); p.drawLine(QPointF(.20*r,-.66*r),QPointF(.47*r,-.70*r))
        gem=QPainterPath(); gem.moveTo(0,-.75*r); gem.lineTo(.10*r,-.61*r); gem.lineTo(0,-.47*r); gem.lineTo(-.10*r,-.61*r); gem.closeSubpath()
        p.setBrush(_alpha(cyan,210)); p.setPen(QPen(white,pen*.65)); p.drawPath(gem)

        # visor
        visor=QPainterPath(); visor.addRoundedRect(QRectF(-.70*r,-.49*r,1.40*r,.54*r),.22*r,.22*r)
        vg=QLinearGradient(0,-.5*r,0,.06*r); vg.setColorAt(0,QColor(1,8,17)); vg.setColorAt(1,QColor(5,20,30))
        p.setPen(QPen(_alpha(cyan,190),pen)); p.setBrush(vg); p.drawPath(visor)
        self._paint_eyes(p,r,cyan,white,dark,pen)
        self._paint_brows(p,r,cyan,pen)
        self._paint_mouth(p,r,cyan,white,dark,pen)

        # cheek panels
        for s in (-1,1):
            p.setPen(QPen(_alpha(cyan,80+self._glow*150),pen*.9,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            for i in range(3):
                y=(.26+i*.075)*r; p.drawLine(QPointF(s*.55*r,y),QPointF(s*(.73-i*.025)*r,y))
        # chin armour seam
        p.setPen(QPen(_alpha(blue,135),pen)); p.drawArc(QRectF(-.42*r,.55*r,.84*r,.35*r),200*16,140*16)
        p.restore()

    def _paint_eyes(self,p,r,cyan,white,dark,pen):
        emo=self._emotion
        openv=_clamp(self._lids*(1-self._blink))
        if emo=="sleep": openv=.04
        eye_y=-.22*r
        for s in (-1,1):
            ex=s*.34*r; ey=eye_y
            rx=(.18 if self.style=="cartoon" else .16)*r
            ry=max(.012*r,.13*r*openv)
            # sad/curious eye offsets create readable asymmetry
            if emo=="sad": ey += (s*.018+.025)*r
            if emo=="curious": ey += (-.018 if s<0 else .018)*r
            halo=QRadialGradient(ex,ey,rx*1.8); halo.setColorAt(0,_alpha(cyan,95)); halo.setColorAt(1,_alpha(cyan,0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(halo); p.drawEllipse(QPointF(ex,ey),rx*1.8,rx*1.5)
            p.setPen(QPen(_alpha(cyan,230),pen)); p.setBrush(_mix(cyan,white,.70)); p.drawEllipse(QPointF(ex,ey),rx,ry)
            if openv>.12:
                px=ex+self._gaze[0]*rx*.38; py=ey+self._gaze[1]*ry*.42
                pr=max(.018*r,ry*.43)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(dark); p.drawEllipse(QPointF(px,py),pr,pr)
                p.setBrush(white); p.drawEllipse(QPointF(px-pr*.35,py-pr*.42),pr*.25,pr*.25)

    def _paint_brows(self,p,r,cyan,pen):
        emo=self._emotion
        for s in (-1,1):
            outer=QPointF(s*.55*r,-.51*r); inner=QPointF(s*.16*r,-.49*r)
            if emo=="happy": outer.setY(-.55*r); inner.setY(-.59*r)
            elif emo=="thinking": outer.setY((- .58 if s<0 else -.50)*r); inner.setY((- .48 if s<0 else -.58)*r)
            elif emo=="sad": outer.setY(-.55*r); inner.setY(-.43*r)
            elif emo=="curious": outer.setY((- .61 if s<0 else -.50)*r); inner.setY((- .55 if s<0 else -.47)*r)
            inner.setY(inner.y()-self._brow*.035*r); outer.setY(outer.y()-self._brow*.035*r)
            p.setPen(QPen(_alpha(cyan,225),pen*1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawLine(inner,outer)

    def _paint_mouth(self,p,r,cyan,white,dark,pen):
        emo=self._emotion; y=.42*r
        if self._mouth<.045:
            path=QPainterPath(); path.moveTo(-.25*r,y)
            curve=.065*r if emo in ("happy","curious") else (-.045*r if emo=="sad" else .012*r)
            path.quadTo(0,y+curve,.25*r,y)
            p.setPen(QPen(_alpha(cyan,230),pen*1.4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path); return
        h=(.055+.22*self._mouth)*r; w=(.25+.08*_clamp(self._wide,-1,1))*r
        m=QPainterPath(); m.moveTo(-w,y); m.quadTo(0,y-.05*r,w,y); m.quadTo(0,y+2*h,-w,y); m.closeSubpath()
        p.setPen(QPen(_alpha(cyan,230),pen)); p.setBrush(QColor(2,8,16)); p.drawPath(m)
        teeth=QPainterPath(); teeth.moveTo(-w*.82,y+.012*r); teeth.quadTo(0,y+.06*r,w*.82,y+.012*r); teeth.lineTo(w*.70,y+.07*r); teeth.quadTo(0,y+.10*r,-w*.70,y+.07*r); teeth.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(white); p.drawPath(teeth)
        p.setBrush(_alpha(cyan,150)); p.drawEllipse(QPointF(0,y+h*1.42),w*.54,h*.24)

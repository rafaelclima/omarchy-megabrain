#!/usr/bin/env python3
import argparse
import math
import os
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Gtk4LayerShell, cairo

DB_FLOOR = -60.0
FRAME_MS = 60
FADE_MS = 20


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def rounded_rect(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    cr.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    cr.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    cr.close_path()


def render_meter(cr, w, h, level, peak, active, accent, idle_color):
    pad_x, pad_y = 12.0, 7.0
    avail_h = h - 2 * pad_y
    bar_w = 4.0
    gap = 2.5
    n = int((w - 2 * pad_x + gap) / (bar_w + gap))
    used = n * bar_w + (n - 1) * gap
    start_x = pad_x + (w - 2 * pad_x - used) / 2
    radius = bar_w / 2
    c = parse_color_hex(accent if active else idle_color)
    for i in range(n):
        x = start_x + i * (bar_w + gap)
        rounded_rect(cr, x, h - pad_y - avail_h * 0.10, bar_w, avail_h * 0.10, radius)
        cr.set_source_rgba(c[0], c[1], c[2], 0.10)
        cr.fill()
    for i in range(n):
        t = (i + 0.5) / n
        filled = clamp((level - t) * n, 0.0, 1.0)
        if filled <= 0.01:
            continue
        bar_h = max(avail_h * 0.10, avail_h * filled * 0.92)
        x = start_x + i * (bar_w + gap)
        y = h - pad_y - bar_h
        cr.set_source_rgba(c[0], c[1], c[2], 0.30 + 0.65 * filled)
        rounded_rect(cr, x, y, bar_w, bar_h, min(radius, bar_h / 2))
        cr.fill()
    if active:
        p = clamp(peak, 0.0, 1.0)
        if p > 0.02:
            px = start_x + int(min(p * n, n - 1)) * (bar_w + gap)
            bhar = max(avail_h * 0.10, avail_h * p * 0.92)
            py = h - pad_y - bhar
            rounded_rect(cr, px - 1.0, py - 2.0, bar_w + 2.0, 2.0, 1.0)
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.80)
            cr.fill()


def parse_color_hex(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


class Indicator:
    def __init__(self, args):
        self.args = args
        self.state_file = Path(args.state_file)
        self.level = 0.0
        self.peak = 0.0
        self.audio_ok = True
        self.ui_state = None
        self.fading = False
        self.pw = None
        self.wav = None
        self.audio_file = Path(args.audio_file)

        self.window = Gtk.Window(title="dictation-indicator", resizable=False)
        self.window.set_decorated(False)

        display = Gdk.Display.get_default()
        monitor = self.pick_monitor(display)
        mon_w = monitor.get_geometry().width if monitor else 1920
        width = max(240, min(1000, int(mon_w * args.width_pct)))

        Gtk4LayerShell.init_for_window(self.window)
        Gtk4LayerShell.set_layer(self.window, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_anchor(self.window, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_margin(self.window, Gtk4LayerShell.Edge.BOTTOM, args.margin_bottom)
        Gtk4LayerShell.set_keyboard_mode(self.window, Gtk4LayerShell.KeyboardMode.NONE)
        Gtk4LayerShell.set_exclusive_zone(self.window, 0)
        if monitor is not None:
            Gtk4LayerShell.set_monitor(self.window, monitor)

        self.window.set_default_size(width, args.height)
        self.window.set_size_request(width, args.height)

        self.accent = args.accent
        self.idle_color = args.idle

        css = Gtk.CssProvider()
        css.load_from_string(
            f"""
            .pill {{ background-color: rgba(14, 9, 29, 0.85); border-radius: 16px; }}
            .state-label {{ font-size: 13px; font-weight: 600; }}
            .idle {{ color: {self.idle_color}; }}
            .active {{ color: {self.accent}; }}
            .error {{ color: #f93d3b; }}
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("pill")
        self.window.set_child(root)

        self.label = Gtk.Label(label="", xalign=0.5)
        self.label.add_css_class("state-label")
        root.append(self.label)

        self.area = Gtk.DrawingArea()
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self.draw)
        root.append(self.area)

        self.update_ui("idle", False)

    def pick_monitor(self, display):
        if display is None:
            return None
        monitors = list(display.get_monitors())
        if not monitors:
            return None
        target = None
        for m in monitors:
            try:
                conn = m.get_connector()
            except Exception:
                conn = None
            if self.args.monitor and conn == self.args.monitor:
                target = m
                break
        return target or monitors[0]

    def update_ui(self, state, audio_ok):
        if self.ui_state == state and self.audio_ok == audio_ok:
            return
        self.ui_state = state
        self.audio_ok = audio_ok
        self.label.remove_css_class("idle")
        self.label.remove_css_class("active")
        self.label.remove_css_class("error")
        if not audio_ok:
            self.label.set_text("Sem microfone")
            self.label.add_css_class("error")
        elif state == "idle":
            self.label.set_text("Aguardando voz…")
            self.label.add_css_class("idle")
        else:
            self.label.set_text("Gravando…")
            self.label.add_css_class("active")
        self.area.queue_draw()

    def audio_cb(self, indata, frames, t, status):
        rms = float(np.sqrt(np.mean(indata ** 2)))
        db = 20.0 * math.log10(rms + 1e-9)
        target = clamp((db - DB_FLOOR) / -DB_FLOOR, 0.0, 1.0)
        if target > self.level:
            self.level += (target - self.level) * 0.45
        else:
            self.level += (target - self.level) * 0.08
        self.peak = max(self.peak - 0.02, self.level)

    def tick(self):
        if self.fading:
            return GLib.SOURCE_CONTINUE
        if not self.state_file.exists():
            self.start_fade()
            return GLib.SOURCE_CONTINUE
        if self.pw is None and self.wav is None and self.audio_ok:
            self.start_pw()
        if self.pw is None:
            self.update_ui("idle", False)
        elif self.level > 0.05:
            self.update_ui("active", True)
        else:
            self.update_ui("idle", True)
        self.area.queue_draw()
        self.debug_n = getattr(self, "debug_n", 0) + 1
        if self.debug_n % 10 == 0:
            with open("/tmp/dictation-indicator.log", "a") as f:
                f.write(
                    f"tick L={self.level:.3f} P={self.peak:.3f} "
                    f"st={self.ui_state} pw={'yes' if self.pw else 'no'}\n"
                )
        return GLib.SOURCE_CONTINUE

    def draw(self, area, cr, w, h):
        if getattr(self, "debug_draw", 0) < 3:
            self.debug_draw = getattr(self, "debug_draw", 0) + 1
            with open("/tmp/dictation-indicator.log", "a") as f:
                f.write(f"draw w={w} h={h} level={self.level:.3f}\n")
        render_meter(
            cr, w, h,
            self.level, self.peak,
            self.ui_state == "active",
            self.accent, self.idle_color,
        )

    def start_fade(self):
        if self.fading:
            return
        self.fading = True
        if self.pw is not None:
            try:
                self.pw.terminate()
            except Exception:
                pass
        steps = 15
        current = [steps]

        def step():
            current[0] -= 1
            if current[0] <= 0:
                self.window.close()
                return GLib.SOURCE_REMOVE
            self.window.set_opacity(current[0] / steps)
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(FADE_MS, step)

    def run(self):
        if Gdk.Display.get_default() is None:
            print("sem display Wayland", file=sys.stderr)
            sys.exit(1)
        app = Gtk.Application(
            application_id="org.dictation.indicator",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        app.connect("activate", self.on_activate)
        app.run(None)

    def on_activate(self, app):
        app.add_window(self.window)
        self.start_pw()
        self.window.present()
        GLib.timeout_add(FRAME_MS, self.tick)
        signal.signal(signal.SIGTERM, self.on_signal)
        signal.signal(signal.SIGINT, self.on_signal)

    def start_pw(self):
        debug = open("/tmp/dictation-indicator.log", "a")
        try:
            self.wav = wave.open(str(self.audio_file), "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)
            self.wav.setframerate(48000)
            self.pw = subprocess.Popen(
                ["pw-cat", "--record", "--raw", "--format", "f32",
                 "--rate", "48000", "--channels", "1", "-"],
                stdout=subprocess.PIPE, stderr=debug,
                start_new_session=True,
            )
            ch = GLib.IOChannel.unix_new(self.pw.stdout.fileno())
            GLib.io_add_watch(
                ch, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP,
                self.on_pw_data,
            )
            print(f"ok: pw-cat pid={self.pw.pid}", file=debug, flush=True)
        except Exception as e:
            self.audio_ok = False
            print(f"fail pw-cat: {type(e).__name__}: {e}", file=debug, flush=True)

    def on_pw_data(self, channel, condition):
        chunk = os.read(self.pw.stdout.fileno(), 65536)
        if not chunk:
            self.finalize()
            return GLib.SOURCE_REMOVE
        audio = np.frombuffer(chunk, dtype="<f4")
        rms = float(np.sqrt(np.mean(audio ** 2)))
        db = 20.0 * math.log10(rms + 1e-9)
        target = clamp((db - DB_FLOOR) / -DB_FLOOR, 0.0, 1.0)
        if target > self.level:
            self.level += (target - self.level) * 0.45
        else:
            self.level += (target - self.level) * 0.08
        self.peak = max(self.peak - 0.02, self.level)
        pcm = np.clip(audio * 32767.0, -32768.0, 32767.0).astype(np.int16)
        if self.wav is not None:
            self.wav.writeframes(pcm.tobytes())
        return GLib.SOURCE_CONTINUE

    def finalize(self):
        if self.pw is not None:
            self.pw.terminate()
            try:
                self.pw.wait(timeout=2)
            except Exception:
                self.pw.kill()
            self.pw = None
        if self.wav is not None:
            try:
                self.wav.close()
            except Exception:
                pass
            self.wav = None

    def on_signal(self, signum, frame):
        GLib.idle_add(self.start_fade)


def main():
    parser = argparse.ArgumentParser(prog="dictation indicator")
    parser.add_argument("--monitor", default=None)
    parser.add_argument("--state-file", default="/tmp/dictation.state")
    parser.add_argument("--audio-file", default="/tmp/dictation.wav")
    parser.add_argument("--width-pct", type=float, default=0.25)
    parser.add_argument("--height", type=int, default=56)
    parser.add_argument("--margin-bottom", type=int, default=28)
    parser.add_argument("--accent", default="#BE3F50")
    parser.add_argument("--idle", default="#14B9B5")
    args = parser.parse_args()
    Indicator(args).run()


if __name__ == "__main__":
    main()

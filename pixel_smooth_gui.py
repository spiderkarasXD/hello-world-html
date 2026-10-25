#!/usr/bin/env python3
"""Pixel Smooth GUI: графическая версия pixel-smooth.sh в стиле Material You.

Нужны Python 3 (с tkinter) и adb в PATH (или рядом с этим файлом).
Бэкап совместим с pixel-smooth.sh: ~/.pixel-smooth-backup-<serial>.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADB = shutil.which("adb") or str(HERE / ("adb.exe" if os.name == "nt" else "adb"))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------- adb-логика

def tweaks(hz):
    return [
        ("global", "window_animation_scale", "1.0"),
        ("global", "transition_animation_scale", "1.0"),
        ("global", "animator_duration_scale", "1.0"),
        ("system", "min_refresh_rate", str(hz)),
        ("system", "peak_refresh_rate", str(hz)),
        ("global", "low_power", "0"),
        ("global", "adaptive_battery_management_enabled", "0"),
        ("global", "app_standby_enabled", "0"),
    ]


class AdbError(Exception):
    pass


def adb(*args, serial=None):
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise AdbError("adb не найден: установите Android platform-tools")
    except subprocess.TimeoutExpired:
        raise AdbError("adb не отвечает")
    return r.returncode, (r.stdout + r.stderr).replace("\r", "").strip()


class Device:
    def __init__(self, serial):
        self.serial = serial
        self.backup = Path.home() / f".pixel-smooth-backup-{serial}"

    def sh(self, *args):
        return adb("shell", *args, serial=self.serial)[1]

    def get(self, ns, key):
        return self.sh("settings", "get", ns, key)

    def put(self, ns, key, val):
        return adb("shell", "settings", "put", ns, key, val, serial=self.serial)[0] == 0

    def info(self):
        sdk = self.sh("getprop", "ro.build.version.sdk")
        return (self.sh("getprop", "ro.product.model"),
                self.sh("getprop", "ro.product.brand"),
                int(sdk) if sdk.isdigit() else 0)

    def max_hz(self):
        fps = [round(float(x)) for x in re.findall(r"fps=(\d+(?:\.\d+)?)", self.sh("dumpsys", "display"))]
        return max(fps, default=60)


def list_devices():
    _, out = adb("devices")
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devs.append((parts[0], parts[1]))
    return devs

# ---------------------------------------------------------------- Material You

# Тональная палитра Material 3 (seed #6750A4, baseline)
THEMES = {
    "light": dict(
        primary="#6750A4", on_primary="#FFFFFF",
        primary_container="#EADDFF", on_primary_container="#21005D",
        secondary_container="#E8DEF8", on_secondary_container="#1D192B",
        surface="#FEF7FF", on_surface="#1D1B20", on_surface_variant="#49454F",
        surface_container="#F3EDF7", surface_container_high="#ECE6F0",
        outline="#79747E", outline_variant="#CAC4D0", error="#B3261E",
    ),
    "dark": dict(
        primary="#D0BCFF", on_primary="#381E72",
        primary_container="#4F378B", on_primary_container="#EADDFF",
        secondary_container="#4A4458", on_secondary_container="#E8DEF8",
        surface="#141218", on_surface="#E6E0E9", on_surface_variant="#CAC4D0",
        surface_container="#211F26", surface_container_high="#2B2930",
        outline="#938F99", outline_variant="#49454F", error="#F2B8B5",
    ),
}


def system_is_dark():
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True)
            return "Dark" in r.stdout
        r = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                           capture_output=True, text=True)
        return "dark" in r.stdout
    except Exception:
        return False


def pick_font(root):
    families = set(tkfont.families(root))
    for f in ("Google Sans", "Roboto", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue"):
        if f in families:
            return f
    return "TkDefaultFont"


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """Скруглённый прямоугольник одним полигоном (smooth)."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def mix(c1, c2, a):
    """Смешать цвета (для state layer при наведении/нажатии)."""
    p = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    q = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * a):02X}" for x, y in zip(p, q))


class Pill(tk.Canvas):
    """Кнопка M3: filled / tonal / outlined / chip (selected)."""

    def __init__(self, parent, text, command, theme, bg, kind="filled", font=None,
                 height=40, width=None, selected=False):
        self.t, self.kind, self.text, self.command = theme, kind, text, command
        self.font, self.selected, self.enabled = font, selected, True
        self.hover = self.pressed = False
        w = width or (tkfont.Font(font=font).measure(text) + 48)
        super().__init__(parent, width=w, height=height, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._state(hover=True))
        self.bind("<Leave>", lambda e: self._state(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._state(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)

    def colors(self):
        t = self.t
        if self.kind == "filled":
            return t["primary"], t["on_primary"], None
        if self.kind == "tonal":
            return t["secondary_container"], t["on_secondary_container"], None
        if self.kind == "chip":
            if self.selected:
                return t["secondary_container"], t["on_secondary_container"], None
            return self["bg"], t["on_surface_variant"], t["outline"]
        return self["bg"], t["primary"], t["outline"]  # outlined

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        fill, fg, border = self.colors()
        layer = 0.12 if self.pressed else 0.08 if self.hover else 0
        if layer and self.enabled:
            fill = mix(fill, fg, layer)
        if not self.enabled:
            fill = mix(self["bg"], self.t["on_surface"], 0.12) if self.kind in ("filled", "tonal") else self["bg"]
            fg = mix(self["bg"], self.t["on_surface"], 0.38)
        round_rect(self, 1, 1, w - 1, h - 1, h / 2 if self.kind != "chip" else 8,
                   fill=fill, outline=border or fill, width=1)
        label = ("✓  " + self.text) if self.kind == "chip" and self.selected else self.text
        self.create_text(w / 2, h / 2, text=label, fill=fg, font=self.font)

    def _state(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, e):
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        self._state(pressed=False)
        if inside and self.enabled and self.command:
            self.command()

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self.draw()


class Card(tk.Canvas):
    """Карточка M3 со скруглением 16px; содержимое кладётся в .body."""

    def __init__(self, parent, color, bg, radius=16, pad=16):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.color, self.radius, self.pad = color, radius, pad
        self.body = tk.Frame(self, bg=color)
        self._win = self.create_window(pad, pad, window=self.body, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.body.bind("<Configure>", self._fit)

    def _layout(self, e):
        self.delete("bg")
        round_rect(self, 0, 0, e.width, e.height, self.radius, fill=self.color,
                   outline=self.color, tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(1, e.width - 2 * self.pad))
        if self.expand_body:
            self.itemconfigure(self._win, height=max(1, e.height - 2 * self.pad))

    def _fit(self, e):
        if not self.expand_body:
            self.configure(height=e.height + 2 * self.pad)

    expand_body = False

# ---------------------------------------------------------------- окно

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pixel Smooth")
        self.geometry("600x640")
        self.minsize(500, 560)
        self.family = pick_font(self)
        self.dark = system_is_dark()
        self.devices = []
        self.dev_index = 0
        self.hz = "Авто"
        self.log_lines = []
        self.busy = False
        self.build()
        self.after(150, self.refresh)

    def f(self, size, weight="normal"):
        return (self.family, size, weight)

    # --- построение UI (пересобирается при смене темы) ---
    def build(self):
        for w in self.winfo_children():
            w.destroy()
        t = self.t = THEMES["dark" if self.dark else "light"]
        S = t["surface"]
        self.configure(bg=S)

        # Top app bar
        bar = tk.Frame(self, bg=S)
        bar.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(bar, text="Pixel Smooth", bg=S, fg=t["on_surface"], font=self.f(22)).pack(side="left")
        Pill(bar, "☾" if not self.dark else "☀", self.toggle_theme, t, S, kind="outlined",
             font=self.f(14), width=40).pack(side="right")
        tk.Label(self, text="Плавные анимации на Pixel без root", bg=S, fg=t["on_surface_variant"],
                 font=self.f(11), anchor="w").pack(fill="x", padx=24, pady=(0, 16))

        # Карточка устройства
        dev_card = Card(self, t["surface_container"], S)
        dev_card.pack(fill="x", padx=16, pady=(0, 12))
        b = dev_card.body
        row = tk.Frame(b, bg=t["surface_container"])
        row.pack(fill="x")
        badge = tk.Canvas(row, width=48, height=48, bg=t["surface_container"], highlightthickness=0)
        badge.create_oval(0, 0, 48, 48, fill=t["primary_container"], outline="")
        badge.create_text(24, 24, text="📱", font=self.f(18), fill=t["on_primary_container"])
        badge.pack(side="left", padx=(0, 14))
        txt = tk.Frame(row, bg=t["surface_container"])
        txt.pack(side="left", fill="x", expand=True)
        self.dev_title = tk.Label(txt, bg=t["surface_container"], fg=t["on_surface"],
                                  font=self.f(14, "bold"), anchor="w")
        self.dev_title.pack(fill="x")
        self.dev_sub = tk.Label(txt, bg=t["surface_container"], fg=t["on_surface_variant"],
                                font=self.f(10), anchor="w")
        self.dev_sub.pack(fill="x")
        Pill(row, "⟳", self.refresh, t, t["surface_container"], kind="tonal",
             font=self.f(14), width=40).pack(side="right")
        self.switch_btn = Pill(row, "⇄", self.next_device, t, t["surface_container"], kind="tonal",
                               font=self.f(14), width=40)
        self.update_device_label()

        # Карточка частоты
        hz_card = Card(self, t["surface_container"], S)
        hz_card.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(hz_card.body, text="Частота экрана", bg=t["surface_container"], fg=t["on_surface"],
                 font=self.f(13, "bold"), anchor="w").pack(fill="x")
        tk.Label(hz_card.body, text="Фиксированная частота убирает скачки 60↔120 Гц во время анимаций",
                 bg=t["surface_container"], fg=t["on_surface_variant"], font=self.f(10),
                 anchor="w", justify="left", wraplength=500).pack(fill="x", pady=(2, 10))
        chips = tk.Frame(hz_card.body, bg=t["surface_container"])
        chips.pack(fill="x")
        for v in ("Авто", "60", "90", "120"):
            Pill(chips, v if v == "Авто" else f"{v} Гц", lambda v=v: self.set_hz(v), t,
                 t["surface_container"], kind="chip", font=self.f(11), height=32,
                 selected=(self.hz == v)).pack(side="left", padx=(0, 8))

        # Кнопки действий
        acts = tk.Frame(self, bg=S)
        acts.pack(fill="x", padx=16, pady=(4, 12))
        self.buttons = [
            Pill(acts, "Применить", lambda: self.run(self.apply), t, S, "filled", self.f(12, "bold")),
            Pill(acts, "Откатить", lambda: self.run(self.revert), t, S, "tonal", self.f(12, "bold")),
            Pill(acts, "Статус", lambda: self.run(self.status), t, S, "outlined", self.f(12, "bold")),
        ]
        for i, btn in enumerate(self.buttons):
            btn.pack(side="left", expand=True, fill="x", padx=(0 if i == 0 else 8, 0))
            btn.set_enabled(not self.busy)

        # Журнал
        log_card = Card(self, t["surface_container_high"], S)
        log_card.expand_body = True
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.log_box = tk.Text(log_card.body, bg=t["surface_container_high"], fg=t["on_surface"],
                               insertbackground=t["on_surface"], relief="flat", bd=0,
                               highlightthickness=0, wrap="word", font=("Consolas", 10),
                               selectbackground=t["primary_container"], state="disabled")
        self.log_box.tag_configure("ok", foreground=t["primary"])
        self.log_box.tag_configure("err", foreground=t["error"])
        self.log_box.tag_configure("head", foreground=t["on_surface"], font=self.f(11, "bold"))
        self.log_box.pack(fill="both", expand=True)
        for line, tag in self.log_lines:
            self._insert(line, tag)

    def toggle_theme(self):
        self.dark = not self.dark
        self.build()

    def set_hz(self, v):
        self.hz = v
        self.build()

    # --- журнал (потокобезопасно через after) ---
    def _insert(self, text, tag):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log(self, text):
        tag = "ok" if text.startswith(("ok", "restored", "Готово", "Откат выполнен")) else \
              "err" if text.startswith(("!", "Ошибка", "Внимание", "Нет ")) else \
              "head" if text.startswith("—") else ""

        def do():
            self.log_lines.append((text, tag))
            self._insert(text, tag)
        self.after(0, do)

    def set_busy(self, busy):
        def do():
            self.busy = busy
            for b in self.buttons:
                b.set_enabled(not busy)
        self.after(0, do)

    # --- устройства ---
    def update_device_label(self):
        if not self.devices:
            self.dev_title.configure(text="Телефон не подключён")
            self.dev_sub.configure(text="Включите отладку по USB и подключите кабель")
        else:
            serial, state = self.devices[self.dev_index]
            self.dev_title.configure(text=serial)
            self.dev_sub.configure(text={"device": "Готов к работе",
                                         "unauthorized": "Подтвердите отладку на экране телефона"}
                                   .get(state, state) +
                                   (f"  ·  {self.dev_index + 1}/{len(self.devices)}" if len(self.devices) > 1 else ""))
        if len(self.devices) > 1:
            self.switch_btn.pack(side="right", padx=(0, 8))
        else:
            self.switch_btn.pack_forget()

    def next_device(self):
        if self.devices:
            self.dev_index = (self.dev_index + 1) % len(self.devices)
            self.update_device_label()

    def refresh(self):
        try:
            self.devices = list_devices()
        except AdbError as e:
            self.devices = []
            self.log(f"Ошибка: {e}")
        self.dev_index = min(self.dev_index, max(0, len(self.devices) - 1))
        self.update_device_label()

    def run(self, action):
        if self.busy:
            return
        if not self.devices or self.devices[self.dev_index][1] != "device":
            self.log("Нет готового устройства")
            return
        dev = Device(self.devices[self.dev_index][0])

        def worker():
            self.set_busy(True)
            try:
                model, brand, sdk = dev.info()
                self.log(f"— {model} (SDK {sdk})")
                if brand != "google":
                    self.log("Внимание: это не Pixel, часть настроек может не сработать")
                action(dev, sdk)
            except AdbError as e:
                self.log(f"Ошибка: {e}")
            finally:
                self.set_busy(False)
        threading.Thread(target=worker, daemon=True).start()

    # --- действия ---
    def apply(self, dev, sdk):
        hz = dev.max_hz() if self.hz == "Авто" else int(self.hz)
        self.log(f"Частота экрана: {hz} Гц")
        fresh = not dev.backup.exists()
        lines = []
        for ns, key, val in tweaks(hz):
            if fresh:
                lines.append(f"{ns} {key} {dev.get(ns, key)}")
            ok = dev.put(ns, key, val)
            self.log(f"{'ok' if ok else '! не удалось'}: {key} = {dev.get(ns, key)}")
        if fresh:
            dev.backup.write_text("\n".join(lines) + "\n")
        else:
            self.log("Бэкап уже есть, исходные значения сохранены ранее")
        code = adb("shell", "cmd", "power", "set-fixed-performance-mode-enabled", "true",
                   serial=dev.serial)[0] if sdk >= 31 else 1
        self.log("ok: fixed performance mode" if code == 0 else "пропущено: fixed performance mode")
        self.log("Готово! Анимации должны стать плавнее")

    def revert(self, dev, sdk):
        if not dev.backup.exists():
            self.log("Нет бэкапа для этого устройства")
            return
        for line in dev.backup.read_text().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            ns, key, val = parts[0], parts[1], (parts[2] if len(parts) > 2 else "null")
            if val == "null":
                adb("shell", "settings", "delete", ns, key, serial=dev.serial)
            else:
                dev.put(ns, key, val)
            self.log(f"restored: {key} = {val}")
        adb("shell", "cmd", "power", "set-fixed-performance-mode-enabled", "false", serial=dev.serial)
        dev.backup.unlink()
        self.log("Откат выполнен")

    def status(self, dev, sdk):
        for ns, key, _ in tweaks(0):
            self.log(f"{key} = {dev.get(ns, key)}")
        self.log(f"max refresh = {dev.max_hz()} Гц")
        self.log(f"бэкап: {'есть' if dev.backup.exists() else 'нет'}")


if __name__ == "__main__":
    App().mainloop()

#!/usr/bin/env python3
"""Vibe MIDI GUI: MIDI на вибромоторе через adb, окно в стиле Material You.

Рядом должны лежать vibe_midi.py и pixel_smooth_gui.py (логика и виджеты).
Нужны Python 3 с tkinter и adb в PATH.
"""
import os
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog
from types import SimpleNamespace

import vibe_midi as vm
from pixel_smooth_gui import THEMES, Card, Pill, pick_font, round_rect, system_is_dark


class Player:
    """Проигрывание в фоне: скрипт на телефоне, прогресс по меткам @chunk."""

    def __init__(self, on_progress, on_done):
        self.on_progress, self.on_done = on_progress, on_done
        self.proc = None
        self.stopping = False

    def start(self, script, total):
        self.stopping = False
        threading.Thread(target=self._run, args=(script, total), daemon=True).start()

    def _run(self, script, total):
        err = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, newline="\n") as f:
                f.write(script)
                local = f.name
            try:
                vm.adb("push", local, vm.REMOTE)
            finally:
                os.unlink(local)
            self.proc = subprocess.Popen([vm.ADB, "shell", "sh", vm.REMOTE], stdout=subprocess.PIPE,
                                         text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in self.proc.stdout:
                m = re.match(r"@(\S+) (\d+)", line.strip())
                if m:
                    self.on_progress(int(m.group(2)), time.monotonic())
            self.proc.wait()
        except SystemExit as e:  # vm.adb сообщает об ошибках через sys.exit
            err = str(e)
        except OSError as e:
            err = str(e)
        finally:
            stop_remote_quiet()
            self.proc = None
            self.on_done(err, self.stopping)

    def stop(self):
        self.stopping = True
        # сначала гасим скрипт и мотор на телефоне, тогда adb shell завершится сам
        threading.Thread(target=stop_remote_quiet, daemon=True).start()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def stop_remote_quiet():
    try:
        vm.stop_remote()
        vm.adb("shell", "rm", "-f", vm.REMOTE, check=False)
    except SystemExit:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Vibe MIDI")
        self.geometry("600x760")
        self.minsize(520, 640)
        self.family = pick_font(self)
        self.dark = system_is_dark()

        # состояние (переживает пересборку UI при смене темы)
        self.tracks, self.song_title, self.demo = [], "", None
        self.caps, self.caps_err = None, ""
        self.mode = "auto"
        self.octave, self.speed, self.volume = tk.IntVar(value=0), tk.IntVar(value=100), tk.IntVar(value=255)
        self.playing, self.total = False, 0
        self.base_ms, self.base_t = 0, 0.0
        self.status = ""
        self.player = Player(self._progress, self._done)

        self.build()
        self.after(150, self.check_device)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def f(self, size, weight="normal"):
        return (self.family, size, weight)

    # ------------------------------------------------------------ UI
    def build(self):
        for w in self.winfo_children():
            w.destroy()
        t = self.t = THEMES["dark" if self.dark else "light"]
        S, C = t["surface"], t["surface_container"]
        self.configure(bg=S)

        bar = tk.Frame(self, bg=S)
        bar.pack(fill="x", padx=24, pady=(14, 2))
        tk.Label(bar, text="Vibe MIDI", bg=S, fg=t["on_surface"], font=self.f(22)).pack(side="left")
        Pill(bar, "☀" if self.dark else "☾", self.toggle_theme, t, S, kind="outlined",
             font=self.f(14), width=40).pack(side="right")
        tk.Label(self, text="MIDI на вибромоторе через adb, как у Steam Controller", bg=S,
                 fg=t["on_surface_variant"], font=self.f(11), anchor="w").pack(fill="x", padx=24, pady=(0, 10))

        # плеер
        pc = Card(self, C, S)
        pc.pack(fill="x", padx=16, pady=(0, 8))
        row = tk.Frame(pc.body, bg=C)
        row.pack(fill="x")
        self.fab = tk.Canvas(row, width=72, height=72, bg=C, highlightthickness=0, cursor="hand2")
        self.fab.pack(side="left", padx=(0, 18))
        self.fab.bind("<Button-1>", lambda e: self.toggle_play())
        info = tk.Frame(row, bg=C)
        info.pack(side="left", fill="x", expand=True)
        self.title_lbl = tk.Label(info, bg=C, fg=t["on_surface"], font=self.f(15, "bold"), anchor="w")
        self.title_lbl.pack(fill="x")
        self.status_lbl = tk.Label(info, bg=C, fg=t["on_surface_variant"], font=self.f(10), anchor="w",
                                   justify="left")
        self.status_lbl.pack(fill="x")
        self.bar = tk.Canvas(pc.body, height=8, bg=C, highlightthickness=0)
        self.bar.pack(fill="x", pady=(16, 4))
        times = tk.Frame(pc.body, bg=C)
        times.pack(fill="x")
        self.t_cur = tk.Label(times, bg=C, fg=t["on_surface_variant"], font=self.f(10))
        self.t_cur.pack(side="left")
        self.t_end = tk.Label(times, bg=C, fg=t["on_surface_variant"], font=self.f(10))
        self.t_end.pack(side="right")

        # мелодия
        sc = Card(self, C, S)
        sc.pack(fill="x", padx=16, pady=(0, 8))
        self.section(sc.body, "Мелодия", "Свой .mid файл или встроенное демо")
        chips = tk.Frame(sc.body, bg=C)
        chips.pack(fill="x")
        Pill(chips, "Открыть .mid", self.open_file, t, C, kind="tonal", font=self.f(11, "bold"),
             height=36).pack(side="left", padx=(0, 8))
        for key, label in (("tetris", "Тетрис"), ("ode", "Ода к радости"), ("scale", "Гамма")):
            Pill(chips, label, lambda k=key: self.load_demo(k), t, C, kind="chip", font=self.f(10),
                 height=32, selected=self.demo == key).pack(side="left", padx=(0, 6))

        # дорожки
        if len(self.tracks) > 1:
            tc = Card(self, C, S)
            tc.pack(fill="x", padx=16, pady=(0, 8))
            self.section(tc.body, "Дорожки", "Звучит одна нота за раз: самая высокая из включённых дорожек")
            box = tk.Frame(tc.body, bg=C)
            box.pack(fill="x")
            for i, tr in enumerate(self.tracks[:12]):
                tk.Checkbutton(
                    box, text=f"{tr.name or f'Дорожка {i + 1}'}   ·   "
                              f"{'ударные' if tr.drums else str(len(tr.notes)) + ' нот'}",
                    variable=tr.var, state="disabled" if tr.drums else "normal",
                    bg=C, fg=t["on_surface"], selectcolor=t["surface"], activebackground=C,
                    activeforeground=t["on_surface"], highlightthickness=0, bd=0, anchor="w",
                    font=self.f(10), disabledforeground=t["outline"],
                ).pack(fill="x", pady=1)
            if len(self.tracks) > 12:
                tk.Label(box, text=f"…и ещё {len(self.tracks) - 12} (включены)", bg=C,
                         fg=t["on_surface_variant"], font=self.f(10), anchor="w").pack(fill="x")

        # звук
        snd = Card(self, C, S)
        snd.pack(fill="x", padx=16, pady=(0, 8))
        self.section(snd.body, "Режим", self.mode_hint())
        mrow = tk.Frame(snd.body, bg=C)
        mrow.pack(fill="x", pady=(0, 8))
        for key, label in (("auto", "Авто"), ("freq", "Частота"), ("pwm", "Импульсы")):
            Pill(mrow, label, lambda k=key: self.set_mode(k), t, C, kind="chip", font=self.f(10),
                 height=32, selected=self.mode == key).pack(side="left", padx=(0, 6))
        sl = tk.Frame(snd.body, bg=C)
        sl.pack(fill="x")
        for i, args in enumerate((
                ("Октава", self.octave, -2, 2, 1, lambda v: f"{int(v):+d}" if int(v) else "0"),
                ("Темп", self.speed, 50, 150, 5, lambda v: f"{int(v)}%"),
                ("Сила", self.volume, 30, 255, 5, lambda v: f"{round(int(v) / 2.55)}%"))):
            col = tk.Frame(sl, bg=C)
            col.grid(row=0, column=i, sticky="we", padx=(0 if i == 0 else 12, 0))
            sl.columnconfigure(i, weight=1, uniform="s")
            self.slider(col, *args)

        self.draw_fab()
        self.update_labels()

    def section(self, parent, title, hint):
        bg = self.t["surface_container"]
        tk.Label(parent, text=title, bg=bg, fg=self.t["on_surface"], font=self.f(13, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(parent, text=hint, bg=bg, fg=self.t["on_surface_variant"], font=self.f(10), anchor="w",
                 justify="left", wraplength=520).pack(fill="x", pady=(2, 10))

    def slider(self, parent, label, var, lo, hi, step, fmt):
        t, bg = self.t, self.t["surface_container"]
        head = tk.Frame(parent, bg=bg)
        head.pack(fill="x", pady=(6, 0))
        tk.Label(head, text=label, bg=bg, fg=t["on_surface"], font=self.f(11)).pack(side="left")
        val = tk.Label(head, text=fmt(var.get()), bg=bg, fg=t["on_surface_variant"], font=self.f(10))
        val.pack(side="right")
        tk.Scale(parent, from_=lo, to=hi, resolution=step, orient="horizontal", variable=var,
                 showvalue=False, bg=t["primary"], troughcolor=t["secondary_container"],
                 activebackground=t["primary"], highlightthickness=0, bd=0, sliderrelief="flat",
                 sliderlength=22, width=10, command=lambda v: val.configure(text=fmt(v))).pack(fill="x", pady=(4, 0))

    def draw_fab(self):
        t, cv = self.t, self.fab
        cv.delete("all")
        round_rect(cv, 2, 2, 70, 70, 22, fill=t["primary_container"], outline=t["primary_container"])
        c = t["on_primary_container"]
        if self.playing:
            cv.create_rectangle(26, 24, 33, 48, fill=c, outline="")
            cv.create_rectangle(39, 24, 46, 48, fill=c, outline="")
        else:
            cv.create_polygon(29, 22, 29, 50, 51, 36, fill=c, outline="")

    def draw_bar(self, pos):
        cv, t = self.bar, self.t
        cv.delete("all")
        w = max(cv.winfo_width(), 10)
        round_rect(cv, 0, 2, w, 6, 2, fill=t["secondary_container"], outline=t["secondary_container"])
        if self.total and pos > 0:
            x = max(4, w * min(1, pos / self.total))
            round_rect(cv, 0, 2, x, 6, 2, fill=t["primary"], outline=t["primary"])

    def mode_hint(self):
        if self.caps is None:
            return self.caps_err or "Подключите телефон с отладкой по USB"
        if self.caps.freq_control:
            return (f"Мотор умеет менять частоту ({self.caps.fmin:g}–{self.caps.fmax:g} Гц): "
                    "«Частота» звучит чище, «Импульсы» как у Steam Controller")
        return "Мотор не умеет менять частоту: доступны только «Импульсы» (вкл/выкл с частотой ноты)"

    def update_labels(self):
        self.title_lbl.configure(text=self.song_title or "Выберите MIDI или демо")
        self.status_lbl.configure(text=self.status, fg=self.t["error"] if self.status.startswith("!")
                                  else self.t["on_surface_variant"])
        pos = self.position()
        self.t_cur.configure(text=vm.fmt(pos))
        self.t_end.configure(text=vm.fmt(self.total))
        self.after_idle(lambda: self.draw_bar(pos))

    def toggle_theme(self):
        self.dark = not self.dark
        self.build()

    def set_mode(self, m):
        self.mode = m
        self.build()

    def set_status(self, text):
        self.status = text
        self.update_labels()

    # ------------------------------------------------------------ данные
    def check_device(self):
        def work():
            try:
                caps, err = vm.device_caps(), ""
            except SystemExit as e:
                caps, err = None, str(e)
            self.after(0, lambda: self._caps(caps, err))
        threading.Thread(target=work, daemon=True).start()

    def _caps(self, caps, err):
        self.caps, self.caps_err = caps, err
        if caps is None:
            self.status = "! " + err
        elif self.status.startswith("!"):
            self.status = "Телефон подключён"
        self.build()

    def _set_tracks(self, tracks, title, demo=None):
        for tr in tracks:
            tr.var = tk.BooleanVar(value=not tr.drums)
        self.tracks, self.song_title, self.demo = tracks, title, demo
        self.total = 0
        self.status = f"{len(tracks)} дорож." if len(tracks) > 1 else ""
        self.build()

    def open_file(self):
        path = filedialog.askopenfilename(title="MIDI файл", filetypes=[("MIDI", "*.mid *.midi"), ("Все", "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                tracks = vm.parse_midi(f.read())
            if not tracks:
                raise ValueError("в файле нет нот")
        except (OSError, ValueError, IndexError) as e:
            self.set_status(f"! Не удалось открыть: {e}")
            return
        self._set_tracks(tracks, os.path.splitext(os.path.basename(path))[0])

    def load_demo(self, key):
        self._set_tracks(vm.demo_tracks(key), vm.DEMOS[key][0], key)
        self.toggle_play()

    # ------------------------------------------------------------ проигрывание
    def position(self):
        if not self.playing:
            return 0
        return min(self.total, self.base_ms + (time.monotonic() - self.base_t) * 1000)

    def toggle_play(self):
        if self.playing:
            self.player.stop()
            return
        if not self.tracks:
            self.set_status("Сначала выберите мелодию")
            return
        if self.caps is None:
            self.check_device()
            self.set_status("! " + (self.caps_err or "Телефон не подключён"))
            return
        segs = vm.monophonic([tr for tr in self.tracks if tr.var.get()])
        if not segs:
            self.set_status("! В выбранных дорожках нет нот")
            return
        mode = self.mode
        if mode == "auto":
            mode = "freq" if self.caps.freq_control else "pwm"
        if mode == "freq" and not self.caps.freq_control:
            self.set_status("! Мотор не поддерживает частоту, выберите «Импульсы»")
            return
        opt = SimpleNamespace(octave=self.octave.get(), speed=self.speed.get() / 100,
                              volume=self.volume.get(), duty=0.45)
        steps = vm.render_freq(segs, self.caps, opt) if mode == "freq" else vm.render_pwm(segs, opt)
        script, self.total = vm.build_script(vm.split(steps), mode == "freq")
        self.playing, self.base_ms, self.base_t = True, 0, time.monotonic()
        self.status = "Загружаю на телефон…"
        self.draw_fab()
        self.update_labels()
        self.player.start(script, self.total)
        self.tick()

    def tick(self):
        if self.playing:
            self.update_labels()
            self.after(100, self.tick)

    def _progress(self, ms, t):
        def do():
            self.base_ms, self.base_t = ms, t
            self.status = "Играет · " + ("частота" if self.mode != "pwm" and self.caps.freq_control else "импульсы")
        self.after(0, do)

    def _done(self, err, stopped):
        def do():
            self.playing = False
            self.status = "Остановлено" if stopped else f"! {err}" if err else "Готово"
            self.draw_fab()
            self.update_labels()
        self.after(0, do)

    def on_close(self):
        if self.playing:
            self.player.stop()
            threading.Thread(target=stop_remote_quiet, daemon=True).start()
        self.after(300, self.destroy)


if __name__ == "__main__":
    App().mainloop()

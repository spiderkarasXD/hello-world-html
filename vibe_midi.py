#!/usr/bin/env python3
"""Vibe MIDI: играет MIDI на вибромоторе Android через adb, как Steam Controller.

    python vibe_midi.py song.mid             # играть
    python vibe_midi.py song.mid --list      # показать дорожки
    python vibe_midi.py song.mid -t 2,3      # только дорожки 2 и 3
    python vibe_midi.py demo:tetris          # встроенное демо (tetris, ode, scale)
    python vibe_midi.py --info               # что умеет вибромотор телефона

Режимы (--mode):
    freq  мотору задаётся частота ноты (нужен FREQUENCY_CONTROL, есть на Pixel 6+)
    pwm   мотор включается/выключается с частотой ноты (работает везде)
    auto  freq если поддерживается, иначе pwm (по умолчанию)

Нужен adb в PATH и включённая отладка по USB. Root не нужен.
"""
import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ADB = shutil.which("adb") or "adb"
REMOTE = "/data/local/tmp/vibemidi.sh"
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ------------------------------------------------------------------ MIDI


class Note:
    __slots__ = ("s", "e", "midi", "ch")

    def __init__(self, s, e, midi, ch):
        self.s, self.e, self.midi, self.ch = s, e, midi, ch


class Track:
    def __init__(self, name=""):
        self.name, self.notes, self.channels = name, [], set()

    @property
    def drums(self):
        return bool(self.channels) and self.channels <= {9}


def parse_midi(data):
    if data[:4] != b"MThd":
        raise ValueError("это не MIDI файл")
    hlen, _fmt, ntrks, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise ValueError("SMPTE-тайминг не поддерживается")
    p = 8 + hlen
    raw, tempos = [], []

    while p + 8 <= len(data) and len(raw) < ntrks:
        cid, length = data[p:p + 4], struct.unpack(">I", data[p + 4:p + 8])[0]
        p += 8
        end = min(p + length, len(data))
        if cid != b"MTrk":
            p = end
            continue
        tr, notes, opened = Track(), [], {}
        tick, status = 0, 0

        def vlq():
            nonlocal p
            v = 0
            while True:
                b = data[p]
                p += 1
                v = (v << 7) | (b & 0x7F)
                if not b & 0x80:
                    return v

        while p < end:
            tick += vlq()
            b = data[p]
            if b & 0x80:
                status = b
                p += 1
            elif status < 0x80:
                p += 1
                continue
            if status == 0xFF:
                typ = data[p]
                p += 1
                ln = vlq()
                if typ == 0x51 and ln == 3:
                    tempos.append((tick, int.from_bytes(data[p:p + 3], "big")))
                elif typ == 0x03 and not tr.name:
                    tr.name = data[p:p + ln].decode("utf-8", "replace").strip()
                p += ln
                status = 0
            elif status in (0xF0, 0xF7):
                p += vlq()
                status = 0
            else:
                kind, ch = status & 0xF0, status & 0x0F
                a = data[p]
                p += 1
                v = 0
                if kind not in (0xC0, 0xD0):
                    v = data[p]
                    p += 1
                key = (ch, a)
                if kind == 0x90 and v > 0:
                    if key in opened:
                        notes.append((opened[key], tick, a, ch))
                    opened[key] = tick
                    tr.channels.add(ch)
                elif kind in (0x80, 0x90) and key in opened:
                    notes.append((opened.pop(key), tick, a, ch))
        for (ch, a), st in opened.items():
            notes.append((st, tick, a, ch))
        p = end
        tr.notes = notes
        raw.append(tr)

    # карта темпа: тики -> секунды
    tempos.sort()
    tmap = [[0, 0.0, 500000]]
    for t, us in tempos:
        lt, ls, lus = tmap[-1]
        if t == lt:
            tmap[-1][2] = us
        else:
            tmap.append([t, ls + (t - lt) * lus / 1e6 / division, us])

    def to_sec(tick):
        i = len(tmap) - 1
        while i > 0 and tmap[i][0] > tick:
            i -= 1
        t, s, us = tmap[i]
        return s + (tick - t) * us / 1e6 / division

    for tr in raw:
        tr.notes = [Note(to_sec(a), to_sec(b), m, ch) for a, b, m, ch in tr.notes if b > a]
    return [t for t in raw if t.notes]


# ------------------------------------------------------------------ демо

DEMOS = {
    "tetris": ("Коробейники (Тетрис)", 150, [
        76, 1, 71, .5, 72, .5, 74, 1, 72, .5, 71, .5, 69, 1, 69, .5, 72, .5, 76, 1, 74, .5, 72, .5,
        71, 1.5, 72, .5, 74, 1, 76, 1, 72, 1, 69, 1, 69, 1, 0, 1,
        0, .5, 74, 1, 77, .5, 81, 1, 79, .5, 77, .5, 76, 1.5, 72, .5, 76, 1, 74, .5, 72, .5,
        71, 1, 71, .5, 72, .5, 74, 1, 76, 1, 72, 1, 69, 1, 69, 1, 0, 1]),
    "ode": ("Ода к радости", 120, [
        64, 1, 64, 1, 65, 1, 67, 1, 67, 1, 65, 1, 64, 1, 62, 1, 60, 1, 60, 1, 62, 1, 64, 1,
        64, 1.5, 62, .5, 62, 2, 64, 1, 64, 1, 65, 1, 67, 1, 67, 1, 65, 1, 64, 1, 62, 1,
        60, 1, 60, 1, 62, 1, 64, 1, 62, 1.5, 60, .5, 60, 2]),
    "scale": ("Гамма до мажор", 120, [
        60, 1, 62, 1, 64, 1, 65, 1, 67, 1, 69, 1, 71, 1, 72, 2,
        71, 1, 69, 1, 67, 1, 65, 1, 64, 1, 62, 1, 60, 2]),
}


def demo_tracks(name):
    title, bpm, seq = DEMOS[name]
    tr, t, beat = Track(title), 0.0, 60 / bpm
    for i in range(0, len(seq), 2):
        dur = seq[i + 1] * beat
        if seq[i]:
            tr.notes.append(Note(t, t + dur * 0.92, seq[i], 0))
        t += dur
    tr.channels = {0}
    return [tr]


# ------------------------------------------------------------------ монофония


def monophonic(tracks):
    """Выбранные дорожки -> непересекающиеся отрезки (s, e, midi): верхний голос."""
    ev = []
    for tr in tracks:
        for n in tr.notes:
            if n.ch != 9:
                ev.append((n.s, 1, n))
                ev.append((n.e, 0, n))
    ev.sort(key=lambda x: (x[0], x[1]))
    active, segs, cur = set(), [], None
    for i, (t, on, n) in enumerate(ev):
        (active.add if on else active.discard)(n)
        if i + 1 < len(ev) and ev[i + 1][0] == t:
            continue
        top = max(active, key=lambda x: x.midi, default=None)
        if top is not (cur[2] if cur else None):
            if cur and t > cur[0]:
                segs.append((cur[0], t, cur[2].midi))
            cur = (t, None, top) if top else None
    return segs


# ------------------------------------------------------------------ вибромотор


class Caps:
    freq_control = False
    fmin, fmax, resonant = 0.0, 0.0, 0.0


def adb(*args, check=True, **kw):
    try:
        r = subprocess.run([ADB, *args], capture_output=True, text=True, **kw)
    except FileNotFoundError:
        sys.exit("adb не найден: установите Android platform-tools")
    if check and r.returncode != 0:
        sys.exit(f"adb: {(r.stderr or r.stdout).strip()}")
    return r.stdout.replace("\r", "")


def device_caps():
    state = adb("get-state", check=False).strip()
    if state != "device":
        err = adb("devices", check=False)
        if "unauthorized" in err:
            sys.exit("Подтвердите отладку по USB на экране телефона")
        sys.exit("Телефон не найден (проверьте adb devices; несколько устройств -> ANDROID_SERIAL)")
    dump = adb("shell", "dumpsys", "vibrator_manager")
    c = Caps()
    c.freq_control = "FREQUENCY_CONTROL" in dump
    m = re.search(r"mMinFrequencyHz=([\d.]+), mMaxFrequencyHz=([\d.]+)", dump) \
        or re.search(r"mFrequencyRange=\[([\d.]+), ([\d.]+)\]", dump)
    if m:
        c.fmin, c.fmax = float(m.group(1)), float(m.group(2))
    m = re.search(r"mResonantFrequency=([\d.]+)", dump)
    if m:
        c.resonant = float(m.group(1))
    if c.freq_control and not (0 < c.fmin < c.fmax):
        c.freq_control = False  # без диапазона частот не рискуем
    return c


def fold(f, lo, hi):
    """Перенести частоту октавами в [lo, hi]."""
    while f > hi:
        f /= 2
    while f < lo:
        f *= 2
    return min(f, hi)


def hz(midi, octave=0):
    return 440 * 2 ** ((midi - 69) / 12 + octave)


def best_shift(segs, lo, hi):
    """Общий сдвиг песни на октавы, чтобы в [lo, hi] попало больше всего звучания.

    Сдвигаем всю мелодию целиком: перенос каждой ноты отдельно ломает её рисунок.
    """
    def score(k):
        inside = sum(e - s for s, e, m in segs if lo <= hz(m, k) <= hi)
        return inside, -abs(k)
    return max(range(-6, 7), key=score)


def render_freq(segs, caps, opt):
    """[(ms, amp, freq)]: шаги с реальной частотой ноты."""
    # рабочий диапазон: октава внутри возможностей мотора, ближе к резонансу громче
    lo = max(caps.fmin, (caps.resonant or caps.fmin * 2) / 1.6)
    hi = min(caps.fmax, lo * 2)
    if hi < lo * 1.9:  # узкий диапазон: берём сколько есть
        lo, hi = caps.fmin, caps.fmax
    out, clock, last_f = [], 0, round(caps.resonant or lo)
    amp, shift = opt.volume, best_shift(segs, lo, hi) + opt.octave
    for s, e, midi in segs:
        s, e = round(s * 1000 / opt.speed), round(e * 1000 / opt.speed)
        if s > clock:
            out.append((s - clock, 0, last_f))
            clock = s
        f = round(fold(hz(midi, shift), caps.fmin, caps.fmax), 1)
        dur = e - clock
        gap = min(15, dur // 6)  # пауза между нотами, чтобы повторы были слышны
        if dur - gap > 0:
            out.append((dur - gap, amp, f))
        if gap:
            out.append((gap, 0, f))
        clock, last_f = e, f
    return out


def render_pwm(segs, opt):
    """[(ms, amp)]: импульсы вкл/выкл на частоте ноты (как Steam Controller)."""
    lo, hi = 55, 220  # шаг 1 мс: выше тона не различить
    out, clock = [], 0
    shift = best_shift(segs, lo, hi) + opt.octave

    def push(ms, amp):
        if ms <= 0:
            return
        if out and out[-1][1] == amp:
            out[-1] = (out[-1][0] + ms, amp)
        else:
            out.append((ms, amp))

    for s, e, midi in segs:
        s, e = round(s * 1000 / opt.speed), round(e * 1000 / opt.speed)
        push(s - clock, 0)
        clock = max(clock, s)
        period = 1000 / fold(hz(midi, shift), lo, hi)
        stop = e - min(15, (e - clock) // 6)
        k = 0
        while True:
            nxt = round(s + (k + 1) * period)
            if nxt > stop:
                break
            on = max(1, min(nxt - clock - 1, round(period * opt.duty)))
            push(on, opt.volume)
            push(nxt - clock - on, 0)
            clock, k = nxt, k + 1
        push(e - clock, 0)
        clock = max(clock, e)
    return out


def split(steps, max_steps=500, min_rest=40):
    """Разбить на куски по паузам: накладные расходы запуска cmd уходят в тишину."""
    chunks, cur = [], []
    for st in steps:
        cur.append(st)
        if len(cur) >= max_steps and st[1] == 0 and st[0] >= min_rest or len(cur) >= max_steps * 2:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_script(chunks, freq):
    lines = ["trap 'cmd vibrator_manager cancel; exit' INT TERM HUP"]
    total = 0
    for i, ch in enumerate(chunks):
        args = []
        for st in ch:
            args += [str(st[0]), str(st[1])] + ([f"{st[2]:g}"] if freq else [])
        lines.append(f"echo @{i} {total}")
        lines.append("cmd vibrator_manager synced -f -d vibemidi waveform -a "
                     + ("-f " if freq else "") + " ".join(args))
        total += sum(st[0] for st in ch)
    lines.append(f"echo @end {total}")
    return "\n".join(lines) + "\n", total


# ------------------------------------------------------------------ main


def fmt(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def stop_remote():
    adb("shell", f"pkill -f {REMOTE}; cmd vibrator_manager cancel", check=False)


def main():
    ap = argparse.ArgumentParser(description="MIDI на вибромоторе через adb")
    ap.add_argument("song", nargs="?", help="файл .mid или demo:tetris|ode|scale")
    ap.add_argument("-t", "--tracks", help="номера дорожек через запятую (см. --list)")
    ap.add_argument("--list", action="store_true", help="показать дорожки и выйти")
    ap.add_argument("--info", action="store_true", help="показать возможности вибромотора")
    ap.add_argument("-m", "--mode", choices=["auto", "freq", "pwm"], default="auto")
    ap.add_argument("-o", "--octave", type=int, default=0, help="сдвиг на октавы (-2..2)")
    ap.add_argument("-s", "--speed", type=float, default=1.0, help="темп, 1.0 = как в файле")
    ap.add_argument("-v", "--volume", type=int, default=255, help="амплитуда 1-255")
    ap.add_argument("--duty", type=float, default=0.45, help="скважность для pwm (0.2-0.7)")
    ap.add_argument("--dry-run", action="store_true", help="только показать скрипт, не играть")
    opt = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    opt.volume = max(1, min(255, opt.volume))

    if opt.info:
        c = device_caps()
        print(f"Управление частотой: {'да' if c.freq_control else 'нет'}")
        if c.fmax:
            print(f"Диапазон: {c.fmin:g}–{c.fmax:g} Гц, резонанс {c.resonant:g} Гц")
        return
    if not opt.song:
        ap.print_help()
        return

    if opt.song.startswith("demo:"):
        name = opt.song[5:]
        if name not in DEMOS:
            sys.exit("демо: " + ", ".join(DEMOS))
        tracks, title = demo_tracks(name), DEMOS[name][0]
    else:
        try:
            with open(opt.song, "rb") as f:
                tracks = parse_midi(f.read())
        except (OSError, ValueError, IndexError, struct.error) as e:
            sys.exit(f"Не удалось открыть {opt.song}: {e}")
        title = os.path.splitext(os.path.basename(opt.song))[0]
    if not tracks:
        sys.exit("В файле нет нот")

    if opt.list:
        for i, tr in enumerate(tracks, 1):
            lo, hi = min(n.midi for n in tr.notes), max(n.midi for n in tr.notes)
            kind = "ударные" if tr.drums else f"{NAMES[lo % 12]}{lo // 12 - 1}–{NAMES[hi % 12]}{hi // 12 - 1}"
            print(f"{i:3}. {tr.name or 'без имени':30} {len(tr.notes):5} нот  {kind}")
        return

    if opt.tracks:
        try:
            idx = [int(x) - 1 for x in opt.tracks.split(",")]
            tracks = [tracks[i] for i in idx]
        except (ValueError, IndexError):
            sys.exit("неверные номера дорожек, см. --list")

    segs = monophonic(tracks)
    if not segs:
        sys.exit("В выбранных дорожках нет нот (ударные не играются)")

    caps = device_caps() if not opt.dry_run else Caps()
    if opt.dry_run and opt.mode != "pwm":
        caps.freq_control, caps.fmin, caps.fmax, caps.resonant = True, 50, 300, 150
    mode = opt.mode
    if mode == "auto":
        mode = "freq" if caps.freq_control else "pwm"
    elif mode == "freq" and not caps.freq_control:
        sys.exit("Этот мотор не поддерживает управление частотой, используйте --mode pwm")

    steps = render_freq(segs, caps, opt) if mode == "freq" else render_pwm(segs, opt)
    script, total = build_script(split(steps), mode == "freq")

    if opt.dry_run:
        sys.stdout.write(script)
        return

    print(f"♪ {title}  ·  {fmt(total)}  ·  режим {mode}"
          + (f" ({caps.fmin:g}–{caps.fmax:g} Гц)" if mode == "freq" else ""))
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, newline="\n") as f:
        f.write(script)
        local = f.name
    try:
        adb("push", local, REMOTE)
    finally:
        os.unlink(local)

    proc = subprocess.Popen([ADB, "shell", "sh", REMOTE], stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            m = re.match(r"@(\S+) (\d+)", line.strip())
            if m:
                done = int(m.group(2))
                bar = int(30 * done / max(1, total))
                print(f"\r[{'#' * bar}{'.' * (30 - bar)}] {fmt(done)} / {fmt(total)}", end="", flush=True)
        proc.wait()
        print("\nГотово")
    except KeyboardInterrupt:
        proc.terminate()
        print("\nОстановлено")
    finally:
        if proc.poll() is None:
            proc.kill()
        stop_remote()
        adb("shell", "rm", "-f", REMOTE, check=False)


if __name__ == "__main__":
    main()

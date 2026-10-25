package com.spiderkaras.vibemidi;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Разбор Standard MIDI File и сведение в монофоническую мелодию (верхний голос). */
public final class MidiFile {

    /** Отрезок мелодии: с s по e секунд звучит нота midi. */
    public static final class Seg {
        public final double s, e;
        public final int midi;

        Seg(double s, double e, int midi) {
            this.s = s;
            this.e = e;
            this.midi = midi;
        }
    }

    private static final class Note {
        final long start, end;
        final int midi, ch;
        double s, e;

        Note(long start, long end, int midi, int ch) {
            this.start = start;
            this.end = end;
            this.midi = midi;
            this.ch = ch;
        }
    }

    private MidiFile() {}

    public static List<Seg> parse(byte[] d) {
        if (d.length < 14 || d[0] != 'M' || d[1] != 'T' || d[2] != 'h' || d[3] != 'd')
            throw new IllegalArgumentException("это не MIDI файл");
        int hlen = u32(d, 4);
        int ntrks = u16(d, 10);
        int division = u16(d, 12);
        if ((division & 0x8000) != 0) throw new IllegalArgumentException("SMPTE-тайминг не поддерживается");

        List<Note> notes = new ArrayList<>();
        List<long[]> tempos = new ArrayList<>(); // {tick, us}
        int p = 8 + hlen, tracks = 0;

        while (p + 8 <= d.length && tracks < ntrks) {
            boolean isTrack = d[p] == 'M' && d[p + 1] == 'T' && d[p + 2] == 'r' && d[p + 3] == 'k';
            int len = u32(d, p + 4);
            p += 8;
            int end = Math.min(d.length, p + Math.max(0, len));
            if (!isTrack) { p = end; continue; }
            tracks++;
            Map<Integer, Long> open = new HashMap<>();
            long tick = 0;
            int status = 0;
            int[] pos = {p};
            while (pos[0] < end) {
                tick += vlq(d, pos);
                if (pos[0] >= end) break;
                int b = d[pos[0]] & 0xff;
                if ((b & 0x80) != 0) { status = b; pos[0]++; }
                else if (status < 0x80) { pos[0]++; continue; }
                if (status == 0xff) {
                    int type = d[pos[0]++] & 0xff;
                    int l = (int) vlq(d, pos);
                    if (type == 0x51 && l == 3)
                        tempos.add(new long[]{tick, ((d[pos[0]] & 0xff) << 16) | ((d[pos[0] + 1] & 0xff) << 8) | (d[pos[0] + 2] & 0xff)});
                    pos[0] += l;
                    status = 0;
                } else if (status == 0xf0 || status == 0xf7) {
                    pos[0] += (int) vlq(d, pos);
                    status = 0;
                } else {
                    int kind = status & 0xf0, ch = status & 0x0f;
                    int a = d[pos[0]++] & 0x7f, v = 0;
                    if (kind != 0xc0 && kind != 0xd0) v = d[pos[0]++] & 0x7f;
                    int key = ch * 128 + a;
                    if (kind == 0x90 && v > 0) {
                        Long st = open.put(key, tick);
                        if (st != null) notes.add(new Note(st, tick, a, ch));
                    } else if (kind == 0x80 || kind == 0x90) {
                        Long st = open.remove(key);
                        if (st != null) notes.add(new Note(st, tick, a, ch));
                    }
                }
            }
            for (Map.Entry<Integer, Long> e : open.entrySet())
                notes.add(new Note(e.getValue(), tick, e.getKey() % 128, e.getKey() / 128));
            p = end;
        }

        // карта темпа
        tempos.sort((x, y) -> Long.compare(x[0], y[0]));
        List<double[]> map = new ArrayList<>(); // {tick, sec, us}
        map.add(new double[]{0, 0, 500000});
        for (long[] t : tempos) {
            double[] last = map.get(map.size() - 1);
            if (t[0] == (long) last[0]) { last[2] = t[1]; continue; }
            double sec = last[1] + (t[0] - last[0]) * last[2] / 1e6 / division;
            map.add(new double[]{t[0], sec, t[1]});
        }
        for (Note n : notes) {
            n.s = toSec(map, n.start, division);
            n.e = toSec(map, n.end, division);
        }
        return monophonic(notes);
    }

    private static double toSec(List<double[]> map, long tick, int division) {
        int i = map.size() - 1;
        while (i > 0 && map.get(i)[0] > tick) i--;
        double[] m = map.get(i);
        return m[1] + (tick - m[0]) * m[2] / 1e6 / division;
    }

    /** Верхний голос без ударных (10-й канал). */
    private static List<Seg> monophonic(List<Note> notes) {
        List<Object[]> ev = new ArrayList<>(); // {time, on(0/1), note}
        for (Note n : notes) {
            if (n.ch == 9 || n.e <= n.s) continue;
            ev.add(new Object[]{n.s, 1, n});
            ev.add(new Object[]{n.e, 0, n});
        }
        ev.sort((x, y) -> {
            int c = Double.compare((double) x[0], (double) y[0]);
            return c != 0 ? c : Integer.compare((int) x[1], (int) y[1]);
        });
        List<Note> active = new ArrayList<>();
        List<Seg> segs = new ArrayList<>();
        Note cur = null;
        double curStart = 0;
        for (int i = 0; i < ev.size(); i++) {
            double t = (double) ev.get(i)[0];
            Note n = (Note) ev.get(i)[2];
            if ((int) ev.get(i)[1] == 1) active.add(n); else active.remove(n);
            if (i + 1 < ev.size() && (double) ev.get(i + 1)[0] == t) continue;
            Note top = null;
            for (Note a : active) if (top == null || a.midi > top.midi) top = a;
            if (top != cur) {
                if (cur != null && t > curStart) segs.add(new Seg(curStart, t, cur.midi));
                cur = top;
                curStart = t;
            }
        }
        return segs;
    }

    /** Сдвиг на октавы, при котором в [lo, hi] звучит больше всего мелодии. */
    public static int bestShift(List<Seg> segs, float lo, float hi) {
        int best = 0;
        double bestScore = -1;
        for (int k = -6; k <= 6; k++) {
            double sc = 0;
            for (Seg s : segs) {
                float f = Synth.hz(s.midi, k);
                if (f >= lo && f <= hi) sc += s.e - s.s;
            }
            if (sc > bestScore || (sc == bestScore && Math.abs(k) < Math.abs(best))) {
                best = k;
                bestScore = sc;
            }
        }
        return best;
    }

    // ------------------------------------------------------------ демо

    public static List<Seg> demo(String name) {
        int bpm;
        double[] seq;
        switch (name) {
            case "tetris":
                bpm = 150;
                seq = new double[]{76, 1, 71, .5, 72, .5, 74, 1, 72, .5, 71, .5, 69, 1, 69, .5, 72, .5, 76, 1, 74, .5, 72, .5,
                        71, 1.5, 72, .5, 74, 1, 76, 1, 72, 1, 69, 1, 69, 1, 0, 1,
                        0, .5, 74, 1, 77, .5, 81, 1, 79, .5, 77, .5, 76, 1.5, 72, .5, 76, 1, 74, .5, 72, .5,
                        71, 1, 71, .5, 72, .5, 74, 1, 76, 1, 72, 1, 69, 1, 69, 1, 0, 1};
                break;
            case "ode":
                bpm = 120;
                seq = new double[]{64, 1, 64, 1, 65, 1, 67, 1, 67, 1, 65, 1, 64, 1, 62, 1, 60, 1, 60, 1, 62, 1, 64, 1,
                        64, 1.5, 62, .5, 62, 2, 64, 1, 64, 1, 65, 1, 67, 1, 67, 1, 65, 1, 64, 1, 62, 1,
                        60, 1, 60, 1, 62, 1, 64, 1, 62, 1.5, 60, .5, 60, 2};
                break;
            default:
                bpm = 120;
                seq = new double[]{60, 1, 62, 1, 64, 1, 65, 1, 67, 1, 69, 1, 71, 1, 72, 2,
                        71, 1, 69, 1, 67, 1, 65, 1, 64, 1, 62, 1, 60, 2};
        }
        List<Seg> segs = new ArrayList<>();
        double t = 0, beat = 60.0 / bpm;
        for (int i = 0; i < seq.length; i += 2) {
            double dur = seq[i + 1] * beat;
            if (seq[i] > 0) segs.add(new Seg(t, t + dur * 0.92, (int) seq[i]));
            t += dur;
        }
        return Collections.unmodifiableList(segs);
    }

    // ------------------------------------------------------------ байты

    private static int u16(byte[] d, int p) {
        return ((d[p] & 0xff) << 8) | (d[p + 1] & 0xff);
    }

    private static int u32(byte[] d, int p) {
        return ((d[p] & 0xff) << 24) | ((d[p + 1] & 0xff) << 16) | ((d[p + 2] & 0xff) << 8) | (d[p + 3] & 0xff);
    }

    private static long vlq(byte[] d, int[] pos) {
        long v = 0;
        while (pos[0] < d.length) {
            int b = d[pos[0]++] & 0xff;
            v = (v << 7) | (b & 0x7f);
            if ((b & 0x80) == 0) break;
        }
        return v;
    }
}

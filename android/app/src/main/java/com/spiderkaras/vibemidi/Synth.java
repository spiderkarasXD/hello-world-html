package com.spiderkaras.vibemidi;

import android.content.Context;
import android.media.AudioAttributes;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationAttributes;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.os.vibrator.VibratorEnvelopeEffectInfo;
import android.os.vibrator.VibratorFrequencyProfile;

import java.util.Arrays;
import java.util.TreeMap;

/**
 * Вибромотор как монофонический синтезатор.
 * FREQ: мотору задаётся частота ноты (envelope API, Android 16+).
 * PWM:  мотор включается/выключается с частотой ноты, как Steam Controller.
 */
public final class Synth {
    public static final int MODE_AUTO = 0, MODE_FREQ = 1, MODE_PWM = 2;
    static final float PWM_LO = 55f, PWM_HI = 220f;

    private static Synth instance;

    public static synchronized Synth get(Context ctx) {
        if (instance == null) instance = new Synth(ctx.getApplicationContext());
        return instance;
    }

    private final Vibrator vib;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final boolean envelope;
    private float fMin, fMax, resonant;
    private long minPoint = 1, maxPoint = 1000, maxDuration = 2000;

    private int mode = MODE_AUTO;
    private int octave = 0;
    private float strength = 1f;

    // живой вход: нота -> счётчик нажатий
    private final TreeMap<Integer, Integer> held = new TreeMap<>();
    private int current = -1;
    private Listener listener;

    public interface Listener { void onNote(int midi); }

    private Synth(Context ctx) {
        VibratorManager vm = ctx.getSystemService(VibratorManager.class);
        vib = vm.getDefaultVibrator();
        boolean env = false;
        if (Build.VERSION.SDK_INT >= 36) {
            try {
                env = vib.areEnvelopeEffectsSupported();
                VibratorFrequencyProfile p = vib.getFrequencyProfile();
                if (env && p != null) {
                    fMin = p.getMinFrequencyHz();
                    fMax = p.getMaxFrequencyHz();
                    VibratorEnvelopeEffectInfo info = vib.getEnvelopeEffectInfo();
                    minPoint = Math.max(1, info.getMinControlPointDurationMillis());
                    maxPoint = Math.max(minPoint, info.getMaxControlPointDurationMillis());
                    if (info.getMaxDurationMillis() > 0) maxDuration = info.getMaxDurationMillis();
                } else {
                    env = false;
                }
            } catch (RuntimeException e) {
                env = false;
            }
        }
        envelope = env && fMin > 0 && fMax > fMin;
        resonant = vib.getResonantFrequency();
        if (!(resonant > 0)) resonant = envelope ? (fMin + fMax) / 2 : 150f;
    }

    // ------------------------------------------------------------ настройки

    public boolean supportsFreq() { return envelope; }
    public float minHz() { return fMin; }
    public float maxHz() { return fMax; }
    public float resonantHz() { return resonant; }
    public boolean hasVibrator() { return vib.hasVibrator(); }

    public synchronized void setMode(int m) { mode = m; retrigger(); }
    public synchronized void setOctave(int o) { octave = o; retrigger(); }
    public synchronized void setStrength(float s) { strength = s; retrigger(); }
    public synchronized void setListener(Listener l) { listener = l; }
    public synchronized int octave() { return octave; }

    public synchronized boolean freqMode() {
        return mode == MODE_FREQ ? envelope : mode == MODE_AUTO && envelope;
    }

    /** Удобный диапазон: октава около резонанса (там громче всего). */
    public synchronized float lo() {
        if (!freqMode()) return PWM_LO;
        float lo = Math.max(fMin, resonant / 1.6f);
        return Math.min(lo, fMax / 2 > fMin ? fMax / 2 : fMin);
    }

    public synchronized float hi() {
        if (!freqMode()) return PWM_HI;
        return Math.min(fMax, lo() * 2);
    }

    // ------------------------------------------------------------ живой вход

    public synchronized void noteOn(int midi) {
        held.merge(midi, 1, Integer::sum);
        updateTop();
    }

    public synchronized void noteOff(int midi) {
        Integer n = held.get(midi);
        if (n == null) return;
        if (n <= 1) held.remove(midi); else held.put(midi, n - 1);
        updateTop();
    }

    public synchronized void allOff() {
        held.clear();
        updateTop();
    }

    private void updateTop() {
        int top = held.isEmpty() ? -1 : held.lastKey();
        if (top == current) return;
        if (top < 0) stop(); else play(top, -1, octave);
    }

    // ------------------------------------------------------------ звук

    private final Runnable sustain = () -> { synchronized (this) { retrigger(); } };

    private void retrigger() {
        if (current >= 0 && held.containsKey(current)) play(current, -1, octave);
    }

    /** Играть ноту durMs мс (или "бесконечно" при durMs < 0, с перезапуском). */
    public synchronized void play(int midi, long durMs, int shift) {
        handler.removeCallbacks(sustain);
        current = midi;
        if (listener != null) listener.onNote(midi);
        float amp = Math.max(0.05f, Math.min(1f, strength));
        VibrationEffect fx;
        if (freqMode()) {
            float f = fold(hz(midi, shift), lo(), hi());
            f = Math.max(fMin, Math.min(fMax, f));
            long total = durMs > 0 ? durMs : Math.min(maxDuration, 2000);
            fx = envelopeTone(f, amp, total);
            if (durMs < 0) handler.postDelayed(sustain, Math.max(50, total - 30));
        } else {
            fx = pwmTone(hz(midi, shift), amp, durMs);
        }
        vibrate(fx);
    }

    public synchronized void stop() {
        handler.removeCallbacks(sustain);
        current = -1;
        if (listener != null) listener.onNote(-1);
        vib.cancel();
    }

    private VibrationEffect envelopeTone(float f, float amp, long total) {
        VibrationEffect.WaveformEnvelopeBuilder b = new VibrationEffect.WaveformEnvelopeBuilder();
        b.setInitialFrequencyHz(f);
        long attack = Math.max(minPoint, 5);
        long release = total > 60 ? Math.max(minPoint, 10) : 0;
        b.addControlPoint(amp, f, attack);
        long body = total - attack - release;
        while (body > 0) {
            long d = Math.max(minPoint, Math.min(maxPoint, body));
            b.addControlPoint(amp, f, d);
            body -= d;
        }
        if (release > 0) b.addControlPoint(0f, f, release);
        return b.build();
    }

    /** Повторяющийся ШИМ на частоте ноты; дизеринг периода даёт точную высоту. */
    private VibrationEffect pwmTone(float hz, float amp, long durMs) {
        double period = 1000.0 / fold(hz, PWM_LO, PWM_HI);
        int cycles = Math.max(1, (int) Math.round(500 / period)); // ~0.5 с паттерна, потом повтор
        long[] t = new long[cycles * 2];
        int[] a = new int[cycles * 2];
        int amp255 = Math.max(1, Math.round(amp * 255));
        long clock = 0;
        for (int k = 0; k < cycles; k++) {
            long next = Math.round((k + 1) * period);
            long on = Math.max(1, Math.min(next - clock - 1, Math.round(period * 0.45)));
            t[2 * k] = on;
            a[2 * k] = amp255;
            t[2 * k + 1] = Math.max(1, next - clock - on);
            a[2 * k + 1] = 0;
            clock = next;
        }
        if (durMs > 0) {
            // конечная нота: развернуть паттерн на нужную длину без повтора
            long[] tt = new long[(int) durMs + 2];
            int[] aa = new int[(int) durMs + 2];
            long sum = 0;
            int i = 0;
            while (sum < durMs) {
                tt[i] = Math.min(t[i % t.length], durMs - sum);
                aa[i] = a[i % a.length];
                sum += tt[i++];
            }
            return VibrationEffect.createWaveform(Arrays.copyOf(tt, i), Arrays.copyOf(aa, i), -1);
        }
        return VibrationEffect.createWaveform(t, a, 0);
    }

    private void vibrate(VibrationEffect fx) {
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                vib.vibrate(fx, VibrationAttributes.createForUsage(VibrationAttributes.USAGE_MEDIA));
            } else {
                vib.vibrate(fx, new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build());
            }
        } catch (RuntimeException ignored) {
            // неподдерживаемый эффект: просто молчим
        }
    }

    // ------------------------------------------------------------ утилиты

    public static float hz(int midi, int octave) {
        return (float) (440.0 * Math.pow(2, (midi - 69) / 12.0 + octave));
    }

    public static float fold(float f, float lo, float hi) {
        while (f > hi) f /= 2;
        while (f < lo) f *= 2;
        return Math.min(f, hi);
    }

    public static String name(int midi) {
        String[] n = {"C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"};
        return n[midi % 12] + (midi / 12 - 1);
    }
}

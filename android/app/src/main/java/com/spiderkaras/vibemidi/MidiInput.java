package com.spiderkaras.vibemidi;

import android.content.Context;
import android.content.pm.ServiceInfo;
import android.media.midi.MidiDevice;
import android.media.midi.MidiDeviceInfo;
import android.media.midi.MidiManager;
import android.media.midi.MidiOutputPort;
import android.media.midi.MidiReceiver;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Слушает все MIDI-устройства (USB в режиме MIDI, Bluetooth, виртуальные) и играет их ноты. */
@SuppressWarnings("deprecation") // getDevices/registerDeviceCallback(Handler) работают на всех версиях
public final class MidiInput {

    public interface StatusListener { void onDevices(List<String> names); }

    private final Context ctx;
    private final MidiManager mm;
    private final Synth synth;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<Integer, MidiDevice> devices = new LinkedHashMap<>();
    private final Map<Integer, String> names = new LinkedHashMap<>();
    private StatusListener listener;
    private boolean running;

    private final MidiManager.DeviceCallback callback = new MidiManager.DeviceCallback() {
        @Override public void onDeviceAdded(MidiDeviceInfo info) { open(info); }
        @Override public void onDeviceRemoved(MidiDeviceInfo info) { close(info.getId()); }
    };

    public MidiInput(Context ctx, Synth synth) {
        this.ctx = ctx;
        this.synth = synth;
        this.mm = ctx.getSystemService(MidiManager.class);
    }

    public boolean available() { return mm != null; }

    public void start(StatusListener l) {
        listener = l;
        if (mm == null || running) { notifyStatus(); return; }
        running = true;
        mm.registerDeviceCallback(callback, handler);
        for (MidiDeviceInfo info : mm.getDevices()) open(info);
        notifyStatus();
    }

    public void stop() {
        if (mm == null || !running) return;
        running = false;
        mm.unregisterDeviceCallback(callback);
        for (Integer id : new ArrayList<>(devices.keySet())) close(id);
        synth.allOff();
    }

    private boolean isOwn(MidiDeviceInfo info) {
        Bundle p = info.getProperties();
        Object si = p.getParcelable(MidiDeviceInfo.PROPERTY_SERVICE_INFO);
        return si instanceof ServiceInfo && ctx.getPackageName().equals(((ServiceInfo) si).packageName);
    }

    private void open(MidiDeviceInfo info) {
        if (!running || info.getOutputPortCount() == 0 || isOwn(info) || devices.containsKey(info.getId())) return;
        mm.openDevice(info, device -> {
            if (device == null) return;
            if (!running) { closeQuietly(device); return; }
            for (int i = 0; i < info.getOutputPortCount(); i++) {
                MidiOutputPort port = device.openOutputPort(i);
                if (port != null) port.connect(new Parser(synth));
            }
            devices.put(info.getId(), device);
            names.put(info.getId(), name(info));
            notifyStatus();
        }, handler);
    }

    private void close(int id) {
        MidiDevice d = devices.remove(id);
        names.remove(id);
        if (d != null) closeQuietly(d);
        synth.allOff();
        notifyStatus();
    }

    private static void closeQuietly(MidiDevice d) {
        try { d.close(); } catch (IOException ignored) { }
    }

    private static String name(MidiDeviceInfo info) {
        Bundle p = info.getProperties();
        String n = p.getString(MidiDeviceInfo.PROPERTY_NAME);
        if (n == null) n = p.getString(MidiDeviceInfo.PROPERTY_PRODUCT);
        return n != null ? n : "MIDI #" + info.getId();
    }

    private void notifyStatus() {
        if (listener != null) listener.onDevices(new ArrayList<>(names.values()));
    }

    /** Поток MIDI-байтов -> noteOn/noteOff (с running status). */
    public static final class Parser extends MidiReceiver {
        private final Synth synth;
        private int status, need, got;
        private final int[] data = new int[2];

        public Parser(Synth synth) { this.synth = synth; }

        @Override
        public void onSend(byte[] msg, int offset, int count, long timestamp) {
            for (int i = offset; i < offset + count; i++) {
                int b = msg[i] & 0xff;
                if (b >= 0xf8) continue;                 // realtime: clock, start, stop
                if (b >= 0x80) {
                    status = b < 0xf0 ? b : 0;             // sysex/common игнорируем
                    int kind = status & 0xf0;
                    need = status == 0 ? 0 : (kind == 0xc0 || kind == 0xd0) ? 1 : 2;
                    got = 0;
                    continue;
                }
                if (status == 0) continue;
                data[got++] = b;
                if (got < need) continue;
                got = 0;                                   // running status
                handle(status & 0xf0, status & 0x0f, data[0], need > 1 ? data[1] : 0);
            }
        }

        private void handle(int kind, int ch, int a, int v) {
            if (ch == 9) return;                           // ударные
            if (kind == 0x90 && v > 0) synth.noteOn(a);
            else if (kind == 0x80 || kind == 0x90) synth.noteOff(a);
            else if (kind == 0xb0 && (a == 120 || a == 123)) synth.allOff();
        }
    }
}

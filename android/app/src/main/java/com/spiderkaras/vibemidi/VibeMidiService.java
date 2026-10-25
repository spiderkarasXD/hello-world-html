package com.spiderkaras.vibemidi;

import android.media.midi.MidiDeviceService;
import android.media.midi.MidiDeviceStatus;
import android.media.midi.MidiReceiver;

/** Виртуальный MIDI-порт «Vibe MIDI»: другие приложения на телефоне играют в вибромотор. */
public class VibeMidiService extends MidiDeviceService {

    @Override
    public MidiReceiver[] onGetInputPortReceivers() {
        return new MidiReceiver[]{new MidiInput.Parser(Synth.get(this))};
    }

    @Override
    public void onDeviceStatusChanged(MidiDeviceStatus status) {
        if (!status.isInputPortOpen(0)) Synth.get(this).allOff();
    }
}

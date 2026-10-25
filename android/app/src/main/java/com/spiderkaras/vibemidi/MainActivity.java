package com.spiderkaras.vibemidi;

import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.OpenableColumns;
import android.view.WindowManager;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.chip.Chip;
import com.google.android.material.chip.ChipGroup;
import com.google.android.material.color.DynamicColors;
import com.google.android.material.floatingactionbutton.FloatingActionButton;
import com.google.android.material.progressindicator.LinearProgressIndicator;
import com.google.android.material.slider.Slider;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {

    private static final Object PLAY = new Object();

    private final Handler handler = new Handler(Looper.getMainLooper());
    private Synth synth;
    private MidiInput midiInput;

    private TextView noteView, titleView, timeView, midiStatus, motorInfo;
    private LinearProgressIndicator progress;
    private FloatingActionButton fab;
    private ChipGroup demos;
    private Slider speedSlider;

    private List<MidiFile.Seg> song;
    private boolean playing;
    private long startUptime, totalMs;
    private double speed = 1;
    private int liveNote = -1;

    private final ActivityResultLauncher<String[]> openDoc =
            registerForActivityResult(new ActivityResultContracts.OpenDocument(), uri -> {
                if (uri != null) loadUri(uri);
            });

    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            updateUi();
            if (playing) handler.postDelayed(this, 50);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        DynamicColors.applyToActivityIfAvailable(this); // Material You: цвета из обоев
        super.onCreate(state);
        setContentView(R.layout.activity_main);
        synth = Synth.get(this);
        midiInput = new MidiInput(this, synth);

        noteView = findViewById(R.id.note);
        titleView = findViewById(R.id.songTitle);
        timeView = findViewById(R.id.time);
        midiStatus = findViewById(R.id.midiStatus);
        motorInfo = findViewById(R.id.motorInfo);
        progress = findViewById(R.id.progress);
        fab = findViewById(R.id.play);
        demos = findViewById(R.id.demos);
        speedSlider = findViewById(R.id.speed);

        fab.setOnClickListener(v -> { if (playing) stopSong(); else playSong(); });
        findViewById(R.id.open).setOnClickListener(v ->
                openDoc.launch(new String[]{"audio/midi", "audio/x-midi", "audio/mid", "audio/*", "application/octet-stream"}));
        bindDemo(R.id.demoTetris, "tetris", "Коробейники (Тетрис)");
        bindDemo(R.id.demoOde, "ode", "Ода к радости");
        bindDemo(R.id.demoScale, "scale", "Гамма до мажор");

        ChipGroup modes = findViewById(R.id.modes);
        Chip freqChip = findViewById(R.id.modeFreq);
        freqChip.setEnabled(synth.supportsFreq());
        modes.setOnCheckedStateChangeListener((g, ids) -> {
            int id = ids.isEmpty() ? R.id.modeAuto : ids.get(0);
            synth.setMode(id == R.id.modeFreq ? Synth.MODE_FREQ : id == R.id.modePwm ? Synth.MODE_PWM : Synth.MODE_AUTO);
            showMotorInfo();
        });
        ((Slider) findViewById(R.id.octave)).addOnChangeListener((s, v, user) -> synth.setOctave(Math.round(v)));
        ((Slider) findViewById(R.id.strength)).addOnChangeListener((s, v, user) -> synth.setStrength(v / 100f));
        speedSlider.addOnChangeListener((s, v, user) -> { if (!playing) speed = v / 100.0; });

        synth.setListener(midi -> handler.post(() -> {
            liveNote = midi;
            if (!playing) updateUi();
        }));
        showMotorInfo();
        updateUi();

        Uri data = getIntent().getData();
        if (data != null) loadUri(data);
    }

    @Override
    protected void onStart() {
        super.onStart();
        midiInput.start(names -> handler.post(() -> midiStatus.setText(names.isEmpty()
                ? "Нет MIDI-устройств"
                : "Слушаю: " + String.join(", ", names))));
        if (!midiInput.available()) midiStatus.setText("MIDI не поддерживается на этом устройстве");
    }

    @Override
    protected void onStop() {
        // в фоне Android может глушить вибрацию: останавливаемся честно
        stopSong();
        midiInput.stop();
        super.onStop();
    }

    // ------------------------------------------------------------ мелодия

    private void bindDemo(int id, String key, String title) {
        findViewById(id).setOnClickListener(v -> {
            stopSong();
            song = MidiFile.demo(key);
            titleView.setText(title);
            playSong();
        });
    }

    private void loadUri(Uri uri) {
        stopSong();
        try (InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IOException("нет доступа к файлу");
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            List<MidiFile.Seg> segs = MidiFile.parse(out.toByteArray());
            if (segs.isEmpty()) throw new IllegalArgumentException("в файле нет мелодических нот");
            song = segs;
            demos.clearCheck();
            titleView.setText(displayName(uri));
            updateUi();
        } catch (IOException | RuntimeException e) {
            Toast.makeText(this, "Не удалось открыть: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private String displayName(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                String n = c.getString(0);
                if (n != null) return n.replaceAll("(?i)\\.midi?$", "");
            }
        } catch (RuntimeException ignored) { }
        return "MIDI";
    }

    private void playSong() {
        if (song == null || song.isEmpty()) {
            Toast.makeText(this, "Сначала выберите мелодию", Toast.LENGTH_SHORT).show();
            return;
        }
        synth.allOff();
        speed = speedSlider.getValue() / 100.0;
        int shift = MidiFile.bestShift(song, synth.lo(), synth.hi()) + synth.octave();
        startUptime = SystemClock.uptimeMillis() + 150;
        for (MidiFile.Seg seg : song) {
            long s = Math.round(seg.s * 1000 / speed), e = Math.round(seg.e * 1000 / speed);
            long dur = Math.max(20, e - s - Math.min(15, (e - s) / 6)); // пауза: повторы различимы
            int midi = seg.midi;
            handler.postAtTime(() -> synth.play(midi, dur, shift), PLAY, startUptime + s);
        }
        totalMs = Math.round(song.get(song.size() - 1).e * 1000 / speed);
        handler.postAtTime(this::finished, PLAY, startUptime + totalMs + 50);
        playing = true;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        fab.setImageResource(android.R.drawable.ic_media_pause);
        handler.post(ticker);
    }

    private void finished() {
        playing = false;
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        fab.setImageResource(android.R.drawable.ic_media_play);
        updateUi();
    }

    private void stopSong() {
        if (!playing) return;
        handler.removeCallbacksAndMessages(PLAY);
        synth.stop();
        finished();
    }

    // ------------------------------------------------------------ UI

    private long position() {
        return playing ? Math.max(0, Math.min(totalMs, SystemClock.uptimeMillis() - startUptime)) : 0;
    }

    private void updateUi() {
        long pos = position();
        int note = -1;
        if (playing) {
            double t = pos * speed / 1000;
            for (MidiFile.Seg s : song) if (s.s <= t && t < s.e) { note = s.midi; break; }
        } else {
            note = liveNote;
        }
        noteView.setText(note >= 0 ? Synth.name(note) : "—");
        long total = playing ? totalMs : song == null || song.isEmpty() ? 0
                : Math.round(song.get(song.size() - 1).e * 1000 / (speedSlider.getValue() / 100.0));
        progress.setProgressCompat(total > 0 ? (int) (1000 * pos / total) : 0, false);
        timeView.setText(fmt(pos) + " / " + fmt(total));
    }

    private void showMotorInfo() {
        if (!synth.hasVibrator()) {
            motorInfo.setText("Вибромотор не найден");
        } else if (synth.supportsFreq()) {
            motorInfo.setText(String.format(Locale.US,
                    "Мотор умеет менять частоту: %.0f–%.0f Гц, резонанс %.0f Гц. Сейчас: %s",
                    synth.minHz(), synth.maxHz(), synth.resonantHz(),
                    synth.freqMode() ? "частота" : "импульсы"));
        } else {
            motorInfo.setText("Управление частотой недоступно (нужен Android 16+ и поддержка мотором). Играю импульсами, как Steam Controller.");
        }
    }

    private static String fmt(long ms) {
        long s = ms / 1000;
        return String.format(Locale.US, "%d:%02d", s / 60, s % 60);
    }
}

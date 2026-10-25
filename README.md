# Pixel Smooth

ADB-твик без root для телефонов Google Pixel: убирает дёрганые и обрывающиеся системные анимации.

## Что делает

| Настройка | Значение | Зачем |
|---|---|---|
| `window/transition_animation_scale`, `animator_duration_scale` | 1.0 | Значение 0 или «Убрать анимации» обрывает анимации, нестандартные ломают тайминги жестов |
| `min_refresh_rate`, `peak_refresh_rate` | максимум экрана (авто) | Нет скачков 60↔90/120 Гц посреди анимации |
| `low_power`, `adaptive_battery_management_enabled`, `app_standby_enabled` | 0 | Экономия заряда режет частоту и анимации |
| fixed performance mode (Android 12+) | вкл | Стабильные частоты CPU/GPU, до перезагрузки |

## Установка

1. На телефоне: Настройки → О телефоне → 7 раз нажать «Номер сборки». Затем Система → Для разработчиков → **Отладка по USB**.
2. На ПК установить [Android platform-tools](https://developer.android.com/tools/releases/platform-tools) (`adb`).
3. Подключить телефон, подтвердить запрос отладки на экране.

## Использование

```bash
./pixel-smooth.sh apply        # применить (частота определится сама)
./pixel-smooth.sh apply 90     # применить с явной частотой
./pixel-smooth.sh status       # текущие значения
./pixel-smooth.sh revert       # вернуть всё как было
```

На Windows запускайте через Git Bash или WSL. Если подключено несколько телефонов: `ANDROID_SERIAL=<serial> ./pixel-smooth.sh apply`.

Исходные значения сохраняются в `~/.pixel-smooth-backup-<serial>` при первом `apply`; повторный `apply` их не затирает.

## GUI (Windows / macOS / Linux)

Окно в стиле Material You: светлая и тёмная тема (подхватывает системную, переключается кнопкой ☾/☀), выбор частоты чипами, журнал действий.

```bash
python pixel_smooth_gui.py
```

Нужен Python 3 с tkinter (на Windows идёт в комплекте) и `adb` в PATH или в папке со скриптом. Бэкап общий со скриптом, так что применить можно в GUI, а откатить из терминала.

## Версия для телефона (без ПК)

Работает прямо на Pixel через [Termux](https://f-droid.org/packages/com.termux/) и «Беспроводную отладку» (Android 11+): телефон подключается по adb сам к себе.

1. Установите Termux из F-Droid и скопируйте в него `pixel-smooth.sh` и `pixel-smooth-termux.sh`.
2. Включите Для разработчиков → **Беспроводная отладка**. Termux и Настройки откройте на разделённом экране.
3. Один раз выполните сопряжение: `bash pixel-smooth-termux.sh pair`, затем введите порт и код из «Подключить устройство с помощью кода».
4. Дальше: `bash pixel-smooth-termux.sh apply` (или `revert` / `status`), введите порт из строки «IP-адрес и порт».

## Минусы

- Батарея садится быстрее (постоянные 90/120 Гц, выключенная адаптивная батарея).
- Fixed performance mode сбрасывается после перезагрузки — просто запустите `apply` снова.

# Vibe MIDI

Проигрывает MIDI на вибромоторе телефона, как Steam Controller играл музыку своими моторами. Вибромотор один, поэтому звучит одна нота за раз (верхний голос выбранных дорожек); ударные пропускаются.

## Через adb (`vibe_midi.py`)

```bash
python vibe_midi.py --info               # что умеет вибромотор
python vibe_midi.py demo:tetris          # демо: tetris, ode, scale
python vibe_midi.py song.mid             # свой файл
python vibe_midi.py song.mid --list      # дорожки файла
python vibe_midi.py song.mid -t 2        # играть только дорожку 2
python vibe_midi.py song.mid -o 1 -s 0.8 # на октаву выше, темп 80%
```

Остановить — Ctrl+C. Песня целиком загружается на телефон как shell-скрипт и играется там через `cmd vibrator_manager`, поэтому задержки adb не рвут ритм.

Режимы (`-m`):

- **freq** — мотору задаётся настоящая частота ноты (`waveform -f`). Звучит чище всего; нужен `FREQUENCY_CONTROL` (есть на Pixel 6 и новее, проверьте `--info`).
- **pwm** — мотор включается и выключается с частотой ноты, как у Steam Controller. Работает на любом Android.
- **auto** (по умолчанию) — freq, если поддерживается, иначе pwm.

Без ПК: в Termux `pkg install python android-tools`, один раз `bash pixel-smooth-termux.sh pair`, затем `bash pixel-smooth-termux.sh connect` и `python vibe_midi.py demo:tetris`.

Если вибрации нет: выключите «Не беспокоить» и проверьте, что вибрация включена в Настройки → Звук и вибрация → Вибрация и тактильный отклик.

## GUI (`vibe_midi_gui.py`)

Окно в стиле Material You: кнопка ▶/❚❚, прогресс, открытие .mid, демо, выбор дорожек, режим (Авто / Частота / Импульсы), октава, темп и сила. Тема светлая или тёмная, как в системе.

```bash
python vibe_midi_gui.py
```

В одной папке должны лежать `vibe_midi_gui.py`, `vibe_midi.py` и `pixel_smooth_gui.py` (из них берутся логика и виджеты). Нужен Python 3 с tkinter и `adb` в PATH.

## В браузере (`midi-vibe.html`)

Откройте файл в Chrome на Android. Работает только режим pwm (Vibration API даёт точность 1 мс), и звук грубее, чем через adb.

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

## Минусы

- Батарея садится быстрее (постоянные 90/120 Гц, выключенная адаптивная батарея).
- Fixed performance mode сбрасывается после перезагрузки — просто запустите `apply` снова.

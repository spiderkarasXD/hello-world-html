#!/usr/bin/env bash
# Pixel Smooth: ADB-твик (без root) против дёрганых и обрывающихся анимаций.
# Использование: ./pixel-smooth.sh [apply|revert|status] [REFRESH_HZ]
# Нужно: "Отладка по USB" включена, adb установлен, телефон подключён.
set -u

ACTION="${1:-apply}"
HZ="${2:-90}"                      # 90 для Pixel 6/7/8a и т.п., 120 для Pro-моделей
BACKUP="${HOME}/.pixel-smooth-backup"

command -v adb >/dev/null || { echo "adb не найден"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "Телефон не найден (adb devices)"; exit 1; }

get() { adb shell settings get "$1" "$2" | tr -d '\r'; }
put() { adb shell settings put "$1" "$2" "$3" >/dev/null 2>&1 || echo "  ! не удалось: $1 $2"; }
del() { adb shell settings delete "$1" "$2" >/dev/null 2>&1; }

# namespace key value
TWEAKS=(
  "global window_animation_scale 1.0"
  "global transition_animation_scale 1.0"
  "global animator_duration_scale 1.0"       # 0 или "Убрать анимации" обрывает аниматоры
  "system min_refresh_rate $HZ"              # держим частоту, чтобы не было просадок/скачков
  "system peak_refresh_rate $HZ"
  "global low_power 0"                       # экономия заряда режет частоту и анимации
  "global adaptive_battery_management_enabled 0"
  "global app_standby_enabled 0"
)

case "$ACTION" in
  apply)
    : > "$BACKUP"
    for t in "${TWEAKS[@]}"; do
      set -- ${t%%#*}
      echo "$1 $2 $(get "$1" "$2")" >> "$BACKUP"
      put "$1" "$2" "$3"
      echo "ok: $2 = $3"
    done
    # Постоянный режим производительности (Android 12+); на части прошивок недоступен
    adb shell cmd power set-fixed-performance-mode-enabled true >/dev/null 2>&1 \
      && echo "ok: fixed performance mode" || echo "пропущено: fixed performance mode не поддерживается"
    echo "Готово. Перезагрузите телефон для надёжности. Откат: $0 revert"
    ;;
  revert)
    [ -f "$BACKUP" ] || { echo "Нет бэкапа $BACKUP"; exit 1; }
    while read -r ns key val; do
      if [ "$val" = "null" ]; then del "$ns" "$key"; else put "$ns" "$key" "$val"; fi
      echo "restored: $key = $val"
    done < "$BACKUP"
    adb shell cmd power set-fixed-performance-mode-enabled false >/dev/null 2>&1
    echo "Откат выполнен."
    ;;
  status)
    for t in "${TWEAKS[@]}"; do set -- ${t%%#*}; echo "$2 = $(get "$1" "$2")"; done
    ;;
  *) echo "Использование: $0 [apply|revert|status] [REFRESH_HZ]"; exit 1 ;;
esac

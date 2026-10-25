#!/usr/bin/env bash
# Pixel Smooth: ADB-твик (без root) против дёрганых и обрывающихся анимаций.
# Использование: ./pixel-smooth.sh [apply|revert|status] [REFRESH_HZ]
#   REFRESH_HZ не указан -> берётся максимальная частота экрана телефона.
#   Несколько телефонов подключено -> укажите ANDROID_SERIAL=<serial>.
# Нужно: "Отладка по USB" включена, adb установлен, телефон подключён.
set -u

ACTION="${1:-apply}"
HZ="${2:-}"

command -v adb >/dev/null || { echo "adb не найден (установите Android platform-tools)"; exit 1; }

state="$(adb get-state 2>&1 | tr -d '\r')"
case "$state" in
  device) ;;
  *unauthorized*) echo "Подтвердите отладку по USB на экране телефона и запустите снова"; exit 1 ;;
  *more\ than\ one*) echo "Подключено несколько устройств: задайте ANDROID_SERIAL=<serial> (см. adb devices)"; exit 1 ;;
  *) echo "Телефон не найден (проверьте adb devices)"; exit 1 ;;
esac

sh_() { adb shell "$@" | tr -d '\r'; }

SERIAL="$(adb get-serialno | tr -d '\r')"
MODEL="$(sh_ getprop ro.product.model)"
BRAND="$(sh_ getprop ro.product.brand)"
SDK="$(sh_ getprop ro.build.version.sdk)"
BACKUP="${HOME}/.pixel-smooth-backup-${SERIAL}"

echo "Устройство: $MODEL (Android SDK $SDK, $SERIAL)"
[ "$BRAND" = "google" ] || echo "Внимание: это не Pixel, часть настроек может не сработать"

# Максимальная частота из поддерживаемых режимов дисплея (60 если не удалось определить)
detect_hz() {
  sh_ dumpsys display | grep -oE 'fps=[0-9]+(\.[0-9]+)?' | cut -d= -f2 \
    | awk '{v=int($1+0.5); if (v>m) m=v} END {print (m ? m : 60)}'
}

get() { sh_ settings get "$1" "$2"; }
put() { adb shell settings put "$1" "$2" "$3" >/dev/null 2>&1 || echo "  ! не удалось: $1 $2"; }
del() { adb shell settings delete "$1" "$2" >/dev/null 2>&1; }

tweaks() {
  cat <<LIST
global window_animation_scale 1.0
global transition_animation_scale 1.0
global animator_duration_scale 1.0
system min_refresh_rate $HZ
system peak_refresh_rate $HZ
global low_power 0
global adaptive_battery_management_enabled 0
global app_standby_enabled 0
LIST
}
# Зачем:
#  *_animation_scale / animator_duration_scale: 0 или "Убрать анимации" обрывает аниматоры,
#    а нестандартные значения ломают тайминги жестов.
#  min/peak_refresh_rate: фиксированная частота убирает скачки 60<->90/120 Гц посреди анимации.
#  low_power / adaptive_battery / app_standby: экономия режет частоту CPU/экрана и анимации.

case "$ACTION" in
  apply)
    [ -n "$HZ" ] || HZ="$(detect_hz)"
    case "$HZ" in ''|*[!0-9]*) echo "REFRESH_HZ должна быть числом"; exit 1 ;; esac
    echo "Частота экрана: $HZ Гц"
    # Бэкап только при первом запуске, чтобы повторный apply не затёр исходные значения
    if [ -f "$BACKUP" ]; then
      echo "Бэкап уже есть ($BACKUP), исходные значения сохранены ранее"
      fresh=0
    else
      : > "$BACKUP"; fresh=1
    fi
    while read -r ns key val; do
      [ "$fresh" = 1 ] && echo "$ns $key $(get "$ns" "$key")" >> "$BACKUP"
      put "$ns" "$key" "$val"
      echo "ok: $key = $(get "$ns" "$key")"
    done < <(tweaks)
    if [ "$SDK" -ge 31 ] 2>/dev/null && \
       adb shell cmd power set-fixed-performance-mode-enabled true >/dev/null 2>&1; then
      echo "ok: fixed performance mode (сбрасывается при перезагрузке)"
    else
      echo "пропущено: fixed performance mode не поддерживается"
    fi
    echo
    echo "Готово. Откат: $0 revert"
    echo "Если частота не держится: Настройки > Экран > Плавное отображение (Smooth Display) — включите."
    ;;
  revert)
    [ -f "$BACKUP" ] || { echo "Нет бэкапа для этого устройства ($BACKUP)"; exit 1; }
    while read -r ns key val; do
      if [ -z "$val" ] || [ "$val" = "null" ]; then del "$ns" "$key"; else put "$ns" "$key" "$val"; fi
      echo "restored: $key = ${val:-<по умолчанию>}"
    done < "$BACKUP"
    adb shell cmd power set-fixed-performance-mode-enabled false >/dev/null 2>&1
    rm -f "$BACKUP"
    echo "Откат выполнен."
    ;;
  status)
    HZ="${HZ:-?}"
    while read -r ns key _; do echo "$key = $(get "$ns" "$key")"; done < <(tweaks)
    echo "max refresh = $(detect_hz) Гц"
    [ -f "$BACKUP" ] && echo "бэкап: $BACKUP" || echo "бэкап: нет (твик не применялся)"
    ;;
  *) echo "Использование: $0 [apply|revert|status] [REFRESH_HZ]"; exit 1 ;;
esac

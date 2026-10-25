#!/data/data/com.termux/files/usr/bin/bash
# Pixel Smooth для телефона: запуск прямо на Pixel через Termux, без ПК и без root.
# Телефон подключается сам к себе по "Беспроводной отладке" (Android 11+).
#
# Использование (в Termux):
#   ./pixel-smooth-termux.sh pair      # один раз: сопряжение
#   ./pixel-smooth-termux.sh apply|revert|status [REFRESH_HZ]
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"

command -v adb >/dev/null || { echo "Устанавливаю adb..."; pkg install -y android-tools || exit 1; }

connect() {
  adb devices | grep -q "localhost.*device$" && return 0
  echo "Настройки > Для разработчиков > Беспроводная отладка — порт в строке «IP-адрес и порт»"
  echo "(разделённый экран: Termux + Настройки, иначе отладка может выключиться)"
  read -rp "Порт подключения: " port
  adb connect "localhost:$port" | grep -q connected || { echo "Не удалось подключиться"; exit 1; }
}

case "${1:-}" in
  pair)
    echo "Беспроводная отладка > «Подключить устройство с помощью кода»"
    echo "Откройте Termux и Настройки на разделённом экране."
    read -rp "Порт сопряжения: " port
    read -rp "Код (6 цифр): " code
    adb pair "localhost:$port" "$code" && echo "Сопряжено. Теперь: $0 apply"
    ;;
  apply|revert|status)
    connect
    serial="$(adb devices | awk '/localhost.*device$/ {print $1; exit}')"
    ANDROID_SERIAL="$serial" bash "$DIR/pixel-smooth.sh" "$@"
    ;;
  *) echo "Использование: $0 pair | apply|revert|status [REFRESH_HZ]"; exit 1 ;;
esac

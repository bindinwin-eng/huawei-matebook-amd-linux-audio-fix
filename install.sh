#!/usr/bin/env bash
# Install the ACP/ES83xx DMI allow-list fix:
#   1) disable any modprobe blacklist that keeps the ACP drivers from loading
#   2) patch the DMI tables in the kernel modules for every installed kernel
#   3) install a pacman hook so the patch is reapplied after kernel updates
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Запусти через sudo / run with sudo"; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for tool in zstd python3 depmod; do
    command -v "$tool" >/dev/null || { echo "Не хватает: $tool / missing: $tool"; exit 1; }
done

echo "=== 1/4 modprobe blacklists ==="
found=0
shopt -s nullglob
for f in /etc/modprobe.d/*.conf; do
    if grep -qE '^\s*blacklist\s+snd[-_](pci[-_]acp|rn[-_]pci[-_]acp|acp)' "$f"; then
        mv -v "$f" "$f.disabled-$(date +%Y%m%d)"
        found=1
    fi
done
shopt -u nullglob
if [[ $found -eq 1 ]]; then
    echo "  Чёрный список отключён. Он также сидит в initramfs — пересоберём ниже."
    echo "  Blacklist disabled; it is also baked into the initramfs, rebuilt below."
    NEED_INITRAMFS=1
else
    echo "  Ничего блокирующего не найдено / nothing blocking found"
    NEED_INITRAMFS=0
fi

echo
echo "=== 2/4 Патч DMI-таблиц / patching DMI tables ==="
install -Dm755 "$HERE/scripts/acp-dmi-patch.py" /usr/local/bin/acp-audio-dmi-fix
/usr/local/bin/acp-audio-dmi-fix "$@"

echo
echo "=== 3/4 Хук обновления ядра / kernel update hook ==="
if command -v pacman >/dev/null; then
    install -Dm644 "$HERE/hooks/95-acp-audio-dmi-fix.hook" \
                   /etc/pacman.d/hooks/95-acp-audio-dmi-fix.hook
    echo "  /etc/pacman.d/hooks/95-acp-audio-dmi-fix.hook"
else
    echo "  pacman не найден — настрой автозапуск /usr/local/bin/acp-audio-dmi-fix"
    echo "  после обновления ядра средствами своего дистрибутива."
    echo "  pacman not found - hook up /usr/local/bin/acp-audio-dmi-fix to your"
    echo "  distribution's kernel post-install mechanism (e.g. kernel-install)."
fi

echo
echo "=== 4/4 initramfs ==="
if [[ $NEED_INITRAMFS -eq 1 ]] && command -v mkinitcpio >/dev/null; then
    mkinitcpio -P 2>&1 | tail -3
else
    echo "  пересборка не требуется / not needed"
fi

echo
echo "Готово. Перезагрузись и проверь: / Done. Reboot, then check:"
echo "  cat /proc/asound/cards"

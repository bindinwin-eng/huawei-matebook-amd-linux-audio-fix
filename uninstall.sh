#!/usr/bin/env bash
# Revert everything install.sh did: restore the original signed modules,
# drop the pacman hook and the helper.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Запусти через sudo / run with sudo"; exit 1; }

echo "=== Восстановление модулей / restoring modules ==="
shopt -s nullglob
restored=0
for orig in /usr/lib/modules/*/kernel/sound/soc/amd/*.ko.zst.orig \
            /usr/lib/modules/*/kernel/sound/soc/amd/acp/*.ko.zst.orig; do
    target="${orig%.orig}"
    mv -vf "$orig" "$target"
    restored=1
done
shopt -u nullglob
[[ $restored -eq 1 ]] || echo "  нечего восстанавливать / nothing to restore"

echo
echo "=== depmod ==="
for kdir in /usr/lib/modules/*/; do
    kver="$(basename "$kdir")"
    [[ -d "$kdir/kernel" ]] && depmod "$kver" && echo "  $kver"
done

echo
echo "=== Удаление хука и хелпера / removing hook and helper ==="
rm -vf /etc/pacman.d/hooks/95-acp-audio-dmi-fix.hook
rm -vf /usr/local/bin/acp-audio-dmi-fix

echo
echo "Готово. Чёрные списки modprobe НЕ восстанавливаются автоматически —"
echo "если они были, ищи файлы *.disabled-* в /etc/modprobe.d."
echo "Done. Disabled modprobe blacklists are left as *.disabled-* in /etc/modprobe.d."
echo "Перезагрузись / reboot to return to the stock state."

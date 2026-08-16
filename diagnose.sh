#!/usr/bin/env bash
# Read-only check: is this machine hitting the ACP/ES83xx DMI allow-list problem?
# Safe to run as a normal user.

echo "=== Machine ==="
for f in sys_vendor product_name product_version board_name bios_version; do
    printf '%-16s %s\n' "$f" "$(cat "/sys/class/dmi/id/$f" 2>/dev/null)"
done

echo
echo "=== Kernel ==="
uname -r

echo
echo "=== ACP PCI function ==="
acp="$(lspci -Dnn 2>/dev/null | grep -i 'Audio Coprocessor' | head -1)"
if [[ -z $acp ]]; then
    echo "  Not found - this machine probably does not use ACP audio"
else
    echo "  $acp"
    slot="${acp%% *}"
    if [[ -e "/sys/bus/pci/devices/$slot/driver" ]]; then
        echo "  driver: $(basename "$(readlink -f "/sys/bus/pci/devices/$slot/driver")")"
    else
        echo "  driver: NOT BOUND   <-- symptom"
    fi
fi

echo
echo "=== Everest codec in ACPI ==="
ls /sys/bus/acpi/devices/ 2>/dev/null | grep -iE 'ESSX83|ESSX8336' || echo "  Not found"

echo
echo "=== Sound cards ==="
cat /proc/asound/cards 2>/dev/null

echo
echo "=== Is this model present in the kernel allow-lists? ==="
model="$(cat /sys/class/dmi/id/product_name 2>/dev/null)"
for m in "/usr/lib/modules/$(uname -r)/kernel/sound/soc/amd/snd-acp-config.ko.zst" \
         "/usr/lib/modules/$(uname -r)/kernel/sound/soc/amd/acp/snd-acp-legacy-mach.ko.zst"; do
    [[ -e $m ]] || { echo "  $(basename "$m"): file missing"; continue; }
    if zstd -dcf "$m" 2>/dev/null | grep -qa "$model"; then
        echo "  $(basename "$m"): listed"
    else
        echo "  $(basename "$m"): MISSING   <-- root cause"
    fi
done

echo
echo "=== modprobe blacklists ==="
grep -rE '^\s*blacklist\s+snd' /etc/modprobe.d/ 2>/dev/null || echo "  None"

echo
echo "=== Kernel messages ==="
journalctl -k -b --no-pager 2>/dev/null \
  | grep -iE 'acp_mach|acp3x|snd_acp|es83|registered in DMI|Cannot probe card|rejected' \
  | tail -10 || echo "  (no journal access)"

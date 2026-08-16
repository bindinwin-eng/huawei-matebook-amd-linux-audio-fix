#!/usr/bin/env python3
"""
Register an unsupported laptop model in the AMD ACP / ES83xx DMI allow-lists
that are compiled into the Linux kernel modules.

Background
----------
Audio on many AMD laptops (Huawei MateBook and friends) goes through the AMD
Audio Co-Processor (ACP) with an Everest ES8316/ES8336 codec attached over I2S.
The kernel only drives that path for machines listed in two hard-coded DMI
tables:

  * snd-acp-config.ko       -> decides whether to claim the ACP PCI function
  * snd-acp-legacy-mach.ko  -> decides whether to register the sound card

If your model is missing from those tables, everything probes silently into
nothing and userspace shows only "Dummy Output".

This script rewrites one donor entry in each table so that it names *your*
machine instead. Entries in both tables carry no per-machine driver data (all
pointer fields are NULL / identical - verified by parsing the ELF relocations),
so the tables act as pure allow-lists and any entry is an equivalent donor.

Because distribution kernel modules are signed, and editing the payload breaks
that signature, the appended signature block is removed as well. The kernel
rejects a *broken* signature outright ("Key was rejected by service") even when
CONFIG_MODULE_SIG_FORCE is disabled, but it happily loads an *unsigned* module
and merely marks itself tainted.

The original module is always kept next to the patched one as "<module>.orig",
which is also used as the source on every run, so this script is idempotent.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import subprocess
import sys

SIG_MARKER = b"~Module signature appended~\n"

# Offset, in bytes, from the start of one DMI match string to the next one
# inside a `struct dmi_system_id`. Each `struct dmi_strmatch` is
# {u8 slot; char substr[79]} == 80 bytes, so product_version sits exactly one
# slot behind product_name.
DMI_SLOT = 80

DEFAULT_MODULES = [
    "kernel/sound/soc/amd/snd-acp-config.ko.zst",
    "kernel/sound/soc/amd/acp/snd-acp-legacy-mach.ko.zst",
]


def dmi(field: str) -> str:
    p = pathlib.Path("/sys/class/dmi/id") / field
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def strip_signature(blob: bytes) -> bytes:
    """Drop the PKCS#7 block the distribution appended after the ELF image."""
    if not blob.endswith(SIG_MARKER):
        return blob
    trailer = blob[-len(SIG_MARKER) - 12:-len(SIG_MARKER)]
    signer_len, key_id_len = trailer[3], trailer[4]
    sig_len = struct.unpack(">I", trailer[8:12])[0]
    total = signer_len + key_id_len + sig_len + 12 + len(SIG_MARKER)
    return blob[:len(blob) - total]


def find_donors(blob: bytes, vendor: str, version: str, needed: int) -> list[tuple[int, str]]:
    """
    Return (offset, name) of product-name strings that belong to a DMI entry
    matching our vendor and our product version, and that are long enough to be
    overwritten with our own model name.

    An entry is laid out as ... [vendor][product_name][product_version] ...
    with DMI_SLOT bytes between the starts of consecutive match strings.
    """
    vendor_b = vendor.encode()
    version_b = version.encode()
    donors: list[tuple[int, str]] = []

    start = 0
    while True:
        idx = blob.find(vendor_b + b"\x00", start)
        if idx == -1:
            break
        start = idx + 1

        name_off = idx + DMI_SLOT
        ver_off = idx + 2 * DMI_SLOT
        if ver_off + len(version_b) + 1 > len(blob):
            continue

        # The version slot of this entry must equal ours, otherwise the entry
        # would not match this machine even after the rename.
        if blob[ver_off:ver_off + len(version_b) + 1] != version_b + b"\x00":
            continue

        end = blob.find(b"\x00", name_off)
        if end == -1:
            continue
        name = blob[name_off:end].decode(errors="replace")
        if not name or len(name) < needed:
            continue
        donors.append((name_off, name))

    return donors


def patch_module(path: pathlib.Path, vendor: str, product: str, version: str,
                 donor_pref: str | None, dry_run: bool) -> bool:
    orig = path.with_suffix(path.suffix + ".orig")

    if not path.exists():
        print(f"  [skip] {path} - not found")
        return False

    if not orig.exists() and not dry_run:
        orig.write_bytes(path.read_bytes())
        orig.chmod(path.stat().st_mode)

    source = orig if orig.exists() else path
    blob = subprocess.run(["zstd", "-dcf", str(source)],
                          capture_output=True, check=True).stdout

    if (product.encode() + b"\x00") in blob:
        print(f"  [ok]   {path.name} - already lists {product}")
        return False

    donors = find_donors(blob, vendor, version, len(product))
    if not donors:
        print(f"  [FAIL] {path.name} - no suitable donor entry "
              f"(vendor {vendor}, version {version}, name >= {len(product)} chars)")
        return False

    if donor_pref:
        chosen = next((d for d in donors if d[1] == donor_pref), None)
        if chosen is None:
            print(f"  [FAIL] {path.name} - donor {donor_pref} not found; available: "
                  + ", ".join(n for _, n in donors))
            return False
    else:
        chosen = donors[0]

    off, donor_name = chosen
    new = product.encode() + b"\x00"
    patched = bytearray(blob)
    patched[off:off + len(new)] = new
    patched = bytes(patched)

    if patched.count(new) != 1:
        print(f"  [FAIL] {path.name} - unexpected number of {product} occurrences")
        return False

    patched = strip_signature(patched)
    if patched[:4] != b"\x7fELF":
        print(f"  [FAIL] {path.name} - result is not an ELF image")
        return False

    print(f"  [+]    {path.name} - {donor_name} -> {product}"
          + (" (dry run)" if dry_run else ", signature stripped"))
    if dry_run:
        return False

    tmp = path.with_suffix(path.suffix + ".new")
    proc = subprocess.run(["zstd", "-19", "-q", "-f", "-o", str(tmp)],
                          input=patched, capture_output=True)
    if proc.returncode != 0:
        print(f"  [FAIL] {path.name} - zstd: {proc.stderr.decode(errors='replace')}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Register this machine in the AMD ACP / ES83xx DMI allow-lists.")
    ap.add_argument("--kernel", action="append", default=None,
                    help="kernel release to patch (default: every installed one)")
    ap.add_argument("--model", default=None,
                    help="model name to inject (default: DMI product_name)")
    ap.add_argument("--donor", default=None,
                    help="model name of the entry to overwrite (default: first suitable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="only report what would change")
    args = ap.parse_args()

    vendor = dmi("sys_vendor")
    product = args.model or dmi("product_name")
    version = dmi("product_version")

    if not vendor or not product or not version:
        print("Cannot read DMI data from /sys/class/dmi/id", file=sys.stderr)
        return 1

    print(f"Machine: {vendor} / {product} / {version}")

    if args.kernel:
        kernels = [pathlib.Path("/usr/lib/modules") / k for k in args.kernel]
    else:
        kernels = sorted(p for p in pathlib.Path("/usr/lib/modules").iterdir()
                         if (p / "kernel").is_dir())

    if not kernels:
        print("No installed kernels found", file=sys.stderr)
        return 1

    for kdir in kernels:
        print(f"\nKernel {kdir.name}:")
        changed = False
        for rel in DEFAULT_MODULES:
            if patch_module(kdir / rel, vendor, product, version, args.donor, args.dry_run):
                changed = True
        if changed:
            subprocess.run(["depmod", kdir.name], check=False)
            print(f"  depmod {kdir.name} - done")

    return 0


if __name__ == "__main__":
    sys.exit(main())

# Huawei MateBook AMD — no sound on Linux (ES8336 / AMD ACP) — fix

**Only "Dummy Output" and HDMI, no speakers, no microphone, on a Huawei MateBook with an AMD Ryzen CPU?**
Your laptop model is probably missing from two hard-coded allow-lists inside the Linux kernel. This repository
registers it, without recompiling the kernel.

Verified on **HUAWEI NBM-WXX9 (MateBook D, product version M1010, board NBM-WXX9-PCB-B2)**, AMD Lucienne/Renoir,
Arch Linux, kernel 7.1.5. The scripts are model-agnostic and read your DMI data at runtime, so they work for any
Huawei/AMD laptop that hits the same wall.

> Русская версия — [ниже](#русская-версия).

---

## Symptoms

* `pavucontrol` / GNOME / KDE show only **Dummy Output**; no internal speakers, no internal or headset microphone.
* HDMI audio works, and that is the only card present:

  ```
  $ cat /proc/asound/cards
   0 [Generic        ]: HDA-Intel - HD-Audio Generic
                        HD-Audio Generic at 0xd03c0000 irq 78
  ```
* The AMD Audio Co-Processor has **no driver bound**:

  ```
  $ lspci -k | grep -A3 'Audio Coprocessor'
  03:00.5 Multimedia controller: AMD Audio Coprocessor (rev 01)
          Kernel modules: snd_pci_acp3x, snd_rn_pci_acp3x, snd_acp_pci, snd_sof_amd_renoir, ...
          # note: no "Kernel driver in use" line
  ```
* The codec **is** there in ACPI (`ESSX8336:00`) and its i2c driver `es8316` is bound — the codec is not the problem.
* If you get as far as loading the machine driver, the kernel says:

  ```
  acp_mach acp3x-es83xx: this system has a ES83xx codec defined in ACPI,
                         but the driver doesn't have this system registered in DMI table
  acp_mach acp3x-es83xx: Cannot probe card (acp3x-es83xx): -19
  ```

Search terms this page answers: *Huawei MateBook no sound Linux*, *MateBook D14/D15/D16 AMD dummy output*,
*ES8336 ES8316 no sound*, *AMD ACP audio not working*, *NBM-WXX9 sound*, *acp3x-es83xx Cannot probe card -19*,
*doesn't have this system registered in DMI table*, *snd_acp_pci not bound*, *Ryzen laptop only HDMI audio*.

---

## Why it happens

Audio on these laptops does **not** go through the usual HD-Audio codec. It goes through the AMD **ACP**
(Audio Co-Processor, PCI function `03:00.5`) with an Everest **ES8336** codec wired over I2S. The kernel only
drives that path on machines it explicitly recognises, and it checks **two separate DMI allow-lists**:

| Module | Decides |
|---|---|
| `snd-acp-config.ko` | whether any driver claims the ACP PCI function at all |
| `snd-acp-legacy-mach.ko` | whether the sound card is actually registered |

Both tables list a handful of Huawei models (`KLVL-WXX9`, `KLVL-WXXW`, `BOM-WXX9`, `HVY-WXX9`, …).
If yours is absent, the first table makes every candidate driver decline the device **silently** — no error,
no card, nothing in the log. That silence is what makes this so hard to diagnose.

This is an upstream gap, not a distribution bug: **the same tables ship in every distribution's kernel**, so
switching from Arch to Ubuntu/Fedora/Mint changes nothing. Reported upstream and still open —
see [codepayne/linux-sound-huawei#33](https://github.com/codepayne/linux-sound-huawei/issues/33) (March 2024).

### The third trap: module signatures

Distribution kernel modules are signed. Editing the payload invalidates that signature, and the kernel rejects a
module with a *broken* signature **outright**:

```
modprobe: ERROR: could not insert 'snd_acp_config': Key was rejected by service
```

This happens even with `CONFIG_MODULE_SIG_FORCE` disabled, Secure Boot off and lockdown `none` — those settings
only relax the rules for modules with **no** signature, not for one that fails verification. So the patcher
**removes the appended signature block** instead of trying to keep it. The module then loads as unsigned and the
kernel sets a taint flag (`8192`), which is informational only.

---

## Install

Requirements: `zstd`, `python3`, `depmod` (kmod). Root. Arch-based distros get the kernel-update hook automatically.

```bash
git clone https://github.com/bindinwin-eng/huawei-matebook-amd-linux-audio-fix.git
cd huawei-matebook-amd-linux-audio-fix
sudo ./install.sh
sudo reboot
```

Want to look before you leap:

```bash
./diagnose.sh                             # read-only, confirms you have this exact problem
sudo ./install.sh --dry-run               # shows what would change, writes nothing
```

`install.sh` does three things:

1. disables any `/etc/modprobe.d/*.conf` that blacklists the ACP drivers (renamed to `*.disabled-<date>`, never deleted)
   and rebuilds the initramfs, because such a blacklist is baked in there too;
2. patches the DMI tables for **every installed kernel**, keeping each original as `<module>.orig`;
3. installs a pacman hook so the patch is reapplied automatically after every kernel update.

### Verify

```bash
$ cat /proc/asound/cards
 0 [Generic        ]: HDA-Intel - HD-Audio Generic
 1 [acp3xes83xx    ]: acp3x-es83xx - acp3x-es83xx
                      HUAWEI-NBM_WXX9-M1010-NBM_WXX9_PCB_B2

$ journalctl -k -b | grep acp_mach
acp_mach acp3x-es83xx: matched DMI table with this system, trying to register sound card
acp_mach acp3x-es83xx: successfully probed the sound card
es8316 i2c-ESSX8336:00: speaker gpio 0 active high, headphone gpio 1 active high
es8316 i2c-ESSX8336:00: Headset Mic is MIC2
```

Speakers, headphone jack with detection, and the headset microphone all come up.

### Uninstall

```bash
sudo ./uninstall.sh && sudo reboot
```

Restores the original signed modules from the `.orig` copies and removes the hook.

---

## How it works

Both tables are arrays of `struct dmi_system_id`. Each entry stores its match strings **inline** as
`struct dmi_strmatch { u8 slot; char substr[79]; }`, so a model name sits at a fixed 80-byte stride from the
vendor string and the product version sits 80 bytes after the name:

```
[ HUAWEI ][ KLVL-WXX9 ][ M1010 ] ...
   +0         +80         +160
```

The patcher therefore does not need to recompile anything. It:

1. reads `sys_vendor`, `product_name` and `product_version` from `/sys/class/dmi/id`;
2. finds **donor entries** — entries whose vendor and product version already equal yours, and whose model name is
   at least as long as yours (the replacement must fit in place, since moving bytes would break every offset);
3. overwrites one donor model name with yours, keeping the file size byte-identical;
4. strips the appended module signature;
5. runs `depmod`.

Overwriting is safe here because **every entry in both tables carries NULL pointers** for `callback`, `ident` and
`driver_data` — verified by parsing the ELF relocations, which show no relocation anywhere inside either table.
The tables are pure allow-lists: the actual per-machine configuration (speaker/headphone GPIOs, mic routing) comes
from ACPI at probe time. So donors are interchangeable, and the only cost is that the donated model is no longer
listed — irrelevant unless you own two different MateBooks.

The original is kept as `<module>.orig` and is used as the source on every run, which makes repeated runs and
kernel-update hooks idempotent.

## Adapting to another laptop

The scripts auto-detect your machine, so usually there is nothing to adapt. If you want control:

```bash
sudo acp-audio-dmi-fix --dry-run              # what would happen
sudo acp-audio-dmi-fix --donor HVY-WXX9       # pick which entry gets overwritten
sudo acp-audio-dmi-fix --model MY-MODEL       # inject a name other than DMI product_name
sudo acp-audio-dmi-fix --kernel 6.12.4-arch1-1
```

If your **product version** differs from every listed entry (`M1010`, `M1020`, `M1040`), no donor will be found and
the script refuses to guess — that case needs a real kernel patch, because both the name and the version would have
to change and there may not be room.

## Caveats

* **The kernel is marked tainted (`8192`, "unsigned module").** Informational; it can matter if you report unrelated
  bugs to kernel maintainers.
* **Secure Boot must be off**, otherwise an unsigned module cannot load at all. (If you run Secure Boot with your own
  keys, re-sign the patched modules instead of relying on the taint path.)
* The patch is **per kernel build**. The pacman hook handles Arch; on other distros wire
  `/usr/local/bin/acp-audio-dmi-fix` into your kernel post-install path.
* The donated model loses its entry.
* This is a **workaround**. The clean fix is a three-line DMI entry upstream — see below.

## The proper fix

Add your machine to `acp_quirk_table` in `sound/soc/amd/acp-config.c` and to `acp3x_es83xx_dmi_table` in
`sound/soc/amd/acp/acp-legacy-mach.c`, then send it to ALSA/kernel maintainers. Once that lands and reaches your
distribution, uninstall this and enjoy stock, signed modules. Patches welcome here too — if you get your model
merged upstream, open an issue so it can be listed as no longer needing this.

## License

MIT — see [LICENSE](LICENSE).

---

# Русская версия

## В чём проблема

На ноутбуках Huawei MateBook с процессорами AMD звук идёт **не** через обычный HD-Audio, а через AMD **ACP**
(звуковой сопроцессор, устройство `03:00.5`) с кодеком Everest **ES8336** по шине I2S. Ядро Linux поднимает
этот путь только для тех моделей, которые оно «знает в лицо», и проверяет это по **двум разным белым спискам**:

| Модуль | За что отвечает |
|---|---|
| `snd-acp-config.ko` | возьмёт ли вообще какой-нибудь драйвер устройство ACP |
| `snd-acp-legacy-mach.ko` | будет ли зарегистрирована звуковая карта |

Если вашей модели там нет, первый список заставляет все драйверы **молча** отказаться от устройства: ни ошибки,
ни карты, ни строчки в журнале. Именно эта тишина и делает диагностику мучительной.

Это пробел в самом ядре, а не в дистрибутиве: **одни и те же таблицы едут во всех дистрибутивах**. Переезд с Arch
на Ubuntu, Fedora или Mint не изменит ничего — проверено на практике, симптом сохраняется.

### Третья ловушка: подписи модулей

Модули дистрибутива подписаны. Правка содержимого ломает подпись, а модуль со **сломанной** подписью ядро
отвергает жёстко:

```
modprobe: ERROR: could not insert 'snd_acp_config': Key was rejected by service
```

Причём независимо от того, что `CONFIG_MODULE_SIG_FORCE` выключен, Secure Boot выключен и lockdown в `none`:
эти настройки смягчают правила только для модулей **без** подписи, а не для подписи, которая не сходится.
Поэтому патчер подпись не подделывает, а **срезает целиком**. Модуль грузится как неподписанный, ядро ставит
пометку tainted (`8192`) — она чисто информационная.

## Установка

Нужны `zstd`, `python3`, `depmod` и root.

```bash
git clone https://github.com/bindinwin-eng/huawei-matebook-amd-linux-audio-fix.git
cd huawei-matebook-amd-linux-audio-fix
./diagnose.sh                 # только чтение: подтверждает, что проблема именно эта
sudo ./install.sh --dry-run   # показать, что будет изменено, ничего не записывая
sudo ./install.sh
sudo reboot
```

Установщик делает три вещи:

1. отключает файлы в `/etc/modprobe.d/`, которые запрещают загрузку драйверов ACP (переименовывает в
   `*.disabled-<дата>`, ничего не удаляет), и пересобирает initramfs — такой запрет лежит и внутри образа;
2. патчит таблицы во **всех установленных ядрах**, сохраняя оригинал каждого модуля рядом как `<модуль>.orig`;
3. ставит хук pacman, чтобы патч возвращался автоматически после каждого обновления ядра.

## Откат

```bash
sudo ./uninstall.sh && sudo reboot
```

Возвращает оригинальные подписанные модули из копий `.orig` и снимает хук.

## Как это устроено

Обе таблицы — массивы `struct dmi_system_id`, где строки хранятся **внутри** структуры кусками по 80 байт.
Поэтому имя модели лежит ровно на 80 байт дальше названия производителя, а версия — ещё на 80 байт дальше:

```
[ HUAWEI ][ KLVL-WXX9 ][ M1010 ] ...
   +0         +80         +160
```

Ничего пересобирать не нужно. Скрипт читает вашу модель из `/sys/class/dmi/id`, находит **запись-донор** (у которой
производитель и версия уже совпадают с вашими, а имя не короче вашего), переписывает имя модели поверх, срезает
подпись и вызывает `depmod`. Размер файла не меняется ни на байт.

Заменять донора безопасно: **во всех записях обеих таблиц указатели нулевые** — это проверено разбором таблицы
перемещений ELF, внутри таблиц нет ни одной релокации. То есть таблицы работают как чистые белые списки «поддерживается
или нет», а реальную конфигурацию железа (какие выводы включают динамики и наушники, куда идёт микрофон) драйвер
берёт из ACPI уже при инициализации. Плата за трюк — донорская модель перестаёт быть в списке, что не важно, если
у вас не два разных MateBook.

## Ограничения

* **Ядро помечается как tainted (`8192`)** — «загружен неподписанный модуль». Само по себе безвредно.
* **Secure Boot должен быть выключен** — иначе неподписанный модуль не загрузится в принципе.
* Патч действует **для конкретной сборки ядра**; на Arch его возвращает хук, на других дистрибутивах привяжите
  `/usr/local/bin/acp-audio-dmi-fix` к своему механизму пост-установки ядра.
* Это **обходной путь**. Правильное решение — три строчки в ядре, см. ниже.

## Правильное решение

Добавить свою модель в `acp_quirk_table` (`sound/soc/amd/acp-config.c`) и в `acp3x_es83xx_dmi_table`
(`sound/soc/amd/acp/acp-legacy-mach.c`) и отправить патч мейнтейнерам ALSA. Когда он доедет до вашего
дистрибутива, этот костыль можно снести и вернуться к штатным подписанным модулям.

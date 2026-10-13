# INFI75 configuration protocol

This document describes the USB protocol used to configure the Infiverse
INFI75. Everything marked **confirmed** has been exercised on the
hardware listed below; everything else is decoded from the vendor
software and not yet tested.

| | |
|---|---|
| Keyboard | Infiverse INFI75, product string `INFI75-1.2`, manufacturer `SONiX` |
| USB ID | `05ac:024f` (Apple's vendor ID, used by many SONiX keyboards) |
| `bcdDevice` | `1.00` |
| Controller | SONiX SN32F290, vendor platform HFD `RKGK890` (`HFD80CP100`) |
| Bluetooth name | `INFI75 5.3` |
| Sources | INFI75 Driver V1.1 (`DeviceDriver.exe`, `mui.dll`, `KeyboardLayout.xml`), hardware tests |
| Implementation | `src/infi75/hfd.py`, `src/infi75/usbctl.py` |

Related work using the same command family:
[gohv/EPOMAKER-Ajazz-AK820-Pro](https://github.com/gohv/EPOMAKER-Ajazz-AK820-Pro)
(Ajazz AK820 Pro) and OpenRGB's Valkyrie VK99 controller.

## 1. USB interfaces

The keyboard enumerates with four HID interfaces when connected by cable
in wired mode:

| Interface | Endpoints | Top-level collections (usage page:usage) | Purpose |
|---|---|---|---|
| 0 | IN 0x81 | `0001:06` keyboard, 8-byte input, 1-byte LED output | boot keyboard |
| 1 | IN 0x82 | `000c:01` consumer (ID 3), `0001:80` system (ID 2), `0001:06` NKRO keyboard (ID 1), `0001:02` mouse (ID 6), `ffff:01` vendor input (ID 5, 3 bytes) | media keys, NKRO |
| 2 | IN 0x84, OUT 0x03 | `ff68:61`: 64-byte input, 4096-byte output, no report IDs | **screen image data** |
| 3 | OUT 0x06 only | `ff13:01`: 64-byte input, output and feature, no report IDs | **configuration** |

### The interface 3 defect (confirmed)

Interface 3 declares an input report but no interrupt IN endpoint. HID
class drivers require an IN endpoint, so Linux (`usbhid`) leaves the
interface unbound and no `hidraw` node is created. Windows most likely
does the same (not tested). The vendor driver under Wine and the Epomaker
web hub found no working configuration channel and sent nothing to it.

Feature reports do not use the interrupt endpoints: they are HID class
requests on the default control endpoint. They can be sent to the
unbound interface with libusb:

| Operation | bmRequestType | bRequest | wValue | wIndex | Length |
|---|---|---|---|---|---|
| Read report descriptor | `0x81` | `0x06` GET_DESCRIPTOR | `0x2200` | 3 | up to 1024 |
| Write feature report | `0x21` | `0x09` SET_REPORT | `0x0300` (feature, ID 0) | 3 | 64 |
| Read feature report | `0xA1` | `0x01` GET_REPORT | `0x0300` | 3 | 64 |

The interface has no kernel driver, so it can be claimed without detaching
anything. The V1.30 firmware image shipped with the vendor driver also
contains the `ff13` collection; whether that firmware declares an IN
endpoint for it has not been checked.

### Bluetooth (confirmed: no configuration path)

Over Bluetooth the keyboard appears as HID bus `0005` with the same
`05ac:024f` ID and the name `INFI75 5.3`. Its report descriptor contains
only input reports (IDs 1, 2, 3, 5, 8, 9, 17) for keyboard, mouse,
consumer and system usages, and no feature or vendor reports. SET_REPORT
for feature report 0 is rejected. Settings written over USB persist and
remain active over Bluetooth.

## 2. Framing

Every configuration message is one **64-byte feature report** with report
ID 0 (the ID is not part of the 64 bytes on the wire). Command packets
start with `0x04`:

```
offset  0     1     2      3..7   8      9..63
        04    cmd   arg    00     count  00
```

`count` (byte 8) announces how many data packets follow, where applicable.
Data packets that follow a command have no `0x04` prefix.

### Acknowledgement (confirmed)

After a command, a GET_REPORT on interface 3 returns the command echoed
with a status in byte 3:

| Byte 3 | Meaning |
|---|---|
| `01` | accepted |
| `00` | accepted (seen on SAVE) |
| `ff` | busy; seen on SAVE and FINISH while the keyboard writes flash, for up to about 3 s |

Example: `04 18` (START) is answered with `04 18 00 01`. Data packets are
echoed verbatim, so byte 3 carries payload, not a status. The vendor
driver ignores failures; `hfd.py` polls a busy status (20 ms steps, up to
3 s) without resending and reports anything else as a warning.

The vendor driver waits about 10 ms between packets; `hfd.py` does the
same.

### Transaction commands

| Command | Name | Notes |
|---|---|---|
| `04 18` | START | opens a transaction |
| `04 02` | SAVE | commits the transaction to flash; may report busy |
| `04 f0` | FINISH | sent by the driver after SAVE for lighting, keymap and colours |

## 3. Lighting effect (confirmed)

```
04 18                    START
04 13 .. .. 01           MODE, 1 data packet follows
<data packet>
04 02                    SAVE
04 f0                    FINISH
```

Data packet:

| Offset | Field | Values |
|---|---|---|
| 0 | effect | see table |
| 1-3 | red, green, blue | 0-255 |
| 8 | colour type | 0 = the colour above, 1 = rainbow |
| 9 | brightness | 0-5 |
| 10 | speed | 0-5 |
| 11 | direction | 0 left, 1 down, 2 up, 3 right |
| 14-15 | marker | `aa 55` |

Effects, observed on the INFI75-1.2 (names from the AK820 Pro project):

| Value | Name | Observed |
|---|---|---|
| `00` | effect-0 | fixed blue pattern, ignores the colour |
| `01` | static | steady colour |
| `02` | single-on | dark; keys light up when pressed |
| `03` | single-off | lit; keys go dark when pressed |
| `04` | glittering | dimmed colour |
| `05` | falling | rainfall, random blinking |
| `06` | colourful | random rainbow |
| `07` | breath | breathing |
| `08` | spectrum | colour rolling |
| `09`-`0d` | outward, scrolling, rolling, rotating, explode | pulsing variants |
| `0e`-`0f` | launch, ripples | pulse on key press |
| `10` | flowing | rows sweeping |
| `11`-`12` | pulsating, tilt | twinkle running left to right |
| `13` | shuttle | sweep right to left |
| `80` | custom | shows the stored per-key colours (section 5) |

"Off" is effect `02` (single-on) with brightness 0; effect `00` is not off.

## 4. Key mapping (confirmed)

```
04 18                    START
04 11 .. .. 09           KEYMAP (base layer), 9 data packets announced
<10 data packets>        the vendor driver sends 0x2b6 >> 6 = 10 packets
04 02                    SAVE
04 f0                    FINISH
```

The data is a table of 4-byte entries indexed by **key slot**; bytes
574-575 hold `aa 55`. A slot of all zeros keeps the key's built-in
function, so every write replaces the whole table and unlisted keys
return to default. An all-zero table resets every remap.

| Entry | Meaning |
|---|---|
| `00 00 00 00` | default |
| `02 mm kk 00` | keyboard usage `kk` with modifier bits `mm` |
| `02 bb 00 00` | modifier key alone (`bb` = its bit) |
| `03 lo hi 00` | consumer usage `0xhilo` (media key) |
| `01 ...` | mouse button (decoded, not implemented) |
| `06 id ...` | macro (decoded, not implemented) |

Modifier bits: `01` LCtrl, `02` LShift, `04` LAlt, `08` LGui, `10` RCtrl,
`20` RShift, `40` RAlt, `80` RGui. Media usages offered by the driver:
`cd` play/pause, `b7` stop, `b6` previous, `b5` next, `e9` volume up,
`ea` volume down, `e2` mute.

Key slots come from `key_index` in the vendor `KeyboardLayout.xml` (also
in `src/infi75/profiles/infi75.json`):

| Row | Keys and slots |
|---|---|
| 0 | Esc 1, F1-F12 2-13 |
| 1 | ` 19, 1-0 20-29, - 30, = 31, Backspace 103, PgUp 118 |
| 2 | Tab 37, Q-P 38-47, [ 48, ] 49, \ 67, PgDn 121 |
| 3 | Caps 55, A-L 56-64, ; 65, ' 66, Enter 85 |
| 4 | LShift 73, Z-/ 74-83, RShift 84, Up 101 |
| 5 | LCtrl 91, LWin 92, LAlt 93, Space 94, RAlt 95, Fn 96, Left 99, Down 100, Right 102 |

`04 27` writes the Fn layer with the same layout (decoded, not
implemented).

## 5. Per-key colours (confirmed)

Stored colours, displayed by effect `0x80`:

```
04 18                    START
04 23 .. .. 09           CUSTOM COLOURS, 9 data packets
<9 data packets>         576 bytes
04 02                    SAVE
04 f0                    FINISH
then the lighting transaction of section 3 with effect 80, brightness 0-5, speed 5
```

The 576 bytes are a slot-indexed table: entry `n` (bytes `4n..4n+3`) is
`[n, R, G, B]`; unused slots are zero; bytes 574-575 hold `aa 55`. Light
slots equal the key slots of section 4.

`04 20` with 8 data packets of `[slot, R, G, B]` entries in key order is
the vendor driver's **live preview**: the colours appear until the next
effect change, then the stored table returns.

## 6. Clock (confirmed)

```
04 18                    START
04 28 .. .. 01           TIME, 1 data packet
<data packet>            acknowledged (echoed verbatim)
04 02                    SAVE
```

| Offset | Field |
|---|---|
| 0 | `00` |
| 1 | profile number + 1 (`01`) |
| 2 | `5a` |
| 3 | year - 2000 |
| 4-8 | month, day, hour, minute, second |
| 62-63 | `aa 55` |

## 7. Screen image (confirmed)

The screen is 135 x 240 pixels (portrait). Frames are RGB565,
little-endian, row-major from the top-left. Up to 141 frames form an
animation.

Buffer:

| Offset | Content |
|---|---|
| 0 | frame count |
| 1..count | per-frame delay in 2 ms units (minimum 1) |
| rest of 256 bytes | `ff` |
| 256 | frame 0 (64,800 bytes), then frame 1, ... |

The buffer is padded with `ff` to a multiple of 4096 bytes and sent as:

```
interface 3:  04 18                  START
interface 3:  04 72 ss .. .. nn nn   SCREEN, slot ss (1), chunk count nn (16-bit little-endian, bytes 8-9)
interface 2:  4096-byte output report, once per chunk; the driver reads one 64-byte input report after each
interface 3:  04 02                  SAVE
```

A still image is 16 chunks; the 20-frame test GIF was 318 chunks.

## 8. Not yet decoded or implemented

| Command | Seen in the driver | Status |
|---|---|---|
| `04 27` | Fn layer keymap | layout known, not implemented |
| `04 17` | sleep timer (one data packet, `aa 55` at 62-63 on the AK820) | not tested |
| `04 15` | unknown, with data | not decoded |
| `04 19` | unknown | not decoded |
| `04 f5` | read back state | not decoded |
| macros | entry type `06` plus macro storage | not decoded |

## 9. Firmware updaters (warning)

The vendor package ships two SONiX ISP updaters:

| File | Target | Contents |
|---|---|---|
| `...V1.27..._带电量计.exe` (with battery gauge) | `0c45:7903` | different USB identity |
| `...V1.30...(INFI75)无电量计.exe` (without battery gauge) | `05ac:024f`, SN32F290 | 256 KB image, product `INFI75`, Bluetooth `INFI75 5.1`, `bcdDevice 1.30` |

Neither matches an INFI75-1.2 (`bcdDevice 1.00`, Bluetooth `INFI75 5.3`).
The updater enters ISP mode with a feature report, which this firmware
cannot receive through the operating system. Do not run them on this
revision.

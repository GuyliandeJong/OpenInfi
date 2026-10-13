# infi75

Open-source configurator for the **Infiverse INFI75** keyboard, as a
replacement for the vendor's Windows-only driver. Command line and GUI,
Linux / Windows / macOS (via [hidapi](https://github.com/libusb/hidapi)).

| Area | Features |
|---|---|
| Lighting | 19 effects, colour, speed, brightness, direction, rainbow; per-key static colours |
| Keys | remap any key to any USB HID key code (incl. F13-F24, media keys) |
| Display | upload an image (any format Pillow reads), sync the clock |
| Reverse engineering | decode, diff, extract and replay USB captures of the official software |

## Status: read this first

No public documentation of the INFI75's USB protocol exists. This tool
implements the **Royuan protocol family** (USB vendor ID `0x3151`), which
is used by keyboards from the same Epomaker-distributed ecosystem and was
reverse-engineered for the Epomaker RT100 by
[epomaker-controller](https://github.com/strodgers/epomaker-controller) and
[OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB). The packet builders
here reproduce that implementation byte for byte (see `tests/`).

Whether the INFI75 speaks exactly this dialect has **not been confirmed on
hardware**. The bundled profile (`src/infi75/profiles/infi75.json`) is
marked `"verified": false` and has these open points:

| Item | Assumed | How to confirm |
|---|---|---|
| USB vendor / product ID | `0x3151`, any PID | `infi75 list --all` |
| Interfaces | lighting = 1, screen = 2 | `infi75 list`, `infi75 capture analyze` |
| Key index per physical key | Royuan column-major order (DynaTab 75X) | `infi75 rgb probe` |
| Screen resolution | unknown | `infi75 capture analyze` on an image-upload capture |

If something does not match, the capture workflow below gives you the real
packets, and every value above is editable in a copy of the profile
(`--profile my-infi75.json`). Use `--dry-run` to see packets without
sending anything.

## Install

Python 3.10+.

```console
git clone https://github.com/guyliandejong/infi75 && cd infi75
python3 -m venv .venv && . .venv/bin/activate
pip install .
```

The GUI needs Tk (`sudo pacman -S tk` on Arch/CachyOS,
`sudo apt install python3-tk` on Debian/Ubuntu; included in the python.org
installers for Windows and macOS). fish users activate the venv with
`. .venv/bin/activate.fish`.

**Linux permissions:** install the udev rule once, then replug the keyboard.

```console
infi75 udev | sudo tee /etc/udev/rules.d/70-infi75.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Connect the keyboard **by USB cable**; wireless modes are not supported.

## Usage

```console
infi75 gui                                    # graphical configurator
infi75 list                                   # find the keyboard's HID interfaces

infi75 rgb mode static --color "#ff8800" --brightness 4
infi75 rgb mode drift --rainbow --speed 5 --direction left
infi75 rgb all purple
infi75 rgb keys ESC=red W=green A=green S=green D=green --default 20,20,20

infi75 keys                                   # physical key names
infi75 keys --hid                             # remap target names
infi75 remap CAPS lctrl
infi75 remap '#59' f13                        # by firmware index

infi75 screen image wallpaper.png --size 240x135
infi75 screen time

infi75 --dry-run rgb all red                  # print packets, send nothing
```

Global options go before the command: `--profile FILE`, `--vid 0x3151`,
`--pid 0x4015`, `--dry-run`.

Effects: `static breathing spectrum drift ripple twinkle stream shadowing
peaks sine_wave surging blooming laser peak_turn rain snow meteor
snow_trace light_shadow`.

## Mapping key indices

```console
infi75 rgb probe
```

lights one firmware index at a time and shows which profile key is assumed
for it. Correct mismatches in your profile copy (`"index"` of each key).

## Learning the real protocol from the official software

1. Install the official INFI75 driver on Windows plus
   [Wireshark](https://www.wireshark.org/) with USBPcap (offered by the
   Wireshark installer). On Linux with the driver in a VM, capture `usbmonN`
   instead.
2. Start a capture on the USB root hub the keyboard is on, change **one**
   setting in the official software, stop, save as `.pcapng`.
3. Inspect it:

   ```console
   infi75 capture analyze red.pcapng          # decoded, repeats collapsed
   infi75 capture extract red.pcapng -o red.txt
   ```

4. Repeat with a different value of the same setting and compare, which
   pinpoints the bytes that encode it:

   ```console
   infi75 capture diff red.pcapng blue.pcapng
   ```

5. Send captured or hand-edited packets to the keyboard:

   ```console
   infi75 replay red.txt
   ```

An image upload capture reveals the screen size: its start packet carries
the byte count, which `analyze` converts to pixels and matches against
common resolutions.

If the captured packets differ from what `--dry-run` prints for the same
action, the profile or `src/infi75/protocol.py` needs adjusting; open an
issue with the capture attached.

## Development

```console
pip install -e ".[dev]"
pytest
```

| Module | Role |
|---|---|
| `protocol.py` | pure packet builders and decoder |
| `transport.py` | hidapi discovery, report I/O, pacing |
| `device.py` | operations that route packets to interfaces |
| `capture.py` | pcap / pcapng (USBPcap, usbmon) and hex-text parsing, diff |
| `screen.py` | image to RGB565 |
| `profile.py`, `profiles/` | per-board configuration |
| `cli.py`, `gui.py` | interfaces |

## Safety

Every command writes volatile or persistent settings the same way the
vendor software does; none writes firmware. A wrong packet on an
incompatible board is normally ignored, but there is no guarantee. Try
`--dry-run` and compare with a capture first.

## License

MIT. Protocol knowledge credited to epomaker-controller and OpenRGB.

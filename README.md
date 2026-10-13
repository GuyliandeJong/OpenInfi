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

## Status

Working on an Infiverse INFI75 (USB ID `05ac:024f`, product string
`INFI75-1.2`, SONiX SN32F290 / HFD RKGK890), confirmed on the hardware:

| Feature | Command |
|---|---|
| 19 lighting effects, colour, brightness 0-5, speed 0-5, direction, rainbow, off | `infi75 rgb mode` |
| Per-key colours (stored on the keyboard) | `infi75 rgb keys`, `infi75 rgb all` |
| Key remapping: keys, combinations, media keys, reset | `infi75 remap` |
| Screen: still images and animated GIFs (135x240) | `infi75 screen image` |
| Screen clock sync | `infi75 screen time` |
| All of the above in a window | `infi75 gui` |

Configuration requires the USB cable in wired mode. Over Bluetooth the
keyboard exposes no configuration interface.

### Why the official software does not work on this keyboard

The `INFI75-1.2` firmware declares its configuration interface (interface 3,
usage page `0xFF13`) without an interrupt IN endpoint. Operating system HID
drivers refuse such an interface, so neither the INFI75 Driver V1.1 nor the
Epomaker web hub can reach it. Its feature reports travel over the USB
control endpoint, so this tool sends them directly through libusb. The
screen image goes to interface 2 (`0xFF68`) through hidraw as usual.

The command set (`04 18` start, `04 13` effect, `04 11` keymap, `04 23`
per-key colours, `04 28` clock, `04 72` screen, `04 02` save, `04 f0`
finish) was decoded from the vendor driver and matches
[gohv/EPOMAKER-Ajazz-AK820-Pro](https://github.com/gohv/EPOMAKER-Ajazz-AK820-Pro)
and OpenRGB's Valkyrie controller. See `src/infi75/hfd.py` for the packet
layouts.

Older Epomaker boards built on the Royuan platform (VID `0x3151`, e.g. the
RT100) are supported by `src/infi75/protocol.py` through a profile with
`"protocol": "royuan"`.

## Install

Python 3.10+ and libusb 1.0 (`libusb` on Arch/CachyOS, `libusb-1.0-0` on Debian/Ubuntu).

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
The rule is scoped to the profile's vendor and product ID.

```console
infi75 udev | sudo tee /etc/udev/rules.d/70-infi75.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Connect the keyboard **by USB cable in wired mode** and disconnect
Bluetooth; wireless modes are not supported.

## Usage

```console
infi75 gui                                        # graphical configurator

infi75 rgb effects                                # list effects
infi75 rgb mode static --color "#ff8800" --brightness 5
infi75 rgb mode spectrum --rainbow --speed 4
infi75 rgb mode off

infi75 rgb all purple
infi75 rgb keys W=red A=red S=red D=red --default 0,0,40

infi75 keys                                       # physical key names
infi75 remap CAPS lctrl
infi75 remap F12 volup                            # volup voldown mute playpause next prev stop
infi75 remap RALT ctrl+c
infi75 remap --list
infi75 remap --reset

infi75 screen image wallpaper.png                 # --fit crop|stretch|pad
infi75 screen image animation.gif
infi75 screen time

infi75 --dry-run rgb all red                      # print packets, send nothing
infi75 probe --usb 3                              # read-only check of the configuration interface
```

Every remap write replaces the keyboard's whole table, so the tool keeps
your remaps in `~/.config/infi75/keymap.json` and re-sends all of them each
time.

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
| `hfd.py` | INFI75 packet builders and session (acknowledgement handling) |
| `board.py` | INFI75 operations shared by CLI and GUI |
| `usbctl.py` | libusb control transfers for the unbound configuration interface |
| `probe.py` | read-only interface and descriptor probing |
| `protocol.py` | Royuan packet builders and decoder |
| `transport.py` | hidapi discovery, report I/O, pacing |
| `device.py` | operations that route packets to interfaces |
| `capture.py` | pcap / pcapng (USBPcap, usbmon) and hex-text parsing, diff |
| `screen.py` | image to RGB565 |
| `profile.py`, `profiles/` | per-board configuration |
| `cli.py`, `gui.py` | interfaces |

## Safety

Every command writes settings the same way the vendor driver does; none
writes firmware. Do not run the firmware updaters shipped with the vendor
driver package on an `INFI75-1.2`: they target a different firmware
revision (`INFI75`, Bluetooth `INFI75 5.1`).

## License

MIT. Protocol knowledge credited to epomaker-controller and OpenRGB.

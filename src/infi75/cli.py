"""Command-line interface: ``infi75 <command> ...``."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime

from . import __version__, capture, hidkeys, protocol
from . import profile as profiles
from .device import Keyboard
from .transport import DeviceError, Transport, enumerate_interfaces, udev_rule

COLOR_NAMES = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
    "black": (0, 0, 0), "off": (0, 0, 0), "yellow": (255, 255, 0), "cyan": (0, 255, 255),
    "magenta": (255, 0, 255), "orange": (255, 128, 0), "purple": (128, 0, 255), "pink": (255, 64, 160),
}


def parse_color(text: str) -> tuple[int, int, int]:
    """``#ff8800``, ``ff8800``, ``255,136,0`` or a colour name."""
    value = text.strip().lower()
    if value in COLOR_NAMES:
        return COLOR_NAMES[value]
    if "," in value:
        parts = tuple(int(p) for p in value.split(","))
    else:
        value = value.lstrip("#")
        if len(value) != 6:
            raise argparse.ArgumentTypeError(f"bad colour {text!r}")
        parts = tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        raise argparse.ArgumentTypeError(f"bad colour {text!r}")
    return parts  # type: ignore[return-value]


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 240x135") from None
    return w, h


def _int(text: str) -> int:
    return int(text, 0)


def _keyboard(args) -> Keyboard:
    prof = profiles.load(args.profile)
    if args.vid is not None:
        prof.vendor_id = args.vid
    if not prof.verified and not args.dry_run:
        print(
            f"warning: profile '{prof.name}' is unverified (protocol: {prof.protocol}). "
            "Use --dry-run to inspect packets first.",
            file=sys.stderr,
        )
    return Keyboard(prof, Transport(prof, product_id=args.pid, dry_run=args.dry_run))


# ------------------------------------------------------------------ commands


def cmd_list(args) -> int:
    prof = profiles.load(args.profile)
    vid = 0 if args.all else (args.vid if args.vid is not None else prof.vendor_id)
    interfaces = enumerate_interfaces(vid)
    if not interfaces:
        print(f"no HID interfaces found for vendor 0x{vid:04x}" if vid else "no HID interfaces found")
        return 1
    for interface in interfaces:
        marker = "  [vendor-defined]" if interface.usage_page >= 0xFF00 else ""
        print(f"{interface}{marker}")
    return 0


def cmd_keys(args) -> int:
    if args.hid:
        for name in hidkeys.names():
            print(f"0x{hidkeys.code(name):02x}  {name}")
        return 0
    prof = profiles.load(args.profile)
    for key in sorted(prof.keys, key=lambda k: (k.row, k.x)):
        print(f"row {key.row}  index {key.index:3d}  {key.name}")
    return 0


def _board(args):
    from .board import InfiBoard

    return InfiBoard(profiles.load(args.profile), args.vid, args.pid, dry_run=args.dry_run,
                     trace=args.trace)


def _is_hfd(args) -> bool:
    return profiles.load(args.profile).protocol == "hfd"


def cmd_rgb(args) -> int:
    if args.rgb_cmd == "effects":
        if _is_hfd(args):
            from . import hfd

            print("  off  (lights off)")
            for name, (value, desc) in hfd.EFFECTS.items():
                print(f"{value:3d}  {name:12s} {desc}")
        else:
            for mode in protocol.Mode:
                print(f"{int(mode):3d}  {mode.name.lower()}")
        return 0
    if _is_hfd(args):
        board = _board(args)
        if args.rgb_cmd == "all":
            board.set_key_colors({}, default=args.color, brightness=args.brightness)
        elif args.rgb_cmd == "keys":
            chosen = {}
            for item in args.assign:
                name, _, color = item.rpartition("=")
                if not name:
                    raise ValueError(f"expected KEY=COLOUR, got {item!r}")
                chosen[name] = parse_color(color)
            board.set_key_colors(chosen, default=args.default, brightness=args.brightness)
        elif args.rgb_cmd == "mode":
            board.set_lighting(args.mode, args.color, args.brightness, args.speed, args.rainbow, args.direction)
        else:
            raise DeviceError(f"'rgb {args.rgb_cmd}' is not available for this keyboard")
        return 0
    kb = _keyboard(args)
    if args.rgb_cmd == "mode":
        kb.set_lighting(
            protocol.Lighting(
                mode=_royuan_mode(args.mode),
                color=args.color,
                speed=args.speed,
                brightness=args.brightness,
                rainbow=args.rainbow,
                direction=protocol.Direction[args.direction.upper()],  # same names in both protocols
            )
        )
    elif args.rgb_cmd == "keys":
        colors = {}
        for item in args.assign:
            name, _, color = item.rpartition("=")
            if not name:
                raise SystemExit(f"expected KEY=COLOUR, got {item!r}")
            colors[name] = parse_color(color)
        kb.set_key_colors(colors, default=args.default)
    elif args.rgb_cmd == "all":
        kb.set_key_colors({key.name: args.color for key in kb.profile.keys})
    elif args.rgb_cmd == "probe":
        if args.index is not None:
            kb.probe_index(args.index, args.color)
            return 0
        print("Lighting one firmware index at a time. Note which key lights up; Ctrl+C to stop.")
        for index in range(args.start, kb.profile.rgb_slots):
            kb.probe_index(index, args.color)
            known = [k.name for k in kb.profile.keys if k.index == index]
            reply = input(f"index {index:3d} (profile: {known[0] if known else '-'}) > enter for next, q to quit: ")
            if reply.strip().lower() == "q":
                break
    return 0


def _royuan_mode(name: str) -> protocol.Mode:
    try:
        return protocol.Mode[name.upper()]
    except KeyError:
        raise ValueError(f"unknown effect {name!r}; known: {', '.join(m.name.lower() for m in protocol.Mode)}") from None


def _remap_hfd(args) -> int:
    board = _board(args)
    layer = "fn" if args.fn else "base"
    prefix = "Fn+" if args.fn else ""
    if args.list:
        any_remap = False
        for name, tag in (("base", ""), ("fn", "Fn+")):
            for key, target in sorted(board.remaps(name).items()):
                print(f"{tag}{key} -> {target}")
                any_remap = True
        if not any_remap:
            print("no remaps (all keys default)")
        return 0
    if args.reset:
        board.reset_remaps(layer)
        state = {}
    else:
        if not args.key or not args.to:
            raise ValueError("usage: infi75 remap [--fn] KEY TARGET  (or --reset / --list)")
        state = board.remap(args.key, args.to, layer)
    for name, target in sorted(state.items()):
        print(f"{prefix}{name} -> {target}")
    if not state:
        print(f"no {'Fn-layer ' if args.fn else ''}remaps (all keys default)")
    return 0


BLOCKABLE = {"alttab": "block_alt_tab", "altf4": "block_alt_f4", "win": "block_win"}


def cmd_system(args) -> int:
    board = _board(args)
    changes = {}
    if args.game_mode is not None:
        changes["game_mode"] = args.game_mode == "on"
    if args.block is not None:
        wanted = {b.strip().lower().replace("+", "") for b in args.block.split(",") if b.strip()}
        wanted.discard("none")
        unknown = wanted - set(BLOCKABLE)
        if unknown:
            raise ValueError(f"unknown key(s) to block: {', '.join(sorted(unknown))}; use alttab, altf4, win or none")
        changes.update({field: name in wanted for name, field in BLOCKABLE.items()})
    if args.sleep is not None:
        changes["sleep"] = args.sleep
    settings = board.set_system(**changes) if changes else board.system()
    blocked = [name for name, field in BLOCKABLE.items() if getattr(settings, field)]
    print(f"game mode: {'on' if settings.game_mode else 'off'}")
    print(f"blocked in game mode: {', '.join(blocked) or 'nothing'}")
    print(f"sleep: {settings.sleep} (vendor setting 1-5)")
    if not changes:
        print("(last values written by this tool; the keyboard cannot be read back yet)")
    return 0


def cmd_remap(args) -> int:
    if _is_hfd(args):
        return _remap_hfd(args)
    if not args.key or not args.to:
        raise ValueError("usage: infi75 remap KEY TARGET")
    kb = _keyboard(args)
    hid_code = hidkeys.code(args.to)
    kb.remap(args.key, hid_code)
    print(f"{args.key} -> {hidkeys.name(hid_code)} (0x{hid_code:02x})", file=sys.stderr)
    return 0


def _upload_screen_hfd(args) -> int:
    board = _board(args)
    count = board.upload_image(args.path, fit=args.fit, slot=args.slot,
                               progress=lambda n, total: print(f"\r{n}/{total}", end="", file=sys.stderr))
    print(f"\nuploaded {count} frame(s)", file=sys.stderr)
    return 0


def cmd_screen(args) -> int:
    if _is_hfd(args):
        if args.screen_cmd == "time":
            _board(args).sync_time(datetime.fromisoformat(args.at) if args.at else None)
            return 0
        return _upload_screen_hfd(args)
    kb = _keyboard(args)
    if args.screen_cmd == "image":
        width, height = args.size if args.size else (None, None)
        kb.upload_image(args.path, width, height)
    elif args.screen_cmd == "time":
        kb.sync_time(datetime.fromisoformat(args.at) if args.at else None)
    return 0


def cmd_macro(args) -> int:
    from . import macro

    board = _board(args)
    if args.macro_cmd == "list":
        macros = board.macros()
        for n, item in enumerate(macros):
            print(f"{n:3d}  {item['name']:20s} {macro.describe(macro.parse(item['sequence']))}")
        if not macros:
            print("no macros ('infi75 macro save NAME \"ctrl+c 50ms enter\"' adds one)")
    elif args.macro_cmd == "save":
        board.save_macro(args.name, args.sequence)
        print(f"saved macro '{args.name}'; assign it with: infi75 remap KEY 'macro:{args.name}'")
    elif args.macro_cmd == "delete":
        board.delete_macro(args.name)
        print(f"deleted macro '{args.name}'")
    return 0


def cmd_setup(args) -> int:
    board = _board(args)
    if args.setup_cmd == "list":
        names = board.setups()
        for name in names:
            saved = board.load_setup(name)
            print(f"{name:24s} saved {saved.get('saved', '?')}  ({', '.join(saved.get('parts', {}))})")
        if not names:
            print("no saved setups ('infi75 setup save NAME' saves the current one)")
    elif args.setup_cmd == "save":
        path = board.save_setup(args.name)
        print(f"saved setup '{args.name}' ({path})")
    elif args.setup_cmd == "apply":
        done = board.apply_setup(args.name, include_screen=not args.no_screen,
                                 progress=lambda n, total: print(f"\rscreen {n}/{total}", end="", file=sys.stderr))
        print(f"\napplied '{args.name}': {', '.join(done)}")
    elif args.setup_cmd == "delete":
        board.delete_setup(args.name)
        print(f"deleted setup '{args.name}'")
    return 0


def cmd_clock(args) -> int:
    from . import clock

    if args.clock_cmd == "sync":
        board = _board(args)
        when = datetime.fromisoformat(args.at) if args.at else None
        if not args.dry_run and (args.if_present or args.wait):
            deadline = time.monotonic() + args.wait
            while board.connection() != "usb" and time.monotonic() < deadline:
                time.sleep(0.5)
            if board.connection() != "usb":
                if args.if_present:
                    print("keyboard not connected by USB; nothing to do", file=sys.stderr)
                    return 0
                raise DeviceError("keyboard not connected by USB")
            time.sleep(1 if args.wait else 0)  # let a freshly plugged keyboard finish starting up
        board.sync_time(when, save=not args.no_save)
        print(f"keyboard clock set to {(when or datetime.now()):%Y-%m-%d %H:%M:%S}")
    elif args.clock_cmd == "install":
        folder = clock.install(args.every)
        print(f"installed {clock.SERVICE} and {clock.TIMER} in {folder}")
        print(f"the clock is synced 30 s after login and every {clock.check_interval(args.every)}")
        print("to also sync on plug-in, install the current udev rule: "
              "infi75 udev | sudo tee /etc/udev/rules.d/70-infi75.rules")
    elif args.clock_cmd == "uninstall":
        clock.uninstall()
        print("automatic clock sync removed")
    elif args.clock_cmd == "status":
        if clock.installed():
            print(f"automatic sync: on, every {clock.interval()} and on plug-in (units in {clock.unit_dir()})")
        else:
            print("automatic sync: off ('infi75 clock install' turns it on)")
    return 0


def cmd_capture(args) -> int:
    reports = capture.load(args.file)
    if args.interface is not None:
        reports = [r for r in reports if r.interface == args.interface]
    if args.capture_cmd == "extract":
        reports = capture.outgoing(reports)
        text = capture.to_text(reports)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(text)
            print(f"wrote {len(reports)} reports to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(text)
    elif args.capture_cmd == "analyze":
        _analyze(reports, args.verbose)
        if not reports and not args.file.endswith(".txt"):
            print("raw USB records in the capture:")
            for key, count in sorted(capture.summary(args.file).items()):
                print(f"  {count:5d}  {key}")
    elif args.capture_cmd == "diff":
        reports = capture.outgoing(reports)
        other = capture.outgoing(capture.load(args.other))
        if args.interface is not None:
            other = [r for r in other if r.interface == args.interface]
        if len(reports) != len(other):
            print(f"note: packet counts differ ({len(reports)} vs {len(other)}); comparing the first "
                  f"{min(len(reports), len(other))}")
        changes = capture.diff(reports, other)
        if not changes:
            print("no differences")
        for n, diffs in changes:
            cells = "  ".join(f"[{off}] {a:02x}->{b:02x}" for off, a, b in diffs[:16])
            more = f"  (+{len(diffs) - 16} more)" if len(diffs) > 16 else ""
            print(f"packet {n:4d} (if={reports[n].interface}): {cells}{more}")
    return 0


def _analyze(reports: list[capture.Report], verbose: bool) -> None:
    if not reports:
        print("no HID reports found")
        return
    devices = Counter(r.device for r in reports)
    print(f"{len(reports)} reports; per USB device address: {dict(devices)}")
    print(f"per interface: {dict(Counter(r.interface for r in reports))}")
    print(f"report sizes: {dict(Counter(len(r.data) for r in reports))}")
    previous = None
    repeats = 0
    for n, report in enumerate(reports):
        data = report.data
        label = protocol.describe(data)
        if data[:1] == b"\xa5" and len(data) >= 7:
            total = int.from_bytes(data[4:7], "little")
            label += _screen_size_hint(total // 2)
        signature = (report.kind, report.interface, tuple(label.split()[:3]))
        if not verbose and signature == previous:
            repeats += 1
            continue
        if repeats:
            print(f"      ... {repeats} similar")
            repeats = 0
        previous = signature
        arrow = "<-" if report.kind == "input" else "->"
        print(f"{n:5d} {arrow} if={report.interface} {report.kind:9s} {data[:16].hex(' ')}{' ..' if len(data) > 16 else ''}  {label}")
    if repeats:
        print(f"      ... {repeats} similar")


def _screen_size_hint(pixels: int) -> str:
    common = [(w, h) for w, h in [(240, 135), (135, 240), (160, 80), (80, 160), (128, 128), (162, 173),
              (173, 162), (240, 240), (320, 172), (172, 320), (284, 76), (76, 284), (128, 64)] if w * h == pixels]
    return f"; matches {', '.join(f'{w}x{h}' for w, h in common)}" if common else ""


def cmd_replay(args) -> int:
    kb = _keyboard(args)
    reports = capture.outgoing(capture.load(args.file))
    if args.only_interface is not None:
        reports = [r for r in reports if r.interface == args.only_interface]
    sent = kb.replay(reports, args.to_interface)
    print(f"sent {sent} reports", file=sys.stderr)
    return 0


def cmd_probe(args) -> int:
    """Identify the configuration protocol with read-only queries."""
    from . import probe
    from .transport import _hid

    prof = profiles.load(args.profile)
    vid = args.vid if args.vid is not None else prof.vendor_id
    pids = [args.pid] if args.pid is not None else prof.product_ids
    log = print
    hid = _hid()
    if not sys.platform.startswith("linux"):
        print("descriptor dump is Linux-only; probing vendor interfaces with 64-byte reports")
        for interface in enumerate_interfaces(vid):
            if interface.usage_page >= 0xFF00 and (not pids or interface.product_id in pids):
                print(f"{interface}")
                probe.query_online(hid, interface.path, 64, log)
        return 0

    if args.usb is not None:
        return _probe_usb(args, vid, pids[0] if pids else None)

    nodes = [n for pid in pids for n in probe.linux_nodes(vid, pid)] if pids else []
    if args.handshake:
        targets = [n for n in nodes if n.interface == args.interface]
        if not targets:
            print(f"no hidraw node for interface {args.interface}")
            return 1
        node = targets[0]
        print(f"{node.path}  interface {node.interface}: sending session start/end (04 18, 04 02)")
        ok = probe.handshake(hid, node.path.encode(), log)
        print("result: " + ("keyboard answered feature reports" if ok else "no feature-report reply"))
        return 0
    if not nodes:
        print(f"no hidraw nodes for {vid:04x}:{','.join(f'{p:04x}' for p in pids) or '*'}; "
              "is the keyboard connected by cable in wired mode?")
        return 1
    answered = False
    for node in nodes:
        print(f"\n{node.path}  interface {node.interface}  {node.name}")
        for col in node.collections:
            sizes = ", ".join(f"{kind}[id {rid}]={size}B" for (kind, rid), size in sorted(col.reports.items()))
            print(f"  collection usage_page=0x{col.usage_page:04x} usage=0x{col.usage:02x}: {sizes or '-'}")
        vendor = [c for c in node.collections if c.usage_page >= 0xFF00]
        if not vendor:
            continue
        try:
            for col in vendor:
                out = col.reports.get(("output", 0))
                if args.online and out and out <= 4200:
                    print(f"  probing 'online' protocol (GET_DEVICE_INFO, {out}-byte output report)")
                    answered |= probe.query_online(hid, node.path.encode(), out, log)
                feature_ids = sorted({rid for kind, rid in col.reports if kind == "feature"})
                if feature_ids:
                    print(f"  reading feature reports {feature_ids}")
                    probe.read_features(hid, node.path.encode(), feature_ids, log)
            # The vendor driver configures the board with 64-byte feature reports
            # (report ID 0) even where the descriptor declares none. Linux hidraw
            # passes GET_REPORT through unvalidated, so read one (no write).
            if not any(kind == "feature" for c in vendor for kind, _ in c.reports):
                print("  reading undeclared feature report 0 (read-only)")
                probe.read_features(hid, node.path.encode(), [0], log)
        except OSError as exc:
            print(f"  cannot open {node.path}: {exc} (install the udev rule: 'infi75 udev')")
    if args.online:
        print("\nresult: " + ("keyboard answered the 'online' protocol" if answered
                               else "no 'online' reply; paste this output for analysis"))
    return 0


def _probe_usb(args, vid: int, pid: int | None) -> int:
    """Talk to an interface through control transfers (works without a HID driver)."""
    from . import probe, usbctl

    if pid is None:
        print("pass --pid")
        return 1
    with usbctl.UsbHid(vid, pid, args.usb) as dev:
        print(f"interface {args.usb} via libusb control transfers")
        try:
            desc = dev.report_descriptor()
            print(f"  report descriptor ({len(desc)} bytes): {desc.hex(' ')}")
            for col in probe.parse_report_descriptor(desc):
                sizes = ", ".join(f"{k}[id {r}]={n}B" for (k, r), n in sorted(col.reports.items()))
                print(f"  collection usage_page=0x{col.usage_page:04x} usage=0x{col.usage:02x}: {sizes or '-'}")
        except Exception as exc:  # pyusb raises USBError subclasses and timeouts
            print(f"  report descriptor: {exc}")
        try:
            data = dev.get_feature(0, 64)
            print(f"  GET_FEATURE id=0: {data.hex(' ')}")
        except Exception as exc:
            print(f"  GET_FEATURE id=0: {exc}")
        if args.handshake:
            for name, cmd in (("start", 0x18), ("end", 0x02)):
                try:
                    written = dev.set_feature(bytes([0x04, cmd]) + bytes(62))
                    print(f"  SET_FEATURE 04 {cmd:02x} ({name}): {written} bytes")
                except Exception as exc:
                    print(f"  SET_FEATURE 04 {cmd:02x} ({name}): {exc}")
                    continue
                try:
                    print(f"  GET_FEATURE: {dev.get_feature(0, 64).hex(' ')}")
                except Exception as exc:
                    print(f"  GET_FEATURE: {exc}")
    return 0


def cmd_udev(args) -> int:
    prof = profiles.load(args.profile)
    if args.vid is not None:
        rule = udev_rule(args.vid, [args.pid] if args.pid is not None else None)
    else:
        rule = udev_rule(prof.vendor_id, prof.product_ids)
    sys.stdout.write(rule)
    print("# save as /etc/udev/rules.d/70-infi75.rules, then: sudo udevadm control --reload && "
          "sudo udevadm trigger", file=sys.stderr)
    return 0


def cmd_desktop(args) -> int:
    from . import desktop

    if args.desktop_cmd == "install":
        entry = desktop.install()
        print(f"added 'INFI75 Configurator' to the app menu ({entry})")
    else:
        desktop.uninstall()
        print("removed 'INFI75 Configurator' from the app menu")
    return 0


def cmd_gui(args) -> int:
    from .gui import run

    return run(args)


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="infi75", description="Configure the Infiverse INFI75 keyboard.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--profile", help="keyboard profile JSON (default: bundled INFI75 profile)")
    parser.add_argument("--vid", type=_int, help="override USB vendor id, e.g. 0x3151")
    parser.add_argument("--pid", type=_int, help="select USB product id, e.g. 0x4015")
    parser.add_argument("-n", "--dry-run", action="store_true", help="print packets instead of sending them")
    parser.add_argument("--trace", action="store_true",
                        help="print every packet sent to the keyboard (>) and every reply read back (<)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list HID interfaces of the keyboard")
    p.add_argument("--all", action="store_true", help="list every HID device, not only the profile's vendor")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("keys", help="list key names usable in commands")
    p.add_argument("--hid", action="store_true", help="list remap target names (HID usages) instead")
    p.set_defaults(func=cmd_keys)

    rgb = sub.add_parser("rgb", help="lighting")
    rgb_sub = rgb.add_subparsers(dest="rgb_cmd", required=True)
    p = rgb_sub.add_parser("mode", help="set the global lighting effect")
    p.add_argument("mode", help="effect name or number; 'infi75 rgb effects' lists them")
    p.add_argument("--color", type=parse_color, default=(255, 255, 255))
    p.add_argument("--speed", type=int, default=3, help="0-5")
    p.add_argument("--brightness", type=int, default=4, help="0-5 (INFI75), 0-4 (Royuan boards)")
    p.add_argument("--rainbow", action="store_true", help="cycle colours instead of --color")
    p.add_argument("--direction", choices=["left", "right", "up", "down"], default="right")
    rgb_sub.add_parser("effects", help="list the lighting effects of the selected keyboard")
    p = rgb_sub.add_parser("keys", help="per-key colours, e.g. ESC=red W=#00ff00 '#40=255,0,0'")
    p.add_argument("assign", nargs="+", metavar="KEY=COLOUR")
    p.add_argument("--default", type=parse_color, default=(0, 0, 0), help="colour for unlisted keys")
    p.add_argument("--brightness", type=int, default=5, help="0-5 (INFI75)")
    p = rgb_sub.add_parser("all", help="set every key to one colour")
    p.add_argument("color", type=parse_color)
    p.add_argument("--brightness", type=int, default=5, help="0-5 (INFI75)")
    p = rgb_sub.add_parser("probe", help="light firmware indices one by one to map them to keys")
    p.add_argument("--index", type=int, help="light only this index and exit")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--color", type=parse_color, default=(255, 255, 255))
    rgb.set_defaults(func=cmd_rgb)

    p = sub.add_parser("remap", help="make a key send a different key code")
    p.add_argument("key", nargs="?", help="physical key (profile name, or #index); 'infi75 keys' lists them")
    p.add_argument("to", nargs="?",
                   help="target: key name (esc, f13, 0x29), combination (ctrl+c), media key "
                        "(volup, voldown, mute, playpause, next, prev, stop), macro:NAME (macro:NAMEx3 "
                        "repeats it 3 times) or 'default'")
    p.add_argument("--reset", action="store_true", help="restore every key to its default")
    p.add_argument("--list", action="store_true", help="show the remaps written by this tool (both layers)")
    p.add_argument("--fn", action="store_true",
                   help="the Fn layer: what the key does while Fn is held (INFI75; not Esc, F5, F6, "
                        "Backspace, \\, Win, Fn)")
    p.set_defaults(func=cmd_remap)

    p = sub.add_parser("system", help="game mode, key blocking and sleep timer (INFI75); no options: show")
    p.add_argument("--game-mode", choices=["on", "off"])
    p.add_argument("--block", metavar="KEYS",
                   help="keys disabled in game mode, comma separated: alttab, altf4, win, or none")
    p.add_argument("--sleep", type=int, choices=range(1, 6), metavar="1-5",
                   help="sleep timer setting from the vendor driver's list (1-5, default 2; durations unconfirmed)")
    p.set_defaults(func=cmd_system)

    scr = sub.add_parser("screen", help="built-in display")
    scr_sub = scr.add_subparsers(dest="screen_cmd", required=True)
    p = scr_sub.add_parser("image", help="upload an image or animated GIF")
    p.add_argument("path")
    p.add_argument("--size", type=parse_size, help="screen resolution WxH (Royuan boards)")
    p.add_argument("--fit", choices=["crop", "stretch", "pad"], default="crop",
                   help="how to fit the image to the 135x240 screen (INFI75)")
    p.add_argument("--slot", type=int, default=1, help="screen slot written by the upload (INFI75, default 1)")
    p = scr_sub.add_parser("time", help="sync the screen clock")
    p.add_argument("--at", help="ISO timestamp instead of now")
    scr.set_defaults(func=cmd_screen)

    mac = sub.add_parser("macro", help="key sequences a key can play (INFI75)")
    mac_sub = mac.add_subparsers(dest="macro_cmd", required=True)
    mac_sub.add_parser("list", help="list saved macros")
    p = mac_sub.add_parser("save", help="add or replace a macro and write the macro table")
    p.add_argument("name")
    p.add_argument("sequence", help="e.g. \"ctrl+c 50ms enter\", \"text:hello\", \"+shift a -shift\", \"mouse1\"")
    p = mac_sub.add_parser("delete", help="delete a macro (not while a key uses it)")
    p.add_argument("name")
    mac.set_defaults(func=cmd_macro)

    st = sub.add_parser("setup", help="saved setups: lighting, colours, remaps, game mode and screen together")
    st_sub = st.add_subparsers(dest="setup_cmd", required=True)
    st_sub.add_parser("list", help="list saved setups")
    p = st_sub.add_parser("save", help="save what was last applied to the keyboard under a name")
    p.add_argument("name")
    p = st_sub.add_parser("apply", help="write a saved setup to the keyboard")
    p.add_argument("name")
    p.add_argument("--no-screen", action="store_true", help="leave the screen picture as it is")
    p = st_sub.add_parser("delete", help="delete a saved setup")
    p.add_argument("name")
    st.set_defaults(func=cmd_setup)

    clk = sub.add_parser("clock", help="set the keyboard clock, once or automatically")
    clk_sub = clk.add_subparsers(dest="clock_cmd", required=True)
    p = clk_sub.add_parser("sync", help="set the keyboard clock to this computer's time now")
    p.add_argument("--at", help="ISO timestamp instead of now")
    p.add_argument("--if-present", action="store_true", help="exit quietly when the keyboard is not connected by USB")
    p.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                   help="wait up to this long for the keyboard to appear (used on plug-in)")
    p.add_argument("--no-save", action="store_true",
                   help="EXPERIMENT: skip the SAVE command (tests whether the clock needs a settings-memory write)")
    p = clk_sub.add_parser("install", help="sync automatically: after login, periodically and on plug-in")
    p.add_argument("--every", default="6h", help="interval, e.g. 30min, 1h, 6h (default 6h)")
    clk_sub.add_parser("uninstall", help="stop syncing automatically")
    clk_sub.add_parser("status", help="show whether automatic sync is on")
    clk.set_defaults(func=cmd_clock)

    cap = sub.add_parser("capture", help="inspect USB captures of the official software")
    cap_sub = cap.add_subparsers(dest="capture_cmd", required=True)
    p = cap_sub.add_parser("analyze", help="summarise and decode the reports in a capture")
    p.add_argument("file")
    p.add_argument("-v", "--verbose", action="store_true", help="do not collapse repeated packets")
    p = cap_sub.add_parser("extract", help="write the reports as editable hex text")
    p.add_argument("file")
    p.add_argument("-o", "--output")
    p = cap_sub.add_parser("diff", help="byte differences between two captures of the same action")
    p.add_argument("file")
    p.add_argument("other")
    for p in cap_sub.choices.values():
        p.add_argument("--interface", type=int, help="only reports sent to this interface")
    cap.set_defaults(func=cmd_capture)

    p = sub.add_parser("replay", help="send reports from a capture or hex text file to the keyboard")
    p.add_argument("file")
    p.add_argument("--only-interface", type=int, help="replay only reports captured on this interface")
    p.add_argument("--to-interface", type=int, help="send everything to this interface")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("probe", help="identify the keyboard's protocol (read-only)")
    p.add_argument("--online", action="store_true",
                   help="also send GET_DEVICE_INFO in the AJAZZ/HFD online framing (a 4096-byte output report)")
    p.add_argument("--handshake", action="store_true",
                   help="WRITE TEST: send the vendor driver's session start/end feature reports (04 18, 04 02)")
    p.add_argument("--interface", type=int, default=1, help="interface for --handshake (default 1)")
    p.add_argument("--usb", type=int, metavar="IFACE",
                   help="probe this interface with libusb control transfers instead of hidraw "
                        "(for HID interfaces the kernel left unbound); with --handshake also writes")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("udev", help="print a Linux udev rule for non-root access")
    p.set_defaults(func=cmd_udev)

    p = sub.add_parser("desktop", help="add or remove the app-menu entry for the graphical configurator")
    p.add_argument("desktop_cmd", choices=["install", "uninstall"])
    p.set_defaults(func=cmd_desktop)

    p = sub.add_parser("gui", help="open the graphical configurator")
    p.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # output piped into e.g. head
        return 0
    except (DeviceError, capture.CaptureError, KeyError, ValueError, OSError, RuntimeError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

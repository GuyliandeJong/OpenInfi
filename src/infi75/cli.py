"""Command-line interface: ``infi75 <command> ...``."""

from __future__ import annotations

import argparse
import sys
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


def cmd_rgb(args) -> int:
    kb = _keyboard(args)
    if args.rgb_cmd == "mode":
        kb.set_lighting(
            protocol.Lighting(
                mode=protocol.Mode[args.mode.upper()],
                color=args.color,
                speed=args.speed,
                brightness=args.brightness,
                rainbow=args.rainbow,
                direction=protocol.Direction[args.direction.upper()],
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


def cmd_remap(args) -> int:
    kb = _keyboard(args)
    hid_code = hidkeys.code(args.to)
    kb.remap(args.key, hid_code)
    print(f"{args.key} -> {hidkeys.name(hid_code)} (0x{hid_code:02x})", file=sys.stderr)
    return 0


def cmd_screen(args) -> int:
    kb = _keyboard(args)
    if args.screen_cmd == "image":
        width, height = args.size if args.size else (None, None)
        kb.upload_image(args.path, width, height)
    elif args.screen_cmd == "time":
        kb.sync_time(datetime.fromisoformat(args.at) if args.at else None)
    return 0


def cmd_capture(args) -> int:
    reports = capture.load(args.file)
    if args.interface is not None:
        reports = [r for r in reports if r.interface == args.interface]
    if args.capture_cmd == "extract":
        text = capture.to_text(reports)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(text)
            print(f"wrote {len(reports)} reports to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(text)
    elif args.capture_cmd == "analyze":
        _analyze(reports, args.verbose)
    elif args.capture_cmd == "diff":
        other = capture.load(args.other)
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
        print("no host-to-device HID reports found")
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
        signature = (report.interface, data[:1], label.split(" ")[0])
        if not verbose and signature == previous:
            repeats += 1
            continue
        if repeats:
            print(f"      ... {repeats} similar")
            repeats = 0
        previous = signature
        print(f"{n:5d} if={report.interface} {report.kind:9s} {data[:16].hex(' ')}{' ..' if len(data) > 16 else ''}  {label}")
    if repeats:
        print(f"      ... {repeats} similar")


def _screen_size_hint(pixels: int) -> str:
    common = [(w, h) for w, h in [(240, 135), (135, 240), (160, 80), (80, 160), (128, 128), (162, 173),
              (173, 162), (240, 240), (320, 172), (172, 320), (284, 76), (76, 284), (128, 64)] if w * h == pixels]
    return f"; matches {', '.join(f'{w}x{h}' for w, h in common)}" if common else ""


def cmd_replay(args) -> int:
    kb = _keyboard(args)
    reports = capture.load(args.file)
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

    nodes = [n for pid in pids for n in probe.linux_nodes(vid, pid)] if pids else []
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
                if out and out <= 4200:
                    print(f"  probing 'online' protocol (GET_DEVICE_INFO, {out}-byte output report)")
                    answered |= probe.query_online(hid, node.path.encode(), out, log)
                feature_ids = sorted({rid for kind, rid in col.reports if kind == "feature"})
                if feature_ids:
                    print(f"  reading feature reports {feature_ids}")
                    probe.read_features(hid, node.path.encode(), feature_ids, log)
        except OSError as exc:
            print(f"  cannot open {node.path}: {exc} (install the udev rule: 'infi75 udev')")
    print("\nresult: " + ("keyboard answered the 'online' protocol" if answered
                           else "no 'online' reply; paste this output for analysis"))
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
    p.add_argument("mode", choices=[m.name.lower() for m in protocol.Mode])
    p.add_argument("--color", type=parse_color, default=(255, 255, 255))
    p.add_argument("--speed", type=int, default=3, help="0-5")
    p.add_argument("--brightness", type=int, default=4, help="0-4")
    p.add_argument("--rainbow", action="store_true", help="cycle colours instead of --color")
    p.add_argument("--direction", choices=[d.name.lower() for d in protocol.Direction], default="right")
    p = rgb_sub.add_parser("keys", help="per-key colours, e.g. ESC=red W=#00ff00 '#40=255,0,0'")
    p.add_argument("assign", nargs="+", metavar="KEY=COLOUR")
    p.add_argument("--default", type=parse_color, default=(0, 0, 0), help="colour for unlisted keys")
    p = rgb_sub.add_parser("all", help="set every key to one colour")
    p.add_argument("color", type=parse_color)
    p = rgb_sub.add_parser("probe", help="light firmware indices one by one to map them to keys")
    p.add_argument("--index", type=int, help="light only this index and exit")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--color", type=parse_color, default=(255, 255, 255))
    rgb.set_defaults(func=cmd_rgb)

    p = sub.add_parser("remap", help="make a key send a different key code")
    p.add_argument("key", help="physical key (profile name, or #index)")
    p.add_argument("to", help="target key name, e.g. esc, f13, volup, 0x29")
    p.set_defaults(func=cmd_remap)

    scr = sub.add_parser("screen", help="built-in display")
    scr_sub = scr.add_subparsers(dest="screen_cmd", required=True)
    p = scr_sub.add_parser("image", help="upload an image")
    p.add_argument("path")
    p.add_argument("--size", type=parse_size, help="screen resolution WxH (overrides profile)")
    p = scr_sub.add_parser("time", help="sync the screen clock")
    p.add_argument("--at", help="ISO timestamp instead of now")
    scr.set_defaults(func=cmd_screen)

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
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("udev", help="print a Linux udev rule for non-root access")
    p.set_defaults(func=cmd_udev)

    p = sub.add_parser("gui", help="open the graphical configurator")
    p.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (DeviceError, capture.CaptureError, KeyError, ValueError, OSError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

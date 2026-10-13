import struct

from openinfi import capture

FEATURE_PAYLOAD = bytes.fromhex("07020404170ac81ee7") + bytes(55)


def _set_report_setup(interface: int, report_id: int = 0, length: int = 64) -> bytes:
    return struct.pack("<BBHHH", 0x21, 0x09, (3 << 8) | report_id, interface, length)


def _usbpcap_frame(irp: int, info: int, stage: int, data: bytes, transfer: int = 2, endpoint: int = 0) -> bytes:
    hlen = 28 if transfer == 2 else 27
    head = struct.pack("<HQIHBHHBBI", hlen, irp, 0, 0, info, 1, 5, endpoint, transfer, len(data))
    if transfer == 2:
        head += bytes([stage])
    return head + data


def _pcapng(linktype: int, frames: list[bytes]) -> bytes:
    def block(kind: int, body: bytes) -> bytes:
        body += bytes(-len(body) % 4)
        size = len(body) + 12
        return struct.pack("<II", kind, size) + body + struct.pack("<I", size)

    out = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    out += block(1, struct.pack("<HHI", linktype, 0, 65535))
    for n, frame in enumerate(frames):
        out += block(6, struct.pack("<IIIII", 0, 0, n, len(frame), len(frame)) + frame)
    return out


def test_usbpcap_setup_with_data(tmp_path):
    frame = _usbpcap_frame(1, 0, 0, _set_report_setup(1) + FEATURE_PAYLOAD)
    path = tmp_path / "a.pcapng"
    path.write_bytes(_pcapng(capture.LINKTYPE_USBPCAP, [frame]))
    (report,) = capture.load(path)
    assert report.data == FEATURE_PAYLOAD
    assert report.interface == 1 and report.kind == "feature" and report.report_id == 0


def test_usbpcap_split_stages_and_interrupt(tmp_path):
    frames = [
        _usbpcap_frame(7, 0, 0, _set_report_setup(2, report_id=6)),
        _usbpcap_frame(7, 0, 1, b"\x06abc"),
        _usbpcap_frame(7, 1, 2, b""),  # status/completion, ignored
        _usbpcap_frame(8, 0, 0, b"\x01\x02", transfer=1, endpoint=0x02),
        _usbpcap_frame(9, 1, 0, b"\x09\x09", transfer=1, endpoint=0x81),  # device-to-host
    ]
    path = tmp_path / "b.pcapng"
    path.write_bytes(_pcapng(capture.LINKTYPE_USBPCAP, frames))
    reports = capture.load(path)
    assert [(r.data, r.interface, r.kind, r.report_id) for r in reports] == [
        (b"\x06abc", 2, "feature", 6),
        (b"\x01\x02", None, "interrupt", None),
        (b"\x09\x09", None, "input", None),
    ]


def test_usbmon_classic_pcap(tmp_path):
    setup = _set_report_setup(1)
    header = struct.pack("<QcBBBHbbqiiII", 1, b"S", 2, 0x00, 5, 1, 0, 0, 0, 0, 0, 64, 64) + setup
    header += bytes(64 - len(header))
    frame = header + FEATURE_PAYLOAD
    complete = struct.pack("<QcBBBHbb", 1, b"C", 2, 0x80, 5, 1, 1, 0) + bytes(56)
    blob = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, capture.LINKTYPE_USB_LINUX_MMAPPED)
    for ts, f in enumerate([frame, complete]):
        blob += struct.pack("<IIII", ts, 0, len(f), len(f)) + f
    path = tmp_path / "c.pcap"
    path.write_bytes(blob)
    (report,) = capture.load(path)
    assert report.data == FEATURE_PAYLOAD and report.interface == 1


def test_text_roundtrip_and_diff(tmp_path):
    reports = [
        capture.Report(b"\x07\x01", interface=1),
        capture.Report(b"\x07\x02", interface=2),
    ]
    path = tmp_path / "r.txt"
    path.write_text(capture.to_text(reports))
    loaded = capture.load(path)
    assert [(r.data, r.interface) for r in loaded] == [(b"\x07\x01", 1), (b"\x07\x02", 2)]
    other = [capture.Report(b"\x07\x01"), capture.Report(b"\x07\x05\x01")]
    assert capture.diff(loaded, other) == [(1, [(1, 0x02, 0x05), (2, 0x00, 0x01)])]


def test_usbmon_interrupt_in_and_out(tmp_path):
    def frame(ev: bytes, ep: int, data: bytes) -> bytes:
        head = struct.pack("<QcBBBHbbqiiII", 1, ev, 1, ep, 4, 1, 1, 0, 0, 0, 0, len(data), len(data))
        return head + bytes(64 - len(head)) + data

    request = bytes.fromhex("aa1038000000010000") + bytes(4087)
    reply = bytes.fromhex("5510300000000000") + bytes(56)
    frames = [frame(b"S", 0x02, request), frame(b"C", 0x02, b""), frame(b"S", 0x81, b""), frame(b"C", 0x81, reply)]
    blob = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, capture.LINKTYPE_USB_LINUX_MMAPPED)
    for ts, f in enumerate(frames):
        blob += struct.pack("<IIII", ts, 0, len(f), len(f)) + f
    path = tmp_path / "bind.pcap"
    path.write_bytes(blob)
    reports = capture.load(path)
    assert [(r.kind, r.data[:2]) for r in reports] == [("interrupt", b"\xaa\x10"), ("input", b"\x55\x10")]
    assert capture.outgoing(reports) == reports[:1]


def test_summary_counts_raw_usbmon_records(tmp_path):
    head = struct.pack("<QcBBBHbbqiiII", 1, b"S", 2, 0x80, 4, 1, 0, 0, 0, 0, 0, 0, 0)
    frame = head + bytes(64 - len(head))
    blob = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, capture.LINKTYPE_USB_LINUX_MMAPPED)
    blob += struct.pack("<IIII", 0, 0, len(frame), len(frame)) + frame
    path = tmp_path / "s.pcap"
    path.write_bytes(blob)
    assert capture.summary(path) == {"dev 4 ep 0x80 control S no-data": 1}

"""Tkinter configurator: lighting, per-key colours, key remapping and the screen."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import hidkeys, protocol
from . import profile as profiles
from .device import Keyboard
from .transport import DeviceError, Transport

UNIT = 46  # pixels per 1u key


class App:
    def __init__(self, root: tk.Tk, args) -> None:
        self.root = root
        self.args = args
        self.profile = profiles.load(args.profile)
        if args.vid is not None:
            self.profile.vendor_id = args.vid
        self.dry_run = tk.BooleanVar(value=args.dry_run)
        self.key_colors: dict[str, tuple[int, int, int]] = {}
        self.selected: set[str] = set()
        self.buttons: dict[str, int] = {}

        root.title(f"INFI75 configurator - {self.profile.name}")
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        notebook.add(self._lighting_tab(notebook), text="Lighting")
        notebook.add(self._keys_tab(notebook), text="Keys")
        notebook.add(self._screen_tab(notebook), text="Display")

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=8)
        ttk.Checkbutton(bottom, text="Dry run (log packets, do not send)", variable=self.dry_run).pack(side="left")
        if not self.profile.verified:
            ttk.Label(bottom, text="Profile unverified - see README", foreground="#b05000").pack(side="right")
        self.log = tk.Text(root, height=8, state="disabled", font=("TkFixedFont", 9))
        self.log.pack(fill="both", padx=8, pady=(4, 8))
        # Worker threads must not touch Tk; they post here and the UI thread drains it.
        self.events: queue.Queue = queue.Queue()
        self._drain_events()

    # ---------------------------------------------------------------- plumbing

    def _write_log(self, message: str) -> None:
        """Thread-safe: queue a log line for the UI thread."""
        self.events.put(("log", message))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", message + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                if kind == "error":
                    messagebox.showerror("INFI75", message)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _keyboard(self) -> Keyboard:
        transport = Transport(self.profile, self.args.pid, self.dry_run.get(), log=self._write_log)
        return Keyboard(self.profile, transport)

    def _run(self, label: str, action) -> None:
        """Run a device action off the UI thread and report the outcome."""
        keyboard = self._keyboard()  # reads Tk variables, so build it on the UI thread

        def work() -> None:
            try:
                action(keyboard)
                self._write_log(f"ok: {label}")
            except (DeviceError, ValueError, KeyError, OSError) as exc:
                self.events.put(("error", f"error: {label}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- lighting

    def _lighting_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        self.mode = tk.StringVar(value="static")
        self.speed = tk.IntVar(value=3)
        self.brightness = tk.IntVar(value=4)
        self.rainbow = tk.BooleanVar(value=False)
        self.direction = tk.StringVar(value="right")
        self.color = (255, 255, 255)

        rows = [
            ("Effect", ttk.Combobox(frame, textvariable=self.mode, state="readonly",
                                    values=[m.name.lower() for m in protocol.Mode])),
            ("Speed", tk.Scale(frame, variable=self.speed, from_=0, to=5, orient="horizontal")),
            ("Brightness", tk.Scale(frame, variable=self.brightness, from_=0, to=4, orient="horizontal")),
            ("Direction", ttk.Combobox(frame, textvariable=self.direction, state="readonly",
                                       values=[d.name.lower() for d in protocol.Direction])),
        ]
        for n, (label, widget) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=n, column=0, sticky="w", pady=3)
            widget.grid(row=n, column=1, sticky="ew", pady=3)
        self.swatch = tk.Button(frame, text="Colour", width=12, bg="#ffffff", command=self._pick_global_color)
        self.swatch.grid(row=len(rows), column=1, sticky="w", pady=3)
        ttk.Checkbutton(frame, text="Rainbow (ignore colour)", variable=self.rainbow).grid(
            row=len(rows) + 1, column=1, sticky="w")
        ttk.Button(frame, text="Apply lighting", command=self._apply_lighting).grid(
            row=len(rows) + 2, column=1, sticky="w", pady=10)
        frame.columnconfigure(1, weight=1)
        return frame

    def _pick_global_color(self) -> None:
        rgb, hex_color = colorchooser.askcolor(color=_hex(self.color), parent=self.root)
        if rgb:
            self.color = tuple(int(c) for c in rgb)
            self.swatch.configure(bg=hex_color)

    def _apply_lighting(self) -> None:
        settings = protocol.Lighting(
            mode=protocol.Mode[self.mode.get().upper()],
            color=self.color,
            speed=self.speed.get(),
            brightness=self.brightness.get(),
            rainbow=self.rainbow.get(),
            direction=protocol.Direction[self.direction.get().upper()],
        )
        self._run("set lighting", lambda kb: kb.set_lighting(settings))

    # -------------------------------------------------------------------- keys

    def _keys_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        width = max((k.x + k.w for k in self.profile.keys), default=16) * UNIT + 8
        rows = max((k.row for k in self.profile.keys), default=5) + 1
        self.canvas = tk.Canvas(frame, width=width, height=rows * UNIT + 8, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack()
        for key in self.profile.keys:
            x0, y0 = 4 + key.x * UNIT, 4 + key.row * UNIT
            rect = self.canvas.create_rectangle(x0 + 2, y0 + 2, x0 + key.w * UNIT - 2, y0 + UNIT - 2,
                                                fill="#000000", outline="#888888", width=2)
            label = self.canvas.create_text((x0 + x0 + key.w * UNIT) / 2, y0 + UNIT / 2,
                                            text=_short(key.name), fill="#dddddd", font=("TkDefaultFont", 8))
            self.buttons[key.name] = rect
            for item in (rect, label):
                self.canvas.tag_bind(item, "<Button-1>", lambda _e, n=key.name: self._toggle(n))

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=8)
        ttk.Label(controls, text="Click keys to select.").pack(side="left")
        ttk.Button(controls, text="Clear selection", command=self._clear_selection).pack(side="left", padx=4)
        ttk.Button(controls, text="Colour selected...", command=self._color_selected).pack(side="left", padx=4)
        ttk.Button(controls, text="Send key colours", command=self._send_key_colors).pack(side="left", padx=4)

        remap = ttk.Frame(frame)
        remap.pack(fill="x")
        ttk.Label(remap, text="Remap selected key to:").pack(side="left")
        self.remap_target = tk.StringVar(value="esc")
        ttk.Combobox(remap, textvariable=self.remap_target, values=hidkeys.names(), width=16).pack(side="left", padx=4)
        ttk.Button(remap, text="Remap", command=self._remap_selected).pack(side="left", padx=4)
        return frame

    def _toggle(self, name: str) -> None:
        if name in self.selected:
            self.selected.discard(name)
        else:
            self.selected.add(name)
        self.canvas.itemconfigure(self.buttons[name], outline="#ffcc00" if name in self.selected else "#888888")

    def _clear_selection(self) -> None:
        for name in list(self.selected):
            self._toggle(name)

    def _color_selected(self) -> None:
        if not self.selected:
            messagebox.showinfo("INFI75", "Select one or more keys first.")
            return
        rgb, hex_color = colorchooser.askcolor(parent=self.root)
        if not rgb:
            return
        for name in self.selected:
            self.key_colors[name] = tuple(int(c) for c in rgb)
            self.canvas.itemconfigure(self.buttons[name], fill=hex_color)

    def _send_key_colors(self) -> None:
        colors = dict(self.key_colors)
        self._run("set key colours", lambda kb: kb.set_key_colors(colors))

    def _remap_selected(self) -> None:
        if len(self.selected) != 1:
            messagebox.showinfo("INFI75", "Select exactly one key to remap.")
            return
        (name,) = self.selected
        try:
            hid_code = hidkeys.code(self.remap_target.get())
        except KeyError as exc:
            messagebox.showerror("INFI75", str(exc.args[0]))
            return
        self._run(f"remap {name} -> {hidkeys.name(hid_code)}", lambda kb: kb.remap(name, hid_code))

    # ------------------------------------------------------------------ screen

    def _screen_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        self.image_path = tk.StringVar()
        self.width = tk.StringVar(value=str(self.profile.screen_width or ""))
        self.height = tk.StringVar(value=str(self.profile.screen_height or ""))
        ttk.Label(frame, text="Image").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.image_path, width=50).grid(row=0, column=1, sticky="ew")
        ttk.Button(frame, text="Browse...", command=self._browse).grid(row=0, column=2, padx=4)
        size = ttk.Frame(frame)
        size.grid(row=1, column=1, sticky="w", pady=6)
        ttk.Label(size, text="Width").pack(side="left")
        ttk.Entry(size, textvariable=self.width, width=6).pack(side="left", padx=4)
        ttk.Label(size, text="Height").pack(side="left")
        ttk.Entry(size, textvariable=self.height, width=6).pack(side="left", padx=4)
        ttk.Button(frame, text="Upload image", command=self._upload).grid(row=2, column=1, sticky="w")
        ttk.Button(frame, text="Sync clock to this computer", command=lambda: self._run(
            "sync time", lambda kb: kb.sync_time())).grid(row=3, column=1, sticky="w", pady=12)
        frame.columnconfigure(1, weight=1)
        return frame

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All", "*")])
        if path:
            self.image_path.set(path)

    def _upload(self) -> None:
        path = self.image_path.get()
        try:
            width = int(self.width.get()) if self.width.get() else None
            height = int(self.height.get()) if self.height.get() else None
        except ValueError:
            messagebox.showerror("INFI75", "Width and height must be whole numbers.")
            return
        if not path:
            messagebox.showinfo("INFI75", "Choose an image first.")
            return
        self._run("upload image", lambda kb: kb.upload_image(path, width, height))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _short(name: str) -> str:
    return {"BACKSPACE": "Bksp", "BACKSLASH": "\\", "LBRACKET": "[", "RBRACKET": "]", "SEMICOLON": ";",
            "QUOTE": "'", "COMMA": ",", "DOT": ".", "SLASH": "/", "GRAVE": "`", "MINUS": "-", "EQUAL": "=",
            "SPACE": "", "LSHIFT": "Shift", "RSHIFT": "Shift", "LCTRL": "Ctrl", "RCTRL": "Ctrl",
            "LALT": "Alt", "RALT": "Alt", "LWIN": "Win"}.get(
        name, name if len(name) <= 2 or name[1:].isdigit() else name.title())


def run(args) -> int:
    root = tk.Tk()
    App(root, args)
    root.mainloop()
    return 0

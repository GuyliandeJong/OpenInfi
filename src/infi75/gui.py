"""Tkinter configurator for HFD-protocol keyboards (the INFI75)."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import hfd, hidkeys
from . import profile as profiles
from .board import InfiBoard
from .transport import DeviceError

UNIT = 46  # pixels per 1u key


class App:
    def __init__(self, root: tk.Tk, args) -> None:
        self.root = root
        self.args = args
        self.profile = profiles.load(args.profile)
        if self.profile.protocol != "hfd":
            raise DeviceError("the GUI supports HFD-protocol keyboards (the INFI75); use the CLI for others")
        self.dry_run = tk.BooleanVar(value=args.dry_run)
        self.key_colors: dict[str, tuple[int, int, int]] = {}
        self.selected: set[str] = set()
        self.rects: dict[str, int] = {}
        self.labels: dict[str, int] = {}

        root.title(f"INFI75 configurator - {self.profile.name}")
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        notebook.add(self._lighting_tab(notebook), text="Lighting")
        notebook.add(self._keys_tab(notebook), text="Keys")
        notebook.add(self._screen_tab(notebook), text="Display")

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", padx=8)
        ttk.Checkbutton(bottom, text="Dry run (log packets, do not send)", variable=self.dry_run).pack(side="left")
        self.log = tk.Text(root, height=7, state="disabled", font=("TkFixedFont", 9))
        self.log.pack(fill="both", padx=8, pady=(4, 8))
        # Worker threads must not touch Tk; they post here and the UI thread drains it.
        self.events: queue.Queue = queue.Queue()
        self._drain_events()
        self._show_remaps()

    # ---------------------------------------------------------------- plumbing

    def _write_log(self, message: str) -> None:
        """Thread-safe: queue a log line for the UI thread."""
        self.events.put(("log", message))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "call":
                    payload()
                    continue
                self.log.configure(state="normal")
                self.log.insert("end", payload + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                if kind == "error":
                    messagebox.showerror("INFI75", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _board(self) -> InfiBoard:
        return InfiBoard(self.profile, self.args.vid, self.args.pid, dry_run=self.dry_run.get(),
                         log=self._write_log)

    def _run(self, label: str, action, then=None) -> None:
        """Run a device action off the UI thread and report the outcome."""
        board = self._board()  # reads Tk variables, so build it on the UI thread

        def work() -> None:
            try:
                result = action(board)
                self._write_log(f"ok: {label}")
                if then:
                    self.events.put(("call", lambda: then(result)))
            except (DeviceError, ValueError, KeyError, OSError, RuntimeError) as exc:
                self.events.put(("error", f"error: {label}: {exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- lighting

    def _lighting_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        self.effect = tk.StringVar(value="static")
        self.speed = tk.IntVar(value=3)
        self.brightness = tk.IntVar(value=5)
        self.rainbow = tk.BooleanVar(value=False)
        self.direction = tk.StringVar(value="right")
        self.color = (255, 255, 255)

        effects = ttk.Combobox(frame, textvariable=self.effect, state="readonly", values=InfiBoard.effects())
        effects.bind("<<ComboboxSelected>>", lambda _e: self._describe_effect())
        rows = [
            ("Effect", effects),
            ("Brightness", tk.Scale(frame, variable=self.brightness, from_=0, to=hfd.MAX_LEVEL, orient="horizontal")),
            ("Speed", tk.Scale(frame, variable=self.speed, from_=0, to=hfd.MAX_LEVEL, orient="horizontal")),
            ("Direction", ttk.Combobox(frame, textvariable=self.direction, state="readonly",
                                       values=list(hfd.DIRECTIONS))),
        ]
        for n, (label, widget) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=n, column=0, sticky="w", pady=3)
            widget.grid(row=n, column=1, sticky="ew", pady=3)
        self.effect_note = ttk.Label(frame, foreground="#666666")
        self.effect_note.grid(row=0, column=2, sticky="w", padx=8)
        self.swatch = tk.Button(frame, text="Colour", width=12, bg="#ffffff", command=self._pick_global_color)
        self.swatch.grid(row=len(rows), column=1, sticky="w", pady=3)
        ttk.Checkbutton(frame, text="Rainbow (ignore colour)", variable=self.rainbow).grid(
            row=len(rows) + 1, column=1, sticky="w")
        ttk.Button(frame, text="Apply lighting", command=self._apply_lighting).grid(
            row=len(rows) + 2, column=1, sticky="w", pady=10)
        frame.columnconfigure(1, weight=1)
        self._describe_effect()
        return frame

    def _describe_effect(self) -> None:
        name = self.effect.get()
        note = "lights off" if name == "off" else hfd.EFFECTS.get(name, (0, ""))[1]
        self.effect_note.configure(text=note)

    def _pick_global_color(self) -> None:
        rgb, hex_color = colorchooser.askcolor(color=_hex(self.color), parent=self.root)
        if rgb:
            self.color = tuple(int(c) for c in rgb)
            self.swatch.configure(bg=hex_color)

    def _apply_lighting(self) -> None:
        effect, color, brightness = self.effect.get(), self.color, self.brightness.get()
        speed, rainbow, direction = self.speed.get(), self.rainbow.get(), self.direction.get()
        self._run(f"lighting {effect}",
                  lambda b: b.set_lighting(effect, color, brightness, speed, rainbow, direction))

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
            self.rects[key.name], self.labels[key.name] = rect, label
            for item in (rect, label):
                self.canvas.tag_bind(item, "<Button-1>", lambda _e, n=key.name: self._toggle(n))

        colours = ttk.LabelFrame(frame, text="Per-key colours", padding=6)
        colours.pack(fill="x", pady=(8, 4))
        ttk.Button(colours, text="Colour selected...", command=self._color_selected).pack(side="left", padx=2)
        ttk.Button(colours, text="Select all", command=self._select_all).pack(side="left", padx=2)
        ttk.Button(colours, text="Clear selection", command=self._clear_selection).pack(side="left", padx=2)
        ttk.Button(colours, text="Clear colours", command=self._clear_colors).pack(side="left", padx=2)
        ttk.Button(colours, text="Apply colours", command=self._send_key_colors).pack(side="right", padx=2)

        remap = ttk.LabelFrame(frame, text="Remap (selected key)", padding=6)
        remap.pack(fill="x")
        self.remap_target = tk.StringVar(value="esc")
        targets = sorted(hfd.MEDIA) + [n for n in hidkeys.names() if n != "none"] + ["default"]
        ttk.Combobox(remap, textvariable=self.remap_target, values=targets, width=16).pack(side="left", padx=2)
        ttk.Label(remap, text="(also ctrl+c style combinations)").pack(side="left", padx=4)
        ttk.Button(remap, text="Remap", command=self._remap_selected).pack(side="left", padx=2)
        ttk.Button(remap, text="Reset all remaps", command=self._reset_remaps).pack(side="right", padx=2)
        self.remap_list = ttk.Label(frame, foreground="#666666", wraplength=int(width))
        self.remap_list.pack(fill="x", pady=(4, 0))
        return frame

    def _toggle(self, name: str) -> None:
        self.selected.symmetric_difference_update({name})
        self.canvas.itemconfigure(self.rects[name], outline="#ffcc00" if name in self.selected else "#888888")

    def _select_all(self) -> None:
        for key in self.profile.keys:
            if key.name not in self.selected:
                self._toggle(key.name)

    def _clear_selection(self) -> None:
        for name in list(self.selected):
            self._toggle(name)

    def _clear_colors(self) -> None:
        self.key_colors.clear()
        for name, rect in self.rects.items():
            self.canvas.itemconfigure(rect, fill="#000000")

    def _color_selected(self) -> None:
        if not self.selected:
            messagebox.showinfo("INFI75", "Click one or more keys first.")
            return
        rgb, hex_color = colorchooser.askcolor(parent=self.root)
        if not rgb:
            return
        for name in self.selected:
            self.key_colors[name] = tuple(int(c) for c in rgb)
            self.canvas.itemconfigure(self.rects[name], fill=hex_color)

    def _send_key_colors(self) -> None:
        colors, brightness = dict(self.key_colors), self.brightness.get()
        self._run("apply key colours", lambda b: b.set_key_colors(colors, brightness=brightness))

    def _remap_selected(self) -> None:
        if len(self.selected) != 1:
            messagebox.showinfo("INFI75", "Select exactly one key to remap.")
            return
        (name,) = self.selected
        target = self.remap_target.get()
        try:
            hfd.key_entry(target)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("INFI75", str(exc))
            return
        self._run(f"remap {name} -> {target}", lambda b: b.remap(name, target), then=self._show_remaps)

    def _reset_remaps(self) -> None:
        if messagebox.askyesno("INFI75", "Restore every key to its default?"):
            self._run("reset remaps", lambda b: b.reset_remaps(), then=self._show_remaps)

    def _show_remaps(self, state=None) -> None:
        state = state if state is not None else self._board().remaps()
        text = ", ".join(f"{k} -> {v}" for k, v in sorted(state.items())) or "none"
        self.remap_list.configure(text=f"Active remaps: {text}")

    # ------------------------------------------------------------------ screen

    def _screen_tab(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        self.image_path = tk.StringVar()
        self.fit = tk.StringVar(value="crop")
        ttk.Label(frame, text=f"Image or GIF ({hfd.SCREEN_WIDTH}x{hfd.SCREEN_HEIGHT})").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.image_path, width=50).grid(row=0, column=1, sticky="ew")
        ttk.Button(frame, text="Browse...", command=self._browse).grid(row=0, column=2, padx=4)
        ttk.Label(frame, text="Fit").grid(row=1, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.fit, state="readonly", values=["crop", "stretch", "pad"],
                     width=10).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Button(frame, text="Upload", command=self._upload).grid(row=2, column=1, sticky="w")
        self.progress = ttk.Progressbar(frame, length=300)
        self.progress.grid(row=3, column=1, sticky="w", pady=6)
        ttk.Button(frame, text="Sync clock to this computer", command=lambda: self._run(
            "sync time", lambda b: b.sync_time())).grid(row=4, column=1, sticky="w", pady=12)
        frame.columnconfigure(1, weight=1)
        return frame

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All", "*")])
        if path:
            self.image_path.set(path)

    def _upload(self) -> None:
        path, fit = self.image_path.get(), self.fit.get()
        if not path:
            messagebox.showinfo("INFI75", "Choose an image first.")
            return

        def progress(n: int, total: int) -> None:
            self.events.put(("call", lambda: self.progress.configure(maximum=total, value=n)))

        self._run("upload image", lambda b: b.upload_image(path, fit=fit, progress=progress))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _short(name: str) -> str:
    return {"BACKSPACE": "Bksp", "BACKSLASH": "\\", "LBRACKET": "[", "RBRACKET": "]", "SEMICOLON": ";",
            "QUOTE": "'", "COMMA": ",", "DOT": ".", "SLASH": "/", "GRAVE": "`", "MINUS": "-", "EQUAL": "=",
            "SPACE": "", "LSHIFT": "Shift", "RSHIFT": "Shift", "LCTRL": "Ctrl", "RCTRL": "Ctrl",
            "LALT": "Alt", "RALT": "Alt", "LWIN": "Win", "PGUP": "PgUp", "PGDN": "PgDn", "ENTER": "Enter",
            "CAPS": "Caps", "TAB": "Tab", "LEFT": "\u2190", "RIGHT": "\u2192", "UP": "\u2191", "DOWN": "\u2193",
            }.get(name, name if len(name) <= 2 or name[1:].isdigit() else name.title())


def run(args) -> int:
    root = tk.Tk()
    App(root, args)
    root.mainloop()
    return 0

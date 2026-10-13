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
PREVIEW_SCALE = 1.5

PALETTE = [
    ("#ff0000", "red"), ("#ff6000", "orange"), ("#ffd000", "yellow"), ("#00ff00", "green"),
    ("#00ffff", "cyan"), ("#0040ff", "blue"), ("#8000ff", "purple"), ("#ff00c0", "pink"),
    ("#ffffff", "white"), ("#000000", "off"),
]

COLORS = {
    "bg": "#1e1f22", "panel": "#2b2d31", "field": "#383a40", "fg": "#e6e6e6", "muted": "#9aa0a6",
    "accent": "#4f8cff", "key": "#121316", "key_outline": "#5c5f66", "selected": "#ffcc00",
    "ok": "#3fb950", "warn": "#d29922", "bad": "#f85149",
}


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _text_on(rgb) -> str:
    r, g, b = rgb
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#e6e6e6"


def _short(name: str) -> str:
    return {"BACKSPACE": "Bksp", "BACKSLASH": "\\", "LBRACKET": "[", "RBRACKET": "]", "SEMICOLON": ";",
            "QUOTE": "'", "COMMA": ",", "DOT": ".", "SLASH": "/", "GRAVE": "`", "MINUS": "-", "EQUAL": "=",
            "SPACE": "Space", "LSHIFT": "Shift", "RSHIFT": "Shift", "LCTRL": "Ctrl", "RCTRL": "Ctrl",
            "LALT": "Alt", "RALT": "Alt", "LWIN": "Win", "PGUP": "PgUp", "PGDN": "PgDn", "ENTER": "Enter",
            "CAPS": "Caps", "TAB": "Tab", "LEFT": "←", "RIGHT": "→", "UP": "↑",
            "DOWN": "↓", "FN": "Fn", "ESC": "Esc",
            }.get(name, name if len(name) <= 3 else name.title())


class App:
    def __init__(self, root: tk.Tk, args) -> None:
        self.root = root
        self.args = args
        self.profile = profiles.load(args.profile)
        if self.profile.protocol != "hfd":
            raise DeviceError("the GUI supports HFD-protocol keyboards (the INFI75); use the CLI for others")
        self.dry_run = tk.BooleanVar(value=args.dry_run)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.action_buttons: list[ttk.Button] = []

        board = self._board()
        self.key_colors, default = board.saved_colors()
        self.default_color = tuple(default)
        self.remaps = board.remaps()
        self.selected: set[str] = set()
        self.rects: dict[str, int] = {}
        self.labels: dict[str, int] = {}
        self.sublabels: dict[str, int] = {}

        self._style()
        root.title("INFI75 configurator")
        root.configure(bg=COLORS["bg"])
        root.minsize(900, 700)

        self._header()
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        notebook.add(self._lighting_tab(notebook), text="  Lighting  ")
        notebook.add(self._keys_tab(notebook), text="  Keys  ")
        notebook.add(self._screen_tab(notebook), text="  Display  ")
        self._footer()

        self._drain_events()
        self._refresh_status()
        self._redraw_keys()

    # ------------------------------------------------------------------ style

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        c = COLORS
        style.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                        bordercolor=c["panel"], lightcolor=c["panel"], darkcolor=c["panel"],
                        troughcolor=c["field"], focuscolor=c["accent"], selectbackground=c["accent"],
                        selectforeground="#ffffff", insertcolor=c["fg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("Panel.TFrame", background=c["panel"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Panel.TLabel", background=c["panel"])
        style.configure("Muted.TLabel", foreground=c["muted"])
        style.configure("PanelMuted.TLabel", background=c["panel"], foreground=c["muted"])
        style.configure("Title.TLabel", font=("TkDefaultFont", 14, "bold"))
        style.configure("Section.TLabel", background=c["panel"], font=("TkDefaultFont", 10, "bold"))
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=c["panel"], foreground=c["muted"], padding=(10, 6))
        style.map("TNotebook.Tab", background=[("selected", c["field"])], foreground=[("selected", c["fg"])])
        style.configure("TButton", background=c["field"], foreground=c["fg"], padding=(10, 5), borderwidth=0)
        style.map("TButton", background=[("active", "#4a4d55"), ("disabled", c["panel"])],
                  foreground=[("disabled", c["muted"])])
        style.configure("Accent.TButton", background=c["accent"], foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#3a73e0"), ("disabled", c["panel"])])
        style.configure("TCheckbutton", background=c["bg"])
        style.configure("Panel.TCheckbutton", background=c["panel"])
        style.map("TCheckbutton", background=[("active", c["bg"])])
        style.map("Panel.TCheckbutton", background=[("active", c["panel"])])
        style.configure("Panel.TRadiobutton", background=c["panel"])
        style.map("Panel.TRadiobutton", background=[("active", c["panel"])])
        style.configure("TCombobox", arrowcolor=c["fg"], background=c["field"])
        style.configure("Horizontal.TScale", background=c["accent"], troughcolor=c["field"],
                        bordercolor=c["panel"], lightcolor=c["accent"], darkcolor=c["accent"],
                        sliderthickness=18, sliderlength=22)
        style.map("Horizontal.TScale", background=[("active", "#6fa0ff")])
        style.configure("TProgressbar", background=c["accent"], troughcolor=c["field"])
        self.root.option_add("*TCombobox*Listbox.background", c["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["fg"])

    def _panel(self, parent, title: str | None = None) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        if title:
            ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        return frame

    def _button(self, parent, text: str, command, accent: bool = False, device: bool = True) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
        if device:
            self.action_buttons.append(button)
        return button

    # ------------------------------------------------------------ header/footer

    def _header(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="INFI75", style="Title.TLabel").pack(side="left")
        ttk.Label(bar, text=self.profile.name, style="Muted.TLabel").pack(side="left", padx=10)
        ttk.Button(bar, text="Refresh", command=self._refresh_status).pack(side="right")
        self.status_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.status_label.pack(side="right", padx=8)
        self.status_dot = tk.Canvas(bar, width=12, height=12, bg=COLORS["bg"], highlightthickness=0)
        self.status_dot.pack(side="right")

    def _footer(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        bar.pack(fill="x")
        ttk.Checkbutton(bar, text="Dry run (log packets, send nothing)", variable=self.dry_run,
                        command=self._refresh_status).pack(side="left")
        self.show_log = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show log", variable=self.show_log, command=self._toggle_log).pack(side="right")
        self.busy_label = ttk.Label(bar, text="", style="Muted.TLabel")
        self.busy_label.pack(side="right", padx=10)
        self.log = tk.Text(self.root, height=8, state="disabled", font=("TkFixedFont", 9),
                           bg=COLORS["panel"], fg=COLORS["muted"], relief="flat", insertbackground=COLORS["fg"])

    def _toggle_log(self) -> None:
        if self.show_log.get():
            self.log.pack(fill="both", padx=10, pady=(0, 10))
        else:
            self.log.pack_forget()

    def _refresh_status(self) -> None:
        if self.dry_run.get():
            state, text, color = "dry", "Dry run: nothing is sent", COLORS["warn"]
        else:
            state = self._board().connection()
            text, color = {
                "usb": ("Connected by USB", COLORS["ok"]),
                "bluetooth": ("Bluetooth only: connect the cable (wired mode) to configure", COLORS["warn"]),
                "none": ("Keyboard not found", COLORS["bad"]),
            }[state]
        self.status_label.configure(text=text)
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 11, 11, fill=color, outline=color)
        self.connected = state in ("usb", "dry")
        self._update_buttons()

    def _update_buttons(self) -> None:
        enabled = self.connected and not self.busy
        for button in self.action_buttons:
            button.state(["!disabled"] if enabled else ["disabled"])

    # -------------------------------------------------------------- plumbing

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

    def _set_busy(self, label: str | None) -> None:
        self.busy = label is not None
        self.busy_label.configure(text=f"{label}..." if label else "")
        self._update_buttons()

    def _run(self, label: str, action, then=None) -> None:
        """Run a device action off the UI thread; one at a time."""
        if self.busy:
            return
        board = self._board()  # reads Tk variables, so build it on the UI thread
        self._set_busy(label)

        def work() -> None:
            try:
                result = action(board)
                self._write_log(f"ok: {label}")
                if then:
                    self.events.put(("call", lambda: then(result)))
            except Exception as exc:  # device, protocol or I/O failure: report, keep the UI alive
                self.events.put(("error", f"{label} failed: {exc}"))
            finally:
                self.events.put(("call", lambda: self._set_busy(None)))

        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- lighting

    def _lighting_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        self.effect = tk.StringVar(value="static")
        self.speed = tk.IntVar(value=3)
        self.brightness = tk.IntVar(value=5)
        self.rainbow = tk.BooleanVar(value=False)
        self.direction = tk.StringVar(value="right")
        self.light_color = (255, 255, 255)
        self.live = tk.BooleanVar(value=False)
        self._live_job: str | None = None

        left = self._panel(tab, "Effect")
        left.pack(side="left", fill="y", padx=(0, 10))
        self.effect_list = tk.Listbox(left, height=21, width=18, exportselection=False, activestyle="none",
                                      bg=COLORS["field"], fg=COLORS["fg"], relief="flat",
                                      selectbackground=COLORS["accent"], highlightthickness=0)
        for name in InfiBoard.effects():
            self.effect_list.insert("end", name)
        self.effect_list.selection_set(InfiBoard.effects().index("static"))
        self.effect_list.bind("<<ListboxSelect>>", lambda _e: self._on_effect())
        self.effect_list.pack(fill="y", expand=True)

        right = self._panel(tab)
        right.pack(side="left", fill="both", expand=True)
        self.effect_title = ttk.Label(right, text="", style="Section.TLabel")
        self.effect_title.pack(anchor="w")
        self.effect_note = ttk.Label(right, text="", style="PanelMuted.TLabel")
        self.effect_note.pack(anchor="w", pady=(0, 12))

        ttk.Label(right, text="Colour", style="Panel.TLabel").pack(anchor="w")
        swatches = ttk.Frame(right, style="Panel.TFrame")
        swatches.pack(anchor="w", pady=4)
        self.light_swatch = tk.Label(swatches, width=6, height=2, bg="#ffffff", relief="flat")
        self.light_swatch.pack(side="left", padx=(0, 10))
        for hex_color, name in PALETTE[:-1]:
            tk.Button(swatches, bg=hex_color, activebackground=hex_color, width=2, relief="flat", bd=0,
                      command=lambda h=hex_color: self._set_light_color(_rgb(h))).pack(side="left", padx=2)
        ttk.Button(swatches, text="Custom...", command=self._pick_light_color).pack(side="left", padx=8)
        ttk.Checkbutton(right, text="Rainbow (multi-colour instead of the colour above)", variable=self.rainbow,
                        style="Panel.TCheckbutton", command=self._on_change).pack(anchor="w", pady=(4, 12))

        for label, var in (("Brightness", self.brightness), ("Speed", self.speed)):
            row = ttk.Frame(right, style="Panel.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, width=11, style="Panel.TLabel").pack(side="left")
            value = ttk.Label(row, text=str(var.get()), width=2, style="Panel.TLabel")
            value.pack(side="right")
            ttk.Scale(row, from_=0, to=hfd.MAX_LEVEL, variable=var, orient="horizontal",
                      command=lambda v, var=var, value=value: self._snap(var, value)).pack(
                side="left", fill="x", expand=True)

        row = ttk.Frame(right, style="Panel.TFrame")
        row.pack(fill="x", pady=(8, 4))
        ttk.Label(row, text="Direction", width=11, style="Panel.TLabel").pack(side="left")
        for name in ("left", "right", "up", "down"):
            ttk.Radiobutton(row, text=name, value=name, variable=self.direction, style="Panel.TRadiobutton",
                            command=self._on_change).pack(side="left", padx=4)

        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.pack(fill="x", side="bottom", pady=(16, 0))
        self._button(actions, "Apply lighting", self._apply_lighting, accent=True).pack(side="left")
        self._button(actions, "Lights off", lambda: self._apply_lighting("off")).pack(side="left", padx=8)
        ttk.Checkbutton(actions, text="Apply on change", variable=self.live,
                        style="Panel.TCheckbutton").pack(side="right")
        self._on_effect()
        return tab

    def _snap(self, var: tk.IntVar, label: ttk.Label) -> None:
        value = round(float(var.get()))
        var.set(value)
        label.configure(text=str(value))
        self._on_change()

    def _on_effect(self) -> None:
        selection = self.effect_list.curselection()
        name = self.effect_list.get(selection[0]) if selection else "static"
        self.effect.set(name)
        self.effect_title.configure(text=name)
        note = "All key lights off." if name == "off" else hfd.EFFECTS[name][1].capitalize() + "."
        self.effect_note.configure(text=note)
        self._on_change()

    def _set_light_color(self, rgb) -> None:
        self.light_color = tuple(rgb)
        self.light_swatch.configure(bg=_hex(rgb))
        self.rainbow.set(False)
        self._on_change()

    def _pick_light_color(self) -> None:
        rgb, _hex_color = colorchooser.askcolor(color=_hex(self.light_color), parent=self.root)
        if rgb:
            self._set_light_color(tuple(int(c) for c in rgb))

    def _on_change(self) -> None:
        if not getattr(self, "live", None) or not self.live.get():
            return
        if self._live_job:
            self.root.after_cancel(self._live_job)
        self._live_job = self.root.after(400, self._apply_lighting)

    def _apply_lighting(self, effect: str | None = None) -> None:
        self._live_job = None
        effect = effect or self.effect.get()
        color, brightness = self.light_color, self.brightness.get()
        speed, rainbow, direction = self.speed.get(), self.rainbow.get(), self.direction.get()
        self._run(f"Lighting: {effect}",
                  lambda b: b.set_lighting(effect, color, brightness, speed, rainbow, direction))

    # ------------------------------------------------------------------ keys

    def _keys_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        width = max((k.x + k.w for k in self.profile.keys), default=16) * UNIT + 12
        rows = max((k.row for k in self.profile.keys), default=5) + 1
        board_panel = self._panel(tab)
        board_panel.pack(fill="x")
        self.canvas = tk.Canvas(board_panel, width=width, height=rows * UNIT + 12, bg=COLORS["panel"],
                                highlightthickness=0)
        self.canvas.pack()
        for key in self.profile.keys:
            x0, y0 = 6 + key.x * UNIT, 6 + key.row * UNIT
            x1, y1 = x0 + key.w * UNIT - 4, y0 + UNIT - 4
            self.rects[key.name] = self.canvas.create_rectangle(
                x0, y0, x1, y1, fill=COLORS["key"], outline=COLORS["key_outline"], width=2, tags=("key",))
            self.labels[key.name] = self.canvas.create_text(
                (x0 + x1) / 2, (y0 + y1) / 2 - 5, text=_short(key.name), fill=COLORS["fg"],
                font=("TkDefaultFont", 9, "bold"), tags=("key",))
            self.sublabels[key.name] = self.canvas.create_text(
                (x0 + x1) / 2, y1 - 9, text="", fill=COLORS["accent"], font=("TkDefaultFont", 7), tags=("key",))
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self._drag_origin = None
        self._drag_box = None
        ttk.Label(board_panel, text="Click a key to select it, drag to select several, Shift adds to the "
                                    "selection. Remapped keys show their new function.",
                  style="PanelMuted.TLabel").pack(anchor="w", pady=(6, 0))

        selection = ttk.Frame(tab, padding=(0, 8))
        selection.pack(fill="x")
        ttk.Button(selection, text="Select all", command=self._select_all).pack(side="left")
        ttk.Button(selection, text="Clear selection", command=self._clear_selection).pack(side="left", padx=6)
        self.selection_label = ttk.Label(selection, text="", style="Muted.TLabel")
        self.selection_label.pack(side="left", padx=10)

        lower = ttk.Frame(tab)
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=3, uniform="lower")
        lower.columnconfigure(1, weight=2, uniform="lower")
        lower.rowconfigure(0, weight=1)
        colours = self._panel(lower, "Colours")
        colours.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        palette = ttk.Frame(colours, style="Panel.TFrame")
        palette.pack(anchor="w")
        for hex_color, name in PALETTE:
            tk.Button(palette, bg=hex_color, activebackground=hex_color, width=2, relief="flat", bd=0,
                      command=lambda h=hex_color: self._paint(_rgb(h))).pack(side="left", padx=2)
        ttk.Label(colours, text="Pick a colour to paint the selected keys.", style="PanelMuted.TLabel").pack(
            anchor="w", pady=(6, 8))
        row = ttk.Frame(colours, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Custom colour...", command=self._paint_custom).pack(side="left", padx=(0, 12))
        ttk.Label(row, text="Other keys:", style="Panel.TLabel").pack(side="left")
        self.default_swatch = tk.Button(row, width=2, relief="flat", bd=0, bg=_hex(self.default_color),
                                        command=self._pick_default)
        self.default_swatch.pack(side="left", padx=6)
        ttk.Button(row, text="Clear painted keys", command=self._clear_colors).pack(side="left", padx=6)
        actions = ttk.Frame(colours, style="Panel.TFrame")
        actions.pack(fill="x", side="bottom", pady=(12, 0))
        self._button(actions, "Apply colours", self._send_key_colors, accent=True).pack(side="left")

        remap = self._panel(lower, "Remap")
        remap.grid(row=0, column=1, sticky="nsew")
        self.remap_target = tk.StringVar(value="esc")
        targets = ([f"{name} (media)" for name in sorted(hfd.MEDIA)]
                   + [n for n in hidkeys.names() if n != "none"])
        ttk.Combobox(remap, textvariable=self.remap_target, values=targets).pack(fill="x")
        ttk.Label(remap, text="Key name, media key, or a combination such as ctrl+c.",
                  style="PanelMuted.TLabel", wraplength=340).pack(anchor="w", pady=(4, 8))
        self._button(remap, "Remap selected key", self._remap_selected, accent=True).pack(anchor="w")
        buttons = ttk.Frame(remap, style="Panel.TFrame")
        buttons.pack(anchor="w", pady=(6, 0))
        self._button(buttons, "Restore selected", self._restore_selected).pack(side="left")
        self._button(buttons, "Reset all", self._reset_remaps).pack(side="left", padx=6)
        self.remap_list = ttk.Label(remap, text="", style="PanelMuted.TLabel", wraplength=340, justify="left")
        self.remap_list.pack(anchor="w", pady=(10, 0))
        return tab

    def _key_at(self, x: float, y: float) -> str | None:
        for item in self.canvas.find_overlapping(x, y, x, y):
            for name, rect in self.rects.items():
                if item in (rect, self.labels[name], self.sublabels[name]):
                    return name
        return None

    def _drag_start(self, event) -> None:
        self._drag_origin = (event.x, event.y, bool(event.state & 0x0001))

    def _drag_move(self, event) -> None:
        if not self._drag_origin:
            return
        x0, y0, _ = self._drag_origin
        if self._drag_box is None:
            self._drag_box = self.canvas.create_rectangle(x0, y0, event.x, event.y, outline=COLORS["accent"],
                                                          dash=(3, 2))
        self.canvas.coords(self._drag_box, x0, y0, event.x, event.y)

    def _drag_end(self, event) -> None:
        if not self._drag_origin:
            return
        x0, y0, shift = self._drag_origin
        self._drag_origin = None
        if self._drag_box is not None:
            self.canvas.delete(self._drag_box)
            self._drag_box = None
            box = (min(x0, event.x), min(y0, event.y), max(x0, event.x), max(y0, event.y))
            hit = {name for name, rect in self.rects.items() if self._overlaps(self.canvas.coords(rect), box)}
            self.selected = (self.selected | hit) if shift else hit
        else:
            name = self._key_at(event.x, event.y)
            if name is None:
                if not shift:
                    self.selected.clear()
            elif shift or name in self.selected and len(self.selected) == 1:
                self.selected ^= {name}
            else:
                self.selected = {name}
        self._redraw_keys()

    @staticmethod
    def _overlaps(rect, box) -> bool:
        return rect[0] < box[2] and rect[2] > box[0] and rect[1] < box[3] and rect[3] > box[1]

    def _redraw_keys(self) -> None:
        for name, rect in self.rects.items():
            rgb = self.key_colors.get(name, self.default_color)
            selected = name in self.selected
            self.canvas.itemconfigure(rect, fill=_hex(rgb),
                                      outline=COLORS["selected"] if selected else COLORS["key_outline"],
                                      width=3 if selected else 2)
            self.canvas.itemconfigure(self.labels[name], fill=_text_on(rgb))
            target = self.remaps.get(name, "")
            self.canvas.itemconfigure(self.sublabels[name], text=f"→{target}" if target else "",
                                      fill="#000000" if _text_on(rgb) == "#000000" else COLORS["accent"])
        count = len(self.selected)
        self.selection_label.configure(text=f"{count} key{'s' if count != 1 else ''} selected" if count else "")
        text = ", ".join(f"{k} → {v}" for k, v in sorted(self.remaps.items()))
        self.remap_list.configure(text=f"Active remaps: {text}" if text else "No remaps: all keys default.")

    def _select_all(self) -> None:
        self.selected = set(self.rects)
        self._redraw_keys()

    def _clear_selection(self) -> None:
        self.selected.clear()
        self._redraw_keys()

    def _paint(self, rgb) -> None:
        if not self.selected:
            messagebox.showinfo("INFI75", "Select one or more keys first.")
            return
        for name in self.selected:
            self.key_colors[name] = tuple(rgb)
        self._redraw_keys()

    def _paint_custom(self) -> None:
        rgb, _hex_color = colorchooser.askcolor(parent=self.root)
        if rgb:
            self._paint(tuple(int(c) for c in rgb))

    def _pick_default(self) -> None:
        rgb, hex_color = colorchooser.askcolor(color=_hex(self.default_color), parent=self.root)
        if rgb:
            self.default_color = tuple(int(c) for c in rgb)
            self.default_swatch.configure(bg=hex_color)
            self._redraw_keys()

    def _clear_colors(self) -> None:
        self.key_colors.clear()
        self._redraw_keys()

    def _send_key_colors(self) -> None:
        colors, default, brightness = dict(self.key_colors), self.default_color, self.brightness.get()
        self._run("Applying key colours", lambda b: b.set_key_colors(colors, default=default, brightness=brightness))

    def _target(self) -> str:
        return self.remap_target.get().replace(" (media)", "").strip()

    def _remap_selected(self) -> None:
        if len(self.selected) != 1:
            messagebox.showinfo("INFI75", "Select exactly one key to remap.")
            return
        (name,) = self.selected
        target = self._target()
        try:
            hfd.key_entry(target)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("INFI75", str(exc.args[0] if exc.args else exc))
            return
        self._run(f"Remapping {name}", lambda b: b.remap(name, target), then=self._remaps_changed)

    def _restore_selected(self) -> None:
        names = [n for n in self.selected if n in self.remaps]
        if not names:
            messagebox.showinfo("INFI75", "None of the selected keys is remapped.")
            return

        def action(b):
            state = b.remaps()
            for name in names:
                state.pop(name, None)
            b.write_remaps(state)
            return state

        self._run("Restoring keys", action, then=self._remaps_changed)

    def _reset_remaps(self) -> None:
        if messagebox.askyesno("INFI75", "Restore every key to its default function?"):
            self._run("Resetting remaps", lambda b: (b.reset_remaps(), {})[1], then=self._remaps_changed)

    def _remaps_changed(self, state) -> None:
        self.remaps = dict(state) if state is not None else self._board().remaps()
        self._redraw_keys()

    # ---------------------------------------------------------------- screen

    def _screen_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=10)
        self.image_path = tk.StringVar()
        self.fit = tk.StringVar(value="crop")
        self.frame_count = 0
        self._preview_image = None

        preview = self._panel(tab, "Preview")
        preview.pack(side="left", fill="y", padx=(0, 10))
        pw, ph = int(hfd.SCREEN_WIDTH * PREVIEW_SCALE), int(hfd.SCREEN_HEIGHT * PREVIEW_SCALE)
        self.preview = tk.Canvas(preview, width=pw, height=ph, bg="#000000", highlightthickness=1,
                                 highlightbackground=COLORS["key_outline"])
        self.preview.pack()
        self.preview.create_text(pw / 2, ph / 2, text="No image", fill=COLORS["muted"])
        self.preview_info = ttk.Label(preview, text=f"{hfd.SCREEN_WIDTH} x {hfd.SCREEN_HEIGHT} px",
                                      style="PanelMuted.TLabel")
        self.preview_info.pack(pady=(6, 0))

        right = self._panel(tab, "Screen image")
        right.pack(side="left", fill="both", expand=True)
        row = ttk.Frame(right, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.image_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left", padx=(6, 0))
        ttk.Label(right, text="PNG, JPG, BMP, WebP or an animated GIF (up to 141 frames).",
                  style="PanelMuted.TLabel").pack(anchor="w", pady=(4, 12))
        fit = ttk.Frame(right, style="Panel.TFrame")
        fit.pack(anchor="w")
        ttk.Label(fit, text="Fit:", style="Panel.TLabel").pack(side="left")
        for value, text in (("crop", "fill and crop"), ("stretch", "stretch"), ("pad", "whole image, black bars")):
            ttk.Radiobutton(fit, text=text, value=value, variable=self.fit, style="Panel.TRadiobutton",
                            command=self._update_preview).pack(side="left", padx=6)
        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.pack(fill="x", pady=(16, 6))
        self._button(actions, "Upload to keyboard", self._upload, accent=True).pack(side="left")
        self.progress = ttk.Progressbar(actions, length=240)
        self.progress.pack(side="left", padx=12)

        clock = self._panel(tab, "Clock")
        clock.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(clock, text="Set the screen clock to\nthis computer's time.", style="PanelMuted.TLabel").pack(
            anchor="w", pady=(0, 10))
        self._button(clock, "Sync clock", lambda: self._run("Syncing clock", lambda b: b.sync_time())).pack(
            anchor="w")
        return tab

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All files", "*")])
        if path:
            self.image_path.set(path)
            self._update_preview()

    def _update_preview(self) -> None:
        path = self.image_path.get()
        if not path:
            return
        try:
            from PIL import Image, ImageOps, ImageTk
        except ImportError:
            return
        size = (hfd.SCREEN_WIDTH, hfd.SCREEN_HEIGHT)
        try:
            with Image.open(path) as image:
                self.frame_count = min(getattr(image, "n_frames", 1), hfd.SCREEN_MAX_FRAMES)
                source = image.convert("RGB")
        except OSError as exc:
            self.preview_info.configure(text=f"Cannot open: {exc}")
            return
        fit = self.fit.get()
        if fit == "stretch":
            frame = source.resize(size, Image.Resampling.LANCZOS)
        elif fit == "pad":
            frame = ImageOps.pad(source, size, Image.Resampling.LANCZOS, color=(0, 0, 0))
        else:
            frame = ImageOps.fit(source, size, Image.Resampling.LANCZOS)
        shown = frame.resize((int(size[0] * PREVIEW_SCALE), int(size[1] * PREVIEW_SCALE)),
                             Image.Resampling.NEAREST)
        self._preview_image = ImageTk.PhotoImage(shown)
        self.preview.delete("all")
        self.preview.create_image(0, 0, anchor="nw", image=self._preview_image)
        frames = f"{self.frame_count} frames, " if self.frame_count > 1 else ""
        self.preview_info.configure(text=f"{frames}{size[0]} x {size[1]} px")

    def _upload(self) -> None:
        path, fit = self.image_path.get(), self.fit.get()
        if not path:
            messagebox.showinfo("INFI75", "Choose an image first.")
            return
        self.progress.configure(value=0)

        def progress(n: int, total: int) -> None:
            self.events.put(("call", lambda: self.progress.configure(maximum=total, value=n)))

        self._run("Uploading image", lambda b: b.upload_image(path, fit=fit, progress=progress))


def run(args) -> int:
    root = tk.Tk()
    App(root, args)
    root.mainloop()
    return 0

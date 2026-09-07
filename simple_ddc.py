#!/usr/bin/env python3
"""
simple-ddc — DDC/CI monitor brightness controller
A lightweight Monitorian-style GUI for Linux using ddcutil.
"""

import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import re


# ── DDC helpers ──────────────────────────────────────────────────────────────

def run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"{cmd[0]!r} not found"


def check_ddcutil() -> str | None:
    """Return None if ddcutil is usable, else a human-readable problem string."""
    rc, out, err = run(["ddcutil", "--version"])
    if rc != 0:
        return (
            "ddcutil is not installed.\n\n"
            "Install it with:\n"
            "  sudo dnf install ddcutil"
        )
    return None


def detect_monitors() -> list[dict]:
    """
    Parse `ddcutil detect` output.
    Returns a list of dicts:
      { bus, display_num, model, serial, edid_hex, mfr }
    """
    rc, out, err = run(["ddcutil", "detect", "--brief"])
    if rc != 0:
        # fall back to verbose parse
        rc, out, err = run(["ddcutil", "detect"])

    monitors = []
    current: dict | None = None

    for line in out.splitlines():
        # "Display N" starts a new monitor block
        m = re.match(r"^Display\s+(\d+)", line)
        if m:
            if current:
                monitors.append(current)
            current = {
                "display_num": int(m.group(1)),
                "bus": None,
                "model": "Unknown",
                "serial": "",
                "mfr": "",
                "connector": "",
            }
            continue

        if current is None:
            continue

        m = re.match(r"\s+I2C bus:\s+/dev/i2c-(\d+)", line)
        if m:
            current["bus"] = int(m.group(1))

        m = re.match(r"\s+DRM(?:_|\s)connector:\s+(.*)", line)
        if m:
            current["connector"] = m.group(1).strip()

        m = re.match(r"\s+Monitor:\s+([^:]+):([^:]+)(?::(.*))?", line)
        if m:
            current["mfr"] = current["mfr"] or m.group(1).strip()
            current["model"] = m.group(2).strip() or current["model"]
            if m.group(3):
                current["serial"] = current["serial"] or m.group(3).strip()

        m = re.match(r"\s+Model:\s+(.*)", line)
        if m:
            current["model"] = m.group(1).strip()

        m = re.match(r"\s+Serial number:\s+(.*)", line)
        if m:
            current["serial"] = m.group(1).strip()

        m = re.match(r"\s+Mfr id:\s+(.*)", line)
        if m:
            current["mfr"] = m.group(1).strip()

    if current:
        monitors.append(current)

    return monitors


def get_vcp(display_num: int, feature: str) -> tuple[int | None, int | None]:
    """Return (current, max) for a VCP feature code, or (None, None) on error."""
    rc, out, err = run(["ddcutil", f"--display={display_num}", "getvcp", feature])
    if rc != 0:
        return None, None
    # "VCP code 0x10 (Brightness): current value = 75, max value = 100"
    m = re.search(r"current value\s*=\s*(\d+).*max value\s*=\s*(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Some monitors report differently: "sl=0x4b"
    m = re.search(r"sl=0x([0-9a-fA-F]+)", out)
    if m:
        return int(m.group(1), 16), 100
    return None, None


def set_vcp(display_num: int, feature: str, value: int) -> bool:
    """Set a VCP feature code to value. Returns True on success."""
    rc, _, _ = run(["ddcutil", f"--display={display_num}", "setvcp", feature, str(value)])
    return rc == 0


def get_vcp_text(display_num: int, feature: str) -> str | None:
    """Return the raw normalized output line for a VCP feature."""
    rc, out, err = run(["ddcutil", f"--display={display_num}", "getvcp", feature])
    if rc != 0:
        return None
    for line in out.splitlines():
        if line.strip():
            return re.sub(r"\s+", " ", line.strip())
    return None


def get_all_info(display_num: int) -> dict[str, tuple[int, int]]:
    """Fetch brightness, contrast, colour temp for info panel."""
    info = {}
    for label, code in [("Brightness", "10"), ("Contrast", "12")]:
        cur, mx = get_vcp(display_num, code)
        if cur is not None:
            info[label] = (cur, mx)
    return info


# ── Permission helper ─────────────────────────────────────────────────────────

PERMISSION_MSG = """\
ddcutil cannot read your monitors.

Quick fix (run these in a terminal, then log out and back in):

  sudo groupadd --system i2c
  sudo usermod -aG i2c $USER
  sudo tee /etc/udev/rules.d/45-ddcutil-i2c.rules <<'EOF'
KERNEL=="i2c-[0-9]*", TAG+="uaccess"
EOF
  sudo udevadm control --reload-rules && sudo udevadm trigger

Alternatively, run simple-ddc with sudo (not recommended).
"""


# ── GUI ───────────────────────────────────────────────────────────────────────

ACCENT   = "#4A90D9"
BG       = "#1E1E2E"
SURFACE  = "#2A2A3E"
TEXT     = "#CDD6F4"
SUBTEXT  = "#7F849C"
SLIDER_H = "#89B4FA"
BTN_BG   = "#313244"
BTN_ACT  = "#45475A"
RED      = "#F38BA8"
GREEN    = "#A6E3A1"
GOLD     = "#F9E2AF"


class MonitorCard(tk.Frame):
    """One card per monitor with brightness slider and info."""

    def __init__(self, parent, monitor: dict, on_refresh, **kw):
        super().__init__(parent, bg=SURFACE, **kw)
        self.monitor = monitor
        self.on_refresh = on_refresh
        self._brightness_var = tk.IntVar(value=0)
        self._contrast_var = tk.IntVar(value=0)
        self._max_brightness = 100
        self._max_contrast = 100
        self._info_visible = False
        self._set_timers: dict[str, str | None] = {"10": None, "12": None}
        self._pending_values: dict[str, int | None] = {"10": None, "12": None}

        self._build()
        self.refresh()

    def _build(self):
        # ── Header row ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=SURFACE)
        hdr.pack(fill="x", padx=14, pady=(12, 2))

        icon_lbl = tk.Label(hdr, text="🖥", font=("Segoe UI", 18), bg=SURFACE, fg=SLIDER_H)
        icon_lbl.pack(side="left")

        name_frame = tk.Frame(hdr, bg=SURFACE)
        name_frame.pack(side="left", padx=(8, 0))

        tk.Label(
            name_frame,
            text=self.monitor["model"],
            font=("Segoe UI", 12, "bold"),
            bg=SURFACE, fg=TEXT,
        ).pack(anchor="w")

        sub = f"Display {self.monitor['display_num']}"
        if self.monitor.get("connector"):
            sub += f"  •  {self.monitor['connector']}"
        if self.monitor.get("mfr"):
            sub += f"  •  {self.monitor['mfr']}"
        tk.Label(name_frame, text=sub, font=("Segoe UI", 9), bg=SURFACE, fg=SUBTEXT).pack(anchor="w")

        badge_text = f"/dev/i2c-{self.monitor['bus']}" if self.monitor.get("bus") is not None else "No bus"
        tk.Label(
            hdr,
            text=badge_text,
            font=("Segoe UI", 8, "bold"),
            bg=BTN_BG,
            fg=TEXT,
            padx=10,
            pady=4,
        ).pack(side="right")

        # ── Brightness row ────────────────────────────────────────────────────
        controls = tk.Frame(self, bg=SURFACE)
        controls.pack(fill="x", padx=14, pady=(8, 2))

        self._brightness_scale, self._brightness_label = self._build_control_row(
            controls,
            icon="☀",
            title="Brightness",
            variable=self._brightness_var,
            command=lambda value: self._on_slider("10", value),
        )
        self._contrast_scale, self._contrast_label = self._build_control_row(
            controls,
            icon="◐",
            title="Contrast",
            variable=self._contrast_var,
            command=lambda value: self._on_slider("12", value),
        )

        # ── Status / info row ─────────────────────────────────────────────────
        bottom = tk.Frame(self, bg=SURFACE)
        bottom.pack(fill="x", padx=14, pady=(2, 10))

        self._status_label = tk.Label(
            bottom, text="", font=("Segoe UI", 9),
            bg=SURFACE, fg=SUBTEXT,
        )
        self._status_label.pack(side="left")

        btn_frame = tk.Frame(bottom, bg=SURFACE)
        btn_frame.pack(side="right")

        self._info_btn = tk.Button(
            btn_frame, text="Details ▸",
            font=("Segoe UI", 8), bg=BTN_BG, fg=SUBTEXT,
            relief="flat", cursor="hand2",
            activebackground=BTN_ACT, activeforeground=TEXT,
            command=self._toggle_info,
        )
        self._info_btn.pack(side="right", padx=(4, 0))

        tk.Button(
            btn_frame, text="⟳",
            font=("Segoe UI", 10), bg=BTN_BG, fg=SUBTEXT,
            relief="flat", cursor="hand2",
            activebackground=BTN_ACT, activeforeground=TEXT,
            command=self.refresh,
        ).pack(side="right")

        # ── Collapsible info panel ─────────────────────────────────────────────
        self._info_panel = tk.Frame(self, bg=BTN_BG)
        # not packed until toggled

        self._info_text = tk.Label(
            self._info_panel, text="Loading…",
            font=("Courier", 9), bg=BTN_BG, fg=TEXT,
            justify="left", anchor="w",
        )
        self._info_text.pack(fill="x", padx=12, pady=6)

    def _build_control_row(self, parent, icon: str, title: str, variable: tk.IntVar, command):
        row_shell = tk.Frame(parent, bg=BTN_BG)
        row_shell.pack(fill="x", pady=(0, 8))

        label = tk.Label(
            row_shell,
            text=f"{icon}  {title}",
            font=("Segoe UI", 10, "bold"),
            bg=BTN_BG,
            fg=TEXT,
            width=14,
            anchor="w",
            padx=10,
            pady=10,
        )
        label.pack(side="left")

        scale = ttk.Scale(
            row_shell,
            from_=0,
            to=100,
            variable=variable,
            orient="horizontal",
            command=command,
        )
        scale.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=10)

        value_label = tk.Label(
            row_shell,
            text="---%",
            font=("Segoe UI", 10, "bold"),
            bg=BTN_BG,
            fg=GOLD,
            width=5,
            anchor="e",
            padx=10,
        )
        value_label.pack(side="left")
        return scale, value_label

    # ── Slider interaction ────────────────────────────────────────────────────

    def _on_slider(self, feature: str, value):
        v = round(float(value))
        self._value_label_for(feature).config(text=f"{v}%")
        self._pending_values[feature] = v
        if self._set_timers[feature]:
            self.after_cancel(self._set_timers[feature])
        # debounce: apply 300 ms after last drag event
        self._set_timers[feature] = self.after(300, lambda: self._apply_control(feature))

    def _apply_control(self, feature: str):
        if self._pending_values[feature] is None:
            return
        value = self._pending_values[feature]
        self._pending_values[feature] = None
        self._set_timers[feature] = None
        self._status_label.config(text="Setting…", fg=SUBTEXT)

        def worker():
            ok = set_vcp(self.monitor["display_num"], feature, value)
            self.after(0, lambda: self._status_label.config(
                text="✓ Applied" if ok else "✗ Failed",
                fg=GREEN if ok else RED,
            ))
            self.after(2000, lambda: self._status_label.config(text=""))

        threading.Thread(target=worker, daemon=True).start()

    # ── Refresh (read current value) ──────────────────────────────────────────

    def refresh(self):
        self._status_label.config(text="Reading…", fg=SUBTEXT)
        self._brightness_scale.state(["disabled"])
        self._contrast_scale.state(["disabled"])

        def worker():
            brightness = get_vcp(self.monitor["display_num"], "10")
            contrast = get_vcp(self.monitor["display_num"], "12")
            self.after(0, lambda: self._apply_read(brightness, contrast))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_read(self, brightness: tuple[int | None, int | None], contrast: tuple[int | None, int | None]):
        self._brightness_scale.state(["!disabled"])
        cur, mx = brightness
        contrast_cur, contrast_max = contrast
        if cur is None:
            self._status_label.config(text="Read error", fg=RED)
            return
        self._max_brightness = mx or 100
        self._brightness_scale.config(to=self._max_brightness)
        self._brightness_var.set(cur)
        self._brightness_label.config(text=f"{cur}%")
        if contrast_cur is not None:
            self._contrast_scale.state(["!disabled"])
            self._max_contrast = contrast_max or 100
            self._contrast_scale.config(to=self._max_contrast)
            self._contrast_var.set(contrast_cur)
            self._contrast_label.config(text=f"{contrast_cur}%")
        else:
            self._contrast_scale.state(["disabled"])
            self._contrast_label.config(text="n/a")
        self._status_label.config(text="")
        if self._info_visible:
            self._load_info()

    def _value_label_for(self, feature: str) -> tk.Label:
        return self._brightness_label if feature == "10" else self._contrast_label

    # ── Details panel ─────────────────────────────────────────────────────────

    def _toggle_info(self):
        self._info_visible = not self._info_visible
        if self._info_visible:
            self._info_panel.pack(fill="x", padx=14, pady=(0, 10))
            self._info_btn.config(text="Details ▾")
            self._load_info()
        else:
            self._info_panel.pack_forget()
            self._info_btn.config(text="Details ▸")

    def _load_info(self):
        def worker():
            data = get_all_info(self.monitor["display_num"])
            preset = get_vcp_text(self.monitor["display_num"], "14")
            lines = [f"  Display {self.monitor['display_num']}  •  Bus: /dev/i2c-{self.monitor['bus']}"]
            if self.monitor.get("serial"):
                lines.append(f"  Serial: {self.monitor['serial']}")
            if self.monitor.get("connector"):
                lines.append(f"  Connector: {self.monitor['connector']}")
            lines.append("")
            for label, (cur, mx) in data.items():
                bar = "█" * round(cur / mx * 20) + "░" * (20 - round(cur / mx * 20))
                lines.append(f"  {label:14s}  {bar}  {cur}/{mx}")
            if preset:
                lines.append("")
                lines.append(f"  Preset: {preset}")
            self.after(0, lambda: self._info_text.config(text="\n".join(lines)))

        threading.Thread(target=worker, daemon=True).start()


class SimpleDDC(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("simple-ddc")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(560, 260)

        self._cards: list[MonitorCard] = []
        self._auto_refresh_id = None

        self._apply_styles()
        self._build_ui()
        self._initial_load()

    def _apply_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "TScale",
            background=BTN_BG,
            troughcolor=BTN_BG,
            sliderthickness=18,
            sliderrelief="flat",
        )
        style.map("TScale", background=[("active", SLIDER_H)])

    def _build_ui(self):
        # ── Titlebar / toolbar ────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg=BG, height=48)
        toolbar.pack(fill="x", padx=0, pady=0)
        toolbar.pack_propagate(False)

        tk.Label(
            toolbar, text="  simple-ddc",
            font=("Segoe UI", 13, "bold"), bg=BG, fg=TEXT,
        ).pack(side="left", padx=4)
        tk.Label(
            toolbar,
            text="Monitor brightness and contrast",
            font=("Segoe UI", 9),
            bg=BG,
            fg=SUBTEXT,
        ).pack(side="left", padx=(0, 8))

        self._scan_btn = tk.Button(
            toolbar, text="⟳  Scan",
            font=("Segoe UI", 9), bg=BTN_BG, fg=TEXT,
            relief="flat", cursor="hand2", padx=8,
            activebackground=BTN_ACT, activeforeground=TEXT,
            command=self._scan,
        )
        self._scan_btn.pack(side="right", padx=8, pady=8)

        self._auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            toolbar, text="Auto-refresh (5s)",
            variable=self._auto_var,
            font=("Segoe UI", 9), bg=BG, fg=SUBTEXT,
            selectcolor=BTN_BG, activebackground=BG,
            relief="flat", cursor="hand2",
            command=self._toggle_auto_refresh,
        ).pack(side="right", padx=4)

        # ── Scrollable card area ──────────────────────────────────────────────
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._card_frame = tk.Frame(self._canvas, bg=BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._card_frame, anchor="nw"
        )

        self._card_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._canvas.bind_all("<Button-5>", self._on_mousewheel)

        # ── Status bar ────────────────────────────────────────────────────────
        self._statusbar = tk.Label(
            self, text="", font=("Segoe UI", 9),
            bg=BG, fg=SUBTEXT, anchor="w",
        )
        self._statusbar.pack(fill="x", padx=14, pady=(0, 4))

    def _on_frame_configure(self, _):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")

    # ── Loading / scanning ────────────────────────────────────────────────────

    def _initial_load(self):
        problem = check_ddcutil()
        if problem:
            self._show_message(problem, error=True)
            return
        self._scan()

    def _scan(self):
        self._statusbar.config(text="Scanning for monitors…", fg=SUBTEXT)
        self._scan_btn.config(state="disabled")
        self._clear_cards()

        def worker():
            monitors = detect_monitors()
            self.after(0, lambda: self._populate(monitors))

        threading.Thread(target=worker, daemon=True).start()

    def _populate(self, monitors: list[dict]):
        self._scan_btn.config(state="normal")

        if not monitors:
            self._show_message(
                "No DDC/CI monitors detected.\n\n" + PERMISSION_MSG,
                error=True,
            )
            self._statusbar.config(text="No monitors found.", fg=RED)
            return

        self._statusbar.config(
            text=f"{len(monitors)} monitor(s) detected.", fg=SUBTEXT
        )

        for mon in monitors:
            card = MonitorCard(
                self._card_frame, mon,
                on_refresh=None,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BTN_ACT,
            )
            card.pack(fill="x", pady=(0, 10))
            self._cards.append(card)

        self._schedule_auto_refresh()

    def _clear_cards(self):
        if self._auto_refresh_id:
            self.after_cancel(self._auto_refresh_id)
            self._auto_refresh_id = None
        for c in self._cards:
            c.destroy()
        self._cards.clear()

    def _show_message(self, msg: str, error=False):
        frame = tk.Frame(self._card_frame, bg=SURFACE)
        frame.pack(fill="x", pady=8)

        tk.Label(
            frame,
            text=msg,
            font=("Segoe UI", 10),
            bg=SURFACE, fg=RED if error else TEXT,
            justify="left", wraplength=520, pady=16, padx=16,
        ).pack(fill="x")

    # ── Auto-refresh ──────────────────────────────────────────────────────────

    def _toggle_auto_refresh(self):
        if self._auto_var.get():
            self._schedule_auto_refresh()
        else:
            if self._auto_refresh_id:
                self.after_cancel(self._auto_refresh_id)
                self._auto_refresh_id = None

    def _schedule_auto_refresh(self):
        if not self._auto_var.get():
            return
        self._auto_refresh_id = self.after(5000, self._auto_refresh)

    def _auto_refresh(self):
        for card in self._cards:
            card.refresh()
        self._schedule_auto_refresh()


def main():
    app = SimpleDDC()

    # Center on screen
    app.update_idletasks()
    w, h = 640, 440
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    app.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    app.mainloop()


if __name__ == "__main__":
    main()

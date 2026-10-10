"""Branded first-run private AI setup."""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import ttk

from .hardware import HardwareProfile, scan_hardware
from .local_ai import PrivateAIClient, installation_path, provision
from .models import ModelCandidate, compatible_models, recommend_model

NAVY = "#0B1B33"; ACCENT = "#18A7FF"; PAGE = "#F3F6FA"; CARD = "#FFFFFF"
TEXT = "#132238"; MUTED = "#637083"; BORDER = "#DCE4EE"; GREEN = "#159570"; RED = "#C44545"


class ModelSetupDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, on_complete=None):
        super().__init__(parent)
        self.on_complete = on_complete
        self.profile: HardwareProfile | None = None
        self.models: list[ModelCandidate] = []
        self.title("PAi Legal — Private AI Setup")
        self.geometry("720x600"); self.minsize(660, 560); self.configure(bg=PAGE)
        self.transient(parent); self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        threading.Thread(target=self._scan, daemon=True).start()

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, height=86); header.pack(fill="x"); header.pack_propagate(False)
        brand = tk.Frame(header, bg=NAVY); brand.pack(side="left", padx=24, pady=16)
        tk.Label(brand, text="PAi", bg=NAVY, fg=ACCENT, font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(brand, text=" LEGAL", bg=NAVY, fg="white", font=("Segoe UI", 15, "bold")).pack(side="left", pady=(3, 0))
        tk.Label(header, text="PRIVATE AI SETUP", bg="#123451", fg="white", font=("Segoe UI", 8, "bold"), padx=10, pady=5).pack(side="right", padx=24)
        body = tk.Frame(self, bg=PAGE); body.pack(fill="both", expand=True, padx=24, pady=18)
        tk.Label(body, text="Set up your private legal AI", bg=PAGE, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(body, text="PAi Legal scans this computer, recommends the strongest safe model, downloads it once, and runs it locally.", bg=PAGE, fg=MUTED, font=("Segoe UI", 9), wraplength=650, justify="left").pack(anchor="w", pady=(3, 12))
        self.steps = tk.Frame(body, bg=PAGE); self.steps.pack(fill="x", pady=(0, 12))
        self.step_labels: list[tk.Label] = []
        for number, label in (("1","Scan device"),("2","Choose model"),("3","Install"),("4","Ready")):
            block = tk.Frame(self.steps, bg=PAGE); block.pack(side="left", fill="x", expand=True)
            chip = tk.Label(block, text=number, bg="#DDE7F0", fg=MUTED, font=("Segoe UI", 9, "bold"), width=3, pady=4); chip.pack(side="left")
            tk.Label(block, text=label, bg=PAGE, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left", padx=6)
            self.step_labels.append(chip)
        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1); card.pack(fill="both", expand=True)
        tk.Label(card, text="DEVICE COMPATIBILITY", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(14, 5))
        self.hardware_text = tk.Text(card, height=5, wrap="word", state="disabled", bg="#F8FAFC", fg=TEXT, font=("Segoe UI", 9), relief="flat", padx=10, pady=8)
        self.hardware_text.pack(fill="x", padx=14)
        model_row = tk.Frame(card, bg=CARD); model_row.pack(fill="x", padx=16, pady=(13, 5))
        tk.Label(model_row, text="COMPATIBLE MODEL", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(model_row, text="Official, vetted GGUF", bg="#EAF8F3", fg=GREEN, font=("Segoe UI", 7, "bold"), padx=7, pady=3).pack(side="right")
        self.choice = tk.StringVar(); self.combo = ttk.Combobox(card, textvariable=self.choice, state="readonly", font=("Segoe UI", 10)); self.combo.pack(fill="x", padx=16)
        self.note = tk.Label(card, text="Scanning this computer…", bg=CARD, fg=MUTED, font=("Segoe UI", 9), wraplength=620, justify="left")
        self.note.pack(anchor="w", padx=16, pady=(9, 5))
        self.progress = ttk.Progressbar(card, mode="determinate"); self.progress.pack(fill="x", padx=16, pady=(3, 10))
        privacy = tk.Frame(card, bg="#EAF8F3"); privacy.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(privacy, text="●", bg="#EAF8F3", fg=GREEN, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 5), pady=8)
        tk.Label(privacy, text="After this one-time download, prompts and case files stay on this computer.", bg="#EAF8F3", fg=TEXT, font=("Segoe UI", 8)).pack(side="left")
        buttons = tk.Frame(body, bg=PAGE); buttons.pack(fill="x", pady=(12, 0))
        self.cancel = ttk.Button(buttons, text="Not now", command=self.destroy); self.cancel.pack(side="right")
        self.install = ttk.Button(buttons, text="Download and install", command=self._install, state="disabled", style="Accent.TButton"); self.install.pack(side="right", padx=8)
        self._set_step(0)

    def _set_step(self, index: int) -> None:
        for position, label in enumerate(self.step_labels):
            label.configure(bg=ACCENT if position <= index else "#DDE7F0", fg="white" if position <= index else MUTED)

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", value); widget.configure(state="disabled")

    def _scan(self) -> None:
        try:
            profile = scan_hardware(); self.after(0, lambda: self._scanned(profile))
        except Exception as exc:
            error = str(exc); self.after(0, lambda: self._failed(error))

    def _scanned(self, profile: HardwareProfile) -> None:
        self.profile = profile; self.models = compatible_models(profile); recommended = recommend_model(profile)
        detail = (f"Memory       {profile.total_ram_gb:.1f} GB total  ·  {profile.available_ram_gb:.1f} GB available\n"
                  f"Storage      {profile.free_disk_gb:.1f} GB free\n"
                  f"Processor    {profile.cpu_count} logical cores  ·  {profile.architecture}\n"
                  f"Graphics     {profile.gpu_name or 'CPU inference'}{f'  ·  {profile.vram_gb:.1f} GB VRAM' if profile.vram_gb else ''}")
        self._set_text(self.hardware_text, detail); self.combo["values"] = [model.label for model in self.models]
        if recommended:
            self.choice.set(recommended.label); self.note.configure(text=f"Recommended for this device: {recommended.label}. Approximate download: {recommended.size_gb:.1f} GB. A smaller compatible model may be selected.", fg=TEXT)
            self.install.configure(state="normal"); self._set_step(1)
        else:
            self.note.configure(text="This device does not currently have enough available memory and storage for the light model.", fg=RED)

    def _install(self) -> None:
        model = next((item for item in self.models if item.label == self.choice.get()), None)
        if not model or not self.profile: return
        self.install.configure(state="disabled"); self.combo.configure(state="disabled"); self.note.configure(text="Checking the official Hugging Face file and beginning the resumable download…", fg=TEXT); self._set_step(2)
        def progress(done: int, total: int) -> None: self.after(0, lambda: self._progress(done, total))
        def worker() -> None:
            try:
                payload = provision(model, self.profile, progress); client = PrivateAIClient(payload, timeout=240); client.start(); client.close()
                payload["launch_confirmed"] = True; installation_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
                self.after(0, self._finished)
            except Exception as exc:
                error = str(exc); self.after(0, lambda: self._failed(error))
        threading.Thread(target=worker, daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        if total: self.progress["value"] = done * 100 / total
        self.note.configure(text=f"Downloading securely…  {done / 2**30:.2f} of {total / 2**30:.2f} GB" if total else f"Downloading securely…  {done / 2**30:.2f} GB")

    def _finished(self) -> None:
        self.progress["value"] = 100; self._set_step(3)
        self.note.configure(text="Private AI is installed, tested and ready. No cloud inference or API key is used.", fg=GREEN)
        self.install.configure(text="Done", state="normal", command=self.destroy); self.cancel.pack_forget()
        if self.on_complete: self.on_complete()

    def _failed(self, error: str) -> None:
        self.note.configure(text=f"Setup stopped: {error}\nA partial model download is preserved so setup can resume.", fg=RED)
        self.install.configure(state="normal"); self.combo.configure(state="readonly")

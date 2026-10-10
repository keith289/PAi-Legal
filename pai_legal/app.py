"""PAi Legal customer-facing desktop interface."""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional

try:  # Optional at source-time; included in the Windows Store build.
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _BaseTk = TkinterDnD.Tk
except ImportError:
    DND_FILES = None
    _BaseTk = tk.Tk

from . import brackets, doctypes
from .capabilities import Capability, CapabilityReport, detect_all, diagnostics
from .corpus import PSiCorpus, SearchResult
from .ingestion import find_tesseract
from .local_ai import LocalAIError, PrivateAIClient, read_installation
from .models import CATALOG
from .drafter_server import DrafterServer
from .governance import parties_from_caption
from .setup_ui import ModelSetupDialog
from .transition_map import CaseTransitionMap, MapEdge, MapNode
from .map_presentation import CaseMapPresentation
from .workspace import CaseRef, IngestedFile, Workspace

NAVY = "#0B1B33"
SIDEBAR = "#102640"
ACCENT = "#18A7FF"
PAGE = "#F3F6FA"
CARD = "#FFFFFF"
TEXT = "#132238"
MUTED = "#637083"
BORDER = "#DCE4EE"
GREEN = "#159570"
YELLOW = "#B7791F"
ORANGE = "#D06728"
RED = "#C44545"
PURPLE = "#7256B3"

DISCLAIMER = "Legal work-product assistanceâ€”not legal advice. Verify authorities and current law."
FOLDER_LABELS = {
    "00_inbox": "Unclassified", "01_originals": "Preserved originals",
    "02_text": "Extracted text", "court_papers": "Court papers",
    "depositions": "Depositions", "correspondence": "Correspondence",
    "exhibits": "Exhibits", "discovery": "Discovery",
    "04_index": "RPM indexes", "05_trace": "Source traces",
    "reasoning_corpus": "Analysis record",
    "notes": "Pinned claims & notes", "research": "Attached authorities",
    "audit": "Epistemic audit", "exports": "Exports",
}


def _open_uri(uri: str) -> None:
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(uri)  # type: ignore[attr-defined]
        else:
            webbrowser.open(uri)
    except Exception:
        pass


class _PAiLegalAppBase(_BaseTk):
    def __init__(self, workspace: Optional[Workspace] = None, report: Optional[CapabilityReport] = None):
        super().__init__()
        self.workspace = workspace or Workspace()
        self.report = report or detect_all()
        self.active_case: Optional[CaseRef] = None
        self.case_map: Dict[str, CaseRef] = {}
        self.search_results: List[SearchResult] = []
        self.selected_authorities: List[SearchResult] = []
        self.drafter_server: Optional[DrafterServer] = None
        self.ai_client: Optional[PrivateAIClient] = None
        self.corpus_client: Optional[PSiCorpus] = None
        self.pages: Dict[str, tk.Frame] = {}
        self.nav_buttons: Dict[str, tk.Button] = {}
        self.file_paths: Dict[str, Path] = {}
        self.current_page = "dashboard"
        self.last_question = ""
        self.current_authority_ids: list[str] = []
        self.transition_map_model: Optional[CaseTransitionMap] = None
        self.transition_view_id = "root"
        self.transition_scale = 1.0
        self.transition_selection: tuple[str, str] | None = None

        self.title(f"PAi Legal â€” {self.report.mode}")
        self.geometry("1440x900")
        self.minsize(1120, 720)
        self.configure(background=PAGE)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self._configure_style()
        self._build_menu()
        self._build_shell()
        self._build_pages()
        self._refresh_cases()
        self._show_page("dashboard")
        self._apply_state()
        self._bind_shortcuts()
        if not self.report.has(Capability.ANALYSIS):
            self.after(700, self._offer_private_ai_setup)

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _event: self._new_case())
        self.bind_all("<Control-o>", lambda _event: self._add_files())
        self.bind_all("<Control-Return>", lambda _event: self._run_analysis())
        self.bind_all("<Control-b>", lambda _event: self._build_case_record())
        self.bind_all("<Control-e>", lambda _event: self._export_case())
        self.bind_all("<F5>", lambda _event: self._refresh_capabilities())
        self.bind_all("<Control-f>", lambda _event: self._focus_case_search())
        self.bind_all("<F1>", lambda _event: self._show_bracket_legend())

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        case_menu = tk.Menu(menu, tearoff=False)
        case_menu.add_command(label="New case\tCtrl+N", command=self._new_case)
        case_menu.add_command(label="Open PAi Claims caseâ€¦", command=self._open_claims_case)
        case_menu.add_command(label="Annual accessâ€¦", command=self._purchase_annual_access)
        case_menu.add_command(label="Add evidence\tCtrl+O", command=self._add_files)
        case_menu.add_command(label="Build analysis record\tCtrl+B", command=self._build_case_record)
        case_menu.add_separator()
        case_menu.add_command(label="Export case record\tCtrl+E", command=self._export_case)
        case_menu.add_command(label="Share encrypted bundle\u2026", command=self._share_encrypted_dialog)
        case_menu.add_command(label="Archive active case", command=self._archive_active_case)
        case_menu.add_command(label="Restore archived case", command=self._restore_archived_case)
        case_menu.add_separator()
        case_menu.add_command(label="Conflict check", command=self._conflict_check_dialog)
        case_menu.add_command(label="Set retention date", command=self._set_retention_dialog)
        case_menu.add_command(label="Place or release legal hold", command=self._legal_hold_dialog)
        case_menu.add_command(label="Encrypted backup", command=self._backup_active_case)
        case_menu.add_command(label="Restore encrypted backup", command=self._restore_case_backup)
        case_menu.add_command(label="Verify audit integrity", command=self._verify_active_audit)
        case_menu.add_command(label="Validate filing", command=self._validate_filing_dialog)
        case_menu.add_separator()
        case_menu.add_command(label="Exit", command=self._quit)
        menu.add_cascade(label="Case", menu=case_menu)

        work_menu = tk.Menu(menu, tearoff=False)
        work_menu.add_command(label="Search active case\tCtrl+F", command=self._focus_case_search)
        work_menu.add_command(label="Pin selected claim", command=self._pin_selected_claim)
        work_menu.add_command(label="Add case note", command=self._add_case_note)
        work_menu.add_separator()
        work_menu.add_command(label="Analyze privately\tCtrl+Enter", command=self._run_analysis)
        menu.add_cascade(label="Work product", menu=work_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        for label, page in (("Case dashboard", "dashboard"), ("Evidence", "evidence"),
                            ("Precognitive Case Map", "map"),
                            ("PSi research", "research"), ("Private analysis", "analysis"),
                            ("Settings", "settings")):
            view_menu.add_command(label=label, command=lambda value=page: self._show_page(value))
        view_menu.add_separator()
        view_menu.add_command(label="Refresh integrations\tF5", command=self._refresh_capabilities)
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Trust Lock legend\tF1", command=self._show_bracket_legend)
        help_menu.add_command(label="About PAi Legal", command=self._show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menu)

    # Shell ---------------------------------------------------------

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=32, font=("Segoe UI", 9), background=CARD, fieldbackground=CARD, foreground=TEXT)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#EAF0F6", foreground=TEXT)
        style.map("Treeview", background=[("selected", "#D8EFFF")], foreground=[("selected", TEXT)])
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("Quiet.TButton", font=("Segoe UI", 9), padding=(10, 7))

    def _build_shell(self) -> None:
        header = tk.Frame(self, bg=NAVY, height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=NAVY)
        brand.pack(side="left", padx=24, pady=13)
        tk.Label(brand, text="PAi", bg=NAVY, fg=ACCENT, font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(brand, text=" LEGAL", bg=NAVY, fg="white", font=("Segoe UI", 17, "bold")).pack(side="left", pady=(4, 0))
        tk.Label(header, text="Private Legal Document Assistant", bg=NAVY, fg="#AFC4DA", font=("Segoe UI", 9)).pack(side="left", padx=18)
        privacy = tk.Frame(header, bg="#123451", highlightbackground="#28516F", highlightthickness=1)
        privacy.pack(side="right", padx=22, pady=19)
        tk.Label(privacy, text="â—", bg="#123451", fg=GREEN, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 4), pady=7)
        tk.Label(privacy, text="LOCAL CASE STORAGE  Â·  EXTERNAL SENDS REQUIRE YOUR ACTION", bg="#123451", fg="white", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 10))
        capability_strip = tk.Frame(header, bg=NAVY)
        capability_strip.pack(side="right", pady=19)
        self.header_capabilities: Dict[str, tk.Label] = {}
        for key, label in (("ai", "PRIVATE AI"), ("psi", "PSi LEGAL"), ("ocr", "OCR")):
            item = tk.Label(capability_strip, text=f"â—  {label}", bg=NAVY, fg="#7892AA",
                            font=("Segoe UI", 8, "bold"), padx=7, pady=7, cursor="hand2")
            item.pack(side="left", padx=2)
            item.bind("<Button-1>", lambda _event: self._show_page("settings"))
            self.header_capabilities[key] = item
        self._paint_header_capabilities()

        body = tk.Frame(self, bg=PAGE)
        body.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(body, bg=SIDEBAR, width=222)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(body, bg=PAGE)
        self.main.pack(side="left", fill="both", expand=True)

        new_case = tk.Button(self.sidebar, text="ï¼‹  New case", command=self._new_case, bg=ACCENT, fg="white",
                             activebackground="#0B91E5", activeforeground="white", relief="flat",
                             font=("Segoe UI", 10, "bold"), cursor="hand2", padx=12, pady=10)
        new_case.pack(fill="x", padx=16, pady=(20, 18))
        for key, label in (("dashboard", "â–¦   Case dashboard"), ("evidence", "â–¤   Evidence"),
                           ("map", "âŒ˜   Precognitive map"),
                           ("research", "âŒ•   PSi research"), ("analysis", "âœ¦   Private analysis"),
                           ("settings", "âš™   Settings")):
            button = tk.Button(self.sidebar, text=label, command=lambda name=key: self._show_page(name),
                               anchor="w", bg=SIDEBAR, fg="#D5E2EF", activebackground="#193A5D",
                               activeforeground="white", relief="flat", font=("Segoe UI", 10), padx=20, pady=12, cursor="hand2")
            button.pack(fill="x", pady=1)
            self.nav_buttons[key] = button
        tk.Frame(self.sidebar, bg="#2A425C", height=1).pack(fill="x", padx=16, pady=18)
        tk.Label(self.sidebar, text="ACTIVE CASE", bg=SIDEBAR, fg="#7F9BB5", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=20)
        self.case_value = tk.StringVar()
        self.case_combo = ttk.Combobox(self.sidebar, textvariable=self.case_value, state="readonly", width=25)
        self.case_combo.pack(fill="x", padx=16, pady=(7, 4))
        self.case_combo.bind("<<ComboboxSelected>>", self._case_selected)
        self.sidebar_case_status = tk.Label(self.sidebar, text="No case selected", bg=SIDEBAR, fg="#91A8BE", font=("Segoe UI", 8), wraplength=180, justify="left")
        self.sidebar_case_status.pack(anchor="w", padx=20, pady=5)

        self.topbar = tk.Frame(self.main, bg=CARD, height=55, highlightbackground=BORDER, highlightthickness=1)
        self.topbar.pack(fill="x")
        self.topbar.pack_propagate(False)
        self.page_title = tk.Label(self.topbar, text="Case dashboard", bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold"))
        self.page_title.pack(side="left", padx=24)
        self.mode_label = tk.Label(self.topbar, text=self.report.mode, bg="#E9F7F2", fg=GREEN, font=("Segoe UI", 8, "bold"), padx=10, pady=5)
        self.mode_label.pack(side="right", padx=22)
        self.content = tk.Frame(self.main, bg=PAGE)
        self.content.pack(fill="both", expand=True)
        statusbar = tk.Frame(self.main, bg=CARD, height=34, highlightbackground=BORDER, highlightthickness=1)
        statusbar.pack(fill="x", side="bottom")
        statusbar.pack_propagate(False)
        self.status_value = tk.StringVar(value="Ready")
        tk.Label(statusbar, textvariable=self.status_value, bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=16)
        tk.Label(statusbar, text=DISCLAIMER, bg=CARD, fg="#7A8797", font=("Segoe UI", 8)).pack(side="right", padx=16)

    def _build_pages(self) -> None:
        for name in ("dashboard", "evidence", "map", "research", "analysis", "settings"):
            self.pages[name] = tk.Frame(self.content, bg=PAGE)
        self._build_dashboard()
        self._build_evidence()
        self._build_case_map()
        self._build_research()
        self._build_analysis()
        self._build_settings()

    def _show_page(self, name: str) -> None:
        for page in self.pages.values(): page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current_page = name
        titles = {"dashboard":"Case dashboard", "evidence":"Evidence workspace", "map":"Precognitive Case Map", "research":"PSi Legal research", "analysis":"Private analysis", "settings":"Settings & system status"}
        self.page_title.configure(text=titles[name])
        for key, button in self.nav_buttons.items():
            button.configure(bg="#193A5D" if key == name else SIDEBAR, fg="white" if key == name else "#D5E2EF")
        if name == "dashboard": self._refresh_dashboard()
        if name == "evidence": self._refresh_evidence()
        if name == "map": self._refresh_case_map()
        if name == "settings": self._show_diagnostics()

    @staticmethod
    def _section_title(parent: tk.Widget, title: str, subtitle: str = "") -> tk.Frame:
        block = tk.Frame(parent, bg=PAGE)
        tk.Label(block, text=title, bg=PAGE, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        if subtitle: tk.Label(block, text=subtitle, bg=PAGE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
        return block

    @staticmethod
    def _card(parent: tk.Widget, bg: str = CARD) -> tk.Frame:
        return tk.Frame(parent, bg=bg, highlightbackground=BORDER, highlightthickness=1)

    # Dashboard -----------------------------------------------------

    def _build_dashboard(self) -> None:
        page = self.pages["dashboard"]
        inner = tk.Frame(page, bg=PAGE)
        inner.pack(fill="both", expand=True, padx=26, pady=22)
        self.dashboard_heading = self._section_title(inner, "Welcome to PAi Legal", "Load your case materials to begin private, source-traced legal analysis.")
        self.dashboard_heading.pack(fill="x")
        actions = tk.Frame(inner, bg=PAGE)
        actions.pack(fill="x", pady=(20, 14))
        self.workflow_cards: list[tk.Frame] = []
        steps = (("1", "Create a case", "Keep every matter isolated", self._new_case),
                 ("2", "Add evidence", "Preserve, OCR and index files", lambda: self._show_page("evidence")),
                 ("3", "Explore transitions", "Zoom inside Float / Mix / Stir", lambda: self._show_page("map")),
                 ("4", "Find authority", "Search stored PSi records", lambda: self._show_page("research")),
                 ("5", "Analyze privately", "Ask against selected sources", lambda: self._show_page("analysis")))
        for number, title, subtitle, command in steps:
            card = self._card(actions); card.pack(side="left", fill="both", expand=True, padx=(0, 10))
            tk.Label(card, text=number, bg=ACCENT, fg="white", font=("Segoe UI", 10, "bold"), width=3, pady=5).pack(anchor="w", padx=14, pady=(14, 8))
            tk.Label(card, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=14)
            tk.Label(card, text=subtitle, bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=180, justify="left").pack(anchor="w", padx=14, pady=(3, 10))
            tk.Button(card, text="Open â†’", command=command, bg=CARD, fg=ACCENT, activebackground=CARD, activeforeground="#087DC2", relief="flat", font=("Segoe UI", 8, "bold"), cursor="hand2").pack(anchor="w", padx=10, pady=(0, 10))
            self.workflow_cards.append(card)
        metrics = tk.Frame(inner, bg=PAGE); metrics.pack(fill="x", pady=(3, 14))
        self.metric_values: Dict[str, tk.Label] = {}
        for key, label, color in (("documents","Documents",ACCENT),("indexed","RPM indexed",PURPLE),("authorities","Authorities selected",ORANGE),("ai","Private AI",GREEN)):
            card = self._card(metrics); card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Frame(card, bg=color, width=5).pack(side="left", fill="y")
            body = tk.Frame(card, bg=CARD); body.pack(side="left", padx=14, pady=12)
            value = tk.Label(body, text="â€”", bg=CARD, fg=TEXT, font=("Segoe UI", 18, "bold")); value.pack(anchor="w")
            tk.Label(body, text=label, bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
            self.metric_values[key] = value
        lower = tk.Frame(inner, bg=PAGE); lower.pack(fill="both", expand=True)
        rpm = self._card(lower); rpm.pack(side="left", fill="both", expand=True, padx=(0, 10))
        tk.Label(rpm, text="RELATIONAL PRESSURE MAP", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        self.dashboard_rpm = tk.Label(rpm, text="Select a case to view Float / Mix / Stir", bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold"), justify="left")
        self.dashboard_rpm.pack(anchor="w", padx=16, pady=(4, 10))
        self.dashboard_relations = tk.Label(rpm, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 8), justify="left", wraplength=600)
        self.dashboard_relations.pack(anchor="w", padx=16, pady=(0, 14))
        tk.Label(rpm, text="Pressure cannot promote or demote a claim's Trust Lock.", bg="#F2EEFF", fg=PURPLE, font=("Segoe UI", 8, "bold"), padx=9, pady=5).pack(anchor="w", padx=16, pady=(0, 14))
        privacy = self._card(lower, "#EAF8F3"); privacy.pack(side="left", fill="both", padx=(0, 0))
        tk.Label(privacy, text="PRIVATE BY DESIGN", bg="#EAF8F3", fg=GREEN, font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16, pady=(16, 8))
        tk.Label(privacy, text="Case files, OCR text, indexes and AI prompts remain on this computer. PSi Legal is queried locally when installed.", bg="#EAF8F3", fg=TEXT, font=("Segoe UI", 9), wraplength=300, justify="left").pack(anchor="w", padx=16, pady=(0, 16))

    def _refresh_dashboard(self) -> None:
        if not self.active_case:
            self.metric_values["documents"].configure(text="0")
            self.metric_values["indexed"].configure(text="0")
            self.metric_values["authorities"].configure(text=str(len(self.selected_authorities)))
            self.metric_values["ai"].configure(text="Ready" if self.report.has(Capability.ANALYSIS) else "Setup")
            self.dashboard_rpm.configure(text="No active case")
            self.dashboard_relations.configure(text="Create or select a case to begin.")
            return
        summary = self.workspace.rpm_summary(self.active_case)
        self.metric_values["documents"].configure(text=str(self.active_case.document_count))
        self.metric_values["indexed"].configure(text=str(summary["documents"]))
        self.metric_values["authorities"].configure(text=str(len(self.workspace.attached_authorities(self.active_case)) or len(self.selected_authorities)))
        self.metric_values["ai"].configure(text="Ready" if self.report.has(Capability.ANALYSIS) else "Setup")
        signatures = []
        for path in sorted((self.active_case.path / "04_index").glob("*.rpm.json")):
            try: signatures.append(str(json.loads(path.read_text(encoding="utf-8")).get("pattern_signature") or "")[:8])
            except Exception: pass
        fingerprint = signatures[0] if signatures else "â€”"
        self.dashboard_rpm.configure(text=f"FLOAT  {summary['float_points']}     MIX  {summary['mix_points']}     STIR  {summary['stir_points']}     PRESSURE  {summary['total_pressure']}     âŒ {fingerprint}")
        relations = [str(item.get("value") or "") for item in summary["top_relations"][:4]]
        self.dashboard_relations.configure(text="Top relations\n" + ("\n".join(f"â€¢ {value[:120]}" for value in relations) if relations else "No indexed relations yet."))

    # Evidence ------------------------------------------------------

    def _build_evidence(self) -> None:
        page = self.pages["evidence"]
        inner = tk.Frame(page, bg=PAGE); inner.pack(fill="both", expand=True, padx=26, pady=20)
        header = self._section_title(inner, "Evidence workspace", "Originals are preserved. OCR text and RPM indexes are derived and rebuildable.")
        header.pack(fill="x")
        tools = tk.Frame(header, bg=PAGE); tools.pack(side="right", anchor="e")
        self.add_folder_button = ttk.Button(tools, text="Add folder", command=self._add_folder, style="Quiet.TButton"); self.add_folder_button.pack(side="right", padx=(6, 0))
        self.build_corpus_button = ttk.Button(tools, text="Build analysis record", command=self._build_case_record, style="Quiet.TButton"); self.build_corpus_button.pack(side="right", padx=(6, 0))
        self.add_files_button = ttk.Button(tools, text="ï¼‹ Add files", command=self._add_files, style="Accent.TButton"); self.add_files_button.pack(side="right")
        self.drop_zone = tk.Frame(inner, bg="#EAF5FD", highlightbackground="#8CCCF3", highlightthickness=2, cursor="hand2")
        self.drop_zone.pack(fill="x", pady=(15, 12))
        self.drop_zone.bind("<Button-1>", lambda _event: self._add_files())
        tk.Label(self.drop_zone, text="â‡©", bg="#EAF5FD", fg=ACCENT, font=("Segoe UI", 22, "bold")).pack(side="left", padx=(24, 12), pady=13)
        drop_text = tk.Frame(self.drop_zone, bg="#EAF5FD"); drop_text.pack(side="left", pady=12)
        tk.Label(drop_text, text="Drop case files here", bg="#EAF5FD", fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(drop_text, text="PDF, scanned images, Office documents, email and structured text", bg="#EAF5FD", fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        if DND_FILES and hasattr(self.drop_zone, "drop_target_register"):
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._files_dropped)
        case_search = tk.Frame(inner, bg=PAGE); case_search.pack(fill="x", pady=(0, 10))
        tk.Label(case_search, text="Search active case", bg=PAGE, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        self.case_search_value = tk.StringVar(); self.case_search_entry = ttk.Entry(case_search, textvariable=self.case_search_value, width=42)
        self.case_search_entry.pack(side="left", padx=8); self.case_search_entry.bind("<Return>", lambda _e: self._search_active_case())
        ttk.Button(case_search, text="Search", command=self._search_active_case, style="Quiet.TButton").pack(side="left")
        rpm_strip = tk.Frame(inner, bg=PAGE); rpm_strip.pack(fill="x", pady=(0, 12))
        self.rpm_values: Dict[str, tk.Label] = {}
        self.rpm_bars: Dict[str, tk.Frame] = {}
        for key, label, color in (("float_points","FLOAT observations",ACCENT),("mix_points","MIX relations",PURPLE),("stir_points","STIR recurrence",ORANGE),("total_pressure","Total pressure",GREEN)):
            card = self._card(rpm_strip); card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=label, bg=CARD, fg=color, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(9, 0))
            value = tk.Label(card, text="0", bg=CARD, fg=TEXT, font=("Segoe UI", 16, "bold")); value.pack(anchor="w", padx=12, pady=(0, 5))
            track = tk.Frame(card, bg="#E8EDF3", height=4); track.pack(fill="x", padx=12, pady=(0, 9)); track.pack_propagate(False)
            bar = tk.Frame(track, bg=color); bar.place(relx=0, rely=0, relheight=1, relwidth=0)
            self.rpm_values[key] = value
            self.rpm_bars[key] = bar
        pane = ttk.Panedwindow(inner, orient="horizontal"); pane.pack(fill="both", expand=True)
        left = self._card(pane); right = self._card(pane); pane.add(left, weight=3); pane.add(right, weight=2)
        tk.Label(left, text="CASE FILES", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 5))
        tree_frame = tk.Frame(left, bg=CARD); tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.file_tree = ttk.Treeview(tree_frame, columns=("size", "state"), show="tree headings")
        self.file_tree.heading("#0", text="Folder / file"); self.file_tree.heading("size", text="Size"); self.file_tree.heading("state", text="State")
        self.file_tree.column("#0", width=420); self.file_tree.column("size", width=85, anchor="e"); self.file_tree.column("state", width=100)
        self.file_tree.pack(side="left", fill="both", expand=True); self.file_tree.bind("<<TreeviewSelect>>", self._file_selected); self.file_tree.bind("<Button-3>", self._show_file_menu)
        self.file_menu = tk.Menu(self, tearoff=False)
        self.file_menu.add_command(label="Inspect document RPM", command=self._inspect_selected_rpm)
        self.file_menu.add_command(label="Re-process this document", command=self._reprocess_selected)
        scroll = ttk.Scrollbar(tree_frame, command=self.file_tree.yview); scroll.pack(side="right", fill="y"); self.file_tree.configure(yscrollcommand=scroll.set)
        tk.Label(right, text="DOCUMENT PREVIEW / INGESTION", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 5))
        self.evidence_preview = tk.Text(right, wrap="word", state="disabled", bg="#FBFCFE", fg=TEXT, font=("Segoe UI", 9), relief="flat", padx=12, pady=10)
        self.evidence_preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _files_dropped(self, event) -> None:
        if not self.active_case: return
        self._ingest([Path(item) for item in self.tk.splitlist(event.data) if Path(item).is_file()])

    def _refresh_evidence(self) -> None:
        self._refresh_file_tree()
        summary = self.workspace.rpm_summary(self.active_case) if self.active_case else {key: 0 for key in self.rpm_values}
        values = [float(summary.get(key, 0) or 0) for key in self.rpm_values]
        ceiling = max(values) if values else 1
        for key, label in self.rpm_values.items():
            value = float(summary.get(key, 0) or 0); label.configure(text=str(summary.get(key, 0)))
            self.rpm_bars[key].place_configure(relwidth=min(1.0, value / ceiling) if ceiling else 0)

    def _file_selected(self, _event=None) -> None:
        selected = self.file_tree.selection()
        if not selected: return
        path = self.file_paths.get(selected[0])
        if not path or not path.is_file(): return
        try:
            if path.name.endswith(".rpm.json") and self.active_case:
                text = self._format_rpm(self.workspace.document_rpm(self.active_case, path))
            elif path.suffix.lower() in {".txt", ".json", ".md", ".log"}:
                text = path.read_text(encoding="utf-8", errors="replace")[:30000]
                if path.suffix.lower() == ".json": text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            else:
                rpm = self.workspace.document_rpm(self.active_case, path) if self.active_case else {}
                suffix = "\n\n" + self._format_rpm(rpm) if rpm else ""
                text = f"{path.name}\n\nPreserved binary evidence. Right-click to re-process or inspect its relational-pressure map.{suffix}"
        except Exception as exc: text = f"Preview unavailable: {exc}"
        self._set_text(self.evidence_preview, text)

    @staticmethod
    def _format_rpm(record: dict) -> str:
        if not record: return "No document RPM index is available."
        lines = [f"DOCUMENT RELATIONAL PRESSURE MAP â€” {record.get('source','')}", "",
                 f"FLOAT observations   {record.get('float_points',0)}",
                 f"MIX relations        {record.get('mix_points',0)}",
                 f"STIR recurrences     {record.get('stir_points',0)}",
                 f"Document pressure    {record.get('total_pressure',0)}",
                 f"Case contribution    {record.get('case_pressure_percent',0)}%",
                 f"Trust Lock           {record.get('bracket','UNVERIFIED')}",
                 f"Pattern signature    {record.get('pattern_signature','')}", "",
                 "Pressure cannot promote or demote this document's Trust Lock.", ""]
        for key, title in (("top_float","TOP FLOAT OBSERVATIONS"),("top_mix","TOP MIX RELATIONS"),("top_stir","TOP STIR RECURRENCES")):
            lines += [title]
            items = record.get(key) or []
            lines += [f"â€¢ {item.get('kind','')} Â· {item.get('value','')} Â· pressure {float(item.get('pressure') or 0):.3f}" for item in items[:8]] or ["â€¢ None"]
            lines.append("")
        return "\n".join(lines)

    def _show_file_menu(self, event) -> None:
        item = self.file_tree.identify_row(event.y)
        if item: self.file_tree.selection_set(item); self.file_menu.tk_popup(event.x_root, event.y_root)

    def _selected_file_path(self) -> Optional[Path]:
        selected = self.file_tree.selection()
        return self.file_paths.get(selected[0]) if selected else None

    def _inspect_selected_rpm(self) -> None:
        path = self._selected_file_path()
        if not path or not self.active_case: return
        self._set_text(self.evidence_preview, self._format_rpm(self.workspace.document_rpm(self.active_case, path)))

    def _reprocess_selected(self) -> None:
        path = self._selected_file_path()
        if not path or not self.active_case: return
        case = self.active_case; self._set_status(f"Re-processing {path.name}â€¦")
        def worker() -> None:
            try: result, error = self.workspace.reprocess_document(case, path), ""
            except Exception as exc: result, error = {}, str(exc)
            self.after(0, lambda: self._reprocess_finished(result, error))
        threading.Thread(target=worker, daemon=True).start()

    def _reprocess_finished(self, result: dict, error: str) -> None:
        if error: self._inline_error(error); return
        self._set_text(self.evidence_preview, "âœ“ Document re-processed\n\n" + self._format_rpm(result))
        self._refresh_evidence(); self._refresh_dashboard(); self._refresh_case_map()
        self._set_status(f"Re-processed {result.get('source','document')}")

    def _focus_case_search(self) -> None:
        self._show_page("evidence"); self.case_search_entry.focus_set()

    def _search_active_case(self) -> None:
        if not self.active_case: self._inline_error("Select a case before searching."); return
        query = self.case_search_value.get().strip()
        if not query: return
        hits = self.workspace.search_case(self.active_case, query)
        lines = [f"CASE SEARCH â€” {query}", f"{len(hits)} result(s)", ""]
        for hit in hits: lines += [f"{hit['source']}:{hit['line']} Â· {hit['kind']}", hit['text'], ""]
        self._set_text(self.evidence_preview, "\n".join(lines)); self._set_status(f"Found {len(hits)} case result(s)")

    # Precognitive Case Map ---------------------------------------

    def _build_case_map(self) -> None:
        page = self.pages["map"]
        inner = tk.Frame(page, bg=PAGE)
        inner.pack(fill="both", expand=True, padx=26, pady=18)

        header = self._section_title(
            inner,
            "Precognitive Case Map",
            "A deterministic map of possible next states. Double-click a transition to see the map inside it.",
        )
        header.pack(fill="x")
        guard = tk.Label(
            header,
            text="STRUCTURAL FORECAST · NOT A COURT-OUTCOME PREDICTION · TRUST LOCK UNCHANGED",
            bg="#F2EEFF", fg=PURPLE, font=("Segoe UI", 8, "bold"), padx=10, pady=5,
        )
        guard.pack(side="right", anchor="e")

        controls = tk.Frame(inner, bg=PAGE)
        controls.pack(fill="x", pady=(12, 8))
        self.map_back_button = ttk.Button(controls, text="â† Back", command=self._map_back, style="Quiet.TButton")
        self.map_back_button.pack(side="left")
        ttk.Button(controls, text="Root", command=self._map_root, style="Quiet.TButton").pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="−", command=lambda: self._map_zoom(0.86), style="Quiet.TButton", width=3).pack(side="left", padx=(16, 0))
        ttk.Button(controls, text="＋", command=lambda: self._map_zoom(1.16), style="Quiet.TButton", width=3).pack(side="left", padx=(4, 0))
        ttk.Button(controls, text="Rebuild map", command=lambda: self._refresh_case_map(force=True), style="Quiet.TButton").pack(side="right")
        self.map_breadcrumb = tk.Label(controls, text="Case map", bg=PAGE, fg=MUTED, font=("Segoe UI", 8, "bold"))
        self.map_breadcrumb.pack(side="left", padx=14)

        pane = ttk.Panedwindow(inner, orient="horizontal")
        pane.pack(fill="both", expand=True)
        map_card = self._card(pane)
        details = self._card(pane)
        pane.add(map_card, weight=4)
        pane.add(details, weight=2)

        canvas_frame = tk.Frame(map_card, bg="#F8FBFE")
        canvas_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.map_canvas = tk.Canvas(
            canvas_frame, bg="#F8FBFE", highlightthickness=0,
            xscrollincrement=20, yscrollincrement=20,
        )
        xscroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.map_canvas.xview)
        yscroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.map_canvas.yview)
        self.map_canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.map_canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.map_canvas.bind("<Configure>", lambda _event: self.after_idle(self._draw_transition_map))
        self.map_canvas.bind("<Button-1>", self._map_canvas_click)
        self.map_canvas.bind("<Double-Button-1>", self._map_canvas_double_click)
        self.map_canvas.bind("<MouseWheel>", self._map_mousewheel)
        self.map_canvas.bind("<Button-4>", lambda _event: self._map_zoom(1.08))
        self.map_canvas.bind("<Button-5>", lambda _event: self._map_zoom(0.92))

        top = tk.Frame(details, bg=CARD)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="TRANSITION INSPECTOR", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        self.map_open_button = ttk.Button(top, text="Open selected", command=self._map_open_selected, style="Quiet.TButton")
        self.map_open_button.pack(side="right")
        self.map_open_button.configure(state="disabled")
        self.map_detail = tk.Text(
            details, wrap="word", state="disabled", bg="#FBFCFE", fg=TEXT,
            font=("Segoe UI", 9), relief="flat", padx=12, pady=10, height=14,
        )
        self.map_detail.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        tk.Label(details, text="PARLIAMENT PROJECTIONS", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(4, 3))
        self.map_parliament = tk.Text(
            details, wrap="word", state="disabled", bg="#F5F2FC", fg=TEXT,
            font=("Segoe UI", 8), relief="flat", padx=10, pady=8, height=13,
        )
        self.map_parliament.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        hint = tk.Label(
            inner,
            text="Click to inspect · double-click to zoom semantically · mouse wheel changes optical zoom · every source and cancellation remains traceable",
            bg=PAGE, fg=MUTED, font=("Segoe UI", 8),
        )
        hint.pack(anchor="w", pady=(7, 0))

    def _refresh_case_map(self, force: bool = False) -> None:
        if not hasattr(self, "map_canvas"):
            return
        if not self.active_case:
            self.transition_map_model = None
            self.transition_view_id = "root"
            self.transition_selection = None
            self._set_text(self.map_detail, "Select a case with indexed evidence to construct its transition map.")
            self._set_text(self.map_parliament, "The Parliament activates after the first document RPM index exists.")
            self._draw_transition_map()
            return
        try:
            previous_signature = self.transition_map_model.input_signature if self.transition_map_model else ""
            model = self.workspace.case_transition_map(self.active_case, force=force)
            self.transition_map_model = model
            if force or previous_signature != model.input_signature or self.transition_view_id not in model.views:
                self.transition_view_id = model.root_view
                self.transition_selection = None
                self.transition_scale = 1.0
            self._paint_parliament()
            self._draw_transition_map()
            self._set_status(
                f"Case Map ready · {len(model.view().edges)} root transition(s) · replay {model.replay_signature[:10]}"
            )
        except Exception as exc:
            self.transition_map_model = None
            self._set_text(self.map_detail, f"Case Map unavailable:\n\n{exc}")
            self._set_text(self.map_parliament, "No projection was produced.")
            self._draw_transition_map()

    def _paint_parliament(self) -> None:
        model = self.transition_map_model
        if not model:
            self._set_text(self.map_parliament, "No map is loaded.")
            return
        lines: list[str] = []
        for item in model.projections:
            lines.extend((
                f"{item.role.upper()} · {item.headline}",
                item.detail,
                f"Channel {item.channel} · Trust Lock {item.bracket} · pressure {item.pressure:.2f}",
                "",
            ))
        self._set_text(self.map_parliament, "\n".join(lines).rstrip())

    @staticmethod
    def _map_channel_color(channel: str) -> str:
        return {"A": ACCENT, "B": PURPLE, "C": ORANGE, "ZERO": MUTED}.get(channel, MUTED)

    @staticmethod
    def _map_bracket_color(bracket: str) -> str:
        return {"VALIDATED": GREEN, "EXPLAINED": PURPLE,
                "SPECULATIVE": YELLOW, "UNVERIFIED": MUTED}.get(bracket.upper(), MUTED)

    def _map_positions(self, nodes: list[MapNode], width: int, height: int) -> dict[str, tuple[float, float]]:
        if self.transition_view_id == "root":
            fixed = {
                "anchor:ZERO": (width * .50, height * .52),
                "anchor:A": (width * .18, height * .73),
                "anchor:B": (width * .50, height * .20),
                "anchor:C": (width * .82, height * .73),
            }
            return {node.id: fixed.get(node.id, (width * .5, height * .5)) for node in nodes}
        count = len(nodes)
        if count <= 3:
            return {
                node.id: (width * (index + 1) / (count + 1), height * .48)
                for index, node in enumerate(nodes)
            }
        radius_x = max(160.0, width * .34)
        radius_y = max(120.0, height * .31)
        center_x, center_y = width * .50, height * .51
        ordered = sorted(nodes, key=lambda item: item.id)
        return {
            node.id: (
                center_x + radius_x * math.cos(-math.pi / 2 + 2 * math.pi * index / count),
                center_y + radius_y * math.sin(-math.pi / 2 + 2 * math.pi * index / count),
            )
            for index, node in enumerate(ordered)
        }

    def _draw_transition_map(self) -> None:
        if not hasattr(self, "map_canvas"):
            return
        canvas = self.map_canvas
        canvas.delete("all")
        model = self.transition_map_model
        if not model:
            width = max(canvas.winfo_width(), 640)
            height = max(canvas.winfo_height(), 420)
            canvas.create_text(
                width / 2, height / 2 - 18, text="NO CASE MAP YET", fill=MUTED,
                font=("Segoe UI", 14, "bold"),
            )
            canvas.create_text(
                width / 2, height / 2 + 16,
                text="Add evidence and build its Float / Mix / Stir indexes.",
                fill=MUTED, font=("Segoe UI", 9),
            )
            return

        view = model.view(self.transition_view_id)
        width = max(canvas.winfo_width() - 30, 720)
        height = max(canvas.winfo_height() - 30, 500)
        nodes = list(view.nodes)
        edges = list(view.edges)
        positions = self._map_positions(nodes, width, height)

        pair_counts: dict[tuple[str, str], int] = {}
        pair_seen: dict[tuple[str, str], int] = {}
        for edge in edges:
            pair = tuple(sorted((edge.source, edge.target)))
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        for edge in edges:
            if edge.source not in positions or edge.target not in positions:
                continue
            x1, y1 = positions[edge.source]
            x2, y2 = positions[edge.target]
            pair = tuple(sorted((edge.source, edge.target)))
            index = pair_seen.get(pair, 0)
            pair_seen[pair] = index + 1
            total = pair_counts[pair]
            color = self._map_channel_color(edge.residue)
            tag = f"edge::{edge.id}"
            if edge.source == edge.target:
                radius = 45 + index * 12
                coords = (x1 - radius, y1 - radius, x1 + radius, y1 + radius)
                canvas.create_arc(*coords, start=25, extent=300, style="arc", outline=color,
                                  width=2, tags=(tag, "map-hit"))
                mid_x, mid_y = x1 + radius, y1 - radius * .35
            else:
                dx, dy = x2 - x1, y2 - y1
                length = max(1.0, math.hypot(dx, dy))
                offset = (index - (total - 1) / 2) * 25.0
                nx, ny = -dy / length, dx / length
                ox, oy = nx * offset, ny * offset
                canvas.create_line(
                    x1 + ox, y1 + oy, x2 + ox, y2 + oy,
                    fill=color, width=2 + min(5, math.log1p(max(0.0, edge.pressure))),
                    arrow="last", arrowshape=(10, 12, 5), smooth=True,
                    tags=(tag, "map-hit"),
                )
                mid_x, mid_y = (x1 + x2) / 2 + ox, (y1 + y2) / 2 + oy
            label = edge.label if len(edge.label) <= 26 else edge.label[:25] + "…"
            text_width = max(76, min(190, 7 * len(label) + 18))
            canvas.create_rectangle(
                mid_x - text_width / 2, mid_y - 17, mid_x + text_width / 2, mid_y + 17,
                fill=CARD, outline=self._map_bracket_color(edge.bracket), width=2,
                tags=(tag, "map-hit"),
            )
            canvas.create_text(
                mid_x, mid_y - 3, text=label, fill=TEXT, font=("Segoe UI", 8, "bold"),
                width=text_width - 10, tags=(tag, "map-hit"),
            )
            canvas.create_text(
                mid_x, mid_y + 9, text=f"residue {edge.residue} · P {edge.pressure:.2f}",
                fill=MUTED, font=("Segoe UI", 7), tags=(tag, "map-hit"),
            )

        for node in nodes:
            x, y = positions[node.id]
            anchor = node.kind == "anchor"
            radius = 54 if anchor else 43
            fill = self._map_channel_color(node.channel)
            tag = f"node::{node.id}"
            canvas.create_oval(
                x - radius, y - radius, x + radius, y + radius,
                fill=fill, outline=self._map_bracket_color(node.bracket), width=3,
                tags=(tag, "map-hit"),
            )
            label = node.label if len(node.label) <= 36 else node.label[:35] + "…"
            canvas.create_text(
                x, y - 5, text=label, fill="white", font=("Segoe UI", 8, "bold"),
                width=radius * 1.65, justify="center", tags=(tag, "map-hit"),
            )
            if not anchor:
                canvas.create_text(
                    x, y + radius - 13, text=f"{node.kind} · P {node.pressure:.2f}",
                    fill="white", font=("Segoe UI", 7), tags=(tag, "map-hit"),
                )

        if self.transition_scale != 1.0:
            canvas.scale("all", width / 2, height / 2, self.transition_scale, self.transition_scale)
        bbox = canvas.bbox("all")
        if bbox:
            canvas.configure(scrollregion=(bbox[0] - 70, bbox[1] - 70, bbox[2] + 70, bbox[3] + 70))
        crumbs = model.breadcrumbs(view.id)
        self.map_breadcrumb.configure(text="  ›  ".join(item.label for item in crumbs))
        self.map_back_button.configure(state="normal" if view.parent else "disabled")
        if not self.transition_selection:
            self._set_text(
                self.map_detail,
                f"{view.label}\n\n{view.description}\n\n"
                f"{len(view.nodes)} state node(s) · {len(view.edges)} transition(s)\n"
                f"Replay signature: {model.replay_signature}\n\n"
                "Select an item to inspect its channel, provenance, pressure and Trust Lock.",
            )

    def _map_current_target(self) -> tuple[str, str] | None:
        tags = self.map_canvas.gettags("current")
        for tag in tags:
            if tag.startswith("node::"):
                return "node", tag[6:]
            if tag.startswith("edge::"):
                return "edge", tag[6:]
        return None

    def _map_find_item(self, target: tuple[str, str] | None) -> MapNode | MapEdge | None:
        if not target or not self.transition_map_model:
            return None
        kind, item_id = target
        view = self.transition_map_model.view(self.transition_view_id)
        values = view.nodes if kind == "node" else view.edges
        return next((item for item in values if item.id == item_id), None)

    def _map_canvas_click(self, _event=None) -> None:
        target = self._map_current_target()
        item = self._map_find_item(target)
        if not target or item is None:
            return
        self.transition_selection = target
        self._inspect_map_item(item)

    def _map_canvas_double_click(self, _event=None) -> None:
        target = self._map_current_target()
        item = self._map_find_item(target)
        if target and item is not None:
            self.transition_selection = target
            self._inspect_map_item(item)
            self._map_open_selected()

    def _inspect_map_item(self, item: MapNode | MapEdge) -> None:
        depth = 0
        if self.transition_map_model:
            depth = max(0, len(self.transition_map_model.breadcrumbs(self.transition_view_id)) - 1)
        if isinstance(item, MapNode):
            lines = [
                item.label, "",
                f"Type               {item.kind}",
                f"Channel            {item.channel} / k{item.anchor}",
                f"Relational pressure {item.pressure:.4f}",
                f"Trust Lock         {item.bracket}",
                f"Causal depth (τ)   {depth}",
                f"Evidence mass      {len(item.provenance)} provenance item(s)",
                f"Semantic zoom      {'Available' if item.focus_view else 'Leaf state'}", "",
                "PROVENANCE",
            ]
        else:
            lines = [
                item.label, "",
                f"Transition         {item.source} → {item.target}",
                f"Klein residue      {item.residue}",
                f"Relational pressure {item.pressure:.4f}",
                f"Trust Lock         {item.bracket}",
                f"Causal depth (τ)   {depth}",
                f"Evidence mass      {len(item.provenance)} provenance item(s)",
                f"Semantic zoom      {'Available' if item.focus_view else 'Leaf transition'}", "",
                "PROVENANCE",
            ]
        lines.extend(f"• {source}" for source in item.provenance)
        lines.extend(("", "DETAILS"))
        for key, value in sorted(dict(item.metadata).items()):
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            lines.append(f"{key.replace('_', ' ').title()}: {rendered}")
        lines.extend(("", "Pressure cannot promote or demote this Trust Lock."))
        self._set_text(self.map_detail, "\n".join(lines))
        self.map_open_button.configure(state="normal" if item.focus_view else "disabled")

    def _map_open_selected(self) -> None:
        item = self._map_find_item(self.transition_selection)
        if item is None or not item.focus_view or not self.transition_map_model:
            return
        if item.focus_view not in self.transition_map_model.views:
            return
        self.transition_view_id = item.focus_view
        self.transition_selection = None
        self.transition_scale = 1.0
        self.map_open_button.configure(state="disabled")
        self._draw_transition_map()

    def _map_back(self) -> None:
        if not self.transition_map_model:
            return
        view = self.transition_map_model.view(self.transition_view_id)
        if view.parent and view.parent in self.transition_map_model.views:
            self.transition_view_id = view.parent
            self.transition_selection = None
            self.transition_scale = 1.0
            self.map_open_button.configure(state="disabled")
            self._draw_transition_map()

    def _map_root(self) -> None:
        if not self.transition_map_model:
            return
        self.transition_view_id = self.transition_map_model.root_view
        self.transition_selection = None
        self.transition_scale = 1.0
        self.map_open_button.configure(state="disabled")
        self._draw_transition_map()

    def _map_zoom(self, factor: float) -> None:
        self.transition_scale = max(.55, min(2.5, self.transition_scale * factor))
        self._draw_transition_map()

    def _map_mousewheel(self, event) -> str:
        self._map_zoom(1.08 if event.delta > 0 else .92)
        return "break"

    # Research ------------------------------------------------------

    def _build_research(self) -> None:
        page = self.pages["research"]
        inner = tk.Frame(page, bg=PAGE); inner.pack(fill="both", expand=True, padx=26, pady=20)
        self._section_title(inner, "PSi Legal research", "Search stored legal records. Results are retrieved authorities, never generated citations.").pack(fill="x")
        self.psi_placeholder = self._build_psi_placeholder(inner)
        self.research_workspace = tk.Frame(inner, bg=PAGE)
        self.research_workspace.pack(fill="both", expand=True)
        search_card = self._card(self.research_workspace); search_card.pack(fill="x", pady=(15, 12))
        row = tk.Frame(search_card, bg=CARD); row.pack(fill="x", padx=14, pady=13)
        self.search_value = tk.StringVar(); self.search_entry = ttk.Entry(row, textvariable=self.search_value, font=("Segoe UI", 11)); self.search_entry.pack(side="left", fill="x", expand=True); self.search_entry.bind("<Return>", lambda _e: self._run_search())
        self.jurisdiction_value = tk.StringVar(); ttk.Entry(row, textvariable=self.jurisdiction_value, width=14).pack(side="left", padx=8)
        self.search_button = ttk.Button(row, text="Search PSi Legal", command=self._run_search, style="Accent.TButton"); self.search_button.pack(side="left")
        pane = ttk.Panedwindow(self.research_workspace, orient="vertical"); pane.pack(fill="both", expand=True)
        result_card = self._card(pane); detail_card = self._card(pane); pane.add(result_card, weight=3); pane.add(detail_card, weight=2)
        result_header = tk.Frame(result_card, bg=CARD); result_header.pack(fill="x", padx=12, pady=(9, 5))
        tk.Label(result_header, text="STORED AUTHORITIES", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        self.selected_count = tk.Label(result_header, text="0 selected for analysis", bg="#FFF4E8", fg=ORANGE, font=("Segoe UI", 8, "bold"), padx=9, pady=4); self.selected_count.pack(side="right")
        tree_frame = tk.Frame(result_card, bg=CARD); tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        columns = ("year", "jurisdiction", "bracket", "rpm", "title")
        self.result_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        for column, width, label in (("year",65,"Year"),("jurisdiction",105,"Jurisdiction"),("bracket",100,"Trust lock"),("rpm",100,"Float/Mix/Stir"),("title",750,"Case / stored title")):
            self.result_tree.heading(column, text=label); self.result_tree.column(column, width=width, anchor="w")
        self.result_tree.tag_configure("VALIDATED", foreground=GREEN); self.result_tree.tag_configure("EXPLAINED", foreground=PURPLE); self.result_tree.tag_configure("SPECULATIVE", foreground=ORANGE); self.result_tree.tag_configure("UNVERIFIED", foreground=MUTED)
        self.result_tree.bind("<<TreeviewSelect>>", self._research_selection); self.result_tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_frame, command=self.result_tree.yview); scroll.pack(side="right", fill="y"); self.result_tree.configure(yscrollcommand=scroll.set)
        detail_header = tk.Frame(detail_card, bg=CARD); detail_header.pack(fill="x", padx=12, pady=(9, 5))
        tk.Label(detail_header, text="AUTHORITY DETAILS", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Button(detail_header, text="Open private analysis â†’", command=lambda: self._show_page("analysis"), style="Quiet.TButton").pack(side="right")
        ttk.Button(detail_header, text="Attach selected to case", command=self._attach_selected_authorities, style="Quiet.TButton").pack(side="right", padx=6)
        self.result_detail = tk.Text(detail_card, wrap="word", state="disabled", bg="#FBFCFE", fg=TEXT, font=("Segoe UI", 9), relief="flat", padx=12, pady=10)
        self.result_detail.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.result_detail.tag_configure("title", font=("Segoe UI", 12, "bold"), foreground=TEXT)
        self.result_detail.tag_configure("label", font=("Segoe UI", 8, "bold"), foreground=MUTED)
        self.result_detail.tag_configure("excerpt", font=("Segoe UI", 9), foreground=TEXT, spacing1=5)

    def _build_psi_placeholder(self, parent: tk.Widget) -> tk.Frame:
        card = self._card(parent)
        card.pack(fill="both", expand=True, pady=(15, 0))
        hero = tk.Frame(card, bg="#EAF5FD")
        hero.pack(fill="x")
        badges = tk.Frame(hero, bg="#EAF5FD")
        badges.pack(anchor="w", padx=22, pady=(20, 8))
        tk.Label(badges, text="SEPARATE MICROSOFT STORE PRODUCT", bg="#D8EDFB", fg=ACCENT,
                 font=("Segoe UI", 8, "bold"), padx=9, pady=5).pack(side="left")
        tk.Label(badges, text="5+ MILLION INDEXED CASE-LAW RECORDS Â· UPDATES INCLUDED", bg="#E6F6EF", fg=GREEN,
                 font=("Segoe UI", 8, "bold"), padx=9, pady=5).pack(side="left", padx=7)
        tk.Label(badges, text="COMPLETELY OFFLINE & PRIVATE", bg="#F2EEFF", fg=PURPLE,
                 font=("Segoe UI", 8, "bold"), padx=9, pady=5).pack(side="left")
        tk.Label(hero, text="PSi Legal â€” Private, Local Case-Law Research", bg="#EAF5FD", fg=TEXT,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22)
        description = (
            "PSi Legal is the research companion for PAi Legal and includes a database of more than 5 million "
            "indexed case-law records, with updates included. It searches case-law records stored on this "
            "computer and returns the actual indexed authorityâ€”not an AI-generated citation. Each result can "
            "carry its court or jurisdiction, year, citation, source identifier, stored excerpt, Trust Lock, "
            "Float observations, Mix relations, Stir recurrence, total relational pressure and pattern signature."
        )
        tk.Label(hero, text=description, bg="#EAF5FD", fg=TEXT, font=("Segoe UI", 10),
                 wraplength=1050, justify="left").pack(anchor="w", padx=22, pady=(8, 10))
        tk.Label(hero, text="All searching, indexing and case hand-off run completely offline and privately on this device. Case files, search terms, prompts and results are not transmitted. PAi Legal remains fully usable when PSi Legal is not installed.",
                 bg="#EAF5FD", fg=PURPLE, font=("Segoe UI", 9, "bold"), wraplength=1050,
                 justify="left").pack(anchor="w", padx=22, pady=(0, 20))

        features = tk.Frame(card, bg=CARD)
        features.pack(fill="x", padx=16, pady=16)
        feature_rows = (
            ("INCLUDED CASE-LAW DATABASE", "Search more than 5 million indexed case-law records by issue and jurisdiction. Database updates are included, and every result can be inspected before use."),
            ("RPM + TRUST LOCKS", "See Float/Mix/Stir values, relational pressure, pattern signatures and the authority's existing Trust Lock without allowing pressure to promote status."),
            ("PERSISTENT CASE HAND-OFF", "Select authorities for an answer or attach them permanently to the active case so their identifiers, excerpts and epistemic metadata travel into analysis and export."),
        )
        for index, (title, body) in enumerate(feature_rows):
            feature = tk.Frame(features, bg="#F8FAFC", highlightbackground=BORDER, highlightthickness=1)
            feature.pack(side="left", fill="both", expand=True, padx=(0, 9 if index < 2 else 0))
            tk.Label(feature, text=title, bg="#F8FAFC", fg=ACCENT, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=13, pady=(12, 5))
            tk.Label(feature, text=body, bg="#F8FAFC", fg=TEXT, font=("Segoe UI", 9), wraplength=310,
                     justify="left").pack(anchor="w", padx=13, pady=(0, 13))

        handoff = tk.Frame(card, bg="#F2EEFF", highlightbackground="#DDD3F8", highlightthickness=1)
        handoff.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(handoff, text="WORKFLOW", bg="#F2EEFF", fg=PURPLE, font=("Segoe UI", 8, "bold")).pack(side="left", padx=(13, 8), pady=10)
        tk.Label(handoff, text="Search PSi Legal  â†’  inspect stored authority  â†’  select or attach  â†’  analyze privately in PAi Legal  â†’  export with brackets preserved",
                 bg="#F2EEFF", fg=TEXT, font=("Segoe UI", 9), wraplength=900, justify="left").pack(side="left", padx=(0, 13), pady=10)

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", padx=16, pady=(0, 17))
        ttk.Button(actions, text="Get PSi Legal from Microsoft Store", command=self._open_psi_legal_store,
                   style="Accent.TButton").pack(side="left")
        ttk.Button(actions, text="I installed it â€” refresh", command=self._refresh_capabilities,
                   style="Quiet.TButton").pack(side="left", padx=8)
        tk.Label(actions, text="No cloud account, API key or connection is required for normal use.", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="right")
        return card

    def _open_psi_legal_store(self) -> None:
        status = self.report.statuses.get(Capability.CORPUS)
        if status and status.remedy_link:
            _open_uri(status.remedy_link)
            self._set_status("Opening PSi Legal in the Microsoft Store")
        else:
            self._show_page("settings")

    # Analysis ------------------------------------------------------

    def _build_analysis(self) -> None:
        page = self.pages["analysis"]
        inner = tk.Frame(page, bg=PAGE); inner.pack(fill="both", expand=True, padx=26, pady=20)
        top = self._section_title(inner, "Private case analysis", "Uses only the active case record and PSi authorities you selected.")
        top.pack(fill="x")
        legend = tk.Frame(top, bg=PAGE); legend.pack(side="right")
        for text, color in (("[{ }] Unverified",MUTED),("[[ ]] Speculative",ORANGE),("{[ ]} Explained",PURPLE),("[[[ ]]] Validated",GREEN)):
            tk.Label(legend, text=text, bg=CARD, fg=color, font=("Segoe UI", 8, "bold"), padx=7, pady=4, highlightbackground=BORDER, highlightthickness=1).pack(side="left", padx=3)
        tk.Label(top, text="Pressure is observed; it cannot promote or demote a Trust Lock.", bg=PAGE, fg=PURPLE, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(7, 0))
        self.authority_strip = tk.Frame(inner, bg="#EEF5FB", highlightbackground=BORDER, highlightthickness=1)
        self.authority_strip.pack(fill="x", pady=(12, 0))
        tk.Label(self.authority_strip, text="AUTHORITIES IN THIS ANALYSIS", bg="#EEF5FB", fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(7, 2))
        self.authority_chips = tk.Frame(self.authority_strip, bg="#EEF5FB")
        self.authority_chips.pack(fill="x", padx=9, pady=(0, 7))
        chat_card = self._card(inner); chat_card.pack(fill="both", expand=True, pady=(14, 10))
        self.analysis_log = tk.Text(chat_card, wrap="word", state="disabled", bg=CARD, fg=TEXT, font=("Segoe UI", 10), relief="flat", padx=20, pady=16, spacing2=2)
        self.analysis_log.pack(fill="both", expand=True)
        self.analysis_log.tag_configure("speaker-user", font=("Segoe UI", 9, "bold"), foreground=ACCENT, spacing1=12)
        self.analysis_log.tag_configure("speaker-ai", font=("Segoe UI", 9, "bold"), foreground=PURPLE, spacing1=12)
        self.analysis_log.tag_configure("speaker-system", font=("Segoe UI", 9, "bold"), foreground=MUTED, spacing1=12)
        self.analysis_log.tag_configure("unverified", foreground=MUTED, background="#F2F4F7")
        self.analysis_log.tag_configure("speculative", foreground="#9A531F", background="#FFF5E9")
        self.analysis_log.tag_configure("explained", foreground="#5B4397", background="#F3EEFF")
        self.analysis_log.tag_configure("validated", foreground="#087A5B", background="#EAF8F3")
        self.analysis_log.tag_configure("source", foreground=ACCENT, underline=True)
        for tag, note in (("unverified","Unverified working or supplied claim"),("speculative","Speculative inference; not independently corroborated"),("explained","Known result with relational explanation"),("validated","Independently corroborated claim")):
            self.analysis_log.tag_bind(tag, "<Enter>", lambda _event, value=note: self._set_status(value))
            self.analysis_log.tag_bind(tag, "<Leave>", lambda _event: self._set_status("Pressure observed; Trust Lock unchanged"))
        actions = tk.Frame(inner, bg=PAGE); actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Pin selected claim", command=self._pin_selected_claim, style="Quiet.TButton").pack(side="left")
        ttk.Button(actions, text="ï¼‹ Add case note", command=self._add_case_note, style="Quiet.TButton").pack(side="left", padx=6)
        ttk.Button(actions, text="Export case record", command=self._export_case, style="Quiet.TButton").pack(side="right")
        self.epistemic_summary = tk.Label(actions, text="Claims: 0 [{ }]  0 [[ ]]  0 {[ ]}  0 [[[ ]]]  Â·  Pressure observed; status unchanged", bg="#F2EEFF", fg=PURPLE, font=("Segoe UI", 8, "bold"), padx=9, pady=5)
        self.epistemic_summary.pack(side="right", padx=8)
        composer = self._card(inner); composer.pack(fill="x")
        scope_row = tk.Frame(composer, bg=CARD); scope_row.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(scope_row, text="MATTER SCOPE", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self.analysis_matter_value = tk.StringVar(value="All documents (no separate matter detected)")
        self.analysis_matter_picker = ttk.Combobox(
            scope_row, textvariable=self.analysis_matter_value, state="readonly", width=52)
        self.analysis_matter_picker.pack(side="left", padx=(8, 0))
        self.analysis_matter_picker.bind("<<ComboboxSelected>>", lambda _event: self._update_analysis_context())
        self.matter_by_label: Dict[str, str] = {}
        compose_row = tk.Frame(composer, bg=CARD); compose_row.pack(fill="x", padx=12, pady=12)
        self.analysis_question = tk.StringVar(); self.analysis_entry = ttk.Entry(compose_row, textvariable=self.analysis_question, font=("Segoe UI", 11)); self.analysis_entry.pack(side="left", fill="x", expand=True); self.analysis_entry.bind("<Return>", lambda _e: self._run_analysis())
        self.analysis_button = ttk.Button(compose_row, text="Analyze privately", command=self._run_analysis, style="Accent.TButton"); self.analysis_button.pack(side="left", padx=(8, 0))
        self.analysis_context = tk.Label(composer, text="Select an active case to begin.", bg=CARD, fg=MUTED, font=("Segoe UI", 8))
        self.analysis_context.pack(anchor="w", padx=14, pady=(0, 10))

    # Settings ------------------------------------------------------

    def _build_settings(self) -> None:
        page = self.pages["settings"]
        inner = tk.Frame(page, bg=PAGE); inner.pack(fill="both", expand=True, padx=26, pady=20)
        self._section_title(inner, "Settings & system status", "Customer controls first. Technical diagnostics remain available below.").pack(fill="x")
        integrations = tk.Frame(inner, bg=PAGE); integrations.pack(fill="x", pady=(15, 12))
        self.integration_cards: Dict[Capability, tuple[tk.Label, tk.Label, tk.Frame]] = {}
        for capability, title in ((Capability.ANALYSIS,"Private AI"),(Capability.CORPUS,"PSi Legal research")):
            card = self._card(integrations); card.pack(side="left", fill="both", expand=True, padx=(0, 10))
            dot = tk.Label(card, text="â—", bg=CARD, fg=MUTED, font=("Segoe UI", 13, "bold")); dot.pack(anchor="w", padx=16, pady=(14, 2))
            tk.Label(card, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16)
            summary = tk.Label(card, text="Checkingâ€¦", bg=CARD, fg=MUTED, font=("Segoe UI", 8), wraplength=440, justify="left"); summary.pack(anchor="w", padx=16, pady=(4, 10))
            actions = tk.Frame(card, bg=CARD); actions.pack(fill="x", padx=12, pady=(0, 12))
            self.integration_cards[capability] = (dot, summary, actions)
        management = self._card(inner); management.pack(fill="x", pady=(0, 12))
        left = tk.Frame(management, bg=CARD); left.pack(side="left", fill="both", expand=True, padx=16, pady=12)
        tk.Label(left, text="CASE MANAGEMENT", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.case_management_status = tk.Label(left, text="Archive completed matters without deleting them.", bg=CARD, fg=TEXT, font=("Segoe UI", 9)); self.case_management_status.pack(anchor="w", pady=(4, 0))
        right = tk.Frame(management, bg=CARD); right.pack(side="right", padx=12, pady=10)
        ttk.Button(right, text="Archive active case", command=self._archive_active_case, style="Quiet.TButton").pack(side="left", padx=4)
        ttk.Button(right, text="Restore archived case", command=self._restore_archived_case, style="Quiet.TButton").pack(side="left", padx=4)
        professional = self._card(inner); professional.pack(fill="x", pady=(0, 12))
        pro_left = tk.Frame(professional, bg=CARD); pro_left.pack(side="left", fill="both", expand=True, padx=16, pady=12)
        tk.Label(pro_left, text="PROFESSIONAL CONTROLS", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.professional_status = tk.Label(pro_left, text="Checking role, vault, encryption, and audit controlsâ€¦",
                                            bg=CARD, fg=TEXT, font=("Segoe UI", 9), justify="left", anchor="w")
        self.professional_status.pack(fill="x", pady=(4, 0))
        pro_actions = tk.Frame(professional, bg=CARD); pro_actions.pack(side="right", padx=12, pady=10)
        ttk.Button(pro_actions, text="Require encrypted volume", command=self._enable_encryption_policy,
                   style="Quiet.TButton").pack(side="left", padx=4)
        ttk.Button(pro_actions, text="Manage role", command=self._manage_role_dialog,
                   style="Quiet.TButton").pack(side="left", padx=4)
        ttk.Button(pro_actions, text="Store PSi token", command=self._store_psi_token,
                   style="Quiet.TButton").pack(side="left", padx=4)
        model = self._card(inner); model.pack(fill="x", pady=(0, 12))
        tk.Label(model, text="INSTALLED MODEL", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(10, 2))
        self.model_detail = tk.Label(model, text="No private model installation detected.", bg=CARD, fg=TEXT, font=("Segoe UI", 9), justify="left", anchor="w")
        self.model_detail.pack(fill="x", padx=16, pady=(2, 10))
        advanced = self._card(inner); advanced.pack(fill="both", expand=True)
        top = tk.Frame(advanced, bg=CARD); top.pack(fill="x", padx=12, pady=(9, 5))
        tk.Label(top, text="ADVANCED SYSTEM DETAILS", bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Button(top, text="Refresh status", command=self._refresh_capabilities, style="Quiet.TButton").pack(side="right")
        self.diagnostics_text = tk.Text(advanced, wrap="word", state="disabled", bg="#F8FAFC", fg="#405064", font=("Consolas", 8), relief="flat", padx=12, pady=10, height=12)
        self.diagnostics_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # Cases ---------------------------------------------------------

    def _refresh_cases(self) -> None:
        cases = self.workspace.list_cases(); self.case_map = {case.label: case for case in cases}; self.case_combo["values"] = list(self.case_map)
        if not self.active_case and len(cases) == 1:
            self.case_value.set(cases[0].label); self._activate_case(cases[0])


    def _purchase_annual_access(self) -> None:
        try:
            status = self.workspace.purchase_annual_access()
        except Exception as exc:
            self._inline_error(str(exc))
            return
        expiry = str(status.get("annual_expires_at") or "")
        detail = "Annual PAi Legal access is active."
        if expiry:
            detail += f"\n\nCurrent entitlement expires/renews through Microsoft: {expiry}"
        messagebox.showinfo("PAi Legal annual access", detail, parent=self)
        self._set_status("Microsoft Store annual access is active.")

    def _open_claims_case(self) -> None:
        folder = filedialog.askdirectory(title="Open PAi Claims case workspace", parent=self)
        if not folder:
            return
        try:
            case = self.workspace.open_claims_workspace(Path(folder))
        except Exception as exc:
            self._inline_error(str(exc))
            return
        self._refresh_cases()
        self.case_value.set(case.label)
        self._activate_case(case)
        self._show_page("dashboard")
        self._set_status("PAi Claims Parliament handed off without rewriting the Claims base graph.")

    def _new_case(self) -> None:
        name = simpledialog.askstring("Create a new case", "Case or matter name:", parent=self)
        if not name: return
        parties = parties_from_caption(name)
        if parties:
            try: hits = self.workspace.conflict_check(parties)
            except Exception as exc: self._inline_error(str(exc)); return
            if hits:
                summary = "\n".join(f"â€¢ {item['queried_name']} matches {item['matched_name']} in {item['case_id']} â€” {item['case_name']}" for item in hits[:10])
                if not messagebox.askyesno(
                        "Potential conflict found",
                        "PAi Legal found possible existing-party matches:\n\n" + summary +
                        "\n\nThis is not a conflicts clearance. Continue creating the case?", parent=self):
                    return
        try: case = self.workspace.create_case(name)
        except Exception as exc: self._inline_error(str(exc)); return
        self._refresh_cases(); self.case_value.set(case.label); self._activate_case(case); self._show_page("evidence")

    def _archive_active_case(self) -> None:
        if not self.active_case: self._inline_error("Select a case to archive."); return
        if not messagebox.askyesno("Archive case", f"Archive {self.active_case.name}?\n\nThe case remains recoverable and no evidence is deleted.", parent=self): return
        name = self.active_case.name; self.workspace.archive_case(self.active_case); self.active_case = None; self.case_value.set(""); self.sidebar_case_status.configure(text="No case selected")
        self._refresh_cases(); self._refresh_dashboard(); self._refresh_evidence(); self._refresh_case_map(); self._apply_state(); self._set_status(f"Archived {name}")

    def _restore_archived_case(self) -> None:
        archived = self.workspace.list_archived_cases()
        if not archived: self._inline_error("There are no archived cases to restore."); return
        options = "\n".join(f"{case.case_id} â€” {case.name}" for case in archived)
        case_id = simpledialog.askstring("Restore archived case", "Enter the case ID to restore:\n\n" + options, parent=self)
        if not case_id: return
        try: case = self.workspace.restore_case(case_id.strip())
        except Exception as exc: self._inline_error(str(exc)); return
        self._refresh_cases(); self.case_value.set(case.label); self._activate_case(case); self._set_status(f"Restored {case.name}")

    def _conflict_check_dialog(self) -> None:
        entered = simpledialog.askstring(
            "Conflict check", "Party, client, adverse party, witness, or related-entity names\n"
            "(separate multiple names with semicolons):", parent=self)
        if not entered: return
        names = [item.strip() for item in entered.split(";") if item.strip()]
        try: hits = self.workspace.conflict_check(names)
        except Exception as exc: self._inline_error(str(exc)); return
        if not hits:
            messagebox.showinfo(
                "Conflict screening result",
                "No normalized-name match was found in this workspace.\n\n"
                "This does not clear the representation. Check former clients, affiliates, "
                "lawyer relationships, and every other required conflicts source.", parent=self)
            return
        lines = [f"{item['confidence'].upper()}: {item['queried_name']} â†” {item['matched_name']}\n"
                 f"  {item['case_id']} â€” {item['case_name']} ({item['reason']})" for item in hits]
        messagebox.showwarning("Potential conflict matches", "\n\n".join(lines[:30]) +
                               "\n\nHuman conflicts review is required.", parent=self)

    def _set_retention_dialog(self) -> None:
        if not self.active_case: self._inline_error("Select a case first."); return
        retain_until = simpledialog.askstring(
            "Set retention", "Approved retention/disposition review date (YYYY-MM-DD):", parent=self)
        if not retain_until: return
        basis = simpledialog.askstring(
            "Retention basis", "Policy, engagement term, or approval supporting that date:", parent=self)
        if not basis: return
        try: governance = self.workspace.set_retention(self.active_case, retain_until, basis)
        except Exception as exc: self._inline_error(str(exc)); return
        self._set_status(f"Retention review set for {governance['retain_until']}")

    def _legal_hold_dialog(self) -> None:
        if not self.active_case: self._inline_error("Select a case first."); return
        try: active = bool((self.workspace.case_governance(self.active_case).get("legal_hold") or {}).get("active"))
        except Exception as exc: self._inline_error(str(exc)); return
        if active:
            reason = simpledialog.askstring("Release legal hold", "Approval/reason for releasing the hold:", parent=self)
            if not reason: return
            if not messagebox.askyesno("Release legal hold", "Release the active legal hold? This action is audited.", parent=self): return
            try: self.workspace.release_legal_hold(self.active_case, reason)
            except Exception as exc: self._inline_error(str(exc)); return
            self._set_status("Legal hold released")
        else:
            reason = simpledialog.askstring("Place legal hold", "Reason for preserving this matter:", parent=self)
            if not reason: return
            try: self.workspace.place_legal_hold(self.active_case, reason)
            except Exception as exc: self._inline_error(str(exc)); return
            self._set_status("Legal hold placed â€” disposition is blocked")

    def _backup_active_case(self) -> None:
        if not self.active_case: self._inline_error("Select a case to back up."); return
        destination = filedialog.asksaveasfilename(
            title="Encrypted case backup", defaultextension=".pailbackup",
            filetypes=(("PAi Legal encrypted backup", "*.pailbackup"),))
        if not destination: return
        passphrase = simpledialog.askstring(
            "Backup passphrase", "Enter a passphrase of at least 12 characters.\n"
            "It is not stored and cannot be recovered by PAi Legal.", show="*", parent=self)
        if not passphrase: return
        try: path = self.workspace.backup_case(self.active_case, Path(destination), passphrase)
        except Exception as exc: self._inline_error(str(exc)); return
        self._set_status(f"Encrypted, manifest-verified backup created: {path.name}")

    def _restore_case_backup(self) -> None:
        source = filedialog.askopenfilename(
            title="Restore encrypted case backup",
            filetypes=(("PAi Legal encrypted backup", "*.pailbackup"),))
        if not source: return
        passphrase = simpledialog.askstring("Backup passphrase", "Enter the backup passphrase:",
                                            show="*", parent=self)
        if not passphrase: return
        try: case = self.workspace.restore_case_backup(Path(source), passphrase)
        except Exception as exc: self._inline_error(str(exc)); return
        self._refresh_cases(); self.case_value.set(case.label); self._activate_case(case)
        self._set_status(f"Verified and restored {case.name}")

    def _verify_active_audit(self) -> None:
        if not self.active_case: self._inline_error("Select a case first."); return
        try:
            result = self.workspace.verify_audit(self.active_case)
            evidence = self.workspace.verify_evidence_integrity(self.active_case)
        except Exception as exc: self._inline_error(str(exc)); return
        if result["valid"] and evidence["valid"]:
            messagebox.showinfo("Audit integrity verified",
                                f"{result['events']} chained event(s) verified with {result['algorithm']}.\n"
                                f"{evidence['checked']} preserved original(s) verified with SHA-256.\n"
                                f"Chain head: {result['head']}", parent=self)
        else:
            messagebox.showerror("Integrity failure", "\n".join((*result["errors"], *evidence["errors"])), parent=self)

    def _validate_filing_dialog(self) -> None:
        if not self.active_case: self._inline_error("Select a case first."); return
        source = filedialog.askopenfilename(
            title="Select filing text for preflight",
            filetypes=(("Text or Markdown", "*.txt *.md"), ("All files", "*.*")))
        if not source: return
        jurisdiction = simpledialog.askstring(
            "Jurisdiction rule pack", "Enter GA for Georgia Superior Court or FEDERAL for U.S. federal civil:",
            parent=self)
        if not jurisdiction: return
        document_type = simpledialog.askstring(
            "Filing type", "Filing type (complaint, petition, motion, answer, or filing):",
            initialvalue="filing", parent=self) or "filing"
        metadata = {}
        if jurisdiction.strip().lower() in {"ga", "georgia", "ga superior"}:
            county = simpledialog.askstring("Georgia county", "County:", parent=self)
            if county: metadata["county"] = county
            if document_type.lower() in {"complaint", "petition"}:
                metadata["case_filing_information_form_confirmed"] = messagebox.askyesno(
                    "Case filing information form", "Is the current case filing information form included?", parent=self)
        try:
            text = Path(source).read_text(encoding="utf-8", errors="replace")
            result = self.workspace.validate_filing(self.active_case, text, jurisdiction,
                                                    document_type, metadata)
        except Exception as exc: self._inline_error(str(exc)); return
        findings = "\n\n".join(
            f"{item['severity'].upper()} Â· {item['code']}\n{item['message']}\n{item['authority']}"
            for item in result["findings"])
        forms = "\n".join(f"â€¢ {item['title']}: {item['url']}" for item in result.get("official_forms", []))
        messagebox.showinfo(
            f"Filing preflight â€” {result['label']}",
            f"Rule pack checked as of {result['verified_as_of']}.\n\n{findings}\n\n"
            f"Official forms and directories:\n{forms}\n\n{result['disclaimer']}", parent=self)

    def _enable_encryption_policy(self) -> None:
        try:
            self.workspace.access.require("access.manage")
            current = self.workspace.storage_policy.require_encrypted_volume
            if current:
                if messagebox.askyesno("Encrypted-volume policy", "Disable strict encrypted-volume enforcement?", parent=self):
                    self.workspace.set_encryption_enforcement(False)
            else:
                status = self.workspace.storage_policy.status()
                if status.protected is not True:
                    self._inline_error("BitLocker protection is not verified for this workspace. " + status.detail); return
                if messagebox.askyesno("Encrypted-volume policy",
                                       "Require verified BitLocker protection before every future case write?", parent=self):
                    self.workspace.set_encryption_enforcement(True)
            self._show_diagnostics()
        except Exception as exc: self._inline_error(str(exc))

    def _manage_role_dialog(self) -> None:
        username = simpledialog.askstring(
            "Assign workspace role", "Operating-system account (DOMAIN\\username):", parent=self)
        if not username: return
        role = simpledialog.askstring(
            "Assign workspace role", "Role: owner, lawyer, paralegal, intake, or auditor:", parent=self)
        if not role: return
        try: self.workspace.assign_role(username, role)
        except Exception as exc: self._inline_error(str(exc)); return
        self._set_status(f"Assigned {role.lower()} role to {username.lower()}")
        self._show_diagnostics()

    def _store_psi_token(self) -> None:
        token = simpledialog.askstring(
            "Store PSi Legal token", "Enter the loopback service bearer token.\n"
            "It will be protected for this Windows account with DPAPI.", show="*", parent=self)
        if not token: return
        try: self.workspace.set_integration_secret("psi_legal_api_token", token)
        except Exception as exc: self._inline_error(str(exc)); return
        self._set_status("PSi Legal token stored in the Windows credential vault")
        self._refresh_capabilities()

    def _case_selected(self, _event=None) -> None:
        case = self.case_map.get(self.case_value.get())
        if case: self._activate_case(case)

    def _activate_case(self, case: CaseRef) -> None:
        self.active_case = case
        self.sidebar_case_status.configure(text=f"{case.document_count} documents  Â·  {case.status}", fg="#B9D3E7")
        self.title(f"PAi Legal â€” {case.name}")
        self._append_analysis("System", f"Active case: {case.name} ({case.case_id})")
        self._refresh_dashboard(); self._refresh_evidence(); self._refresh_case_map(); self._apply_state()

    # Ingestion -----------------------------------------------------

    def _add_files(self) -> None:
        if not self.active_case: self._inline_error("Create or select a case before adding evidence."); return
        paths = filedialog.askopenfilenames(title="Add evidence to active case")
        if paths: self._ingest([Path(item) for item in paths])

    def _add_folder(self) -> None:
        if not self.active_case: self._inline_error("Create or select a case before adding evidence."); return
        folder = filedialog.askdirectory(title="Add evidence folder")
        if folder: self._ingest([item for item in Path(folder).rglob("*") if item.is_file()])

    def _ingest(self, paths: List[Path]) -> None:
        if not self.active_case or not paths: return
        self._set_status(f"Preserving, extracting and indexing {len(paths)} file(s)â€¦")
        case = self.active_case
        def worker() -> None:
            results = self.workspace.ingest(case, paths)
            self.after(0, lambda: self._ingest_finished(results))
        threading.Thread(target=worker, daemon=True).start()

    def _ingest_finished(self, results: List[IngestedFile]) -> None:
        lines = []
        for result in results:
            if result.error:
                lines.append(f"âš  {result.filed_copy.name}\n{result.error}")
            else:
                lines.append(f"âœ“ {result.filed_copy.name}\nPreserved â†’ {result.extraction_method} â†’ Float/Mix/Stir indexed â†’ Ready")
        self._set_text(self.evidence_preview, "\n\n".join(lines))
        if self.active_case:
            self.active_case = next((case for case in self.workspace.list_cases() if case.case_id == self.active_case.case_id), self.active_case)
            self.sidebar_case_status.configure(text=f"{self.active_case.document_count} documents  Â·  {self.active_case.status}")
        self._refresh_evidence(); self._refresh_dashboard(); self._refresh_case_map()
        self._set_status(f"Processed {sum(1 for result in results if result.original.is_file())} of {len(results)} file(s)")

    def _build_case_record(self) -> None:
        if not self.active_case: return
        try:
            path = self.workspace.build_reasoning_corpus(self.active_case)
            self._refresh_case_map(force=True)
            self._set_status(f"Analysis record ready: {path.name}")
            self._set_text(self.evidence_preview, "âœ“ Analysis record ready\n\nEvery claim retains its source line, bracket lock and document RPM signature.")
        except Exception as exc: self._inline_error(str(exc))

    def _refresh_file_tree(self) -> None:
        self.file_paths.clear()
        for item in self.file_tree.get_children(): self.file_tree.delete(item)
        if not self.active_case: return
        counter = 0
        for folder in sorted(item for item in self.active_case.path.iterdir() if item.is_dir()):
            files = sorted(item for item in folder.iterdir() if item.is_file())
            if not files: continue
            counter += 1; parent = f"folder-{counter}"
            self.file_tree.insert("", "end", iid=parent, text=f"{FOLDER_LABELS.get(folder.name, folder.name)} ({len(files)})", values=("", ""), open=folder.name in {"01_originals", "02_text", "04_index"})
            for file in files:
                counter += 1; iid = f"file-{counter}"; self.file_paths[iid] = file
                state = "Preserved" if folder.name == "01_originals" else "Derived" if folder.name in {"02_text", "04_index", "reasoning_corpus"} else "Filed"
                self.file_tree.insert(parent, "end", iid=iid, text=file.name, values=(f"{file.stat().st_size / 1024:,.0f} KB", state))

    # Research handlers --------------------------------------------

    def _run_search(self) -> None:
        query = self.search_value.get().strip()
        if not query: return
        if not self.report.has(Capability.CORPUS): self._inline_error("PSi Legal research is not connected. Open Settings for the available remedy."); return
        self.corpus_client = self.corpus_client or PSiCorpus(self.report.statuses[Capability.CORPUS].resources)
        self.search_button.configure(state="disabled"); self._set_status("Searching stored PSi Legal recordsâ€¦")
        def worker() -> None:
            try: results, error = self.corpus_client.search(query, 20, self.jurisdiction_value.get().strip()), ""
            except Exception as exc: results, error = [], str(exc)
            self.after(0, lambda: self._search_finished(results, error))
        threading.Thread(target=worker, daemon=True).start()

    def _search_finished(self, results: List[SearchResult], error: str) -> None:
        self.search_button.configure(state="normal" if self.report.has(Capability.CORPUS) else "disabled")
        for item in self.result_tree.get_children(): self.result_tree.delete(item)
        self.search_results = results; self.selected_authorities = []
        if error: self._inline_error(error); self._set_status("PSi Legal search stopped"); return
        for index, result in enumerate(results):
            bracket = result.bracket.upper() if result.bracket else "UNVERIFIED"
            self.result_tree.insert("", "end", iid=str(index), values=(result.year, result.jurisdiction, bracket.title(), f"{result.float_points}/{result.mix_points}/{result.stir_points}", result.title), tags=(bracket,))
        self.selected_count.configure(text="0 selected for analysis")
        self._set_status(f"Found {len(results)} stored record(s)")

    def _research_selection(self, _event=None) -> None:
        selected = []
        for item in self.result_tree.selection():
            try: selected.append(self.search_results[int(item)])
            except (ValueError, IndexError): pass
        self.selected_authorities = selected; self.selected_count.configure(text=f"{len(selected)} selected for analysis")
        if not selected: self._set_text(self.result_detail, "Select one or more stored authorities to inspect and use in analysis."); return
        result = selected[-1]
        self.result_detail.configure(state="normal"); self.result_detail.delete("1.0", "end")
        self.result_detail.insert("end", result.title + "\n", "title")
        for label, value in (("COURT / JURISDICTION", result.jurisdiction), ("YEAR", result.year), ("CITATION", result.citation or "Not stored"), ("SOURCE ID", result.source_id), ("TRUST LOCK", result.bracket), ("FLOAT / MIX / STIR", f"{result.float_points} / {result.mix_points} / {result.stir_points}"), ("TOTAL PRESSURE", str(result.total_pressure)), ("TOPOLOGY", f"{result.float_color or 'â€”'} / {result.mix_color or 'â€”'} / {result.stir_color or 'â€”'}")):
            self.result_detail.insert("end", f"\n{label}\n", "label"); self.result_detail.insert("end", f"{value}\n")
        self.result_detail.insert("end", "\nSTORED EXCERPT\n", "label"); self.result_detail.insert("end", result.excerpt or "No excerpt stored.", "excerpt")
        self.result_detail.configure(state="disabled"); self._refresh_dashboard(); self._update_analysis_context()

    def _attach_selected_authorities(self) -> None:
        if not self.active_case: self._inline_error("Select a case before attaching authorities."); return
        if not self.selected_authorities: self._inline_error("Select one or more PSi authorities first."); return
        added = self.workspace.attach_authorities(self.active_case, [item.as_dict() for item in self.selected_authorities])
        self._set_status(f"Attached {added} new authority record(s) to {self.active_case.name}")
        self._update_analysis_context()

    # Analysis handlers --------------------------------------------

    def _run_analysis(self) -> None:
        if not self.active_case: self._inline_error("Select a case before analysis."); return
        if not self.report.has(Capability.ANALYSIS): self._inline_error("Private AI is not set up. Open Settings to install the recommended model."); return
        question = self.analysis_question.get().strip()
        if not question: return
        matter = self._selected_matter_scope(required=True)
        if matter is None: return
        self.last_question = question; self.analysis_question.set(""); self._append_analysis("You", question); self.analysis_button.configure(state="disabled")
        self._set_status("Private AI is analyzing the source-traced recordâ€¦")
        self.ai_client = self.ai_client or PrivateAIClient(self.report.statuses[Capability.ANALYSIS].resources)
        case = self.active_case
        authority_map = {str(item.get("source_id") or item.get("id") or item.get("title")): item for item in self.workspace.attached_authorities(case)}
        for item in self.selected_authorities: authority_map[item.source_id or item.title] = item.as_dict()
        authorities = list(authority_map.values())
        self.current_authority_ids = [str(item.get("source_id") or item.get("id") or item.get("title") or "") for item in authorities]
        corpus = None
        if self.report.has(Capability.CORPUS):
            self.corpus_client = self.corpus_client or PSiCorpus(self.report.statuses[Capability.CORPUS].resources)
            corpus = self.corpus_client
        jurisdiction = (self.jurisdiction_value.get().strip() if hasattr(self, "jurisdiction_value") else "")
        def worker() -> None:
            try:
                context = self.workspace.context(case, question=question, matter=matter)
                if not context: raise LocalAIError("Build the analysis record from Evidence before asking a question.")
                # Retrieve stored authorities for this question. Previously the
                # model saw only what the user had already searched for and
                # attached by hand, so an unasked-about doctrine was invisible
                # even with the corpus installed.
                if corpus is not None:
                    known = {str(item.get("source_id") or item.get("id") or item.get("title") or "") for item in authorities}
                    for record in self.workspace.research_for_question(
                            case, question, corpus, jurisdiction=jurisdiction, matter=matter):
                        key = str(record.get("source_id") or record.get("id") or record.get("title") or "")
                        if key and key not in known:
                            authorities.append(record); known.add(key)
                answer, error = self.ai_client.complete(question, context, authorities), ""
            except Exception as exc: answer, error = "", str(exc)
            self.after(0, lambda: self._analysis_finished(answer, error))
        threading.Thread(target=worker, daemon=True).start()

    def _analysis_finished(self, answer: str, error: str) -> None:
        self.analysis_button.configure(state="normal" if self.active_case and self.report.has(Capability.ANALYSIS) else "disabled")
        if error: self._append_analysis("System", f"Analysis unavailable: {error}"); self._set_status("Analysis stopped"); return
        self._append_analysis("PAi Legal", answer)
        counts = self.workspace.bracket_counts(answer)
        self.epistemic_summary.configure(text=f"Claims: {counts['UNVERIFIED']} [{{ }}]  {counts['SPECULATIVE']} [[ ]]  {counts['EXPLAINED']} {{[ ]}}  {counts['VALIDATED']} [[[ ]]]  Â·  Pressure observed; status unchanged")
        if self.active_case:
            summary = self.workspace.rpm_summary(self.active_case)
            self.workspace.append_event(self.active_case, "analysis_completed", {
                "question": self.last_question, "answer": answer,
                "authority_ids": self.current_authority_ids,
                "matter_scope": getattr(self, "current_matter_id", ""),
                "bracket_counts": counts, "case_pressure": summary.get("total_pressure", 0),
            })
            tensions = self.workspace.claim_tensions(self.active_case)
            if tensions: self._set_status(f"Analysis complete Â· {len(tensions)} exact-claim Trust Lock tension(s) visible")
            else: self._set_status("Private analysis complete")
        else: self._set_status("Private analysis complete")

    def _append_analysis(self, speaker: str, text: str) -> None:
        if not hasattr(self, "analysis_log"): return
        self.analysis_log.configure(state="normal")
        tag = "speaker-user" if speaker == "You" else "speaker-ai" if speaker == "PAi Legal" else "speaker-system"
        self.analysis_log.insert("end", f"\n{speaker}\n", tag)
        for line in text.strip().splitlines(): self._insert_analysis_line(line)
        self.analysis_log.see("end"); self.analysis_log.configure(state="disabled")

    def _insert_analysis_line(self, line: str) -> None:
        start = self.analysis_log.index("end-1c")
        cursor = 0
        for match_start, match_end, lock, _claim in brackets.spans(line):
            self.analysis_log.insert("end", line[cursor:match_start])
            value = line[match_start:match_end]
            self.analysis_log.insert("end", value, lock.name.lower()); cursor = match_end
        self.analysis_log.insert("end", line[cursor:] + "\n")
        for source_start, source_end, _marker in brackets.source_spans(line):
            self.analysis_log.tag_add("source", f"{start}+{source_start}c", f"{start}+{source_end}c")

    def _pin_selected_claim(self) -> None:
        if not self.active_case: self._inline_error("Select a case before pinning a claim."); return
        try: selected = self.analysis_log.get("sel.first", "sel.last").strip()
        except tk.TclError: selected = ""
        if not selected: self._inline_error("Highlight a bracketed claim in the analysis first."); return
        status, claim = "UNVERIFIED", selected
        parsed = list(brackets.spans(selected))
        if len(parsed) == 1 and parsed[0][0] == 0 and parsed[0][1] == len(selected):
            status, claim = parsed[0][2].name, parsed[0][3]
        record = self.workspace.pin_claim(self.active_case, claim, status)
        tensions = self.workspace.claim_tensions(self.active_case)
        self._set_status(f"Pinned {record['bracket'].title()} claim" + (f" Â· {len(tensions)} exact tension(s)" if tensions else ""))

    def _add_case_note(self) -> None:
        if not self.active_case: self._inline_error("Select a case before adding a note."); return
        note = simpledialog.askstring("Add case note", "Note text (stored as Unverified until independently locked):", parent=self)
        if note: self.workspace.pin_claim(self.active_case, note, "UNVERIFIED", note_type="note"); self._set_status("Case note saved with Unverified Trust Lock")

    @staticmethod
    def _drafter_page() -> Path:
        """The bundled drafter page, wherever PyInstaller put it."""
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        for candidate in (base / "resources" / "drafter.html",
                          Path(__file__).resolve().parent / "resources" / "drafter.html"):
            if candidate.is_file():
                return candidate
        return Path()

    def _serve_drafter(self, brief: dict) -> str:
        """Hand the brief to a loopback server so the page loads it itself.

        Asking someone to export a file and then find it again is a step they
        do not need. Bound to 127.0.0.1 with a per-session token, so nothing
        on the network - or in another browser tab - can read it.
        """
        page = self._drafter_page()
        if not page.is_file():
            return ""
        if self.drafter_server is None:
            self.drafter_server = DrafterServer(page)
        try:
            return self.drafter_server.publish(brief)
        except Exception:
            return ""

    def _offer_drafter(self, path: Path) -> None:
        """Open only the bundled, loopback-served drafter.

        Falling back to a remotely hosted page would give mutable third-party
        JavaScript access to any brief the user drops on it. Legal records fail
        closed instead: if the signed package omitted the bundled page, drafting
        is unavailable until the installation is repaired.
        """
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            brief = {}
        local = self._serve_drafter(brief) if brief else ""
        if not local:
            self._inline_error(
                "The case brief was saved, but the bundled PSi Drafter is missing. "
                "Repair or reinstall PAi Legal; the app will not load legal records "
                "into a remotely hosted drafting page.")
            return
        message = (f"Brief saved:\n{path}\n\n"
                   "Open PSi Drafter? It runs on this computer and loads the brief "
                   "for you.\n\nSending it to an AI provider is a separate step you "
                   "choose there.")
        if not messagebox.askyesno("Open PSi Drafter", message, parent=self):
            return
        try:
            webbrowser.open(local)
            self._set_status(f"PSi Drafter running on this computer (port {self.drafter_server.port})")
        except Exception as exc:
            self._inline_error(f"Could not open the browser: {exc}")

    def _export_case(self) -> None:
        if not self.active_case: self._inline_error("Select a case before exporting."); return
        destination = filedialog.asksaveasfilename(title="Export PAi Legal case record", defaultextension=".md", filetypes=(("Markdown work product","*.md"),("PDF work product","*.pdf"),("Drafting brief for external AI","*.json"),("Plain-English brief (name it *-plain.json)","*.json")))
        if not destination: return
        matter = self._selected_matter_scope(required=True)
        if matter is None: return
        try:
            analysis = self.analysis_log.get("1.0", "end-1c")
            corpus = None
            if self.report.has(Capability.CORPUS):
                self.corpus_client = self.corpus_client or PSiCorpus(self.report.statuses[Capability.CORPUS].resources)
                corpus = self.corpus_client
            path = self.workspace.export_case_package(
                self.active_case, Path(destination), analysis,
                [item.as_dict() for item in self.selected_authorities],
                corpus=corpus,
                jurisdiction=(self.jurisdiction_value.get().strip() if hasattr(self, "jurisdiction_value") else ""),
                matter=matter)
            self._set_status(f"Exported bracket-preserving case record: {path.name}")
            if path.suffix.lower() == ".json":
                self._offer_drafter(path)
        except Exception as exc: self._inline_error(f"Export failed: {exc}")

    def _share_encrypted_dialog(self) -> None:
        if not self.active_case:
            self._inline_error("Select a case before sharing.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Share Encrypted Bundle")
        dlg.geometry("440x290")
        dlg.configure(background=PAGE)
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Share Encrypted Bundle", font=("Segoe UI", 13, "bold"),
                 background=PAGE, foreground=TEXT).pack(pady=(18, 4))
        tk.Label(dlg, text="Choose an encryption tier for the .pailegal file.",
                 font=("Segoe UI", 9), background=PAGE, foreground=MUTED).pack()
        tier_var = tk.StringVar(value="recipient")
        for val, label, desc in (
            ("seal",      "Seal only",        "Signed, readable by anyone \u2014 good for court filing."),
            ("recipient", "Recipient-locked", "Encrypted; send the unlock code separately."),
            ("tenant",    "Tenant-locked",    "Encrypted with your firm\u2019s shared passphrase."),
        ):
            f = tk.Frame(dlg, background=PAGE)
            f.pack(fill="x", padx=24, pady=2)
            tk.Radiobutton(f, text=label, variable=tier_var, value=val,
                           background=PAGE, foreground=TEXT,
                           font=("Segoe UI", 9, "bold")).pack(side="left")
            tk.Label(f, text=desc, background=PAGE, foreground=MUTED,
                     font=("Segoe UI", 8)).pack(side="left", padx=6)
        def _do_export():
            tier = tier_var.get()
            dlg.destroy()
            dest = filedialog.asksaveasfilename(
                title="Save encrypted bundle",
                defaultextension=".pailegal",
                filetypes=(("PAi Legal bundle", "*.pailegal"),),
                initialfile=f"{self.active_case.case_id}-{tier}",
            )
            if not dest:
                return
            case_path = self.active_case.path
            try:
                from .case_export import export_seal, export_recipient, export_tenant
                if tier == "seal":
                    export_seal(case_path, dest)
                    messagebox.showinfo("Bundle saved",
                        f"Sealed bundle written.\n\n{dest}\n\n"
                        "The recipient can open this in PAi Legal \u2014 signed but not encrypted.")
                elif tier == "recipient":
                    _, unlock_code = export_recipient(case_path, dest)
                    self._show_unlock_code(unlock_code, dest)
                elif tier == "tenant":
                    pw = simpledialog.askstring("Firm passphrase",
                        "Enter your firm\u2019s shared encryption passphrase:", show="*", parent=self)
                    if not pw:
                        return
                    export_tenant(case_path, dest, pw)
                    messagebox.showinfo("Bundle saved",
                        f"Tenant-locked bundle written.\n\n{dest}\n\n"
                        "Any attorney with the same firm passphrase can open this in PAi Legal.")
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc))
        btn_frame = tk.Frame(dlg, background=PAGE)
        btn_frame.pack(side="bottom", pady=14)
        tk.Button(btn_frame, text="Cancel", command=dlg.destroy, width=10).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Choose file & export \u2192", command=_do_export,
                  background=ACCENT, foreground="white", width=22).pack(side="left", padx=6)

    def _show_unlock_code(self, unlock_code: str, dest: str) -> None:
        w = tk.Toplevel(self)
        w.title("Unlock code \u2014 send separately")
        w.geometry("500x230")
        w.configure(background=PAGE)
        w.resizable(False, False)
        w.grab_set()
        tk.Label(w, text="Bundle saved \u2014 send the unlock code separately",
                 font=("Segoe UI", 11, "bold"), background=PAGE, foreground=TEXT).pack(pady=(18, 4))
        tk.Label(w, text="Do NOT send the code in the same message as the .pailegal file.",
                 font=("Segoe UI", 9), background=PAGE, foreground=RED).pack()
        code_var = tk.StringVar(value=unlock_code)
        tk.Entry(w, textvariable=code_var, font=("Consolas", 9),
                 width=68, state="readonly", readonlybackground=CARD).pack(padx=20, pady=10)
        def _copy():
            w.clipboard_clear()
            w.clipboard_append(unlock_code)
            copy_btn.configure(text="Copied \u2713")
        copy_btn = tk.Button(w, text="Copy unlock code", command=_copy,
                             background=ACCENT, foreground="white", width=18)
        copy_btn.pack()
        tk.Label(w, text=f"File: {dest}", background=PAGE, foreground=MUTED,
                 font=("Segoe UI", 8)).pack(pady=(8, 0))
        tk.Button(w, text="Done", command=w.destroy, width=10).pack(pady=8)
    def _update_analysis_context(self) -> None:
        if not hasattr(self, "analysis_context"): return
        entries = list((self.workspace.matters(self.active_case).get("matters") or []) if self.active_case else [])
        previous_id = self.matter_by_label.get(self.analysis_matter_value.get(), "") if hasattr(self, "matter_by_label") else ""
        self.matter_by_label = {}
        if not entries:
            values = ["All documents (no separate matter detected)"]
            self.matter_by_label[values[0]] = ""
        else:
            values = [f"{item.get('matter_id')} â€” {item.get('label')} â€” {str(item.get('status') or '').title()}"
                      for item in entries]
            self.matter_by_label = {label: str(item.get("matter_id") or "")
                                    for label, item in zip(values, entries)}
            if len(entries) > 1:
                values.insert(0, "Select one matter before analysis or export")
                self.matter_by_label[values[0]] = ""
        self.analysis_matter_picker.configure(values=values)
        chosen = next((label for label, matter_id in self.matter_by_label.items()
                       if previous_id and matter_id == previous_id), "")
        if not chosen:
            chosen = values[0]
        self.analysis_matter_value.set(chosen)
        case = self.active_case.name if self.active_case else "No case"
        attached = len(self.workspace.attached_authorities(self.active_case)) if self.active_case else 0
        scope = self.matter_by_label.get(chosen, "") or ("selection required" if len(entries) > 1 else "all documents")
        self.analysis_context.configure(text=f"Active case: {case}  Â·  Matter: {scope}  Â·  {len(self.selected_authorities)} selected now  Â·  {attached} attached to case  Â·  All inference remains local")
        if hasattr(self, "authority_chips"):
            for child in self.authority_chips.winfo_children(): child.destroy()
            attached = self.workspace.attached_authorities(self.active_case) if self.active_case else []
            attached_ids = {str(item.get("source_id") or item.get("id") or item.get("title") or "") for item in attached}
            rows = [(item, True, None) for item in attached]
            rows += [(item.as_dict(), False, index) for index, item in enumerate(self.selected_authorities)
                     if (item.source_id or item.title) not in attached_ids]
            if not rows:
                tk.Label(self.authority_chips, text="No authorities selected or attached. Add them from PSi research when useful.",
                         bg="#EEF5FB", fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=3, pady=3)
            for item, stored, index in rows[:6]:
                color = GREEN if str(item.get("bracket") or "").upper() == "VALIDATED" else PURPLE if str(item.get("bracket") or "").upper() == "EXPLAINED" else ORANGE
                chip = tk.Frame(self.authority_chips, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
                chip.pack(side="left", padx=3, pady=3)
                title = str(item.get("citation") or item.get("title") or item.get("source_id") or "Stored authority")
                fms = f"{item.get('float_points',0)}/{item.get('mix_points',0)}/{item.get('stir_points',0)}"
                tk.Label(chip, text=f"{'SAVED' if stored else 'SELECTED'} Â· {str(item.get('bracket') or 'UNVERIFIED').title()} Â· F/M/S {fms}\n{title[:36]}",
                         bg=CARD, fg=color, font=("Segoe UI", 7, "bold"), justify="left", padx=7, pady=4).pack(side="left")
                if index is not None:
                    tk.Button(chip, text="Ã—", command=lambda value=index: self._drop_selected_authority(value),
                              bg=CARD, fg=MUTED, activebackground="#FDECEC", activeforeground=RED,
                              relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2").pack(side="left", padx=(0, 4))

    def _selected_matter_scope(self, *, required: bool = False) -> Optional[str]:
        """Return the explicit matter scope, blocking ambiguous whole-case work."""
        entries = list((self.workspace.matters(self.active_case).get("matters") or []) if self.active_case else [])
        selected = self.matter_by_label.get(self.analysis_matter_value.get(), "") if hasattr(self, "matter_by_label") else ""
        if len(entries) > 1 and not selected:
            if required:
                self._inline_error("This case contains multiple legal matters. Select one matter before analysis or export.")
            return None
        self.current_matter_id = selected
        return selected

    def _drop_selected_authority(self, index: int) -> None:
        if 0 <= index < len(self.selected_authorities):
            del self.selected_authorities[index]
            self.selected_count.configure(text=f"{len(self.selected_authorities)} selected for analysis")
            self._update_analysis_context(); self._refresh_dashboard()

    def _paint_header_capabilities(self) -> None:
        if not hasattr(self, "header_capabilities"): return
        self.header_capabilities["ai"].configure(fg=GREEN if self.report.has(Capability.ANALYSIS) else "#7892AA")
        self.header_capabilities["psi"].configure(fg=GREEN if self.report.has(Capability.CORPUS) else "#7892AA")
        self.header_capabilities["ocr"].configure(fg=GREEN if find_tesseract() else ORANGE)

    def _show_bracket_legend(self) -> None:
        message = "\n".join(f"{brackets.SHORT[item]}  {brackets.MEANING[item]}" for item in (
            brackets.BracketType.UNVERIFIED, brackets.BracketType.SPECULATIVE,
            brackets.BracketType.EXPLAINED, brackets.BracketType.VALIDATED))
        messagebox.showinfo("PAi Legal Trust Locks", message + "\n\nPressure and recurrence never promote or demote a Trust Lock.", parent=self)

    def _show_about(self) -> None:
        messagebox.showinfo("About PAi Legal", "PAi Legal 0.9.6\n\nPrivate, on-device legal document analysis with PSi Legal research and Relational Pressure Mapping.\n\n" + DISCLAIMER, parent=self)

    # Capabilities/settings ----------------------------------------

    def _offer_private_ai_setup(self) -> None:
        if messagebox.askyesno("Set up private AI?", "PAi Legal can scan this computer and recommend the strongest private AI model that fits. The model runs locally.\n\nSet it up now?", parent=self):
            ModelSetupDialog(self, self._refresh_capabilities)

    def _refresh_capabilities(self) -> None:
        self._set_status("Checking private AI and PSi Legalâ€¦")
        def worker() -> None:
            report = detect_all()
            self.after(0, lambda: self._capabilities_finished(report))
        threading.Thread(target=worker, daemon=True).start()

    def _capabilities_finished(self, report: CapabilityReport) -> None:
        self.report = report; self.mode_label.configure(text=report.mode)
        self.corpus_client = None
        if self.ai_client: self.ai_client.close()
        self.ai_client = None; self._paint_header_capabilities(); self._show_diagnostics(); self._apply_state(); self._refresh_dashboard(); self._set_status(report.mode)

    def _show_diagnostics(self) -> None:
        if not hasattr(self, "diagnostics_text"): return
        for capability, (dot, summary, actions) in self.integration_cards.items():
            status = self.report.statuses[capability]; dot.configure(fg=GREEN if status.available else ORANGE); summary.configure(text=status.summary)
            for child in actions.winfo_children(): child.destroy()
            if capability == Capability.ANALYSIS and not status.available:
                ttk.Button(actions, text="Set up private AI", command=lambda: ModelSetupDialog(self, self._refresh_capabilities), style="Accent.TButton").pack(side="left")
            elif capability == Capability.CORPUS and not status.available and status.remedy_link:
                ttk.Button(actions, text="Open PSi Legal in Microsoft Store", command=lambda uri=status.remedy_link: _open_uri(uri), style="Accent.TButton").pack(side="left")
            else:
                tk.Label(actions, text="Ready on this device", bg=CARD, fg=GREEN, font=("Segoe UI", 8, "bold")).pack(side="left")
        tesseract = find_tesseract()
        installation = read_installation()
        if hasattr(self, "model_detail"):
            if installation:
                hardware = installation.get("hardware") or {}
                gpu = hardware.get("gpu_name") or "CPU inference"
                headroom = max(0.0, float(hardware.get("available_ram_gb") or 0) - float(next((item.size_gb for item in CATALOG if item.key == installation.get("model_id")), 0)))
                self.model_detail.configure(text=f"{installation.get('model_label','Local GGUF')}  Â·  Context {installation.get('context',8192):,}  Â·  {gpu}  Â·  estimated recorded RAM headroom {headroom:.1f} GB")
            else: self.model_detail.configure(text="No private model installation detected. Use Private AI setup above.")
        if hasattr(self, "case_management_status"):
            self.case_management_status.configure(text=f"{len(self.workspace.list_cases())} active case(s)  Â·  {len(self.workspace.list_archived_cases())} archived case(s)")
        if hasattr(self, "professional_status"):
            try:
                security = self.workspace.security_status()
                encryption = security["encryption"]
                encryption_label = ("verified encrypted" if encryption["protected"] is True else
                                    "NOT encrypted" if encryption["protected"] is False else
                                    "encryption not verified")
                vault_label = "DPAPI vault ready" if security["credential_vault"]["available"] else "credential vault unavailable"
                policy = "strict writes enabled" if security["encryption_required"] else "strict writes not enabled"
                self.professional_status.configure(
                    text=f"{security['access']['username']} Â· {security['access']['role']}\n"
                         f"{encryption['provider']}: {encryption_label} Â· {policy} Â· {vault_label}")
            except Exception as exc:
                self.professional_status.configure(text=f"Professional control status unavailable: {exc}", fg=RED)
        detail = diagnostics(self.report) + ("\n\nLOCAL PROCESSING\n" + "=" * 58 + f"\nTesseract OCR: {tesseract or 'runtime not found'}\nExtractors: PDF, images, Office, email and structured text\nRPM: Float observations Â· Mix relations Â· Stir recurrence\nBrackets: unverified Â· speculative Â· explained Â· validated")
        self._set_text(self.diagnostics_text, detail)

    def _apply_state(self) -> None:
        case_state = "normal" if self.active_case else "disabled"
        for widget in (self.add_files_button, self.add_folder_button, self.build_corpus_button): widget.configure(state=case_state)
        research_state = "normal" if self.report.has(Capability.CORPUS) else "disabled"
        for widget in (self.search_entry, self.search_button): widget.configure(state=research_state)
        if self.report.has(Capability.CORPUS):
            self.psi_placeholder.pack_forget()
            self.research_workspace.pack(fill="both", expand=True)
        else:
            self.research_workspace.pack_forget()
            self.psi_placeholder.pack(fill="both", expand=True, pady=(15, 0))
        analysis_state = "normal" if self.active_case and self.report.has(Capability.ANALYSIS) else "disabled"
        for widget in (self.analysis_entry, self.analysis_button): widget.configure(state=analysis_state)
        self._update_analysis_context()

    # Utilities -----------------------------------------------------

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", text); widget.configure(state="disabled")

    def _inline_error(self, message: str) -> None:
        self._set_status(message)
        if self.current_page == "evidence" and hasattr(self, "evidence_preview"): self._set_text(self.evidence_preview, "âš  " + message)
        elif self.current_page == "map" and hasattr(self, "map_detail"): self._set_text(self.map_detail, "âš  " + message)
        elif self.current_page == "research" and hasattr(self, "result_detail"): self._set_text(self.result_detail, "âš  " + message)
        elif self.current_page == "analysis": self._append_analysis("System", message)

    def _set_status(self, value: str) -> None:
        self.status_value.set(value); self.update_idletasks()

    def _quit(self) -> None:
        if self.drafter_server is not None:
            self.drafter_server.stop()
        if self.ai_client: self.ai_client.close()
        self.destroy()



class PAiLegalApp(CaseMapPresentation, _PAiLegalAppBase):
    """Real-data case map presentation."""
    pass


def main() -> None:
    PAiLegalApp().mainloop()


if __name__ == "__main__":
    main()

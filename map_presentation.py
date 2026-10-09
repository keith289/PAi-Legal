"""Local presentation for existing CaseTransitionMap objects; no inference or I/O."""
from collections import defaultdict
import math
import tkinter as tk
from tkinter import ttk


def transition_groups(view, query=""):
    """Group by actual directed endpoints, never by inferred channel or pressure."""
    groups = defaultdict(list)
    query = query.casefold().strip()
    for edge in view.edges:
        if query and query not in (edge.label + " " + " ".join(edge.provenance)).casefold():
            continue
        groups[(edge.source, edge.target)].append(edge)
    return {key: tuple(sorted(items, key=lambda e: (e.label.casefold(), e.id)))
            for key, items in sorted(groups.items())}


class CaseMapPresentation:
    """Mixin: use the app's original model, inspector, and semantic navigation."""

    def _build_case_map(self):
        super()._build_case_map()
        self.map_canvas.configure(bg="#F6F9FC")
        # Replace the original toolbar labels with portable text.
        controls = self.map_back_button.master
        self.map_back_button.configure(text="Back")
        zoom_index = 0
        for child in controls.winfo_children():
            if isinstance(child, ttk.Button):
                if str(child.cget("width")) == "3":
                    child.configure(text="-" if zoom_index == 0 else "+")
                    zoom_index += 1
        bar = tk.Frame(self.map_detail.master, bg="white")
        bar.pack(fill="x", before=self.map_detail, padx=12, pady=4)
        self._map_query = tk.StringVar()
        tk.Label(bar, text="Find transition", bg="white", fg="#637083").pack(anchor="w")
        entry = ttk.Entry(bar, textvariable=self._map_query)
        entry.pack(fill="x", pady=(3, 6))
        self._map_query.trace_add("write", lambda *_: self._map_search_changed())
        ttk.Button(bar, text="Overview / clear selection", command=self._map_overview).pack(fill="x")
        tk.Label(bar, text="REAL TRANSITIONS", bg="white", fg="#637083",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(10, 3))
        self._map_list = ttk.Treeview(bar, columns=("pressure",), show="tree headings", height=7)
        self._map_list.heading("#0", text="Document / transition")
        self._map_list.heading("pressure", text="Pressure")
        self._map_list.column("#0", width=190, stretch=True)
        self._map_list.column("pressure", width=75, stretch=False, anchor="e")
        self._map_list.pack(fill="x")
        scroll = ttk.Scrollbar(bar, command=self._map_list.yview)
        self._map_list.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._map_list.bind("<<TreeviewSelect>>", self._map_list_selected)
        self._map_list.bind("<Double-1>", lambda _e: self._map_open_selected())
        self._map_group = None
        self._map_last_view = None
        self._map_rows = {}

    def _map_search_changed(self):
        self._map_group = None
        self.transition_selection = None
        self.map_open_button.configure(state="disabled")
        self._draw_transition_map()

    def _map_overview(self):
        self._map_group = None
        self.transition_selection = None
        self.transition_scale = 1.0
        self.map_open_button.configure(state="disabled")
        if self._map_query.get():
            self._map_query.set("")
        else:
            self._draw_transition_map()
        self.map_canvas.xview_moveto(0)
        self.map_canvas.yview_moveto(0)

    def _map_list_selected(self, _event=None):
        selected = self._map_list.selection()
        edge = self._map_rows.get(selected[0]) if selected else None
        if edge is None:
            return
        self.transition_selection = ("edge", edge.id)
        self._inspect_map_item(edge)
        self._draw_transition_map(refresh_list=False)

    def _map_canvas_click(self, _event=None):
        for tag in self.map_canvas.gettags("current"):
            if tag.startswith("group::"):
                self._map_group = self._map_group_keys.get(tag)
                self.transition_selection = None
                self.map_open_button.configure(state="disabled")
                self._draw_transition_map()
                return
        super()._map_canvas_click(_event)
        self._draw_transition_map(refresh_list=False)

    def _draw_transition_map(self, refresh_list=True):
        if not hasattr(self, "_map_query") or not self.transition_map_model:
            return super()._draw_transition_map()
        model = self.transition_map_model
        view = model.view(self.transition_view_id)
        view_key = (model.input_signature, view.id)
        if self._map_last_view != view_key:
            self._map_last_view = view_key
            self._map_group = None
            # Avoid recursive StringVar callback when changing semantic levels.
            self._map_query.set("") if self._map_query.get() else None
        groups = transition_groups(view, self._map_query.get())
        if self._map_group not in groups:
            self._map_group = None
        visible_edges = [e for key, edges in groups.items()
                         if self._map_group is None or key == self._map_group for e in edges]
        if refresh_list:
            self._map_list.delete(*self._map_list.get_children())
            self._map_rows = {}
            for i, edge in enumerate(visible_edges):
                iid = str(i)
                self._map_rows[iid] = edge
                self._map_list.insert("", "end", iid=iid, text=edge.label,
                                      values=(f"{edge.pressure:.2f}",))
        canvas = self.map_canvas
        canvas.delete("all")
        width = max(620, canvas.winfo_width() - 24)
        height = max(440, canvas.winfo_height() - 24)
        nodes = list(view.nodes)
        # Four real root states retain their familiar triangular arrangement.
        if view.id == model.root_view:
            positions = self._map_positions(nodes, width, height)
        else:
            cols = max(1, min(5, math.ceil(math.sqrt(len(nodes)))))
            rows = max(1, math.ceil(len(nodes) / cols))
            height = max(height, rows * 135 + 130)
            positions = {node.id: (width * ((i % cols) + 1) / (cols + 1),
                                   110 + (i // cols) * 135)
                         for i, node in enumerate(sorted(nodes, key=lambda n: n.id))}
        labels = {n.id: n.label.replace("\n", " / ") for n in nodes}
        selected = self._map_find_item(self.transition_selection)
        self._map_group_keys = {}
        for index, (pair, edges) in enumerate(groups.items()):
            if pair[0] not in positions or pair[1] not in positions:
                continue
            x1, y1 = positions[pair[0]]
            x2, y2 = positions[pair[1]]
            active = (self._map_group == pair or
                      any(self.transition_selection == ("edge", e.id) for e in edges))
            color = "#92A3B8" if not active else "#1FB6C9"
            tag = f"group::{index}"
            self._map_group_keys[tag] = pair
            if pair[0] == pair[1]:
                cx, cy = x1 + 85, y1 - 65
                canvas.create_line(x1, y1-25, x1+130, y1-115, x1+145, y1+30,
                                   x1+28, y1, smooth=True, arrow="last", fill=color,
                                   width=2, tags=(tag, "map-hit"))
            else:
                dx, dy = x2-x1, y2-y1
                length = max(1, math.hypot(dx, dy))
                # Bounded curve with endpoints on state circles, regardless of count.
                bend = 42
                cx, cy = (x1+x2)/2-dy/length*bend, (y1+y2)/2+dx/length*bend
                canvas.create_line(x1+dx/length*43, y1+dy/length*43, cx, cy,
                                   x2-dx/length*43, y2-dy/length*43,
                                   smooth=True, arrow="last", fill=color,
                                   width=2 if not active else 3, tags=(tag, "map-hit"))
            canvas.create_rectangle(cx-68, cy-15, cx+68, cy+15,
                                    fill="white", outline=color, tags=(tag, "map-hit"))
            canvas.create_text(cx, cy, text=f"{len(edges)} transition" + ("s" if len(edges)!=1 else ""),
                               fill="#132238", font=("Segoe UI", 9, "bold"), tags=(tag, "map-hit"))
        # Draw the selected real transition in its actual residue color.
        if selected is not None and self.transition_selection[0] == "edge":
            if selected.source in positions and selected.target in positions and selected.source != selected.target:
                x1, y1 = positions[selected.source]
                x2, y2 = positions[selected.target]
                dx, dy = x2-x1, y2-y1
                length = max(1, math.hypot(dx, dy))
                canvas.create_line(x1+dx/length*43, y1+dy/length*43,
                                   x2-dx/length*43, y2-dy/length*43, arrow="last",
                                   fill=self._map_channel_color(selected.residue), width=3,
                                   tags=(f"edge::{selected.id}", "map-hit"))
        for node in nodes:
            x, y = positions[node.id]
            tag = f"node::{node.id}"
            color = self._map_channel_color(node.channel)
            radius = 43
            canvas.create_oval(x-radius-5, y-radius-5, x+radius+5, y+radius+5,
                               fill="white", outline="#E2E8F0")
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius, fill=color,
                               outline=self._map_bracket_color(node.bracket), width=2,
                               tags=(tag, "map-hit"))
            text = node.label if len(node.label) < 62 else node.label[:59]+"..."
            canvas.create_text(x, y, text=text, width=78, fill="white",
                               font=("Segoe UI", 8, "bold"), tags=(tag, "map-hit"))
        caption = (f"{len(visible_edges)} of {len(view.edges)} transitions listed. "
                   "Select a connection to expand its list.")
        if self._map_group:
            caption = "Selected: " + labels.get(self._map_group[0], self._map_group[0]) + " -> " + labels.get(self._map_group[1], self._map_group[1])
        canvas.create_text(18, 22, text=caption, anchor="nw", width=width-36,
                           fill="#637083", font=("Segoe UI", 9))
        if self.transition_scale != 1:
            canvas.scale("all", width/2, height/2, self.transition_scale, self.transition_scale)
        bbox = canvas.bbox("all")
        if bbox:
            canvas.configure(scrollregion=(min(0,bbox[0]-20), min(0,bbox[1]-20),
                                           max(width,bbox[2]+20), max(height,bbox[3]+20)))
        self.map_breadcrumb.configure(text=" / ".join(v.label for v in model.breadcrumbs(view.id)))
        self.map_back_button.configure(state="normal" if view.parent else "disabled")
        if not self.transition_selection:
            self._set_text(self.map_detail, f"{view.label}\n\n{view.description}\n\n"
                           "Select a real transition in the list to inspect its pressure, residue, "
                           "Trust Lock and provenance. Double-click to open its inner map.\n\n"
                           "Connection counts group existing transitions by their directed endpoints. "
                           "No evidence or engine values are changed.")

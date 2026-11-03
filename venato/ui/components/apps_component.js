// Applications table: compact rows, one line per cell. Text too long for its
// column is cut off and ends in a clickable "..."; clicking it shows the whole text in a
// bubble (click anywhere, or Esc, to close). Click a cell to edit it in place;
// Status is a coloured pill with a dropdown.
//
// Python passes { rows: [{id, industry, company, route, description, contact,
// deadline, deadlineText, due, status, notes}], statuses, colours, acked }.
// Edits show straight away and go to Python as ops:
//   {opId, kind: "edit", id, field, value}      {opId, kind: "delete", id}
// Ops stay pending until Python lists their opId in `acked` (like the to-do lists).

const COLS = [
  { key: "industry", label: "Industry" },
  { key: "company", label: "Company" },
  { key: "route", label: "Route" },
  { key: "description", label: "Description" },
  { key: "contact", label: "Contact / lead" },
  { key: "deadline", label: "Deadline", kind: "date" },
  { key: "due", label: "Due", kind: "fixed" },
  { key: "status", label: "Status", kind: "status" },
  { key: "notes", label: "Notes" },
];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () =>
  (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));

const TRASH = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const instances = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".ap-root");
  let t = instances.get(root);
  if (!t) {
    t = new AppsTable(root);
    instances.set(root, t);
  }
  t.send = (ops) => setTriggerValue("ops", ops);
  t.update(data);
  return () => t.detach();
}

class AppsTable {
  constructor(root) {
    this.root = root;
    this.pending = [];
    this.editing = null;          // {id, field}
    this.onOutside = (e) => {
      if (this.bubble && !e.composedPath().includes(this.bubble)) this.closeBubble();
    };
    this.onKey = (e) => {
      if (e.key === "Escape" && this.bubble) { this.closeBubble(true); e.stopPropagation(); }
    };
    this.onResize = () => this.markOverflow();
    root.addEventListener("click", (e) => this.onClick(e));
    root.addEventListener("keydown", (e) => this.onKeyDown(e));
    root.addEventListener("change", (e) => this.onChange(e));
  }

  update(data) {
    this.data = data;
    const acked = new Set(data.acked);
    this.pending = this.pending.filter((op) => !acked.has(op.opId));
    this.rows = data.rows.map((r) => ({ ...r }));
    this.pending.forEach((op) => this.applyLocal(op));
    if (!this.editing) this.render();
    this.attach();
  }

  attach() {
    if (this.attached) return;
    this.attached = true;
    document.addEventListener("pointerdown", this.onOutside, true);
    document.addEventListener("keydown", this.onKey, true);
    window.addEventListener("resize", this.onResize);
  }

  detach() {
    this.attached = false;
    document.removeEventListener("pointerdown", this.onOutside, true);
    document.removeEventListener("keydown", this.onKey, true);
    window.removeEventListener("resize", this.onResize);
  }

  applyLocal(op) {
    if (op.kind === "delete") { this.rows = this.rows.filter((r) => r.id !== op.id); return; }
    const r = this.rows.find((x) => x.id === op.id);
    if (!r) return;
    r[op.field] = op.value || null;
    if (op.field === "deadline") { r.deadlineText = op.value ? op.value : ""; r.due = ""; }
  }

  commit(op) {
    op.opId = uid();
    this.applyLocal(op);
    this.pending.push(op);
    this.render();
    this.send(this.pending.slice());
    clearTimeout(this.resendTimer);
    this.resendTimer = setTimeout(() => { if (this.pending.length) this.send(this.pending.slice()); }, 3000);
  }

  // ---------- Drawing ----------

  render() {
    this.closeBubble();
    if (!this.rows.length) { this.root.innerHTML = ""; return; }
    const head = COLS.map((c) => `<th class="c-${c.key}" scope="col">${esc(c.label)}</th>`).join("") +
      '<th class="c-del"><span class="sr">Delete</span></th>';
    const body = this.rows.map((r) => `<tr data-id="${esc(r.id)}">${COLS.map((c) => this.cell(r, c)).join("")}
      <td class="c-del"><button class="ap-del" data-del="${esc(r.id)}" title="Delete" aria-label="Delete ${esc(r.company || "application")}">${TRASH}</button></td></tr>`).join("");
    this.root.innerHTML = `<div class="ap-wrap"><table class="ap"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    this.markOverflow();
  }

  cell(r, c) {
    const label = `${c.label}${r.company ? ", " + r.company : ""}`;
    if (c.kind === "status") {
      const colour = this.data.colours[r.status] || "#9E9E9E";
      const opts = this.data.statuses.map((s) => `<option${s === r.status ? " selected" : ""}>${esc(s)}</option>`).join("");
      return `<td class="c-status"><span class="ap-pill" style="--c:${colour}"><i></i><select data-status="${esc(r.id)}" aria-label="Status, ${esc(r.company || "application")}">${opts}</select></span></td>`;
    }
    if (c.kind === "fixed") return `<td class="c-${c.key}"><span class="ap-text">${esc(r.due || "")}</span></td>`;
    const editing = this.editing && this.editing.id === r.id && this.editing.field === c.key;
    if (editing) {
      const type = c.kind === "date" ? "date" : "text";
      return `<td class="c-${c.key} editing"><input class="ap-input" type="${type}" data-input="${c.key}" value="${esc(r[c.key] || "")}" aria-label="${esc(label)}"></td>`;
    }
    const text = c.kind === "date" ? r.deadlineText : r[c.key];
    return `<td class="c-${c.key}"><span class="ap-cell" tabindex="0" role="button" data-edit="${c.key}" aria-label="${esc(label)}: ${esc(text || "empty")}. Press Enter to edit">` +
      `<span class="ap-text" data-key="${c.key}">${esc(text || "")}</span></span></td>`;
  }

  // Text too long for its cell: cut it at a word or letter and end it with a clickable "...",
  // in the same font and colour, so it reads like "PI in astroph...".
  markOverflow() {
    this.root.querySelectorAll(".ap-text[data-key]").forEach((el) => {
      const row = this.rows.find((r) => r.id === el.closest("tr").dataset.id);
      const key = el.dataset.key;
      const full = String((key === "deadline" ? row.deadlineText : row[key]) || "");
      el.textContent = full;
      if (!full || el.scrollWidth <= el.clientWidth + 1) return;
      const more = `<button class="ap-more" data-more="${key}" aria-label="Show all of ${esc(COLS.find((c) => c.key === key).label)}">...</button>`;
      let lo = 0, hi = full.length;
      while (lo < hi) {                                   // the most characters that fit with "..."
        const mid = Math.ceil((lo + hi) / 2);
        el.innerHTML = `${esc(full.slice(0, mid).trimEnd())}${more}`;
        if (el.scrollWidth <= el.clientWidth + 1) lo = mid; else hi = mid - 1;
      }
      el.innerHTML = `${esc(full.slice(0, lo).trimEnd())}${more}`;
    });
  }

  // ---------- The bubble ----------

  openBubble(btn) {
    this.closeBubble();
    const td = btn.closest("td"), row = this.rows.find((r) => r.id === btn.closest("tr").dataset.id);
    const col = COLS.find((c) => c.key === btn.dataset.more);
    const text = col.kind === "date" ? row.deadlineText : row[col.key];
    const b = document.createElement("div");
    b.className = "ap-bubble";
    b.setAttribute("role", "dialog");
    b.setAttribute("aria-label", col.label);
    b.tabIndex = -1;
    b.innerHTML = `<div class="ap-bubble-h">${esc(col.label)}</div><div class="ap-bubble-t">${esc(text)}</div>`;
    this.root.appendChild(b);
    const box = this.root.getBoundingClientRect(), cell = td.getBoundingClientRect();
    const width = Math.min(360, box.width - 16);
    b.style.width = width + "px";
    b.style.left = Math.max(8, Math.min(cell.left - box.left, box.width - width - 8)) + "px";
    b.style.top = cell.bottom - box.top + 4 + "px";
    this.bubble = b;
    this.bubbleFrom = btn;
    b.focus();
  }

  closeBubble(refocus = false) {
    if (!this.bubble) return;
    this.bubble.remove();
    this.bubble = null;
    if (refocus && this.bubbleFrom && this.bubbleFrom.isConnected) this.bubbleFrom.focus();
  }

  // ---------- Editing ----------

  startEdit(id, field) {
    this.editing = { id, field };
    this.render();
    const input = this.root.querySelector(".ap-input");
    if (!input) return;
    input.focus();
    if (input.type === "text") input.select();
    const finish = (save) => {
      if (!this.editing) return;
      const value = input.value.trim();
      const row = this.rows.find((r) => r.id === id);
      this.editing = null;
      if (save && row && value !== (row[field] || "")) this.commit({ kind: "edit", id, field, value });
      else this.render();
      const back = this.root.querySelector(`tr[data-id="${CSS.escape(id)}"] [data-edit="${field}"]`);
      if (back) back.focus();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  }

  onClick(e) {
    const more = e.target.closest("[data-more]");
    if (more) { this.openBubble(more); return; }
    const del = e.target.closest("[data-del]");
    if (del) { this.commit({ kind: "delete", id: del.dataset.del }); return; }
    const cell = e.target.closest("[data-edit]");
    if (!cell) return;
    // Wait a moment: a double-click (selecting a word) or a drag that selected text means
    // "copy this", not "edit this".
    clearTimeout(this.editTimer);
    if (e.detail > 1 || String(window.getSelection() || "")) return;
    const id = cell.closest("tr").dataset.id, field = cell.dataset.edit;
    this.editTimer = setTimeout(() => {
      if (!String(window.getSelection() || "")) this.startEdit(id, field);
    }, 280);
  }

  onKeyDown(e) {
    const cell = e.target.closest && e.target.closest("[data-edit]");
    if (cell && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      this.startEdit(cell.closest("tr").dataset.id, cell.dataset.edit);
    }
  }

  onChange(e) {
    const sel = e.target.closest("[data-status]");
    if (sel) this.commit({ kind: "edit", id: sel.dataset.status, field: "status", value: sel.value });
  }
}

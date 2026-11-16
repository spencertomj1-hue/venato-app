// Weekly Timetable: 7 days side by side, each with Plan/Actual columns in
// 30-minute slots, like a calendar week view.
//
// Python passes { days, today, groups, categories, entries, labelMap, acked },
// with only that week's entries. Edits are applied locally straight away, then
// sent to Python as "ops": {opId, kind: "paint", date, track, start, end, block, newId}
// for drags, {opId, kind: "upsert", entry} / {opId, kind: "delete", id} for right-click edits.
// Ops stay pending until Python lists their opId in `acked`, so a slow rerun
// never makes the grid flicker back to old data.
// Swiping sideways on the grid sends a "nav" trigger (-1 / +1 week).
//
// One timeline (data.view === "one", the default): one column per day. Slots from now on show
// and edit the Plan; slots that have passed show what happened: the Actual where the day's
// Actual is the truth (dayState.upto) or exists, else the Plan drawn as "assumed". Corrections
// are ops on ranges, so both sides agree without knowing each other's ids:
//   {kind: "skip", date, start, end}                      didn't happen
//   {kind: "replace", date, start, end, block, newId}     did something else / an unplanned block
//   {kind: "retime", date, fromStart, fromEnd, start, end, block, newId}   change times
//   {kind: "confirm_day", date}                           all as planned
// Suggested sittings (data.suggestions, worked out in Python by tools.goal_spots) are drawn dashed in
// free time; clicking one sends {kind: "add_suggestion", date, start, end, block, newId, ghost}.
// Each first materialises the day (store.materialise; mirrored here by materialiseLocal).

let SLOTS = 36;                   // 30-minute slots in a day (07:00 -> 01:00 by default; from Python)
let FIRST_MIN = 7 * 60;           // the day's first minute
const TRACKS = ["plan", "actual"];
const SWIPE_THRESHOLD = 120;      // px of sideways scroll that flips a week

// ---------- Small helpers ----------

const pad = (n) => String(n).padStart(2, "0");

// Slot index (0..SLOTS) -> "HH:mm". Slot SLOTS is the end of the last slot.
function slotTime(i) {
  const m = (FIRST_MIN + 30 * i) % 1440;
  return `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
}

// Keyboard shortcuts use Cmd on a Mac and Ctrl elsewhere.
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = IS_MAC ? "⌘" : "Ctrl+";

// A box you type in (not a radio button, checkbox or button, which are <input>s too).
const TEXT_INPUTS = /^(text|search|email|number|password|url|tel|date|time|datetime-local|month|week)$/;
function isTextField(el) {
  if (!el || !el.closest) return false;
  if (el.closest("textarea, select, [contenteditable=''], [contenteditable='true']")) return true;
  return el.tagName === "INPUT" && TEXT_INPUTS.test(el.type || "text");
}

// Should a shortcut leave this key press alone? Typing in a box, selected text on the page
// (so normal copy works), or a dialog open: then the browser does what it normally does.
// A key the timetable used: Safari puts a focus ring round whatever page element has focus
// (often the whole page) when a key is pressed, so take the focus off it.
function dropFocus() {
  const el = document.activeElement;
  if (el && el !== document.body && !isTextField(el) && el.blur) el.blur();
}

// The "?" panel at the top right: everything you can do on the timetable.
function helpHtml(single) {
  const key = (k) => `<kbd>${k}</kbd>`;
  const items = ONE ? [
    ["One timeline", "Plan your time once. From now on the timetable shows your Plan; time that has passed shows what happened."],
    ["Assumed", "Until you confirm a day, its Plan is <b>assumed</b> to have happened (drawn faded with a dashed edge). Stats and goals only count confirmed days."],
    ["Correct a day", "Click a block that has passed: <b>Didn't happen</b>, <b>Change times</b> or <b>Did something else</b>. Drag across empty past time (with a category picked) to add something you didn't plan."],
    ["Confirm", "<b>Confirm</b> under a day's name, or Home's end-of-day prompt, says the day went as planned. Skipped blocks are hatched and struck through; unplanned ones are outlined."],
  ] : [
    ["Plan and Actual", "Each day has two columns: <b>Plan</b> is what you mean to do, <b>Actual</b> is what you really did."],
    ["Add a block", "Pick a category from the key, then drag down a column. The block takes the category's name; rename it in its details."],
    ["Put a category down", "Click it again, or press " + key("Esc") + ". With no category picked, dragging selects instead of adding."],
    ["Select", "Point at a block to select it (moving off deselects it). Click it to see its details, edit it or delete it."],
    ["Move or resize", ONE ? "Drag a block to move it to another time or day. Drag its top or bottom edge to change when it starts or ends." : "Drag a block to move it (to another time, day, or between Plan and Actual). Drag its top or bottom edge to change when it starts or ends."],
    ["Select several", "Drag from empty time with no category picked (or holding " + key("Shift") + ") to draw a box: every block it touches is selected. " + key("Shift") + " or " + key(MOD.replace("+", "")) + "-click adds or removes one. Drag any selected block to move them all."],
    ["Copy and paste", key(MOD + "C") + " copies the block you're pointing at (or the selected ones); point at a time and " + key(MOD + "V") + " pastes them there, layout kept, on any day or week."],
    ["Delete and undo", key("Delete") + " or " + key("Backspace") + " removes the block you're pointing at (or the selected ones); " + key(MOD + "Z") + " brings them back."],
    ["Right-click", "Right-click a block to edit it straight away."],
    ["Outlook", "Outlook events show in Plan. ↻ syncs now; the Outlook button shows or hides them. Moving or deleting one only changes Venato, never Outlook."],
    ["Fit time", "<b>Fit time</b> (above) finds free gaps for hours of something, e.g. 6 hours of revision, and shows you before adding them."],
    ["Categories", "<b>Adjust categories</b> (above) adds, renames and recolours categories, and sets which category an activity uses."],
  ];
  if (!single) items.push(["Change week", "‹ Today › at the top, the date box, or swipe sideways on a trackpad."]);
  return `<div class="tt-help-h">How the timetable works</div><dl>` +
    items.map(([t, d]) => `<dt>${t}</dt><dd>${d}</dd>`).join("") + "</dl>";
}

function leaveShortcutAlone(e) {
  if (isTextField(e.composedPath()[0])) return true;
  const sel = window.getSelection && String(window.getSelection() || "");
  if (sel.trim()) return true;
  return !!document.querySelector("[role=dialog]");
}

// How times and dates are shown (Settings -> Region); data stays "HH:mm" and ISO dates.
let CLOCK = "24-hour", DATEFMT = "DD/MM/YYYY";
function fmtTime(t) {
  if (!t || CLOCK !== "12-hour") return t;
  const [h, m] = t.split(":").map(Number);
  return `${h % 12 || 12}${m ? ":" + pad(m) : ""} ${h < 12 ? "am" : "pm"}`;
}
const fmtRange = (a, b) => `${fmtTime(a)}–${fmtTime(b)}`;
const LOC = () => (DATEFMT === "MM/DD/YYYY" ? "en-US" : "en-GB");     // the order of day and month in words
function dayNum(iso) {
  const [, m, d] = iso.split("-");
  return DATEFMT === "MM/DD/YYYY" ? `${m}/${d}` : DATEFMT === "YYYY-MM-DD" ? `${m}-${d}` : `${d}/${m}`;
}

// One timeline (one column a day) or Plan and Actual side by side; set from Python's data.view.
let ONE = false;

// Grid column of a day's Plan or Actual (for box selection across days).
const col = (di, track) => (ONE ? di : di * 2 + (track === "actual" ? 1 : 0));
const colCell = (c) => (ONE ? [c, "plan"] : [Math.floor(c / 2), c % 2 ? "actual" : "plan"]);

// "HH:mm" -> slot index. Times before the day's start are after midnight.
function slotOf(t) {
  const [h, m] = t.split(":").map(Number);
  let mins = h * 60 + m;
  if (mins < FIRST_MIN) mins += 1440;
  return Math.round((mins - FIRST_MIN) / 30);
}

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CAL_ICON = '<svg class="cal-ic" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>';

const PIN_ICON = '<svg class="cal-ic" viewBox="0 0 24 24"><path d="M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11z"/><circle cx="12" cy="10" r="2"/></svg>';

// "26 – 31 Oct 2026" or "26 Oct – 1 Nov 2026" from two ISO dates.
function weekTitle(first, last) {
  const a = new Date(first + "T00:00"), b = new Date(last + "T00:00");
  const mon = (d) => d.toLocaleDateString("en-GB", { month: "short" });
  if (DATEFMT === "MM/DD/YYYY") {                 // "Oct 26 – 31, 2026" / "Oct 26 – Nov 1, 2026"
    const end = a.getMonth() === b.getMonth() ? `${b.getDate()}` : `${mon(b)} ${b.getDate()}`;
    return `${mon(a)} ${a.getDate()} – ${end}, ${b.getFullYear()}`;
  }
  const start = a.getMonth() === b.getMonth() ? `${a.getDate()}` : `${a.getDate()} ${mon(a)}`;
  return `${start} – ${b.getDate()} ${mon(b)} ${b.getFullYear()}`;
}

// Block text is black or white, whichever contrasts more with the fill (WCAG), so it's 4.5:1 or
// better on any category colour: black on mid colours and bright red, white on deep purple or navy.
function contrastText(hex) {
  const n = parseInt(hex.slice(1), 16);
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const L = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return (L + 0.05) / 0.05 >= 1.05 / (L + 0.05) ? "#000000" : "#ffffff";
}

const uid = () =>
  (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));

// sessionStorage can be unavailable; the grid works without it.
function remember(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
}
function recall(key) {
  try { return JSON.parse(sessionStorage.getItem(key)); } catch (e) { return null; }
}

// How each kind of passed piece is described (titles, the block list, the details card).
const PIECE_WORDS = { actual: "Done", assumed: "Assumed, not confirmed", unplanned: "Not planned", skipped: "Didn't happen" };

// One instance per mounted root, so brush/selection survive data updates.
const instances = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".tt-root");
  let tt = instances.get(root);
  if (!tt) {
    tt = new Timetable(root);
    instances.set(root, tt);
  }
  tt.send = (ops) => setTriggerValue("ops", ops);
  tt.trigger = (name, value) => setTriggerValue(name, { ...value, nonce: uid() });
  // Week navigation: {dir: -1 | 1}, {dir: 0} for this week, or {date: "YYYY-MM-DD"}.
  tt.nav = (nav) => setTriggerValue("nav", { ...nav, nonce: uid() });
  tt.update(data);
  return () => tt.detach();
}

class Timetable {
  constructor(root) {
    this.root = root;
    // Focus rings only for keyboard users: Tab turns them on, any click turns them off. (Safari
    // focuses things on a click, so a later key press used to draw a grey ring.)
    if (!window.__ttRoots) {
      window.__ttRoots = new Set();           // (the roots may be inside shadow DOM, so keep them, don't query)
      const set = (on) => window.__ttRoots.forEach((r) => (r.isConnected ? r.classList.toggle("kbd", on) : window.__ttRoots.delete(r)));
      document.addEventListener("keydown", (e) => { if (e.key === "Tab") set(true); }, true);
      document.addEventListener("pointerdown", () => set(false), true);
    }
    window.__ttRoots.add(root);
    this.entries = new Map();   // id -> entry (server data + pending ops)
    this.pending = [];          // ops not yet acknowledged by Python
    this.brush = recall("tt-brush");   // category id, or null
    if (this.brush === "eraser" || this.brush === "select") this.brush = null;   // tools that no longer exist
    this.drag = null;           // {di, track, a, b} while painting
    this.picked = new Set();    // selected blocks: entry ids, or "outlook:<uid>"
    this.selected = [];         // cells currently highlighted
    this.builtFor = null;       // week + categories the view was built for
    this.swipe = 0;             // accumulated sideways scroll
    this.swipeLocked = false;
    this.onMouseUp = () => this.endDrag();
    this.onWindowResize = () => this.fitToWindow();
    this.onKey = (e) => {
      const mod = IS_MAC ? e.metaKey : e.ctrlKey;
      if (mod && !e.shiftKey && !e.altKey && (e.key === "c" || e.key === "v") && this.data && !this.data.readonly) {
        if (leaveShortcutAlone(e)) return;
        if (e.key === "c" ? this.copyBlock() : this.pasteBlock()) { e.preventDefault(); dropFocus(); }
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && this.picked.size && this.data && !this.data.readonly) {
        if (leaveShortcutAlone(e)) return;
        e.preventDefault();
        this.deletePicked();
        dropFocus();
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && !leaveShortcutAlone(e)) {
        e.preventDefault();                        // nothing selected: do nothing at all (and leave no focus ring)
        dropFocus();
        return;
      }
      if (e.key !== "Escape") return;
      const help = this.root.querySelector(".tt-help");
      if (help && !help.hidden) { this.toggleHelp(false); this.root.querySelector(".tt-help-btn").focus(); return; }
      // Esc closes whatever is open first; with nothing open, it puts the category down.
      if (!this.drag && !this.blockDrag && !this.marquee && !this.groupDrag && !this.popover && !this.picked.size
          && this.brush && this.data && !this.data.readonly && !isTextField(e.composedPath()[0])) this.clearBrush();
      this.cancelDrag();
      this.closePopover();
      this.setPicked([]);
      if (this.returnFocus) { this.returnFocus.focus(); this.returnFocus = null; }
    };
    this.onOutside = (e) => {
      const help = this.root.querySelector(".tt-help");
      if (help && !help.hidden && !e.composedPath().some((el) => el.classList && (el.classList.contains("tt-help") || el.classList.contains("tt-help-btn")))) this.toggleHelp(false);
      if (this.popover && !e.composedPath().includes(this.popover) && !e.composedPath().includes(this.wrapEl)) this.closePopover();
    };
  }

  // ---------- Data ----------

  update(data) {
    this.data = data;
    CLOCK = data.clock || "24-hour";
    SLOTS = data.slots || 36;
    FIRST_MIN = data.firstMin ?? 7 * 60;
    DATEFMT = data.dateFormat || "DD/MM/YYYY";
    this.nowAt = { min: data.nowMin, ms: Date.now() };   // the time in the user's zone when Python drew this
    this.cats = new Map(data.categories.map((c) => [c.id, c]));
    this.dayIndex = new Map(data.days.map((d, i) => [d, i]));
    ONE = data.view === "one";
    // Per day: {gone: slots passed, upto: slots where Actual is the truth, confirmed}. Replayed ops update it.
    this.dayState = Object.fromEntries(data.days.map((d) => [d, { gone: 0, upto: 0, confirmed: false, ...((data.dayState || {})[d] || {}) }]));

    // Server entries, then re-apply anything Python hasn't saved yet.
    const acked = new Set(data.acked);
    this.pending = this.pending.filter((op) => !acked.has(op.opId));
    this.entries = new Map(data.entries.map((e) => [e.id, { ...e }]));
    this.outlook = (data.outlook || []).slice();   // Python already leaves out removed ones
    this.hidden = new Set();                       // removed / detached here, not yet saved
    this.suggestions = (data.suggestions || []).slice();
    this.ghostsTaken = new Set();                  // suggestions added here, not yet saved
    this.pending.forEach((op) => this.applyLocal(op));

    const key = JSON.stringify([data.categories, data.days, data.today, data.view]);
    if (key !== this.builtFor) {
      this.build();
      this.builtFor = key;
    }
    this.refreshDatalist();
    this.showOutlookStatus();
    this.fitToWindow();
    this.paint();
    // Re-measure once the page around the grid (agenda, fonts) has settled.
    requestAnimationFrame(() => this.fitToWindow());
    clearTimeout(this.fitTimer);
    this.fitTimer = setTimeout(() => this.fitToWindow(), 400);
    this.attach();
  }

  applyLocal(op) {
    if (op.kind === "batch") { op.ops.forEach((o) => this.applyLocal(o)); return; }
    if (op.kind === "confirm_day") { this.materialiseLocal(op.date, true); return; }
    if (op.kind === "add_suggestion") {
      this.ghostsTaken.add(op.ghost);
      this.planPaint({ date: op.date, track: "plan", start: op.start, end: op.end, block: op.block, newId: op.newId })
        .forEach((o) => this.applyLocal(o));
      return;
    }
    if (op.kind === "skip" || op.kind === "replace" || op.kind === "retime") {
      this.materialiseLocal(op.date);
      if (op.kind === "retime") {
        this.planPaint({ date: op.date, track: "actual", start: op.fromStart, end: op.fromEnd, block: null }).forEach((o) => this.applyLocal(o));
      }
      this.planPaint({ date: op.date, track: "actual", start: op.start, end: op.end,
                       block: op.kind === "skip" ? null : op.block, newId: op.newId }).forEach((o) => this.applyLocal(o));
      return;
    }
    if (op.kind === "paint") {
      // Outlook events in the way become the user's own blocks first (like store.paint).
      if (op.track === "plan") {
        const s = slotOf(op.start), e = slotOf(op.end);
        for (const ev of this.visibleOutlook()) {
          if (ev.date === op.date && slotOf(ev.start) < e && slotOf(ev.end) > s) {
            this.applyLocal({ kind: "detach_outlook", uid: ev.id });
          }
        }
      }
      this.planPaint(op).forEach((o) => this.applyLocal(o));
    } else if (op.kind === "move") {
      // A dragged block: take it out, then paint it in its new place with the same id (like store.move_block).
      const en = this.entries.get(op.id);
      if (!en) return;
      this.entries.delete(op.id);
      this.applyLocal({ kind: "paint", date: op.date, track: op.track, start: op.start, end: op.end, newId: op.id,
                        block: { label: en.label, categoryId: en.categoryId, details: en.details } });
    } else if (op.kind === "upsert") this.entries.set(op.entry.id, { ...op.entry });
    else if (op.kind === "hide_outlook") this.hidden.add(op.uid);
    else if (op.kind === "detach_outlook") {
      const ev = this.outlook.find((x) => x.id === op.uid);
      if (ev && !this.hidden.has(ev.id)) {
        this.hidden.add(ev.id);
        this.entries.set(`ol:${ev.id}`, {
          id: `ol:${ev.id}`, date: ev.date, track: "plan", start: ev.start, end: ev.end,
          label: ev.title, categoryId: ev.categoryId, details: ev.details,
        });
      }
    } else this.entries.delete(op.id);
  }

  visibleOutlook() {
    return this.outlook.filter((ev) => !this.hidden.has(ev.id));
  }

  // The day's Plan as blocks: the user's own, and visible timed calendar events (store._plan_items).
  planItems(date) {
    const own = this.entriesFor(date, "plan");
    const evs = this.visibleOutlook().filter((ev) => ev.date === date).map((ev) => ({
      id: `ol:${ev.id}`, date, track: "plan", start: ev.start, end: ev.end, label: ev.title,
      categoryId: ev.categoryId, details: ev.details }));
    return [...own, ...evs].sort((a, b) => slotOf(a.start) - slotOf(b.start));
  }

  // Local copy of store.materialise / materialise_ops, only to show a correction instantly:
  // copy the passed Plan into the empty Actual slots not done before (ids "m:<day>:<HH:mm>").
  materialiseLocal(date, confirm = false) {
    const st = this.dayState[date];
    if (!st) return;
    const upto = st.gone, done = st.upto;
    if (upto > done) {
      const taken = new Array(SLOTS).fill(false);
      const actual = this.entriesFor(date, "actual");
      const ids = new Set(actual.map((b) => b.id));
      actual.forEach((b) => { for (let i = Math.max(0, slotOf(b.start)); i < Math.min(slotOf(b.end), SLOTS); i++) taken[i] = true; });
      for (const p of this.planItems(date)) {
        const e = Math.min(slotOf(p.end), upto, SLOTS);
        let i = Math.max(slotOf(p.start), done);
        while (i < e) {
          if (taken[i]) { i++; continue; }
          let j = i;
          while (j < e && !taken[j]) taken[j++] = true;
          let id = `m:${date}:${slotTime(i)}`;
          if (ids.has(id)) id = uid();
          ids.add(id);
          this.entries.set(id, { id, date, track: "actual", start: slotTime(i), end: slotTime(j), label: p.label,
                                 categoryId: p.categoryId, details: p.details || null });
          i = j;
        }
      }
    }
    st.upto = Math.max(upto, done);
    if (upto >= SLOTS || (confirm && upto > 0)) st.confirmed = true;     // never a day that hasn't started
  }

  // Apply ops locally, queue them, and send everything still pending.
  commit(ops) {
    if (!ops.length) return;
    ops.forEach((op) => this.applyLocal(op));
    this.pending.push(...ops);
    this.paint();
    this.send(this.pending.slice());
    // If a trigger ever gets lost, resend whatever is still unacknowledged.
    clearTimeout(this.resendTimer);
    this.resendTimer = setTimeout(() => {
      if (this.pending.length) this.send(this.pending.slice());
    }, 3000);
  }

  entriesFor(date, track) {
    return [...this.entries.values()].filter((e) => e.date === date && e.track === track);
  }

  // Fill slots a..b (inclusive) of one day/track with a new block, or clear
  // them when `block` is null. Python saves it with the same rules
  // (store.plan_paint); newId keeps the new block's id the same on both sides.
  paintRange(di, track, a, b, block) {
    const s = Math.min(a, b), e = Math.max(a, b) + 1;
    this.commit([{
      opId: uid(), kind: "paint", date: this.data.days[di], track,
      start: slotTime(s), end: slotTime(e), block, newId: uid(),
    }]);
  }

  // Local copy of store.plan_paint, used only to show a paint instantly.
  // Overlapped blocks are trimmed or split, and the new block merges with
  // touching blocks that have the same label/category. Keep the two in sync.
  planPaint({ date, track, start, end, block, newId }) {
    const s = slotOf(start), e = slotOf(end);
    const ops = [];
    const up = (entry) => ({ kind: "upsert", entry });
    const del = (id) => ({ kind: "delete", id });

    for (const en of this.entriesFor(date, track)) {
      const es = slotOf(en.start), ee = slotOf(en.end);
      if (ee <= s || es >= e) continue;
      const left = es < s, right = ee > e;
      if (left) ops.push(up({ ...en, end: slotTime(s) }));
      if (right) ops.push(up({ ...en, id: left ? uid() : en.id, start: slotTime(e) }));
      if (!left && !right) ops.push(del(en.id));
    }

    if (block) {
      // Look at the state after trimming to find blocks to merge with.
      const after = new Map(this.entries);
      ops.forEach((op) => (op.kind === "upsert" ? after.set(op.entry.id, op.entry) : after.delete(op.id)));
      let ns = s, ne = e;
      for (const en of after.values()) {
        if (en.date !== date || en.track !== track) continue;
        if (en.label !== block.label || en.categoryId !== block.categoryId) continue;
        if (slotOf(en.end) === ns) { ns = slotOf(en.start); ops.push(del(en.id)); }
        else if (slotOf(en.start) === ne) { ne = slotOf(en.end); ops.push(del(en.id)); }
      }
      ops.push(up({ id: newId, date, track, start: slotTime(ns), end: slotTime(ne), ...block }));
    }
    return ops;
  }

  // ---------- Building the view ----------

  build() {
    const { categories, groups, days, today } = this.data;

    // Key: one line of colour dots (groups separated by a thin divider).
    // Clicking an item picks the brush.
    const item = (c) =>
      `<button class="sw" data-cat="${esc(c.id)}" title="${esc(c.group)}"><i style="background:${esc(c.colour)}"></i>${esc(c.name)}</button>`;
    const key = groups
      .map((g) => categories.filter((c) => c.group === g).sort((x, y) => x.order - y.order).map(item).join(""))
      .join('<span class="sep"></span>');

    // Two header rows: weekday + dd/mm (spanning Plan + Actual), then Plan / Actual.
    const dayHead = days
      .map((d) => {
        const dt = new Date(d + "T00:00");
        const name = dt.toLocaleDateString(LOC(), { weekday: "long" });
        return `<th colspan="${ONE ? 1 : 2}" class="day ${d === today ? "today" : ""}"><div class="dn">${name}</div><div class="dd">${dayNum(d)}</div>` +
          `${ONE ? `<div class="dstate" data-d="${days.indexOf(d)}"></div>` : ""}<div class="chips" data-d="${days.indexOf(d)}"></div></th>`;
      })
      .join("");
    const subHead = ONE ? "" : days.map(() => `<th class="sub first">Plan</th><th class="sub">Actual</th>`).join("");

    // One timeline: a single column of cells per day (data-t "plan": the slots that haven't passed edit the Plan).
    const tracks = ONE ? ["plan"] : TRACKS;
    const rows = [];
    for (let s = 0; s < SLOTS; s++) {
      const cells = days
        .map((d, di) => tracks.map((t) =>
          `<td class="s ${t === "plan" ? "first" : ""} ${d === today ? "today" : ""}" data-d="${di}" data-t="${t}" data-s="${s}"></td>`).join(""))
        .join("");
      // Label each hour on its grid line, like a calendar.
      const time = s % 2 === 0 ? `<span>${fmtTime(slotTime(s))}</span>` : "";
      rows.push(`<tr class="${s % 2 ? "half" : "hour"}"><td class="t">${time}</td>${cells}</tr>`);
    }

    const cols = days.map(() => (ONE ? "<col>" : "<col><col>")).join("");

    this.root.classList.toggle("single", !!this.data.single);   // one day: no week navigation
    this.root.classList.toggle("readonly", !!this.data.readonly); // view only: no editing tools
    this.root.classList.toggle("one", ONE);                         // one timeline
    this.root.innerHTML = `
      <div class="tt-head">
        <div class="tt-title">${this.data.single
          ? new Date(days[0] + "T00:00").toLocaleDateString(LOC(), { weekday: "long", day: "numeric", month: "long" })
          : weekTitle(days[0], days[days.length - 1])}</div>
        <div class="tt-nav">
          <button data-nav="-1" title="Previous week">‹</button>
          <button data-nav="0">Today</button>
          <button data-nav="1" title="Next week">›</button>
        </div>
        <input type="date" class="tt-goto" title="Go to date" aria-label="Go to date" value="${days[0]}">
        <div class="tt-outlook">
          <button class="tt-sync" title="Sync Outlook now"><span class="msr">sync</span></button>
          <span class="tt-synced"></span>
          <button class="tt-ol-toggle" title="Show or hide Outlook events">${CAL_ICON}Outlook</button>
        </div>
        <div class="tt-tools">
          <datalist id="tt-labels"></datalist>
          <button class="tt-help-btn" aria-expanded="false" aria-controls="tt-help" title="How the timetable works">?</button>
          <div class="tt-help" id="tt-help" role="dialog" aria-label="How the timetable works" hidden>${helpHtml(this.data.single)}</div>
        </div>
      </div>
      <div class="tt-legend">${key}</div>
      <div class="tt-card">
        <div class="tt-wrap">
          <table class="tt" aria-hidden="true">
            <colgroup><col class="c-time">${cols}</colgroup>
            <thead>
              <tr><th rowspan="${ONE ? 1 : 2}" class="h-time"></th>${dayHead}</tr>
              ${ONE ? "" : `<tr>${subHead}</tr>`}
            </thead>
            <tbody>${rows.join("")}</tbody>
          </table>
          <div class="tt-blocks" aria-hidden="true"></div>
          <div class="tt-lines" aria-hidden="true"></div>
        </div>
      </div>
      <div class="tt-a11y" role="region" aria-label="Timetable blocks (press Enter on one for details)"></div>`;

    // Blocks are positioned from the cells, so redo them when the size changes.
    this.blocksEl = this.root.querySelector(".tt-blocks");
    this.wrapEl = this.root.querySelector(".tt-wrap");
    if (this.resizeObserver) this.resizeObserver.disconnect();
    this.resizeObserver = new ResizeObserver(() => this.layoutBlocks());
    if (this.attached) this.resizeObserver.observe(this.wrapEl);

    // Index the slot cells: cells[day][track][slot]. One timeline: both tracks are the same column.
    this.cells = days.map(() => { const plan = []; return { plan, actual: ONE ? plan : [] }; });
    this.root.querySelectorAll("td.s").forEach((td) => {
      this.cells[+td.dataset.d][td.dataset.t][+td.dataset.s] = td;
    });

    this.bindEvents();
    this.showBrush();
  }

  showOutlookStatus() {
    const { sync, showOutlook } = this.data;
    const note = this.root.querySelector(".tt-synced");
    note.textContent = sync ? sync.text : "";
    note.classList.toggle("warn", !!(sync && sync.error));
    note.title = (sync && sync.detail) || "";
    this.root.querySelector(".tt-ol-toggle").classList.toggle("on", !!showOutlook);
    const btn = this.root.querySelector(".tt-sync");
    btn.classList.remove("spin");
    btn.title = `Sync Outlook now${sync && sync.text ? ` (${sync.text.toLowerCase()})` : ""}`;   // Home hides the note
  }

  refreshDatalist() {
    const labels = new Set([
      ...Object.keys(this.data.labelMap),
      ...this.data.categories.map((c) => c.name),
      ...[...this.entries.values()].map((e) => e.label),
    ]);
    this.root.querySelector("#tt-labels").innerHTML =
      [...labels].sort().map((l) => `<option value="${esc(l)}">`).join("");
  }

  // Work out which entry fills each slot, then draw the blocks.
  paint() {
    if (ONE) { this.paintOne(); return; }
    this.occupant = this.data.days.map(() => ({ plan: [], actual: [] }));
    this.blocks = [];
    for (const day of this.cells) {
      for (const td of [...day.plan, ...day.actual]) {
        td.title = "";
        td.classList.remove("filled");
      }
    }
    for (const en of this.entries.values()) {
      const di = this.dayIndex.get(en.date);
      if (di === undefined) continue;
      const s = slotOf(en.start), e = Math.min(slotOf(en.end), SLOTS);
      if (e <= s) continue;
      for (let i = s; i < e; i++) {
        const td = this.cells[di][en.track][i];
        td.title = `${en.label} · ${fmtRange(en.start, en.end)}`;
        td.classList.add("filled");
        this.occupant[di][en.track][i] = en.id;
      }
      this.blocks.push({ en, di, s, e });
    }

    // Outlook events: drawn on top of the Plan column (click for details, edit or remove).
    this.outlookAt = this.data.days.map(() => []);
    for (const ev of this.visibleOutlook()) {
      const di = this.dayIndex.get(ev.date);
      if (di === undefined) continue;
      const s = slotOf(ev.start), e = Math.min(slotOf(ev.end), SLOTS);
      if (e <= s) continue;
      for (let i = s; i < e; i++) {
        const td = this.cells[di].plan[i];
        td.title = `${ev.title} · ${ev.exact} (Outlook)`;
        td.classList.add("filled");
        this.outlookAt[di][i] = ev;
      }
      this.blocks.push({ en: { ...ev, label: ev.title, track: "plan" }, di, s, e, outlook: true });
    }

    // All-day Outlook events: small chips in the day header.
    this.root.querySelectorAll("th.day .chips").forEach((box) => {
      const date = this.data.days[+box.dataset.d];
      box.innerHTML = (this.data.outlookAllDay || []).filter((c) => c.date === date)
        .map((c) => `<span class="chip${c.deadline ? " due" : ""}" title="${esc(c.title)} (${c.deadline ? "deadline" : "Outlook, all day"})">${esc(c.title)}</span>`).join("");
    });
    this.addGhosts();
    this.layoutBlocks();
    this.renderBlockList();
  }

  // Suggested sittings: only where the Plan is still free (and, on the one timeline, not passed).
  addGhosts() {
    this.ghostAt = this.data.days.map(() => []);
    if (this.data.readonly) return;
    for (const g of this.suggestions) {
      const di = this.dayIndex.get(g.date);
      if (di === undefined || this.ghostsTaken.has(g.id)) continue;
      const s = slotOf(g.start), e = Math.min(slotOf(g.end), SLOTS);
      let free = e > s;
      for (let i = s; i < e && free; i++) {
        if (this.occupant[di].plan[i] || this.outlookAt[di][i] || this.isPast(di, i)) free = false;
      }
      if (!free) continue;
      for (let i = s; i < e; i++) this.ghostAt[di][i] = g;
      this.blocks.push({ en: { ...g, track: "plan" }, di, s, e, ghost: true });
    }
  }

  // Add one suggested sitting to the Plan (Python checks the slots are still free).
  takeGhost(g) {
    this.commit([{ opId: uid(), kind: "add_suggestion", ghost: g.id, date: g.date, start: g.start, end: g.end,
                   block: { label: g.label, categoryId: g.categoryId, details: null }, newId: uid() }]);
  }

  // One timeline: per day, the slots that haven't passed show the Plan (blocks and calendar events, editable
  // as in the Plan column); the passed ones show "pieces": what happened, as the store sees it.
  //   actual     an Actual block that matches the Plan (or the Plan was confirmed)
  //   assumed    no Actual yet, day not materialised there: the Plan, unconfirmed
  //   unplanned  an Actual block where nothing (or something else) was planned: outlined
  //   skipped    planned, but the day's Actual says nothing happened: hatched and struck through
  paintOne() {
    const days = this.data.days;
    this.occupant = days.map(() => ({ plan: [], actual: [] }));
    this.outlookAt = days.map(() => []);
    this.pieceAt = days.map(() => []);
    this.blocks = [];
    for (const day of this.cells) for (const td of day.plan) { td.title = ""; td.classList.remove("filled", "past"); }
    const evs = this.visibleOutlook();
    days.forEach((date, di) => {
      const st = this.dayState[date] || { gone: 0, upto: 0 };
      const planAt = [], actAt = [];
      for (const en of this.entriesFor(date, "plan"))
        for (let i = Math.max(0, slotOf(en.start)); i < Math.min(slotOf(en.end), SLOTS); i++) planAt[i] = { en };
      for (const ev of evs.filter((x) => x.date === date))
        for (let i = Math.max(0, slotOf(ev.start)); i < Math.min(slotOf(ev.end), SLOTS); i++) planAt[i] = { ev };
      for (const en of this.entriesFor(date, "actual"))
        for (let i = Math.max(0, slotOf(en.start)); i < Math.min(slotOf(en.end), SLOTS); i++) actAt[i] = en;
      const same = (p, a) => p && a && (p.en ? p.en.label === a.label && p.en.categoryId === a.categoryId
                                           : p.ev.title === a.label && p.ev.categoryId === a.categoryId);
      const asEntry = (p) => (p.en ? p.en : { id: `outlook:${p.ev.id}`, date, track: "plan", start: p.ev.start, end: p.ev.end,
                                              label: p.ev.title, categoryId: p.ev.categoryId, details: p.ev.details, ev: p.ev });
      // Future: the Plan as in the Plan column (whole blocks / events, from the first slot that hasn't passed).
      for (let i = st.gone; i < SLOTS; i++) {
        const p = planAt[i];
        if (!p) continue;
        const td = this.cells[di].plan[i];
        td.classList.add("filled");
        if (p.en) { this.occupant[di].plan[i] = p.en.id; td.title = `${p.en.label} · ${fmtRange(p.en.start, p.en.end)}`; }
        else { this.outlookAt[di][i] = p.ev; td.title = `${p.ev.title} · ${p.ev.exact} (calendar)`; }
      }
      let i = st.gone;
      while (i < SLOTS) {
        const p = planAt[i];
        if (!p) { i++; continue; }
        let j = i;
        while (j < SLOTS && planAt[j] && (planAt[j].en || planAt[j].ev) === (p.en || p.ev)) j++;
        if (p.en) this.blocks.push({ en: p.en, di, s: i, e: j });
        else this.blocks.push({ en: { ...p.ev, label: p.ev.title, track: "plan" }, di, s: i, e: j, outlook: true });
        i = j;
      }
      // Passed slots: one piece per run of the same thing.
      const kindAt = [];
      for (let k = 0; k < st.gone; k++) {
        const a = actAt[k], p = planAt[k];
        if (a) kindAt[k] = { kind: k < st.upto && !same(p, a) ? "unplanned" : "actual", en: a, key: a.id };
        else if (p && k < st.upto) kindAt[k] = { kind: "skipped", en: asEntry(p), key: (p.en || p.ev).id };
        else if (p) kindAt[k] = { kind: "assumed", en: asEntry(p), key: (p.en || p.ev).id };
      }
      i = 0;
      while (i < st.gone) {
        const k = kindAt[i];
        if (!k) { i++; continue; }
        let j = i;
        while (j < st.gone && kindAt[j] && kindAt[j].key === k.key && kindAt[j].kind === k.kind) j++;
        const piece = { en: k.en, di, s: i, e: j, kind: k.kind, past: true, id: `past:${date}:${slotTime(i)}` };
        this.blocks.push(piece);
        for (let x = i; x < j; x++) {
          this.pieceAt[di][x] = piece;
          const td = this.cells[di].plan[x];
          td.classList.add("filled");
          td.title = `${PIECE_WORDS[k.kind]}: ${k.en.label} · ${fmtRange(slotTime(i), slotTime(j))}`;
        }
        i = j;
      }
      for (let k = 0; k < st.gone; k++) this.cells[di].plan[k].classList.add("past");
    });
    this.addGhosts();
    this.root.querySelectorAll("th.day .chips").forEach((box) => {
      const date = this.data.days[+box.dataset.d];
      box.innerHTML = (this.data.outlookAllDay || []).filter((c) => c.date === date)
        .map((c) => `<span class="chip${c.deadline ? " due" : ""}" title="${esc(c.title)} (${c.deadline ? "deadline" : "Outlook, all day"})">${esc(c.title)}</span>`).join("");
    });
    // Each day's state under its name: confirmed, or a Confirm button once it has passed (also in the block list).
    this.root.querySelectorAll("th.day .dstate").forEach((box) => {
      const date = this.data.days[+box.dataset.d], st = this.dayState[date] || {};
      box.innerHTML = st.confirmed ? `<span class="ok">✓ Confirmed</span>`
        : st.gone > 0 && !this.data.readonly ? `<button class="confirm" tabindex="-1" data-confirm="${esc(date)}" title="It went as planned: confirm this day">Confirm</button>`
        : st.gone > 0 ? `<span class="unconf">Not confirmed</span>` : "";
    });
    this.layoutBlocks();
    this.renderBlockList();
  }

  // For keyboard and screen-reader users: every block as a button, grouped by day,
  // in a list that's invisible until something in it has focus. Enter opens the
  // block's details card (with Edit / Delete), the same as clicking it.
  renderBlockList() {
    const list = this.root.querySelector(".tt-a11y");
    if (!list) return;
    this.listed = [...this.blocks].sort((x, y) => x.di - y.di || x.s - y.s || (x.en.track < y.en.track ? -1 : 1));
    const groups = this.data.days.map((d, di) => {
      const day = new Date(d + "T00:00").toLocaleDateString(LOC(), { weekday: "long", day: "numeric", month: "long" });
      const items = this.listed.map((b, i) => [b, i]).filter(([b]) => b.di === di).map(([b, i]) => {
        const cat = this.cats.get(b.en.categoryId);
        if (b.ghost) return `<button data-i="${i}">${esc(`Suggested: ${b.en.label} ${fmtRange(b.en.start, b.en.end)}, for ${b.en.goal} (add to Plan)`)}</button>`;
        const head = b.past ? PIECE_WORDS[b.kind] : b.outlook ? "Plan (Outlook)" : b.en.track === "plan" ? "Plan" : "Actual";
        const when = b.past ? `${fmtTime(slotTime(b.s))} to ${fmtTime(slotTime(b.e))}`
          : b.outlook ? b.en.exact : `${fmtTime(b.en.start)} to ${fmtTime(b.en.end)}`;
        const what = `${head}: ${b.en.label}, ${when}${cat ? `, ${cat.name}` : ""}`;
        return `<button data-i="${i}">${esc(what)}</button>`;
      });
      const st = ONE && !this.data.readonly && this.dayState[d];
      if (st && st.gone > 0 && !st.confirmed) items.push(`<button data-confirm="${esc(d)}">Confirm ${esc(day)} as planned</button>`);
      return items.length ? `<div role="group" aria-label="${esc(day)}"><span class="a11y-day">${esc(day)}</span>${items.join("")}</div>` : "";
    }).join("");
    list.innerHTML = groups || `<button disabled>Nothing in the timetable this ${this.data.single ? "day" : "week"}</button>`;
  }

  // Draw each entry as one rounded block laid over its slot cells.
  // Home (view only): shrink the rows so the whole day fits in the window, no scrolling.
  // Shrink (or grow) the rows so the whole day fits in the window without scrolling:
  // Home down to 9px rows, the Timetable page down to 10px (still big enough to drag in).
  fitToWindow() {
    if (!this.wrapEl || !this.cells || !this.cells[0]) return;
    const min = this.data.readonly ? 9 : 10, max = 18;
    const main = document.querySelector(".stMainBlockContainer");
    const bottomPad = main ? parseFloat(getComputedStyle(main).paddingBottom) : 24;
    const bottom = () => Math.max(...[".tt-card", ".tt-legend"].map((sel) => {
      const r = this.root.querySelector(sel)?.getBoundingClientRect();
      return r && r.height ? r.bottom : 0;
    }));
    let row = parseFloat(getComputedStyle(this.root).getPropertyValue("--row-h")) || 18;
    for (let i = 0; i < 3; i++) {        // a few times: borders make the first guess a little off
      const over = bottom() + bottomPad - window.innerHeight;
      row = Math.max(min, Math.min(max, Math.floor(row - over / SLOTS)));
      this.root.style.setProperty("--row-h", `${row}px`);
    }
  }


  // Home only: a thin red line across today at the current time, moving down as time passes.
  drawNow() {
    let line = this.wrapEl && this.wrapEl.querySelector(".tt-now");
    const di = this.data && (this.data.readonly || ONE) && this.data.nowMin != null ? this.dayIndex.get(this.data.today) : undefined;
    let m = di === undefined ? -1 : this.nowAt.min + (Date.now() - this.nowAt.ms) / 60000 - FIRST_MIN;
    if (m < 0 && di !== undefined) m += 24 * 60;          // after midnight, when the day runs past it
    const slot = m / 30;
    if (di === undefined || slot < 0 || slot >= SLOTS || !this.cells[di]) { if (line) line.remove(); return; }
    const origin = this.wrapEl.getBoundingClientRect();
    const cell = this.cells[di].plan[Math.floor(slot)].getBoundingClientRect();
    const end = (this.cells[di].actual[Math.floor(slot)] || this.cells[di].plan[Math.floor(slot)]).getBoundingClientRect();
    if (!line) {
      line = document.createElement("div");
      line.className = "tt-now";
      line.setAttribute("aria-hidden", "true");
      this.wrapEl.appendChild(line);
    }
    line.style.top = `${cell.top - origin.top + (slot - Math.floor(slot)) * cell.height}px`;
    line.style.left = `${cell.left - origin.left}px`;
    line.style.width = `${end.right - cell.left}px`;
    clearTimeout(this.nowTimer);
    this.nowTimer = setTimeout(() => this.drawNow(), 30000);    // keep it moving
  }

  // A thin line under each half hour, across every day (over the blocks too).
  drawLines() {
    const el = this.root.querySelector(".tt-lines");
    if (!el || !this.cells[0]) return;
    const origin = this.wrapEl.getBoundingClientRect();
    const days = this.cells.length;
    const left = this.cells[0].plan[0].getBoundingClientRect().left - origin.left;
    const right = (this.cells[days - 1].actual[0] || this.cells[days - 1].plan[0]).getBoundingClientRect().right - origin.left;
    let html = "";
    for (let s = 0; s < SLOTS - 1; s++) {
      const td = this.cells[0].plan[s];
      const top = td.getBoundingClientRect().bottom - origin.top - 1;
      const hour = td.parentElement.classList.contains("half");
      html += `<i class="${hour ? "h" : ""}" style="top:${top}px;left:${left}px;width:${right - left}px"></i>`;
    }
    el.innerHTML = html;
  }

  // Where a block goes: exactly over the tiles it covers (the same gaps and rounded corners),
  // so blocks and empty tiles line up. The gaps come from the CSS (--gap, --day-gap).
  boxStyle(first, last, origin) {
    const css = getComputedStyle(this.root);
    const gap = parseFloat(css.getPropertyValue("--gap")) || 2.5;
    const dayGap = parseFloat(css.getPropertyValue("--day-gap")) || 7;
    const a = first.getBoundingClientRect(), b = last.getBoundingClientRect();
    const border = parseFloat(getComputedStyle(last).borderBottomWidth) || 0;
    const left = a.left - origin.left + (first.classList.contains("first") ? dayGap : gap);
    const top = a.top - origin.top + gap;
    const right = a.right - origin.left - gap;
    const bottom = b.bottom - origin.top - border - gap;
    return `left:${left}px;top:${top}px;width:${right - left}px;height:${bottom - top}px;`;
  }

  layoutBlocks() {
    this.drawNow();
    this.drawLines();
    if (!this.blocks) return;
    const origin = this.wrapEl.getBoundingClientRect();
    this.blocksEl.innerHTML = this.blocks
      .map(({ en, di, s, e, outlook, past, kind, id, ghost }) => {
        const firstTd = this.cells[di][en.track][s], lastTd = this.cells[di][en.track][e - 1];
        const first = firstTd.getBoundingClientRect(), last = lastTd.getBoundingClientRect();
        const cat = this.cats.get(en.categoryId);
        const bg = cat ? cat.colour : "#9e9e9e";
        const fg = (cat && cat.textColour) || contrastText(bg);
        const tall = last.bottom - first.top >= 30;   // room for the time line under the title
        if (ghost) {          // a suggested sitting: dashed, "+ Study 2 h"
          const h = (e - s) / 2;
          return `<div class="blk ghost ${tall ? "tall" : ""}" data-id="${esc(en.id)}" style="${this.boxStyle(firstTd, lastTd, origin)}--fill:${esc(bg)}">` +
            `<b>+ ${esc(en.label)} ${h} h</b>${tall ? `<span>Suggested · click to add</span>` : ""}</div>`;
        }
        if (past) {           // one timeline, time that has passed: what happened (see paintOne)
          const mark = kind === "assumed" ? "?" : kind === "skipped" ? "✕" : kind === "unplanned" ? "+" : "✓";
          return `<div class="blk past ${kind} ${tall ? "tall" : ""} ${this.focusId === id ? "focus" : ""}${this.hovered === id ? " hover" : ""}${this.picked.has(id) ? " picked" : ""}" data-id="${esc(id)}" style="${this.boxStyle(firstTd, lastTd, origin)}` +
            `--fill:${esc(bg)};${kind === "skipped" || kind === "assumed" ? "" : `background:${esc(bg)};color:${fg}`}">` +
            `<b><i class="mk" aria-hidden="true">${mark}</i>${esc(en.label)}</b>${tall ? `<span>${esc(fmtRange(slotTime(s), slotTime(e)))}</span>` : ""}</div>`;
        }
        if (outlook) {
          return `<div class="blk outlook ${tall ? "tall" : ""} ${this.focusId === "outlook:" + en.id ? "focus" : ""}${this.hovered === "outlook:" + en.id ? " hover" : ""}${this.picked.has("outlook:" + en.id) ? " picked" : ""}" data-id="outlook:${esc(en.id)}" style="${this.boxStyle(firstTd, lastTd, origin)}` +
            `background:${esc(bg)};color:${fg}">` +
            `<b>${CAL_ICON}${esc(en.title)}</b>${tall ? `<span>${esc(en.exact)}</span>` : ""}</div>`;
        }
        return `<div class="blk ${tall ? "tall" : ""} ${this.focusId === en.id ? "focus" : ""}${this.hovered === en.id ? " hover" : ""}${this.picked.has(en.id) ? " picked" : ""}" data-id="${esc(en.id)}" style="${this.boxStyle(firstTd, lastTd, origin)}` +
          `background:${esc(bg)};color:${fg}">` +
          `<b>${esc(en.label)}</b>${tall ? `<span>${esc(fmtRange(en.start, en.end))}</span>` : ""}</div>`;
      })
      .join("");
  }

  // ---------- Brush ----------

  setBrush(id) {
    this.brush = id;
    remember("tt-brush", id);
    this.showBrush();
  }

  // Nothing picked: dragging empty time draws a selection box instead of adding.
  clearBrush() {
    this.brush = null;
    remember("tt-brush", null);
    this.showBrush();
  }

  showBrush() {
    this.root.querySelectorAll("[data-cat]").forEach((el) => {
      el.classList.toggle("on", el.dataset.cat === this.brush);
      el.setAttribute("aria-pressed", el.dataset.cat === this.brush ? "true" : "false");
    });
  }

  // Default category for a typed label (case-insensitive), if any.
  mapLabel(label) {
    const want = label.trim().toLowerCase();
    if (!want) return null;
    for (const [l, id] of Object.entries(this.data.labelMap)) if (l.toLowerCase() === want) return id;
    for (const c of this.data.categories) if (c.name.toLowerCase() === want) return c.id;
    return null;
  }

  // ---------- Events ----------

  bindEvents() {
    const table = this.root.querySelector("table.tt");

    this.root.querySelectorAll("[data-cat]").forEach((el) =>
      el.addEventListener("click", () =>
        el.dataset.cat === this.brush ? this.clearBrush() : this.setBrush(el.dataset.cat)));   // click again to deselect

    this.root.querySelector(".tt-sync").addEventListener("click", (e) => {
      e.currentTarget.classList.add("spin");
      this.trigger("sync", {});
    });
    this.root.querySelector(".tt-ol-toggle").addEventListener("click", () =>
      this.trigger("outlook", { show: !this.data.showOutlook }));

    this.root.querySelector(".tt-help-btn").addEventListener("click", () => this.toggleHelp());
    this.root.querySelectorAll("[data-nav]").forEach((el) =>
      el.addEventListener("click", () => this.nav({ dir: +el.dataset.nav })));
    this.root.querySelector(".tt-goto").addEventListener("change", (e) => {
      if (e.target.value) this.nav({ date: e.target.value });
    });

    table.addEventListener("mousedown", (e) => {
      const td = e.target.closest("td.s");
      if (!td || e.button !== 0) return;
      e.preventDefault();
      // preventDefault keeps focus where it was: leave the label box, so Delete / Backspace act on blocks.
      const typing = this.root.getRootNode().activeElement || document.activeElement;
      if (isTextField(typing)) typing.blur();
      if (this.data.readonly) {                     // Home: no editing, just the details card
        const hit = this.blockAt(+td.dataset.d, td.dataset.t, +td.dataset.s);
        if (hit) this.openCard(hit); else this.closePopover();
        return;
      }
      this.closePopover();
      const di = +td.dataset.d, track = td.dataset.t, slot = +td.dataset.s;
      const hit = this.blockAt(di, track, slot);
      const hitId = hit && this.idOf(hit);
      if (this.isPast(di, slot)) {                  // one timeline, time that has passed: corrections only
        if (hit) {
          this.setPicked([hitId]);
          const { s0, e0 } = this.spanOf(hit);
          this.blockDrag = { hit, zone: this.zoneAt(di, track, s0, e0, e.clientY), di, track, downSlot: slot, s0, e0,
                             target: { di, track, s: s0, e: e0 }, moved: false, past: true };
        } else {
          if (this.picked.size) this.setPicked([]);
          this.drag = { di, track, a: slot, b: slot, past: true };   // with a category picked: something unplanned
        }
        this.highlight();
        return;
      }
      const adding = e.shiftKey || (IS_MAC ? e.metaKey : e.ctrlKey);   // Shift or Cmd/Ctrl: add to the selection
      const ghost = !hit && !adding && track === "plan" && this.ghostAt[di] && this.ghostAt[di][slot];
      if (ghost) { this.takeGhost(ghost); return; }      // a suggested sitting: add just that one
      // Dragging empty time draws a selection box with Shift / Cmd / Ctrl held, or when no category is picked.
      const selecting = adding || (!hit && !this.cats.has(this.brush));
      if (adding && hit) {                          // Shift / Cmd / Ctrl-click a block: add it to / take it out of the selection
        const next = new Set(this.picked);
        next.has(hitId) ? next.delete(hitId) : next.add(hitId);
        this.setPicked([...next]);
        return;
      }
      if (hit && this.picked.has(hitId) && this.picked.size > 1) {   // a selected block: move the whole group
        this.groupDrag = { downDi: di, downSlot: slot, hit, ddi: 0, ds: 0, moved: false,
                           items: [...this.picked].map((id) => this.itemOf(id)).filter(Boolean) };
        this.highlight();
        return;
      }
      // The top or bottom edge of any block (selected or not): resize it straight away.
      if (hit && !selecting && !(this.picked.has(hitId) && this.picked.size > 1)) {
        const { s0, e0 } = this.spanOf(hit);
        const zone = this.zoneAt(di, track, s0, e0, e.clientY);
        if (zone !== "move") {
          const fresh = !(this.picked.size === 1 && this.picked.has(hitId));   // a first click only selects it
          if (fresh) this.setPicked([hitId]);
          this.blockDrag = { hit, zone, di, track, downSlot: slot, s0, e0, target: { di, track, s: s0, e: e0 }, moved: false,
                             fresh };
          this.highlight();
          return;
        }
      }
      // An unselected block: a click selects it; dragging from it draws a box that selects
      // every block it touches. Empty time draws a box too when no category is picked.
      if (selecting || (hit && !this.picked.has(hitId))) {
        this.marquee = { di0: di, t0: track, s0: slot, di1: di, t1: track, s1: slot, add: adding,
                         from: hit && !adding ? hitId : null };
        this.highlight();
        return;
      }
      if (hit) {                                    // the selected block: move it, or drag its top / bottom edge
        const { s0, e0 } = this.spanOf(hit);
        this.blockDrag = { hit, zone: this.zoneAt(di, track, s0, e0, e.clientY), di, track, downSlot: slot, s0, e0,
                           target: { di, track, s: s0, e: e0 }, moved: false };
        this.highlight();
        return;
      }
      if (this.picked.size) this.setPicked([]);   // clicking empty time clears the selection
      this.drag = { di, track, a: slot, b: slot };
      this.highlight();
    });

    // Hovering a block: the cursor (and two little bars) show you can drag its edges or move it.
    table.addEventListener("mousemove", (e) => {
      if (this.data.readonly || this.drag) return;
      if (this.blockDrag) { table.style.cursor = this.blockDrag.zone === "move" ? "grabbing" : "ns-resize"; return; }
      if (this.groupDrag) { table.style.cursor = "grabbing"; return; }
      if (this.marquee) { table.style.cursor = "crosshair"; return; }
      const td = e.target.closest("td.s");
      this.hoverCell = td ? { di: +td.dataset.d, track: td.dataset.t, slot: +td.dataset.s } : null;
      const hit = td && this.blockAt(+td.dataset.d, td.dataset.t, +td.dataset.s);
      this.hoverBlock(hit ? (hit.outlook ? `outlook:${hit.ev.id}` : hit.entry.id) : null);
      const adding = e.shiftKey || (IS_MAC ? e.metaKey : e.ctrlKey);
      if (!hit && td && td.dataset.t === "plan" && this.ghostAt[+td.dataset.d][+td.dataset.s]) { table.style.cursor = "pointer"; return; }
      if (!hit) { table.style.cursor = td && (adding || !this.cats.has(this.brush)) ? "crosshair" : ""; return; }
      const { s0, e0 } = this.spanOf(hit);
      const zone = this.zoneAt(+td.dataset.d, td.dataset.t, s0, e0, e.clientY);
      const inGroup = this.picked.has(this.idOf(hit)) && this.picked.size > 1;
      table.style.cursor = adding ? "pointer"
        : zone !== "move" && !inGroup ? "ns-resize"                         // any block's edge: drag to resize
        : !this.picked.has(this.idOf(hit)) ? "pointer"                     // not selected: a click selects it
        : "grab";
    });
    table.addEventListener("mouseleave", () => {
      this.hoverCell = null;
      if (!this.blockDrag) { table.style.cursor = ""; this.hoverBlock(null); }
    });

    // "Confirm" under a day's name (and in the block list): the day went as planned.
    this.root.addEventListener("click", (e) => {
      const c = e.target.closest("[data-confirm]");
      if (!c || this.data.readonly) return;
      this.commit([{ opId: uid(), kind: "confirm_day", date: c.dataset.confirm }]);
    });

    this.root.querySelector(".tt-a11y").addEventListener("click", (e) => {
      const b = e.target.closest("[data-i]");
      if (!b) return;
      const block = this.listed[+b.dataset.i];
      if (block.ghost) { this.takeGhost(block.en); return; }
      const hit = block.past ? { past: true, piece: block, outlook: false, entry: block.en }
        : block.outlook ? { outlook: true, ev: { ...block.en, title: block.en.label } } : { outlook: false, entry: block.en };
      this.openCard(hit);
      // Move focus into the card so its buttons are next; Esc closes it and returns here.
      this.returnFocus = b;
      if (this.popover) { this.popover.tabIndex = -1; this.popover.focus(); }
    });

    table.addEventListener("mouseover", (e) => {
      const td = e.target.closest("td.s");
      if (this.blockDrag && td) { this.dragBlockTo(+td.dataset.d, td.dataset.t, +td.dataset.s); return; }
      if (this.marquee && td) {
        Object.assign(this.marquee, { di1: +td.dataset.d, t1: td.dataset.t, s1: +td.dataset.s });
        this.highlight();
        return;
      }
      if (this.groupDrag && td) { this.dragGroupTo(+td.dataset.d, +td.dataset.s); return; }
      if (!this.drag || !td) return;
      if (+td.dataset.d !== this.drag.di || td.dataset.t !== this.drag.track) return;
      // One timeline: a drag stays on its side of now (the past is the Actual, the rest the Plan).
      if (ONE && this.drag.past !== this.isPast(this.drag.di, +td.dataset.s)) return;
      this.drag.b = +td.dataset.s;
      this.highlight();
    });

    table.addEventListener("contextmenu", (e) => {
      const td = e.target.closest("td.s");
      if (!td) return;
      const hit = this.blockAt(+td.dataset.d, td.dataset.t, +td.dataset.s);
      if (!hit) return;
      e.preventDefault();
      if (this.data.readonly || hit.outlook || hit.past) this.openCard(hit);   // details first for Outlook events
      else this.openPopover(hit.entry, e.clientX, e.clientY);           // straight to the editor
    });

    // Trackpad swipe sideways = previous / next week (one flip per gesture).
    this.root.querySelector(".tt-card").addEventListener("wheel", (e) => {
      if (this.data.single || Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
      e.preventDefault();
      if (this.swipeLocked) return;
      this.swipe += e.deltaX;
      if (Math.abs(this.swipe) >= SWIPE_THRESHOLD) {
        this.nav({ dir: this.swipe > 0 ? 1 : -1 });
        this.swipe = 0;
        this.swipeLocked = true;
        setTimeout(() => { this.swipeLocked = false; }, 700);
      }
    }, { passive: false });
  }

  attach() {
    if (this.attached) return;
    window.addEventListener("resize", this.onWindowResize);
    window.addEventListener("mousedown", this.onOutside);
    this.resizeObserver.observe(this.wrapEl);
    window.addEventListener("mouseup", this.onMouseUp);
    window.addEventListener("keydown", this.onKey);
    this.attached = true;
  }

  detach() {
    clearTimeout(this.nowTimer);
    window.removeEventListener("resize", this.onWindowResize);
    window.removeEventListener("mousedown", this.onOutside);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    window.removeEventListener("mouseup", this.onMouseUp);
    window.removeEventListener("keydown", this.onKey);
    this.attached = false;
  }

  highlight() {
    this.selected.forEach((td) => td.classList.remove("sel", "box"));
    this.selected = [];
    // Fade the blocks while dragging so the selection shows through.
    this.wrapEl.classList.toggle("dragging", !!this.drag || !!this.blockDrag || !!this.groupDrag);
    if (this.marquee) {
      const m = this.marquee, c0 = col(m.di0, m.t0), c1 = col(m.di1, m.t1);
      for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++)
        for (let i = Math.min(m.s0, m.s1); i <= Math.max(m.s0, m.s1); i++) {
          const [cd, ct] = colCell(c);
          const td = this.cells[cd][ct][i];
          td.classList.add("sel", "box");
          this.selected.push(td);
        }
      return;
    }
    if (this.groupDrag) {
      const g = this.groupDrag;
      for (const it of g.items)
        for (let i = it.s + g.ds; i < it.e + g.ds; i++) {
          const td = this.cells[it.di + g.ddi][it.track][i];
          td.classList.add("sel");
          this.selected.push(td);
        }
      return;
    }
    if (this.blockDrag) {
      const { di, track, s, e } = this.blockDrag.target;
      for (let i = s; i < e; i++) {
        const td = this.cells[di][track][i];
        td.classList.add("sel");
        this.selected.push(td);
      }
      return;
    }
    if (!this.drag) return;
    const { di, track, a, b } = this.drag;
    for (let s = Math.min(a, b); s <= Math.max(a, b); s++) {
      const td = this.cells[di][track][s];
      td.classList.add("sel");
      this.selected.push(td);
    }
  }

  cancelDrag() {
    this.drag = null;
    this.blockDrag = null;
    this.marquee = null;
    this.groupDrag = null;
    this.highlight();
  }

  // ---------- Selecting several blocks ----------

  idOf(hit) { return hit.past ? hit.piece.id : hit.outlook ? `outlook:${hit.ev.id}` : hit.entry.id; }

  // One timeline: has this slot of a day passed (so it shows, and corrects, what happened)?
  isPast(di, slot) {
    if (!ONE) return false;
    const st = this.dayState[this.data.days[di]];
    return !!st && slot < st.gone;
  }

  // A selected block as {id, outlook, en, di, track, s, e} (or null if it's gone).
  itemOf(id) {
    const b = (this.blocks || []).find((x) => !x.past && !x.ghost && (x.outlook ? `outlook:${x.en.id}` : x.en.id) === id);
    return b ? { id, outlook: !!b.outlook, en: b.en, di: b.di, track: b.en.track, s: b.s, e: b.e } : null;
  }

  setPicked(ids) {
    this.picked = new Set(ids);
    this.blocksEl.querySelectorAll(".blk").forEach((el) => el.classList.toggle("picked", this.picked.has(el.dataset.id)));
  }

  endMarquee() {
    const m = this.marquee;
    this.marquee = null;
    this.highlight();
    this.root.querySelector("table").style.cursor = "";
    const c0 = Math.min(col(m.di0, m.t0), col(m.di1, m.t1)), c1 = Math.max(col(m.di0, m.t0), col(m.di1, m.t1));
    const s0 = Math.min(m.s0, m.s1), s1 = Math.max(m.s0, m.s1);
    if (m.from && c0 === c1 && s0 === s1) { this.setPicked([m.from]); return; }   // a click on a block: select it
    const inside = this.blocks.filter((b) => {
      if (b.past || b.ghost) return false;            // passed time is corrected one piece at a time
      const c = col(b.di, b.en.track);
      return c >= c0 && c <= c1 && b.s <= s1 && b.e > s0;
    }).map((b) => (b.outlook ? `outlook:${b.en.id}` : b.en.id));
    this.setPicked(m.add ? [...this.picked, ...inside] : inside);
    // A box over empty time with no category picked: they probably meant to add a block.
    if (!inside.length && !m.add && (s1 > s0 || c1 > c0)) this.flashHint("Pick a category first to add a block");
  }

  dragGroupTo(di, slot) {
    const g = this.groupDrag, ddi = di - g.downDi, ds = slot - g.downSlot;
    const fits = g.items.every((it) => it.di + ddi >= 0 && it.di + ddi < this.data.days.length &&
                                      it.s + ds >= 0 && it.e + ds <= SLOTS);
    if (!fits) return;                                     // keep the last place where they all fit
    g.ddi = ddi; g.ds = ds; g.moved = ddi !== 0 || ds !== 0;
    this.highlight();
  }

  // Ops that lift every item out first and then put each down in its new place, so blocks in the
  // group never trim each other on the way. Outlook events become the user's own blocks first.
  placeOps(items, where) {
    const ops = [];
    for (const it of items) if (it.outlook) ops.push({ kind: "detach_outlook", uid: it.en.id });
    const idOf = (it) => (it.outlook ? `ol:${it.en.id}` : it.en.id);
    for (const it of items) ops.push({ kind: "delete", id: idOf(it) });
    for (const it of items) {
      const w = where(it);
      ops.push({ kind: "paint", date: this.data.days[w.di], track: w.track, start: slotTime(w.s), end: slotTime(w.e),
                 newId: idOf(it), block: { label: it.en.label, categoryId: it.en.categoryId, details: it.en.details || null } });
    }
    return ops;
  }

  endGroupDrag() {
    const g = this.groupDrag;
    this.groupDrag = null;
    this.highlight();
    this.root.querySelector("table").style.cursor = "";
    if (!g.moved) { this.setPicked([this.idOf(g.hit)]); return; }   // a click: just that one (click again for details)
    const ops = this.placeOps(g.items, (it) => ({ di: it.di + g.ddi, track: it.track, s: it.s + g.ds, e: it.e + g.ds }));
    this.commit([{ opId: uid(), kind: "batch", label: `Moved ${g.items.length} blocks`, ops }]);
    this.setPicked(g.items.map((it) => (it.outlook ? `ol:${it.en.id}` : it.en.id)));
  }

  deletePicked() {
    const past = (this.blocks || []).filter((b) => b.past && this.picked.has(b.id) && b.kind !== "skipped");
    if (past.length) {                               // Delete on passed time: it didn't happen
      past.forEach((b) => this.skipPiece(b));
      this.setPicked([]);
      return;
    }
    const items = [...this.picked].map((id) => this.itemOf(id)).filter(Boolean);
    if (!items.length) return;
    const ops = items.map((it) => (it.outlook ? { kind: "hide_outlook", uid: it.en.id } : { kind: "delete", id: it.en.id }));
    const label = items.length === 1 ? `Deleted ${items[0].en.label}` : `Deleted ${items.length} blocks`;
    this.closePopover();
    this.commit([{ opId: uid(), kind: "batch", label, ops }]);
    this.setPicked([]);
  }

  // ---------- Copy and paste (Cmd/Ctrl+C, Cmd/Ctrl+V) ----------

  // Copy the block under the pointer (or the one whose card is open). True if something was copied.
  copyBlock() {
    let items = [...this.picked].map((id) => this.itemOf(id)).filter(Boolean);
    if (!items.length) {
      const h = this.hoverCell;
      const hit = (h && this.blockAt(h.di, h.track, h.slot)) || this.cardHit;
      if (!hit) return false;
      items = [this.itemOf(this.idOf(hit))].filter(Boolean);
      if (!items.length) return false;
    }
    // Keep their layout: days and times relative to the earliest one.
    const d0 = Math.min(...items.map((it) => it.di)), s0 = Math.min(...items.map((it) => it.s));
    this.clip = { items: items.map((it) => ({ label: it.en.label, categoryId: it.en.categoryId, details: it.en.details || null,
                                             len: it.e - it.s, ddi: it.di - d0, ds: it.s - s0, track: it.track })) };
    remember("tt-clip", this.clip);
    const what = items.length === 1 ? items[0].en.label : `${items.length} blocks`;
    this.flashHint(`Copied ${what}: point at where it should go and press ${MOD}V`, false);
    return true;
  }

  // Paste the copied block where the pointer is (same length). True if it was pasted.
  pasteBlock() {
    if (!this.clip) this.clip = recall("tt-clip");                // copied earlier (e.g. on another week)
    if (this.clip && !this.clip.items) this.clip = { items: [{ ...this.clip, ddi: 0, ds: 0, track: null }] };
    if (!this.clip || !this.clip.items.length) return false;       // nothing copied: leave the key alone
    const h = this.hoverCell;
    if (!h) { this.flashHint("Point at a time in the timetable, then paste"); return true; }
    const one = this.clip.items.length === 1;
    const ops = [], ids = [];
    let skipped = 0;
    for (const it of this.clip.items) {
      const di = h.di + it.ddi;
      const s = one ? Math.max(0, Math.min(SLOTS - it.len, h.slot)) : h.slot + it.ds;
      if (di >= this.data.days.length || s + it.len > SLOTS) { skipped++; continue; }   // off the end of the week / day
      const id = uid();
      ids.push(id);
      ops.push({ opId: uid(), kind: "paint", date: this.data.days[di], track: one || !it.track ? h.track : it.track,
                 start: slotTime(s), end: slotTime(s + it.len), newId: id,
                 block: { label: it.label, categoryId: it.categoryId, details: it.details } });
    }
    if (!ops.length) { this.flashHint("Not enough room there: point further up or earlier in the week"); return true; }
    // Undoable with Cmd/Ctrl+Z, quietly (no Undo bar for a paste).
    this.commit(ops.length === 1 ? [{ ...ops[0], quiet: true, label: `Pasted ${ops[0].block.label}` }]
                                 : [{ opId: uid(), kind: "batch", quiet: true, label: `Pasted ${ops.length} blocks`, ops }]);
    if (!one) this.setPicked(ids);
    if (skipped) this.flashHint(`${skipped} didn't fit (past the end of the week or day) and weren't pasted`);
    return true;
  }

  // ---------- Moving and resizing blocks ----------

  spanOf(hit) {
    if (hit.past) return { s0: hit.piece.s, e0: hit.piece.e };
    const item = hit.outlook ? hit.ev : hit.entry;
    return { s0: Math.max(0, slotOf(item.start)), e0: Math.min(SLOTS, slotOf(item.end)) };
  }

  // Which part of a block the pointer is on: its top edge, its bottom edge, or the middle.
  zoneAt(di, track, s0, e0, y) {
    const top = this.cells[di][track][s0].getBoundingClientRect().top;
    const bottom = this.cells[di][track][e0 - 1].getBoundingClientRect().bottom;
    const edge = Math.min(8, (bottom - top) / 4);
    return y - top <= edge ? "start" : bottom - y <= edge ? "end" : "move";
  }

  // Hovering a block selects it (and moving off deselects it), so Delete, dragging and a
  // click for details act on it straight away. A selection of several (Shift / a box) stays put.
  hoverBlock(id) {
    if (this.hovered === id) return;
    this.hovered = id;
    this.blocksEl.querySelectorAll(".blk.hover").forEach((b) => b.classList.remove("hover"));
    if (id) this.blocksEl.querySelector(`[data-id="${CSS.escape(id)}"]`)?.classList.add("hover");
    if (!this.data.readonly && this.picked.size <= 1 && !this.drag && !this.blockDrag && !this.marquee && !this.groupDrag) {
      this.setPicked(id ? [id] : []);
    }
  }

  dragBlockTo(di, track, slot) {
    const bd = this.blockDrag, len = bd.e0 - bd.s0;
    if (bd.past) {                                   // a passed piece: same day, and only within time that has passed
      const gone = this.dayState[this.data.days[bd.di]].gone;
      slot = Math.min(slot, gone - 1);
      if (bd.zone === "move") { const s = Math.max(0, Math.min(gone - len, bd.s0 + slot - bd.downSlot)); bd.target = { di: bd.di, track, s, e: s + len }; }
      else if (bd.zone === "start") bd.target = { di: bd.di, track, s: Math.min(slot, bd.e0 - 1), e: bd.e0 };
      else bd.target = { di: bd.di, track, s: bd.s0, e: Math.max(slot + 1, bd.s0 + 1) };
      const t = bd.target;
      bd.moved = t.s !== bd.s0 || t.e !== bd.e0;
      this.highlight();
      return;
    }
    if (bd.zone === "move") {
      const s = Math.max(0, Math.min(SLOTS - len, bd.s0 + slot - bd.downSlot));
      bd.target = { di, track, s, e: s + len };
    } else if (bd.zone === "start") {
      bd.target = { di: bd.di, track: bd.track, s: Math.min(slot, bd.e0 - 1), e: bd.e0 };
    } else {
      bd.target = { di: bd.di, track: bd.track, s: bd.s0, e: Math.max(slot + 1, bd.s0 + 1) };
    }
    const t = bd.target;
    bd.moved = t.di !== bd.di || t.track !== bd.track || t.s !== bd.s0 || t.e !== bd.e0;
    this.highlight();
  }

  endBlockDrag() {
    const bd = this.blockDrag;
    this.blockDrag = null;
    this.highlight();
    this.root.querySelector("table").style.cursor = "";
    if (!bd.moved) {                                 // a second click: its details (a first one just selected it)
      this.setPicked([this.idOf(bd.hit)]);
      if (!bd.fresh) this.openCard(bd.hit);
      return;
    }
    if (bd.past) {                                   // "change times" by dragging a passed piece
      this.retimePiece(bd.hit.piece, bd.target.s, bd.target.e);
      return;
    }
    const t = bd.target;
    const where = { date: this.data.days[t.di], track: t.track, start: slotTime(t.s), end: slotTime(t.e) };
    const ops = bd.hit.outlook
      // An Outlook event becomes the user's own block first (as when it's edited), then moves.
      ? [{ opId: uid(), kind: "detach_outlook", uid: bd.hit.ev.id },
         { opId: uid(), kind: "move", id: `ol:${bd.hit.ev.id}`, ...where }]
      : [{ opId: uid(), kind: "move", id: bd.hit.entry.id, ...where }];
    this.commit(ops);
  }

  endDrag() {
    if (this.blockDrag) { this.endBlockDrag(); return; }
    if (this.marquee) { this.endMarquee(); return; }
    if (this.groupDrag) { this.endGroupDrag(); return; }
    const drag = this.drag;
    this.cancelDrag();
    if (!drag) return;
    if (drag.past) {                                 // empty passed time: something that wasn't planned
      const cat = this.cats.get(this.brush);
      if (!cat) { this.flashHint("Pick a category first"); return; }
      const s = Math.min(drag.a, drag.b), e = Math.max(drag.a, drag.b) + 1;
      this.commit([{ opId: uid(), kind: "replace", date: this.data.days[drag.di], start: slotTime(s), end: slotTime(e),
                     block: { label: cat.name, categoryId: cat.id }, newId: uid() }]);
      return;
    }
    // A click (no drag) on a block opens its details card; dragging paints.
    if (drag.a === drag.b) {
      const hit = this.blockAt(drag.di, drag.track, drag.a);
      if (hit) {
        this.openCard(hit);
        return;
      }
    }
    const cat = this.cats.get(this.brush);
    if (!cat) {
      this.flashHint("Pick a category first");
      return;
    }
    const label = cat.name;                     // renamed in its details (click it twice)
    this.paintRange(drag.di, drag.track, drag.a, drag.b, { label, categoryId: cat.id });
  }

  toggleHelp(open) {
    const help = this.root.querySelector(".tt-help"), btn = this.root.querySelector(".tt-help-btn");
    if (!help) return;
    open = open ?? help.hidden;
    help.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  }

  flashHint() {}                      // the timetable doesn't show messages (they pushed the grid about)


  // ---------- Right-click editor ----------

  openPopover(entry, x, y) {
    this.closePopover();
    const options = this.data.categories
      .map((c) => `<option value="${esc(c.id)}" ${c.id === entry.categoryId ? "selected" : ""}>${esc(c.name)}</option>`)
      .join("");
    const day = new Date(entry.date + "T00:00").toLocaleDateString(LOC(), { weekday: "short", day: "numeric", month: "short" });
    const pop = document.createElement("div");
    pop.className = "tt-pop";
    pop.innerHTML = `
      <div><b>${day} · ${esc(fmtRange(entry.start, entry.end))}</b> · ${entry.track === "plan" ? "Plan" : "Actual"}</div>
      <input class="p-label" list="tt-labels" value="${esc(entry.label)}">
      <select class="p-cat">${options}</select>
      <textarea class="p-details" rows="2" placeholder="Description (optional)">${esc(entry.details || "")}</textarea>
      <div class="row">
        <button class="del">Delete</button>
        <button class="cancel">Cancel</button>
        <button class="save"><b>Save</b></button>
      </div>`;
    pop.style.left = Math.min(x, window.innerWidth - 260) + "px";
    pop.style.top = Math.min(y, window.innerHeight - 160) + "px";
    this.root.appendChild(pop);
    this.popover = pop;

    const labelEl = pop.querySelector(".p-label");
    const catEl = pop.querySelector(".p-cat");
    labelEl.focus();
    labelEl.select();
    labelEl.addEventListener("input", () => {
      const id = this.mapLabel(labelEl.value);
      if (id && this.cats.has(id)) catEl.value = id;
    });

    const save = () => {
      const label = labelEl.value.trim() || this.cats.get(catEl.value).name;
      const details = pop.querySelector(".p-details").value.trim() || null;
      this.commit([{ opId: uid(), kind: "upsert", entry: { ...entry, label, categoryId: catEl.value, details } }]);
      this.closePopover();
    };
    labelEl.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    pop.querySelector(".save").addEventListener("click", save);
    pop.querySelector(".cancel").addEventListener("click", () => this.closePopover());
    pop.querySelector(".del").addEventListener("click", () => {
      this.commit([{ opId: uid(), kind: "delete", id: entry.id }]);
      this.closePopover();
    });
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
  }

  // Which block (own or Outlook) covers a slot. Outlook events are drawn on top.
  blockAt(di, track, slot) {
    if (this.isPast(di, slot)) {
      const piece = this.pieceAt[di][slot];
      return piece ? { past: true, piece, outlook: false, entry: piece.en } : null;
    }
    const ev = track === "plan" && this.outlookAt[di][slot];
    if (ev) return { outlook: true, ev };
    const id = this.occupant[di][track][slot];
    return id ? { outlook: false, entry: this.entries.get(id) } : null;
  }

  // Click on a block: it grows slightly and a card shows what it is and when,
  // like Outlook's peek. Edit / Delete (Remove for Outlook events) unless view only.
  openCard(hit) {
    if (hit.past) { this.openPastCard(hit); return; }
    this.closePopover();
    this.cardHit = hit;
    const item = hit.outlook ? hit.ev : hit.entry;
    const blockId = hit.outlook ? `outlook:${item.id}` : item.id;
    const cat = this.cats.get(item.categoryId);
    const day = new Date(item.date + "T00:00").toLocaleDateString(LOC(), { weekday: "long", day: "numeric", month: "long" });
    const when = hit.outlook ? item.exact : fmtRange(item.start, item.end);
    const text = hit.outlook ? item.description : item.details;
    const title = hit.outlook ? item.title : item.label;

    const card = document.createElement("div");
    card.className = "tt-pop tt-peek";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", `${hit.outlook ? item.title : item.label}, details`);
    card.innerHTML = `
      <div class="pk-title">${hit.outlook ? CAL_ICON : ""}<b>${esc(title)}</b></div>
      <div class="pk-when">${esc(day)} · ${esc(when)}</div>
      <div class="pk-meta"><i style="background:${esc(cat ? cat.colour : "#9e9e9e")}"></i>${esc(cat ? cat.name : "No category")}
        · ${hit.outlook || item.track === "plan" ? "Plan" : "Actual"}${hit.outlook ? " · from Outlook" : ""}</div>
      ${hit.outlook && item.location ? `<div class="pk-loc">${PIN_ICON}${esc(item.location)}</div>` : ""}
      ${text ? `<div class="pk-text">${esc(text).replace(/\n/g, "<br>")}</div>` : ""}
      ${this.data.readonly ? "" : `
      <div class="row">
        <button class="del">${hit.outlook ? "Remove" : "Delete"}</button>
        <button class="edit">Edit</button>
      </div>`}`;
    this.root.appendChild(card);
    this.popover = card;

    // Grow the block a little and put the card beside it.
    this.focusId = blockId;
    const blockEl = this.blocksEl.querySelector(`[data-id="${CSS.escape(blockId)}"]`);
    if (blockEl) blockEl.classList.add("focus");
    const r = blockEl ? blockEl.getBoundingClientRect() : { left: 200, right: 200, top: 200 };
    const w = 280;
    const left = r.right + 10 + w < window.innerWidth ? r.right + 10 : Math.max(8, r.left - 10 - w);
    card.style.left = `${left}px`;
    card.style.top = `${Math.max(8, Math.min(r.top, window.innerHeight - card.offsetHeight - 8))}px`;
    card.addEventListener("mousedown", (e) => e.stopPropagation());

    if (this.data.readonly) return;
    card.querySelector(".del").addEventListener("click", () => {
      this.commit([hit.outlook ? { opId: uid(), kind: "hide_outlook", uid: item.id }
                               : { opId: uid(), kind: "delete", id: item.id }]);
      this.closePopover();
    });
    card.querySelector(".edit").addEventListener("click", () => {
      let entry = item;
      if (hit.outlook) {   // editing an Outlook event makes it the user's own block
        this.commit([{ opId: uid(), kind: "detach_outlook", uid: item.id }]);
        entry = this.entries.get(`ol:${item.id}`);
      }
      const box = card.getBoundingClientRect();
      this.openPopover(entry, box.left, box.top);
    });
  }

  // ---------- One timeline: correcting time that has passed ----------

  pieceBlock(p) { return { label: p.en.label, categoryId: p.en.categoryId, details: p.en.details || null }; }

  // Didn't happen: nothing in the Actual for those slots (the Plan stays as it was).
  skipPiece(p) {
    this.commit([{ opId: uid(), kind: "skip", date: this.data.days[p.di], start: slotTime(p.s), end: slotTime(p.e) }]);
  }

  // It did happen after all (a skipped piece), or something else happened instead.
  replacePiece(p, block) {
    this.commit([{ opId: uid(), kind: "replace", date: this.data.days[p.di], start: slotTime(p.s), end: slotTime(p.e),
                   block, newId: uid() }]);
  }

  retimePiece(p, s, e) {
    this.commit([{ opId: uid(), kind: "retime", date: this.data.days[p.di], fromStart: slotTime(p.s), fromEnd: slotTime(p.e),
                   start: slotTime(s), end: slotTime(e), block: this.pieceBlock(p), newId: uid() }]);
  }

  // The details card of a passed piece, with the three corrections (or "It did happen" for a skipped one).
  openPastCard(hit) {
    this.closePopover();
    this.cardHit = hit;
    const p = hit.piece, en = p.en, date = this.data.days[p.di];
    const cat = this.cats.get(en.categoryId);
    const day = new Date(date + "T00:00").toLocaleDateString(LOC(), { weekday: "long", day: "numeric", month: "long" });
    const gone = this.dayState[date].gone;
    const card = document.createElement("div");
    card.className = "tt-pop tt-peek";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", `${en.label}, ${PIECE_WORDS[p.kind].toLowerCase()}`);
    const times = (sel, from, to) => Array.from({ length: to - from + 1 }, (_, k) => from + k)
      .map((i) => `<option value="${i}" ${i === sel ? "selected" : ""}>${esc(fmtTime(slotTime(i)))}</option>`).join("");
    const options = this.data.categories
      .map((c) => `<option value="${esc(c.id)}" ${c.id === en.categoryId ? "selected" : ""}>${esc(c.name)}</option>`).join("");
    card.innerHTML = `
      <div class="pk-title"><b>${esc(en.label)}</b></div>
      <div class="pk-when">${esc(day)} · ${esc(fmtRange(slotTime(p.s), slotTime(p.e)))}</div>
      <div class="pk-meta"><i style="background:${esc(cat ? cat.colour : "#9e9e9e")}"></i>${esc(cat ? cat.name : "No category")} · ${PIECE_WORDS[p.kind]}</div>
      ${this.data.readonly ? "" : p.kind === "skipped" ? `
      <div class="row"><button class="undo-skip">It did happen</button></div>` : `
      <div class="row fix">
        <button class="skip">Didn't happen</button>
        <button class="times" aria-expanded="false">Change times</button>
        <button class="other" aria-expanded="false">Did something else</button>
      </div>
      <div class="pk-form f-times" hidden>
        <label>From <select class="t-s" aria-label="Started at">${times(p.s, 0, gone - 1)}</select></label>
        <label>to <select class="t-e" aria-label="Ended at">${times(p.e, 1, gone)}</select></label>
        <button class="save">Save</button>
      </div>
      <div class="pk-form f-other" hidden>
        <input class="p-label" list="tt-labels" aria-label="What you did instead" placeholder="What you did instead">
        <select class="p-cat" aria-label="Category">${options}</select>
        <button class="save">Save</button>
      </div>`}`;
    this.root.appendChild(card);
    this.popover = card;
    this.focusId = p.id;
    const blockEl = this.blocksEl.querySelector(`[data-id="${CSS.escape(p.id)}"]`);
    if (blockEl) blockEl.classList.add("focus");
    const r = blockEl ? blockEl.getBoundingClientRect() : { left: 200, right: 200, top: 200 };
    const w = 300;
    card.style.left = `${r.right + 10 + w < window.innerWidth ? r.right + 10 : Math.max(8, r.left - 10 - w)}px`;
    card.style.top = `${Math.max(8, Math.min(r.top, window.innerHeight - card.offsetHeight - 8))}px`;
    card.addEventListener("mousedown", (e) => e.stopPropagation());
    if (this.data.readonly) return;
    const on = (sel, fn) => { const el = card.querySelector(sel); if (el) el.addEventListener("click", fn); };
    on(".undo-skip", () => { this.replacePiece(p, this.pieceBlock(p)); this.closePopover(); });
    if (p.kind === "skipped") return;                // (its card has just "It did happen")
    on(".skip", () => { this.skipPiece(p); this.closePopover(); });
    const show = (which) => {
      for (const [btn, form] of [[".times", ".f-times"], [".other", ".f-other"]]) {
        const open = form === which;
        card.querySelector(form).hidden = !open;
        card.querySelector(btn).setAttribute("aria-expanded", String(open));
      }
      const first = card.querySelector(`${which} select, ${which} input`);
      if (first) first.focus();
    };
    on(".times", () => show(".f-times"));
    on(".other", () => show(".f-other"));
    on(".f-times .save", () => {
      const a = +card.querySelector(".t-s").value, b = +card.querySelector(".t-e").value;
      if (b <= a) { card.querySelector(".t-e").focus(); return; }
      this.retimePiece(p, a, b);
      this.closePopover();
    });
    const labelEl = card.querySelector(".p-label"), catEl = card.querySelector(".p-cat");
    labelEl.addEventListener("input", () => {
      const id = this.mapLabel(labelEl.value);
      if (id && this.cats.has(id)) catEl.value = id;
    });
    const saveOther = () => {
      const label = labelEl.value.trim() || this.cats.get(catEl.value).name;
      this.replacePiece(p, { label, categoryId: catEl.value, details: null });
      this.closePopover();
    };
    labelEl.addEventListener("keydown", (e) => { if (e.key === "Enter") saveOther(); });
    on(".f-other .save", saveOther);
  }

  closePopover() {
    if (this.popover) this.popover.remove();
    this.popover = null;
    this.cardHit = null;
    if (this.focusId) {
      this.focusId = null;
      this.blocksEl.querySelectorAll(".blk.focus").forEach((b) => b.classList.remove("focus"));
    }
  }
}

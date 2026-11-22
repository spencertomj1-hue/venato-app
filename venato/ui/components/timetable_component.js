// Weekly Timetable: 7 days side by side, one column a day, in 30-minute slots, like a calendar week view.
//
// Python passes { days, today, groups, categories, entries, labelMap, acked, mode, dayState, ... },
// with only that week's entries. Edits are applied locally straight away, then
// sent to Python as "ops": {opId, kind: "paint", date, track, start, end, block, newId}
// for drags, {opId, kind: "upsert", entry} / {opId, kind: "delete", id} for edits.
// Ops stay pending until Python lists their opId in `acked`, so a slow rerun
// never makes the grid flicker back to old data. An op Python couldn't save is acked
// with a reason in `rejected` ({opId: why}): it's dropped (the grid shows what was saved,
// so the block goes back) and the reason shows in a note over the grid.
// Swiping sideways on the grid sends a "nav" trigger (-1 / +1 week).
//
// Plan and Actual (switched with the Plan / Actual buttons, in the browser only: no rerun, remembered in
// sessionStorage; data.mode, when set, forces one, e.g. "actual" from Home's Review):
//   A day's Plan is locked when the day starts (dayState[date].locked; store.lock_day copied it into
//   the Actual). Actual mode shows a started day's Actual (editable: that's what you did) and a day
//   that hasn't started's Plan (editable: nothing has happened yet). Plan mode shows every day's Plan:
//   locked days view only, the rest editable. So each day's column shows one track: trackFor(di).
//   {kind: "confirm_day", date}     this Actual is what I did (counts in stats and goals)
//   {kind: "unconfirm_day", date}   undo that
// Suggested sittings (data.suggestions, worked out in Python by tools.goal_spots) are drawn dashed in
// free Plan time on days that haven't started; clicking one sends {kind: "add_suggestion", date, start, end, block, newId, ghost}.

let SLOTS = 36;                   // 30-minute slots in a day (07:00 -> 01:00 by default; from Python)
let FIRST_MIN = 7 * 60;           // the day's first minute
const SWIPE_THRESHOLD = 120;      // px of sideways scroll that flips a week
const RAIL = 4;                   // px: the Plan's strip down the left of a locked day's Actual column
const SWAP_MS = 380;              // ms: the Plan / Actual cross-fade
const SHOW_MISSED = true;         // also hatch Plan time where nothing was done (set false to drop it)
const HOME_MIN_ROW = 8;           // the smallest row Home's tile shrinks to (fitHome)
const PREVIEW_EASE = 0.35;        // share of the gap the resize preview closes each frame (it glides, lagging a few ms)

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
  const items = [
    ["Plan and Actual", "The <b>Plan</b> / <b>Actual</b> switch at the top shows what you planned or what you did. The Plan is drawn as a blueprint (pale, outlined, on graph paper); what you did is solid. Days that haven't started show their Plan either way. In Actual, where a day didn't go to plan, the Plan shows as a faint outline behind it."],
    ["Locked at the start of the day", "When a day starts its Plan is locked in (that's what Plan vs Actual compares against) and copied into its Actual. From then on, change the Actual: move, stretch, delete or add blocks as the day really goes."],
    ["Confirm", "<b>Confirm</b> under a day's name (or Home's end-of-day prompt) says that day's Actual is what you really did. Only confirmed days count in stats and goals; <b>Undo</b> takes it back."],
    ["Add a block", "Click an empty half hour, or drag down empty time (no category picked), and a box opens to name it, with the times filled in. Or pick a category from the key and drag: the block takes the category's name."],
    ["Put a category down", "Click it again, or press " + key("Esc") + ". With no category picked, dragging selects instead of adding."],
    ["Select", "Point at a block to select it (a thin red outline). Click it to see its details, edit it or delete it."],
    ["Move or resize", "Drag a block to move it to another time or day. Drag its top or bottom edge to make it start or end earlier or later."],
    ["Select several", "Drag from empty time with no category picked (or holding " + key("Shift") + ") to draw a box: every block it touches is selected. " + key("Shift") + " or " + key(MOD.replace("+", "")) + "-click adds or removes one. Drag any selected block to move them all."],
    ["Copy and paste", key(MOD + "C") + " copies the block you're pointing at (or the selected ones); point at a time and " + key(MOD + "V") + " pastes them there, layout kept, on any day or week."],
    ["Delete and undo", key("Delete") + " or " + key("Backspace") + " removes the block you're pointing at (or the selected ones); " + key(MOD + "Z") + " brings them back."],
    ["Right-click", "Right-click a block to edit it straight away. Its edit box also changes its day and times."],
    ["Done or not", "Click a block (or calendar event) and press <b>✓ Done</b>: it turns green. <b>✗ Not done</b> fades it. Press it again to clear it. Both are saved for analysis."],
    ["Add an event", "<b>Add event</b> (above) adds something at times you type, e.g. Boxing 18:00–19:30 on Thursday."],
    ["Calendars", "Calendar events show in the Plan. ↻ syncs now; the Outlook button shows or hides them. Edit one to change its times. Moving, editing or deleting one only changes Venato, never the calendar."],
    ["Fit time", "<b>Fit time</b> (above) finds free gaps for hours of something, e.g. 6 hours of revision, and shows you before adding them."],
    ["Categories", "<b>Adjust categories</b> (above) adds, renames and recolours categories, and sets which category an activity uses."],
  ];
  if (!single) items.push(["Change week", "‹ Today › at the top, or swipe sideways on a trackpad."]);
  const legend =
    `<div class="tt-help-key" aria-label="Key">` +
    `<span><i class="k-did"></i>What you did</span>` +
    `<span><i class="k-rail"></i>What you planned (the strip on the left: bright where the day went differently)</span>` +
    `<span><i class="k-miss"></i>Planned but skipped (nothing done then)</span>` +
    `<span><i class="k-plan"></i>Plan (blueprint: days that haven't started, and the Plan view)</span></div>`;
  return `<div class="tt-help-h">How the timetable works</div>${legend}<dl>` +
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

// <option>s for slots first..last ("09:30"), with `chosen` selected: the edit box's start / end.
function timeOptions(first, last, chosen) {
  let out = "";
  for (let i = first; i <= last; i++) {
    out += `<option value="${i}" ${i === chosen ? "selected" : ""}>${fmtTime(slotTime(i))}</option>`;
  }
  return out;
}

// Grid column of a day (for box selection across days): one column a day.
const col = (di) => di;

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

const TODO_ICON = '<svg class="cal-ic" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/></svg>';

const LOCK_ICON = '<svg class="cal-ic" viewBox="0 0 24 24"><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/></svg>';

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
    this.status = {};           // block id or "outlook:<uid>" -> "done" | "missed" (server data + pending ops)
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
    if (data.mode) { this.mode = data.mode; if (!data.readonly) remember("tt-mode", data.mode); }   // (Home: always Actual)
    else if (!this.mode) this.mode = recall("tt-mode") === "plan" ? "plan" : "actual";
    // Per day: {gone: slots passed, locked: started (Plan frozen), confirmed}. Replayed ops update it.
    this.dayState = Object.fromEntries(data.days.map((d) => [d, { gone: 0, locked: false, confirmed: false, ...((data.dayState || {})[d] || {}) }]));

    // Server entries, then re-apply anything Python hasn't saved yet.
    const acked = new Set(data.acked);
    const rejected = data.rejected || {};
    const refused = this.pending.filter((op) => rejected[op.opId]);   // not saved: drop it and say why
    this.pending = this.pending.filter((op) => !acked.has(op.opId) && !rejected[op.opId]);
    this.entries = new Map(data.entries.map((e) => [e.id, { ...e }]));
    this.status = { ...(data.status || {}) };
    this.outlook = (data.outlook || []).slice();   // Python already leaves out removed ones
    this.hidden = new Set();                       // removed / detached here, not yet saved
    this.suggestions = (data.suggestions || []).slice();
    this.ghostsTaken = new Set();                  // suggestions added here, not yet saved
    this.todos = (data.todos || []).map((t) => ({ ...t, link: t.link && { ...t.link } }));
    this.pending.forEach((op) => this.applyLocal(op));

    const key = JSON.stringify([data.categories, data.days, data.today, !!data.readonly]);
    if (key !== this.builtFor) {
      this.build();
      this.builtFor = key;
    }
    this.refreshDatalist();
    this.showOutlookStatus();
    if (refused.length) this.showError(rejected[refused[refused.length - 1].opId]);
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
    if (op.kind === "confirm_day" || op.kind === "unconfirm_day") {
      if (this.dayState[op.date]) this.dayState[op.date].confirmed = op.kind === "confirm_day";
      return;
    }
    if (op.kind === "todo_done") {
      const t = this.todos.find((x) => x.id === op.todoId);
      if (t) this.markTodo(t, !!op.done);
      return;
    }
    if (op.kind === "schedule_todo") {              // like store.schedule_todo
      const t = this.todos.find((x) => x.id === op.todoId);
      if (!t) return;
      const track = (this.dayState[op.date] || {}).locked ? "actual" : "plan";
      const s = slotOf(op.start), e = Math.min(s + Math.max(1, Math.ceil((t.minutes || 30) / 30)), SLOTS);
      this.planPaint({ date: op.date, track, start: slotTime(s), end: slotTime(e), newId: op.newId,
                       block: { label: t.title, categoryId: this.mapLabel(t.title), details: null } })
        .forEach((o) => this.applyLocal(o));
      t.link = { date: op.date, start: slotTime(s), end: slotTime(e) };
      t.date = op.date;
      if (t.done) this.markTodo(t, true);
      return;
    }
    if (op.kind === "add_suggestion") {
      this.ghostsTaken.add(op.ghost);
      const di = this.dayIndex.get(op.date);
      const track = di === undefined || !(this.dayState[op.date] || {}).locked ? "plan" : "actual";   // like store.live_track
      this.planPaint({ date: op.date, track, start: op.start, end: op.end, block: op.block, newId: op.newId })
        .forEach((o) => this.applyLocal(o));
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
      const todo = this.todoAt(en.date, en.start);  // its to-do goes with it
      this.entries.delete(op.id);
      this.applyLocal({ kind: "paint", date: op.date, track: op.track, start: op.start, end: op.end, newId: op.id,
                        block: { label: en.label, categoryId: en.categoryId, details: en.details } });
      if (todo) { todo.link = { date: op.date, start: op.start, end: op.end }; todo.date = op.date; }
    } else if (op.kind === "upsert") this.entries.set(op.entry.id, { ...op.entry });
    else if (op.kind === "set_status") {
      const en = this.entries.get(op.id);
      const todo = en && this.todoAt(en.date, en.start);
      if (todo) this.markTodo(todo, op.status === "done");      // done ticks its to-do; anything else unticks it
      if (op.status) this.status[op.id] = op.status;
      else delete this.status[op.id];
    }
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

  // ---------- To-dos: chips in the day header; a scheduled one's block is the one at its date and start ----------

  todoAt(date, start) {
    return (this.todos || []).find((t) => t.link && t.link.date === date && t.link.start === start);
  }

  // Like store.set_todo_done: the to-do, and its block (the Plan one and its Actual copy).
  markTodo(t, done) {
    t.done = done;
    if (!t.link) return;
    for (const en of this.entries.values()) {
      if (en.date !== t.link.date || en.start !== t.link.start) continue;
      if (done) this.status[en.id] = "done";
      else delete this.status[en.id];
    }
  }

  visibleOutlook() {
    return this.outlook.filter((ev) => !this.hidden.has(ev.id));
  }

  // Which track a day's column shows: the Plan in Plan mode and before the day starts; else its Actual.
  trackFor(di) {
    const st = this.dayState[this.data.days[di]];
    return this.mode === "plan" || !st || !st.locked ? "plan" : "actual";
  }

  // View only: Home, or a locked day's Plan (it's what you meant to do; change the Actual instead).
  frozen(di) {
    if (this.data.readonly) return true;
    const st = this.dayState[this.data.days[di]];
    return this.trackFor(di) === "plan" && !!st && !!st.locked;
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.closePopover();
    this.setPicked([]);
    remember("tt-mode", mode);
    // Cross-fade: the old view, copied on top, fades out over the new one. On locked days it's a
    // revolving door: the Plan grows out of its rail (Actual -> Plan) as the Actual is pushed out the
    // right edge, or shrinks back into it (Plan -> Actual) as the Actual sweeps back in from the right.
    const toPlan = mode === "plan";
    const railDays = toPlan ? new Set(this.railDays || []) : null;
    this.wrapEl.querySelectorAll(".tt-leaving").forEach((el) => el.remove());
    const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const old = reduce ? null : this.blocksEl.cloneNode(true);
    // The 30-minute tiles and the Plan tint fade over the same SWAP_MS (CSS: .swapping), not jump.
    if (!reduce) {
      this.root.classList.add("swapping");
      clearTimeout(this.swapTimer);
      this.swapTimer = setTimeout(() => this.root.classList.remove("swapping"), SWAP_MS + 20);
    }
    this.paint();
    if (!old) return;
    old.classList.add("tt-leaving");
    this.blocksEl.after(old);
    const days = toPlan ? railDays : this.railDays || new Set();
    const rail = `inset(0 calc(100% - ${RAIL}px) 0 0 round 2px)`, full = "inset(0 0 0 0 round 0px)";
    const gone = "inset(0 0 0 100% round 0px)";                       // squeezed out at the right edge
    const opts = { duration: SWAP_MS, easing: "cubic-bezier(.4,0,.2,1)" };
    for (const el of (toPlan ? this.blocksEl : old).querySelectorAll(".blk.plan[data-di]")) {
      if (!days.has(+el.dataset.di)) continue;
      el.animate({ clipPath: toPlan ? [rail, full] : [full, rail] }, opts);
    }
    for (const el of (toPlan ? old : this.blocksEl).querySelectorAll(".blk.act[data-di]")) {
      if (!days.has(+el.dataset.di)) continue;
      el.animate({ clipPath: toPlan ? [full, gone] : [gone, full] }, opts);
    }
    // Blocks fade in as the old ones fade out, so both views cross-fade the same way.
    this.blocksEl.animate({ opacity: [0, 1] }, { ...opts, easing: toPlan ? "ease-in" : "ease-out" });
    old.animate({ opacity: [1, 0] }, { ...opts, easing: toPlan ? "ease-out" : "ease-in" })
      .finished.then(() => old.remove(), () => old.remove());
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

    // One header row: weekday, dd/mm, the day's state (locked / Confirm), all-day chips.
    const dayHead = days
      .map((d, di) => {
        const dt = new Date(d + "T00:00");
        const name = dt.toLocaleDateString(LOC(), { weekday: "long" });
        return `<th class="day ${d === today ? "today" : ""}"><div class="dn">${name}</div><div class="dd">${dayNum(d)}</div>` +
          `<div class="dstate" data-d="${di}"></div><div class="chips" data-d="${di}"></div></th>`;
      })
      .join("");

    // A single column of cells per day; data-t is the track it shows (set in paint, by trackFor).
    const rows = [];
    for (let s = 0; s < SLOTS; s++) {
      const cells = days
        .map((d, di) => `<td class="s first ${d === today ? "today" : ""}" data-d="${di}" data-t="plan" data-s="${s}"></td>`)
        .join("");
      // Label each hour on its grid line, like a calendar.
      const time = s % 2 === 0 ? `<span>${fmtTime(slotTime(s))}</span>` : "";
      rows.push(`<tr class="${s % 2 ? "half" : "hour"}"><td class="t">${time}</td>${cells}</tr>`);
    }

    const cols = days.map(() => "<col>").join("");

    this.root.classList.toggle("single", !!this.data.single);   // one day: no week navigation
    this.root.classList.toggle("readonly", !!this.data.readonly); // view only: no editing tools
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
        <div class="tt-mode" role="group" aria-label="Show">
          <button data-mode="plan" title="What you planned: each day's Plan, locked when the day started">Plan</button>
          <button data-mode="actual" title="What you did: started days' Actual (change it as the day goes), later days' Plan">Actual</button>
        </div>
        <div class="tt-outlook">
          <button class="tt-sync" title="Sync Outlook now"><span class="msr">sync</span></button>
          <span class="tt-synced"></span>
          <button class="tt-ol-toggle" title="Show or hide Outlook events" aria-label="Outlook">${CAL_ICON}${this.data.readonly ? "" : "Outlook"}</button>
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
              <tr><th class="h-time"></th>${dayHead}</tr>
            </thead>
            <tbody>${rows.join("")}</tbody>
          </table>
          <div class="tt-blocks" aria-hidden="true"></div>
          <div class="tt-lines" aria-hidden="true"></div>
        </div>
        <div class="tt-error" role="alert" hidden></div>
      </div>
      <div class="tt-a11y" role="region" aria-label="Timetable blocks (press Enter on one for details)"></div>`;

    // Blocks are positioned from the cells, so redo them when the size changes.
    this.blocksEl = this.root.querySelector(".tt-blocks");
    this.wrapEl = this.root.querySelector(".tt-wrap");
    if (this.resizeObserver) this.resizeObserver.disconnect();
    this.resizeObserver = new ResizeObserver(() => this.layoutBlocks());
    if (this.attached) this.resizeObserver.observe(this.wrapEl);

    // Index the slot cells: cells[day][track][slot]. Both tracks are the same column (it shows one at a time).
    this.cells = days.map(() => { const plan = []; return { plan, actual: plan }; });
    this.root.querySelectorAll("td.s").forEach((td) => {
      this.cells[+td.dataset.d].plan[+td.dataset.s] = td;
    });

    this.bindEvents();
    this.showBrush();
  }

  // A change Python couldn't save: it has already been taken back; say why for a few seconds.
  showError(text) {
    const el = this.root.querySelector(".tt-error");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(this.errorTimer);
    this.errorTimer = setTimeout(() => { el.hidden = true; }, 6000);
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

  // Work out which entry fills each slot of the track each day shows, then draw the blocks.
  paint() {
    const days = this.data.days;
    this.occupant = days.map(() => ({ plan: [], actual: [] }));
    this.outlookAt = days.map(() => []);
    this.blocks = [];
    this.railDays = new Set();
    this.rails = [];                              // Actual view of a locked day: its Plan as a thin strip down the left edge
    this.missed = [];                             // ...and Plan time with nothing done in it, hatched
    const evs = this.visibleOutlook();
    days.forEach((date, di) => {
      const track = this.trackFor(di), frozen = this.frozen(di);
      for (const td of this.cells[di].plan) {
        td.dataset.t = track;
        td.title = "";
        td.classList.remove("filled");
        td.classList.toggle("frozen", frozen && !this.data.readonly);
        td.classList.toggle("bp", track === "plan");          // blueprint: the Plan
      }
      for (const en of this.entriesFor(date, track)) {
        const s = Math.max(0, slotOf(en.start)), e = Math.min(slotOf(en.end), SLOTS);
        if (e <= s) continue;
        for (let i = s; i < e; i++) {
          const td = this.cells[di].plan[i];
          td.title = `${en.label} · ${fmtRange(en.start, en.end)}`;
          td.classList.add("filled");
          this.occupant[di][track][i] = en.id;
        }
        this.blocks.push({ en, di, s, e, frozen, plan: track === "plan" });
      }
      if (track !== "plan") { this.addPlanOutlines(date, di); return; }   // (events are copied into a locked day's Actual)
      for (const ev of evs.filter((x) => x.date === date)) {
        const s = Math.max(0, slotOf(ev.start)), e = Math.min(slotOf(ev.end), SLOTS);
        if (e <= s) continue;
        for (let i = s; i < e; i++) {
          const td = this.cells[di].plan[i];
          td.title = `${ev.title} · ${ev.exact} (calendar)`;
          td.classList.add("filled");
          this.outlookAt[di][i] = ev;
        }
        this.blocks.push({ en: { ...ev, label: ev.title, track: "plan" }, di, s, e, outlook: true, frozen, plan: true });
      }
    });

    // All-day events and deadlines: small chips in the day header.
    this.root.querySelectorAll("th.day .chips").forEach((box) => {
      const date = days[+box.dataset.d];
      box.innerHTML = (this.data.outlookAllDay || []).filter((c) => c.date === date)
        .map((c) => `<span class="chip${c.deadline ? " due" : ""}" title="${esc(c.title)} (${c.deadline ? "deadline" : "Outlook, all day"})">${esc(c.title)}</span>`).join("")
        + (this.data.readonly ? [] : this.todos.filter((t) => t.date === date && !t.link))     // to-dos not on the grid yet
          .map((t) => `<span class="chip todo${t.done ? " done" : ""}" draggable="${!t.done}" data-todo="${esc(t.id)}" ` +
            `title="${esc(t.title)} (to-do, ${t.minutes} min)${t.done ? "" : ": drag it onto the grid"}">` +
            `<button class="tick" tabindex="-1" data-todo-tick="${esc(t.id)}" aria-pressed="${t.done}" ` +
            `aria-label="${t.done ? "Untick" : "Tick off"} ${esc(t.title)}">${t.done ? "✓" : ""}</button>${esc(t.title)}</span>`).join("");
    });
    // Each day's state under its name. Actual: Confirm once it has started, then "Confirmed" (Undo).
    // Plan: "Locked" once it has started.
    this.root.querySelectorAll("th.day .dstate").forEach((box) => {
      const date = days[+box.dataset.d], st = this.dayState[date] || {};
      box.innerHTML = this.data.readonly ? (st.confirmed ? `<span class="ok">✓ Confirmed</span>` : "")
        : this.mode === "plan" ? (st.locked ? `<span class="lock" title="Locked when the day started: this is what you planned. Change the Actual instead.">${LOCK_ICON}Locked</span>` : "")
        : st.confirmed ? `<span class="ok">✓ Confirmed</span> <button class="unconfirm" tabindex="-1" data-unconfirm="${esc(date)}" title="Undo: not confirmed">Undo</button>`
        : st.locked ? `<button class="confirm" tabindex="-1" data-confirm="${esc(date)}" title="This is what I actually did: confirm the day">Confirm</button>`
        : `<span class="ptag" title="Hasn't started: this is still the Plan">Plan</span>`;
    });
    // Home: no all-day chip and no day state leaves the header row empty, so it goes (more room for the rows).
    if (this.data.readonly) {
      const bare = [...this.root.querySelectorAll("th.day .chips, th.day .dstate")].every((b) => !b.innerHTML.trim());
      if (bare !== this.root.classList.contains("bare-head")) {
        this.root.classList.toggle("bare-head", bare);
        if (this.attached) requestAnimationFrame(() => this.fitToWindow());
      }
    }
    this.root.querySelectorAll("[data-mode]").forEach((b) => {
      b.classList.toggle("on", b.dataset.mode === this.mode);
      b.setAttribute("aria-pressed", String(b.dataset.mode === this.mode));
    });
    this.root.classList.toggle("plan-mode", this.mode === "plan");
    this.root.querySelectorAll("th.day").forEach((th, di) => th.classList.toggle("bp", this.trackFor(di) === "plan"));
    this.addGhosts();
    this.layoutBlocks();
    this.renderBlockList();
  }

  // Actual view of a locked day: its Plan (blocks and calendar events) as a thin rail down the left edge of the
  // column, bright where the day went differently, faint where it matched. Plan time where nothing was done at
  // all is also hatched in the gap ("Skipped: Gym 18:00–19:00"), when SHOW_MISSED is on.
  addPlanOutlines(date, di) {
    const planAt = [], actAt = [];
    const fill = (arr, item, a, b) => { for (let i = Math.max(0, a); i < Math.min(b, SLOTS); i++) arr[i] = item; };
    for (const en of this.entriesFor(date, "plan")) fill(planAt, en, slotOf(en.start), slotOf(en.end));
    for (const ev of this.visibleOutlook().filter((x) => x.date === date))
      fill(planAt, { id: `ol:${ev.id}`, label: ev.title, categoryId: ev.categoryId }, slotOf(ev.start), slotOf(ev.end));
    for (const en of this.entriesFor(date, "actual")) fill(actAt, en, slotOf(en.start), slotOf(en.end));
    const differs = (i) => planAt[i] && !(actAt[i] && actAt[i].label === planAt[i].label && actAt[i].categoryId === planAt[i].categoryId);
    this.railDays.add(di);
    if (SHOW_MISSED) {
      let i = 0;
      while (i < SLOTS) {
        if (!planAt[i] || actAt[i]) { i++; continue; }
        let j = i;
        while (j < SLOTS && planAt[j] === planAt[i] && !actAt[j]) j++;
        this.missed.push({ en: planAt[i], di, s: i, e: j });
        i = j;
      }
    }
    let i = 0;
    while (i < SLOTS) {
      if (!planAt[i]) { i++; continue; }
      let j = i;
      const d = differs(i);
      while (j < SLOTS && planAt[j] === planAt[i] && differs(j) === d) j++;
      this.rails.push({ en: planAt[i], di, s: i, e: j, differs: d });
      i = j;
    }
  }

  // Suggested sittings: only on days you can change (not a locked Plan), where the column is still free.
  addGhosts() {
    this.ghostAt = this.data.days.map(() => []);
    if (this.data.readonly) return;
    for (const g of this.suggestions) {
      const di = this.dayIndex.get(g.date);
      if (di === undefined || this.ghostsTaken.has(g.id) || this.frozen(di)) continue;
      const track = this.trackFor(di);
      const s = slotOf(g.start), e = Math.min(slotOf(g.end), SLOTS);
      let free = e > s;
      for (let i = s; i < e && free; i++) {
        if (this.occupant[di][track][i] || this.outlookAt[di][i]) free = false;
      }
      if (!free) continue;
      for (let i = s; i < e; i++) this.ghostAt[di][i] = g;
      this.blocks.push({ en: { ...g, track }, di, s, e, ghost: true });
    }
  }

  // Add one suggested sitting to the Plan (Python checks the slots are still free).
  takeGhost(g) {
    this.commit([{ opId: uid(), kind: "add_suggestion", ghost: g.id, date: g.date, start: g.start, end: g.end,
                   block: { label: g.label, categoryId: g.categoryId, details: null }, newId: uid() }]);
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
        const head = b.outlook ? "Plan (calendar)" : b.en.track === "plan" ? (b.frozen ? "Plan (locked)" : "Plan") : "Actual";
        const when = b.outlook ? b.en.exact : `${fmtTime(b.en.start)} to ${fmtTime(b.en.end)}`;
        const what = `${head}: ${b.en.label}, ${when}${cat ? `, ${cat.name}` : ""}`;
        return `<button data-i="${i}">${esc(what)}</button>`;
      });
      const st = !this.data.readonly && this.mode === "actual" && this.dayState[d];
      if (st && st.locked && !st.confirmed) items.push(`<button data-confirm="${esc(d)}">Confirm ${esc(day)}: this is what I did</button>`);
      if (st && st.confirmed) items.push(`<button data-unconfirm="${esc(d)}">Unconfirm ${esc(day)}</button>`);
      return items.length ? `<div role="group" aria-label="${esc(day)}"><span class="a11y-day">${esc(day)}</span>${items.join("")}</div>` : "";
    }).join("");
    list.innerHTML = groups || `<button disabled>Nothing in the timetable this ${this.data.single ? "day" : "week"}</button>`;
  }

  // Shrink (or grow) the rows so the whole day fits in the window without scrolling (runs again on
  // every window resize): the Timetable page, 10px rows (still big enough to drag in) to 18px.
  // Home (view only) fits the whole day into its tile instead: fitHome.
  fitToWindow() {
    if (!this.wrapEl || !this.cells || !this.cells[0]) return;
    // On Home, while its widget is pinned or gliding to a new place (home_flip.js) the boxes measured here are
    // transformed: wait for it to land (it sends "venato:flip-settled").
    const SEL = '[class*="st-key-hw_"]';
    const card = this.root.closest(SEL) || this.root.getRootNode().host?.closest(SEL);
    if (card && (card.style.transform || card.getAnimations().some((a) => a.id === "flip"))) return;
    if (this.data.readonly) { this.fitHome(); return; }
    const [min, max] = [10, 18];
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


  // Home's tile: the whole day, no scrolling. The rows share the height the tile has room for (min 10px; a
  // tile too short even for that clips the end of the day rather than scroll). On a narrow window, where Home
  // scrolls and the tile is as tall as what's in it, the rows are a fixed 18px.
  fitHome() {
    const box = this.root.querySelector(".tt-card");
    const host = this.root.getRootNode().host || this.root;
    const tile = host.closest && host.closest('[class*="st-key-hwc_"]');
    const clip = tile && tile.parentElement && tile.parentElement.dataset.testid === "stLayoutWrapper" ? tile.parentElement : tile;
    box.style.height = "";
    box.scrollTop = 0;
    if (!(clip && matchMedia("(min-width: 1001px)").matches)) { this.root.style.setProperty("--row-h", "18px"); return; }
    const room = Math.floor(clip.getBoundingClientRect().bottom - box.getBoundingClientRect().top - 2);
    if (room < 40) return;
    const head = this.root.querySelector("thead")?.getBoundingClientRect().height || 0;
    let row = Math.max(HOME_MIN_ROW, Math.floor((room - head) / SLOTS));
    for (let i = 0; i < 3; i++) {        // a few times: borders make the first guess a little off
      this.root.style.setProperty("--row-h", `${row}px`);
      const over = this.wrapEl.getBoundingClientRect().height - room;
      if (over <= 0 || row === HOME_MIN_ROW) break;
      row = Math.max(HOME_MIN_ROW, row - Math.ceil(over / SLOTS));
    }
    box.style.height = `${room}px`;
  }

  // Home only: a thin red line across today at the current time, moving down as time passes.
  drawNow() {
    let line = this.wrapEl && this.wrapEl.querySelector(".tt-now");
    const di = this.data && this.data.nowMin != null ? this.dayIndex.get(this.data.today) : undefined;
    let m = di === undefined ? -1 : this.nowAt.min + (Date.now() - this.nowAt.ms) / 60000 - FIRST_MIN;
    if (m < 0 && di !== undefined) m += 24 * 60;          // after midnight, when the day runs past it
    const slot = m / 30;
    if (di === undefined || slot < 0 || slot >= SLOTS || !this.cells[di]) { if (line) line.remove(); return; }
    const origin = this.wrapEl.getBoundingClientRect();
    const cell = this.cells[di].plan[Math.floor(slot)].getBoundingClientRect();
    // Across the whole table: from the edge of the time labels (the dot sits there) to the last day's edge.
    const last = this.cells.length - 1;
    const tableLeft = this.cells[0].plan[0].getBoundingClientRect().left;
    const tableRight = (this.cells[last].actual[0] || this.cells[last].plan[0]).getBoundingClientRect().right;
    if (!line) {
      line = document.createElement("div");
      line.className = "tt-now";
      line.setAttribute("aria-hidden", "true");
      this.wrapEl.appendChild(line);
    }
    line.style.top = `${cell.top - origin.top + (slot - Math.floor(slot)) * cell.height}px`;
    line.style.left = `${tableLeft - origin.left}px`;
    line.style.width = `${tableRight - tableLeft}px`;
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
  boxStyle(first, last, origin, inset = 0) {
    const r = this.boxRect(first, last, origin, inset);
    return `left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;`;
  }

  boxRect(first, last, origin, inset = 0) {
    const css = getComputedStyle(this.root);
    const gap = parseFloat(css.getPropertyValue("--gap")) || 2.5;
    const dayGap = parseFloat(css.getPropertyValue("--day-gap")) || 7;
    const a = first.getBoundingClientRect(), b = last.getBoundingClientRect();
    const border = parseFloat(getComputedStyle(last).borderBottomWidth) || 0;
    const left = a.left - origin.left + (first.classList.contains("first") ? dayGap : gap) + inset;
    const top = a.top - origin.top + gap;
    const right = a.right - origin.left - gap;
    const bottom = b.bottom - origin.top - border - gap;
    return { left, top, width: right - left, height: bottom - top };
  }

  layoutBlocks() {
    this.drawNow();
    this.drawLines();
    if (!this.blocks) return;
    const origin = this.wrapEl.getBoundingClientRect();
    const fillOf = (en) => esc((this.cats.get(en.categoryId) || {}).colour || "#9e9e9e");
    const rails = (this.rails || []).map(({ en, di, s, e, differs }) => {
      const a = this.cells[di].plan[s], b = this.cells[di].plan[e - 1];
      const box = this.boxStyle(a, b, origin).replace(/width:[^;]+;/, `width:${RAIL}px;`);
      return `<div class="prail${differs ? " off" : ""}" style="${box}--fill:${fillOf(en)}" ` +
        `title="Planned: ${esc(en.label)} ${esc(fmtRange(slotTime(s), slotTime(e)))}"></div>`;
    }).join("");
    const missed = (this.missed || []).map(({ en, di, s, e }) => {
      const a = this.cells[di].plan[s], b = this.cells[di].plan[e - 1];
      const tall = b.getBoundingClientRect().bottom - a.getBoundingClientRect().top >= 30;
      const what = `Skipped: ${esc(en.label)} ${esc(fmtRange(slotTime(s), slotTime(e)))}`;
      return `<div class="pmiss" style="${this.boxStyle(a, b, origin, RAIL + 2)}--fill:${fillOf(en)}" title="${what}">` +
        `${tall ? `<span>${what}</span>` : ""}</div>`;
    }).join("");
    this.blocksEl.innerHTML = rails + missed + this.blocks
      .map(({ en, di, s, e, outlook, ghost, frozen, plan }) => {
        const inset = !plan && this.railDays.has(di) ? RAIL + 2 : 0;   // room for the Plan rail
        const firstTd = this.cells[di][en.track][s], lastTd = this.cells[di][en.track][e - 1];
        const first = firstTd.getBoundingClientRect(), last = lastTd.getBoundingClientRect();
        const cat = this.cats.get(en.categoryId);
        const bg = cat ? cat.colour : "#9e9e9e";
        const fg = (cat && cat.textColour) || contrastText(bg);
        // Room for the time line under the title. Home's small rows: the name from 2 rows, the time from 3;
        // shorter blocks are colour only (their name in the tooltip).
        const rows = e - s, home = this.data.readonly;
        const tall = last.bottom - first.top >= 30 && (!home || rows >= 3);
        const named = !home || rows >= 2;
        if (ghost) {          // a suggested sitting: dashed, "+ Study 2 h"
          const h = (e - s) / 2;
          return `<div data-di="${di}" class="blk ghost ${tall ? "tall" : ""}" data-id="${esc(en.id)}" style="${this.boxStyle(firstTd, lastTd, origin)}--fill:${esc(bg)}">` +
            `<b>+ ${esc(en.label)} ${h} h</b>${tall ? `<span>Suggested · click to add</span>` : ""}</div>`;
        }
        if (outlook) {
          return `<div data-di="${di}" class="blk outlook plan ${this.statusClass("outlook:" + en.id)} ${tall ? "tall" : ""} ${frozen ? "frozen" : ""} ${this.focusId === "outlook:" + en.id ? "focus" : ""}${this.hovered === "outlook:" + en.id ? " hover" : ""}${this.picked.has("outlook:" + en.id) ? " picked" : ""}" data-id="outlook:${esc(en.id)}"${named ? "" : ` title="${esc(en.title)} ${esc(en.exact)}"`} style="${this.boxStyle(firstTd, lastTd, origin)}` +
            `--fill:${esc(bg)}">` +
            `${named ? `<b>${this.statusMark("outlook:" + en.id)}${CAL_ICON}${esc(en.title)}</b>` : ""}${tall ? `<span>${esc(en.exact)}</span>` : ""}</div>`;
        }
        return `<div data-di="${di}" class="blk ${this.statusClass(en.id)} ${tall ? "tall" : ""} ${frozen ? "frozen" : ""} ${plan ? "plan" : "act"} ${this.focusId === en.id ? "focus" : ""}${this.hovered === en.id ? " hover" : ""}${this.picked.has(en.id) ? " picked" : ""}" data-id="${esc(en.id)}"${named ? "" : ` title="${esc(en.label)} ${esc(fmtRange(en.start, en.end))}"`} style="${this.boxStyle(firstTd, lastTd, origin, inset)}` +
          (plan ? `--fill:${esc(bg)}">` : `background:${esc(bg)};color:${fg}">`) +
          `${named ? `<b>${this.statusMark(en.id)}${this.todoAt(en.date, en.start) ? `<i class="tdo" title="To-do: marking it done ticks it off">${TODO_ICON}</i>` : ""}${esc(en.label)}</b>` : ""}${tall ? `<span>${esc(fmtRange(en.start, en.end))}</span>` : ""}</div>`;
      })
      .join("");
    this.syncResizePreview();              // keep the preview on its cells if the grid moved
  }

  // Done blocks are green with a tick; not done ones are faded and struck through.
  statusClass(id) {
    const st = this.status[id];
    return st === "done" ? "is-done" : st === "missed" ? "is-missed" : "";
  }

  statusMark(id) {
    const st = this.status[id];
    return st === "done" ? "✓ " : st === "missed" ? "✗ " : "";
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

  // Default category for a typed label, if any (mirrors store.match_category): an exact match (any case)
  // with an activity's default, then a category's name; then the longest of those found as whole words
  // inside the label ("Rugby training" -> Sports from "Rugby"). Activities beat category names.
  mapLabel(label) {
    const want = label.trim().toLowerCase();
    if (!want) return null;
    const defaults = Object.entries(this.data.labelMap)
      .filter(([, id]) => this.cats.has(id)).map(([l, id]) => [l.trim().toLowerCase(), id]);
    const names = this.data.categories.map((c) => [c.name.trim().toLowerCase(), c.id]);
    for (const pool of [defaults, names]) for (const [p, id] of pool) if (p === want) return id;
    const word = /[\p{L}\p{N}_]/u;
    for (const pool of [defaults, names]) {      // an activity inside the label beats a category name
      let best = null, bestLen = 0;
      for (const [p, id] of pool) {
        if (!p || p.length <= bestLen) continue;
        for (let i = want.indexOf(p); i >= 0; i = want.indexOf(p, i + 1)) {
          const before = want[i - 1], after = want[i + p.length];
          if ((!before || !word.test(before)) && (!after || !word.test(after))) { best = id; bestLen = p.length; break; }
        }
      }
      if (best) return best;
    }
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
    this.root.querySelectorAll("[data-mode]").forEach((el) =>
      el.addEventListener("click", () => this.setMode(el.dataset.mode)));
    this.root.querySelectorAll("[data-nav]").forEach((el) =>
      el.addEventListener("click", () => this.nav({ dir: +el.dataset.nav })));

    table.addEventListener("mousedown", (e) => {
      const td = e.target.closest("td.s");
      if (!td || e.button !== 0) return;
      e.preventDefault();
      // preventDefault keeps focus where it was: leave the label box, so Delete / Backspace act on blocks.
      const typing = this.root.getRootNode().activeElement || document.activeElement;
      if (isTextField(typing)) typing.blur();
      const di = +td.dataset.d, track = td.dataset.t, slot = +td.dataset.s;
      if (this.frozen(di)) {                        // Home, or a locked Plan: no editing, just the details card
        const hit = this.blockAt(di, track, slot);
        if (hit) { this.setPicked([this.idOf(hit)]); this.openCard(hit); } else { this.closePopover(); this.setPicked([]); }
        return;
      }
      this.closePopover();
      const hit = this.blockAt(di, track, slot);
      const hitId = hit && this.idOf(hit);
      const adding = e.shiftKey || (IS_MAC ? e.metaKey : e.ctrlKey);   // Shift or Cmd/Ctrl: add to the selection
      const ghost = !hit && !adding && this.ghostAt[di] && this.ghostAt[di][slot];
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
                           items: [...this.picked].map((id) => this.itemOf(id)).filter((it) => it && !this.frozen(it.di)) };
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
                         from: hit && !adding ? hitId : null, hadPicked: this.picked.size > 0 };
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
      this.hoverBlock(hit ? this.idOf(hit) : null);
      if (td && this.frozen(+td.dataset.d)) { table.style.cursor = hit ? "pointer" : "default"; return; }
      const adding = e.shiftKey || (IS_MAC ? e.metaKey : e.ctrlKey);
      if (!hit && td && this.ghostAt[+td.dataset.d][+td.dataset.s]) { table.style.cursor = "pointer"; return; }
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
      const tick = e.target.closest("[data-todo-tick]");       // a to-do chip's tick
      if (tick && !this.data.readonly) {
        const t = this.todos.find((x) => x.id === tick.dataset.todoTick);
        if (t) this.commit([{ opId: uid(), kind: "todo_done", todoId: t.id, date: t.date, done: !t.done }]);
        return;
      }
      const u = e.target.closest("[data-unconfirm]");
      if (u && !this.data.readonly) { this.commit([{ opId: uid(), kind: "unconfirm_day", date: u.dataset.unconfirm }]); return; }
      const c = e.target.closest("[data-confirm]");
      if (!c || this.data.readonly) return;
      this.commit([{ opId: uid(), kind: "confirm_day", date: c.dataset.confirm }]);
    });

    // A to-do chip dragged onto the grid: scheduled there (on the day's Plan, or its Actual once started).
    const cellUnder = (e) => {
      const at = this.root.getRootNode().elementsFromPoint ? this.root.getRootNode() : document;
      return at.elementsFromPoint(e.clientX, e.clientY).find((el) => el.matches && el.matches("td.s"));
    };
    const dropOn = (td) => {
      if (this.dropTd === td) return;
      if (this.dropTd) this.dropTd.classList.remove("todo-drop");
      this.dropTd = td;
      if (td) td.classList.add("todo-drop");
    };
    this.root.addEventListener("dragstart", (e) => {
      const chip = e.target.closest && e.target.closest("[data-todo]");
      if (!chip || this.data.readonly) return;
      this.dragTodo = chip.dataset.todo;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", chip.textContent);
    });
    this.root.addEventListener("dragover", (e) => {
      if (!this.dragTodo) return;
      const td = cellUnder(e);
      dropOn(td);
      if (td) e.preventDefault();
    });
    this.root.addEventListener("drop", (e) => {
      const td = this.dragTodo && cellUnder(e);
      if (td) {
        e.preventDefault();
        this.commit([{ opId: uid(), kind: "schedule_todo", todoId: this.dragTodo, date: this.data.days[+td.dataset.d],
                       start: slotTime(+td.dataset.s), newId: uid() }]);
      }
      this.dragTodo = null;
      dropOn(null);
    });
    this.root.addEventListener("dragend", () => { this.dragTodo = null; dropOn(null); });

    this.root.querySelector(".tt-a11y").addEventListener("click", (e) => {
      const b = e.target.closest("[data-i]");
      if (!b) return;
      const block = this.listed[+b.dataset.i];
      if (block.ghost) { this.takeGhost(block.en); return; }
      const hit = block.outlook ? { outlook: true, ev: { ...block.en, title: block.en.label }, di: block.di }
        : { outlook: false, entry: block.en, di: block.di };
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
      this.drag.b = +td.dataset.s;
      this.highlight();
    });

    table.addEventListener("contextmenu", (e) => {
      const td = e.target.closest("td.s");
      if (!td) return;
      const hit = this.blockAt(+td.dataset.d, td.dataset.t, +td.dataset.s);
      if (!hit) return;
      e.preventDefault();
      if (this.frozen(+td.dataset.d) || hit.outlook) this.openCard(hit);   // details first for calendar events
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
    window.addEventListener("venato:flip-settled", this.onWindowResize);   // Home: a widget glide has landed
    window.addEventListener("mousedown", this.onOutside);
    this.resizeObserver.observe(this.wrapEl);
    window.addEventListener("mouseup", this.onMouseUp);
    window.addEventListener("keydown", this.onKey);
    this.attached = true;
  }

  detach() {
    clearTimeout(this.nowTimer);
    window.removeEventListener("resize", this.onWindowResize);
    window.removeEventListener("venato:flip-settled", this.onWindowResize);
    window.removeEventListener("mousedown", this.onOutside);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    window.removeEventListener("mouseup", this.onMouseUp);
    window.removeEventListener("keydown", this.onKey);
    this.attached = false;
  }

  highlight() {
    this.syncResizePreview();
    this.selected.forEach((td) => td.classList.remove("sel", "box"));
    this.selected = [];
    if (this.marquee) {
      const m = this.marquee, c0 = col(m.di0), c1 = col(m.di1);
      for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++)
        for (let i = Math.min(m.s0, m.s1); i <= Math.max(m.s0, m.s1); i++) {
          const td = this.cells[c].plan[i];
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

  idOf(hit) { return hit.outlook ? `outlook:${hit.ev.id}` : hit.entry.id; }

  // A selected block as {id, outlook, en, di, track, s, e} (or null if it's gone).
  itemOf(id) {
    const b = (this.blocks || []).find((x) => !x.ghost && (x.outlook ? `outlook:${x.en.id}` : x.en.id) === id);
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
    const c0 = Math.min(col(m.di0), col(m.di1)), c1 = Math.max(col(m.di0), col(m.di1));
    const s0 = Math.min(m.s0, m.s1), s1 = Math.max(m.s0, m.s1);
    if (m.from && c0 === c1 && s0 === s1) { this.setPicked([m.from]); return; }   // a click on a block: select it
    const inside = this.blocks.filter((b) => {
      if (b.ghost) return false;
      const c = col(b.di);
      return c >= c0 && c <= c1 && b.s <= s1 && b.e > s0;
    }).map((b) => (b.outlook ? `outlook:${b.en.id}` : b.en.id));
    this.setPicked(m.add ? [...this.picked, ...inside] : inside);
    // Empty time in one day (no category picked), dragged over or clicked: add an event there, times
    // filled in. A click that only clears a selection doesn't open it.
    if (!inside.length && !m.add && c0 === c1 && (s1 > s0 || !m.hadPicked) && !this.frozen(c0)) {
      const track = this.trackFor(c0), cell = this.cells[c0][track][s1].getBoundingClientRect();
      const cat = this.cats.get(this.brush) || this.data.categories[0];
      this.openPopover({ id: uid(), isNew: true, date: this.data.days[c0], track, start: slotTime(s0),
                         end: slotTime(s1 + 1), label: "", categoryId: cat && cat.id, details: null },
                       cell.right + 8, cell.top - 40);
    }
  }

  dragGroupTo(di, slot) {
    const g = this.groupDrag, ddi = di - g.downDi, ds = slot - g.downSlot;
    const fits = g.items.length && g.items.every((it) => it.di + ddi >= 0 && it.di + ddi < this.data.days.length &&
                                      !this.frozen(it.di + ddi) && it.s + ds >= 0 && it.e + ds <= SLOTS);
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
    const ops = this.placeOps(g.items, (it) => ({ di: it.di + g.ddi, track: this.trackFor(it.di + g.ddi), s: it.s + g.ds, e: it.e + g.ds }));
    this.commit([{ opId: uid(), kind: "batch", label: `Moved ${g.items.length} blocks`, ops }]);
    this.setPicked(g.items.map((it) => (it.outlook ? `ol:${it.en.id}` : it.en.id)));
  }

  deletePicked() {
    const items = [...this.picked].map((id) => this.itemOf(id)).filter((it) => it && !this.frozen(it.di));
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
      if (di >= this.data.days.length || s + it.len > SLOTS || this.frozen(di)) { skipped++; continue; }   // off the end, or a locked Plan
      const id = uid();
      ids.push(id);
      ops.push({ opId: uid(), kind: "paint", date: this.data.days[di], track: this.trackFor(di),
                 start: slotTime(s), end: slotTime(s + it.len), newId: id,
                 block: { label: it.label, categoryId: it.categoryId, details: it.details } });
    }
    if (!ops.length) { this.flashHint("Can't paste there"); return true; }
    // Undoable with Cmd/Ctrl+Z, quietly (no Undo bar for a paste).
    this.commit(ops.length === 1 ? [{ ...ops[0], quiet: true, label: `Pasted ${ops[0].block.label}` }]
                                 : [{ opId: uid(), kind: "batch", quiet: true, label: `Pasted ${ops.length} blocks`, ops }]);
    if (!one) this.setPicked(ids);
    if (skipped) this.flashHint(`${skipped} didn't fit (past the end of the week or day) and weren't pasted`);
    return true;
  }

  // ---------- Moving and resizing blocks ----------

  spanOf(hit) {
    const item = hit.outlook ? hit.ev : hit.entry;
    return { s0: Math.max(0, slotOf(item.start)), e0: Math.min(SLOTS, slotOf(item.end)) };
  }

  // Which part of a block the pointer is on: its top edge, its bottom edge, or the middle.
  zoneAt(di, track, s0, e0, y) {
    const top = this.cells[di][track][s0].getBoundingClientRect().top;
    const bottom = this.cells[di][track][e0 - 1].getBoundingClientRect().bottom;
    const edge = Math.min(7, (bottom - top) / 3);
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
    if (bd.zone === "move") {
      if (this.frozen(di)) return;                   // not onto a locked Plan: stays where it last fitted
      const s = Math.max(0, Math.min(SLOTS - len, bd.s0 + slot - bd.downSlot));
      bd.target = { di, track: this.trackFor(di), s, e: s + len };
    } else if (bd.zone === "start") {
      bd.target = { di: bd.di, track: bd.track, s: Math.min(slot, bd.e0 - 1), e: bd.e0 };
    } else {
      bd.target = { di: bd.di, track: bd.track, s: bd.s0, e: Math.max(slot + 1, bd.s0 + 1) };
    }
    const t = bd.target;
    bd.moved = t.di !== bd.di || t.track !== bd.track || t.s !== bd.s0 || t.e !== bd.e0;
    this.highlight();
  }

  // Resizing a block: a preview of it at its new length (its colour, its new times) over the grid.
  // It eases toward the edge being dragged, so the steps between half hours glide rather than jump.
  // Its title and times sit at its top, as a tall block's do, so they move with the top edge and stay
  // put when the bottom edge moves. Gone when the drag ends.
  syncResizePreview() {
    const bd = this.blockDrag;
    const show = bd && bd.zone !== "move" && bd.moved && this.wrapEl;
    if (!show) { this.removePreview(); return; }
    const { di, track, s, e } = bd.target;
    const item = bd.hit.outlook ? bd.hit.ev : bd.hit.entry;
    const cat = this.cats.get(item.categoryId);
    const origin = this.wrapEl.getBoundingClientRect();
    const target = this.boxRect(this.cells[di][track][s], this.cells[di][track][e - 1], origin);
    const label = bd.hit.outlook ? item.title : item.label;
    const text = `${label}|${fmtRange(slotTime(s), slotTime(e))}`;
    let p = this.preview;
    if (!p) {
      const el = document.createElement("div");
      el.className = "tt-preview";
      el.setAttribute("aria-hidden", "true");
      this.wrapEl.appendChild(el);
      p = this.preview = { el, cur: { ...target }, target, text: "" };
    }
    p.target = target;
    p.el.style.setProperty("--fill", (cat && cat.colour) || "#9e9e9e");
    if (p.text !== text) {                          // only when it changes, so the text isn't redrawn each move
      p.text = text;
      p.el.innerHTML = `<b>${esc(label)}</b><span>${esc(fmtRange(slotTime(s), slotTime(e)))}</span>`;
    }
    this.placePreview();
  }

  placePreview() {
    const p = this.preview;
    if (!p) return;
    p.el.style.left = `${p.cur.left}px`; p.el.style.top = `${p.cur.top}px`;
    p.el.style.width = `${p.cur.width}px`; p.el.style.height = `${p.cur.height}px`;
    if (this.previewRaf) return;                    // already easing
    const step = () => {
      this.previewRaf = null;
      const q = this.preview;
      if (!q) return;
      let moving = false;
      for (const k of ["left", "top", "width", "height"]) {
        const d = q.target[k] - q.cur[k];
        if (Math.abs(d) < 0.3) q.cur[k] = q.target[k];
        else { q.cur[k] += d * PREVIEW_EASE; moving = true; }
      }
      q.el.style.left = `${q.cur.left}px`; q.el.style.top = `${q.cur.top}px`;
      q.el.style.width = `${q.cur.width}px`; q.el.style.height = `${q.cur.height}px`;
      if (moving) this.previewRaf = requestAnimationFrame(step);
    };
    this.previewRaf = requestAnimationFrame(step);
  }

  removePreview() {
    if (this.previewRaf) cancelAnimationFrame(this.previewRaf);
    this.previewRaf = null;
    if (this.preview) this.preview.el.remove();
    this.preview = null;
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
      <div><b>${entry.isNew ? "New event · " : ""}${day} · ${esc(fmtRange(entry.start, entry.end))}</b> · ${entry.track === "plan" ? "Plan" : "Actual"}</div>
      <input class="p-label" list="tt-labels" value="${esc(entry.label)}" placeholder="What is it? e.g. Boxing">
      <select class="p-cat">${options}</select>
      <div class="p-when">
        <input type="date" class="p-date" value="${esc(entry.date)}" aria-label="Day">
        <select class="p-start" aria-label="Starts">${timeOptions(0, SLOTS - 1, slotOf(entry.start))}</select>
        <span>–</span>
        <select class="p-end" aria-label="Ends">${timeOptions(1, SLOTS, slotOf(entry.end))}</select>
      </div>
      <textarea class="p-details" rows="2" placeholder="Description (optional)">${esc(entry.details || "")}</textarea>
      <div class="row">
        ${entry.isNew ? `<span style="margin-right:auto"></span>` : `<button class="del">Delete</button>`}
        <button class="cancel">Cancel</button>
        <button class="save"><b>${entry.isNew ? "Add" : "Save"}</b></button>
      </div>`;
    pop.style.left = Math.min(x, window.innerWidth - 260) + "px";
    pop.style.top = Math.min(y, window.innerHeight - 160) + "px";
    this.root.appendChild(pop);
    this.popover = pop;

    const labelEl = pop.querySelector(".p-label");
    const catEl = pop.querySelector(".p-cat");
    labelEl.focus();
    labelEl.select();
    let picked = false;                          // the category was chosen by hand: typing no longer changes it
    catEl.addEventListener("change", () => { picked = true; });
    const guess = () => {
      const id = !picked && this.mapLabel(labelEl.value);
      if (id && this.cats.has(id)) catEl.value = id;
    };
    labelEl.addEventListener("input", guess);
    labelEl.addEventListener("change", guess);   // a label picked from the suggestions list

    const startEl = pop.querySelector(".p-start"), endEl = pop.querySelector(".p-end");
    const dateEl = pop.querySelector(".p-date");
    startEl.addEventListener("change", () => {     // keep the length when the start moves
      const len = slotOf(entry.end) - slotOf(entry.start);
      if (+endEl.value <= +startEl.value) endEl.value = String(Math.min(SLOTS, +startEl.value + Math.max(1, len)));
    });

    const save = () => {
      const s = +startEl.value, e = +endEl.value, date = dateEl.value || entry.date;
      if (e <= s) {
        endEl.setCustomValidity("Ends after it starts");
        endEl.reportValidity();
        return;
      }
      if (!catEl.value) return;                 // no category to put it in: nothing to save
      const label = labelEl.value.trim() || (this.cats.get(catEl.value) || {}).name || "";
      const lower = label.toLowerCase();         // remember it now, so the next block knows (the server does too)
      if (this.mapLabel(label) !== catEl.value) {
        for (const l of Object.keys(this.data.labelMap)) if (l.toLowerCase() === lower) delete this.data.labelMap[l];
        this.data.labelMap[label] = catEl.value;
      }
      const details = pop.querySelector(".p-details").value.trim() || null;
      if (entry.isNew) {                         // a new event over the selected time (overlaps trimmed like painting)
        const track = date === entry.date ? entry.track
          : ((this.dayState[date] || {}).locked ? "actual" : "plan");
        this.commit([{ opId: uid(), kind: "paint", date, track, start: slotTime(s), end: slotTime(e), newId: entry.id,
                       learn: true, block: { label, categoryId: catEl.value, details } }]);
        this.closePopover();
        return;
      }
      const edit = { opId: uid(), kind: "upsert", entry: { ...entry, label, categoryId: catEl.value, details } };
      const moved = date !== entry.date || s !== slotOf(entry.start) || e !== slotOf(entry.end);
      if (moved) {                               // new times: then move it there (overlaps trimmed like a drag)
        const track = date === entry.date ? entry.track
          : ((this.dayState[date] || {}).locked ? "actual" : "plan");   // a started day changes its Actual
        this.commit([{ opId: uid(), kind: "batch", label: `Changed ${label}'s times`, ops: [
          edit, { opId: uid(), kind: "move", id: entry.id, date, track, start: slotTime(s), end: slotTime(e) }] }]);
      } else {
        this.commit([edit]);
      }
      this.closePopover();
    };
    endEl.addEventListener("change", () => endEl.setCustomValidity(""));
    labelEl.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    pop.querySelector(".save").addEventListener("click", save);
    if (!catEl.value) pop.querySelector(".save").disabled = true;
    pop.querySelector(".cancel").addEventListener("click", () => this.closePopover());
    if (!entry.isNew) pop.querySelector(".del").addEventListener("click", () => {
      this.commit([{ opId: uid(), kind: "delete", id: entry.id }]);
      this.closePopover();
    });
    pop.addEventListener("mousedown", (e) => e.stopPropagation());
  }

  // Which block (own or Outlook) covers a slot. Outlook events are drawn on top.
  blockAt(di, track, slot) {
    const ev = track === "plan" && this.outlookAt[di][slot];
    if (ev) return { outlook: true, ev, di };
    const id = this.occupant[di][track][slot];
    return id ? { outlook: false, entry: this.entries.get(id), di } : null;
  }

  // Click on a block: it grows slightly and a card shows what it is and when,
  // like Outlook's peek. Edit / Delete (Remove for Outlook events) unless view only.
  openCard(hit) {
    this.closePopover();
    this.cardHit = hit;
    const item = hit.outlook ? hit.ev : hit.entry;
    const blockId = hit.outlook ? `outlook:${item.id}` : item.id;
    const cat = this.cats.get(item.categoryId);
    const day = new Date(item.date + "T00:00").toLocaleDateString(LOC(), { weekday: "long", day: "numeric", month: "long" });
    const when = hit.outlook ? item.exact : fmtRange(item.start, item.end);
    const text = hit.outlook ? item.description : item.details;
    const title = hit.outlook ? item.title : item.label;
    const di = hit.di ?? this.dayIndex.get(item.date);
    const locked = !this.data.readonly && di !== undefined && this.frozen(di);
    const viewOnly = this.data.readonly || locked;

    const card = document.createElement("div");
    card.className = "tt-pop tt-peek";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", `${hit.outlook ? item.title : item.label}, details`);
    card.innerHTML = `
      <div class="pk-title">${hit.outlook ? CAL_ICON : ""}<b>${esc(title)}</b></div>
      <div class="pk-when">${esc(day)} · ${esc(when)}</div>
      <div class="pk-meta"><i style="background:${esc(cat ? cat.colour : "#9e9e9e")}"></i>${esc(cat ? cat.name : "No category")}
        · ${hit.outlook || item.track === "plan" ? "Plan" : "Actual"}${hit.outlook ? " · from your calendar" : ""}${locked ? " · locked" : ""}</div>
      ${hit.outlook && item.location ? `<div class="pk-loc">${PIN_ICON}${esc(item.location)}</div>` : ""}
      ${text ? `<div class="pk-text">${esc(text).replace(/\n/g, "<br>")}</div>` : ""}
      ${locked ? `<div class="pk-note">Locked when the day started. Switch to <b>Actual</b> to change what happened.</div>` : ""}
      ${this.data.readonly ? "" : `
      <div class="row pk-status" role="group" aria-label="Did it happen?">
        <button class="st-done ${this.status[blockId] === "done" ? "on" : ""}" aria-pressed="${this.status[blockId] === "done"}">✓ Done</button>
        <button class="st-missed ${this.status[blockId] === "missed" ? "on" : ""}" aria-pressed="${this.status[blockId] === "missed"}">✗ Not done</button>
      </div>`}
      ${viewOnly ? "" : `
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

    if (!this.data.readonly) {
      const mark = (status) => {             // click the same one again to clear it
        const next = this.status[blockId] === status ? null : status;
        this.commit([{ opId: uid(), kind: "set_status", id: blockId, status: next, date: item.date,
                       start: item.start, end: item.end, label: title, categoryId: item.categoryId }]);
        this.closePopover();
      };
      card.querySelector(".st-done").addEventListener("click", () => mark("done"));
      card.querySelector(".st-missed").addEventListener("click", () => mark("missed"));
    }
    if (viewOnly) return;
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

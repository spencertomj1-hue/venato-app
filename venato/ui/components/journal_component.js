// The journal: a book that opens, one page per day, turned like a book.
//
// Python passes { open, date, today, title, text, prompt, prevTitle, notice,
//                 showSleep, showWater, sleep, water, waterUnit, waterStep, waterMax,
//                 trackers: [{id, name, unit, step, value}],
//                 habits: [{id, name, done}], sessions: [{id, title, km, done}] }.
// Triggers back to Python:
//   open     {open: true | false}
//   save     {date, text, final}   final = on leaving the page (blur, turning, closing): to-dos are made then
//   nav      {date}                 the page to turn to
//   log      {date, field, value}   sleep (hours) or water (waterUnit), when switched on in Settings
//   track    {date, id, value}      one of the user's own day trackers (null clears it)
//   habit    {date, id, done}       tick a habit for the day
//   session  {id, done}             tick off the day's training session
//
// The component is kept on its element between reruns, so typing is never interrupted:
// incoming text only replaces the page when the date changes or the page isn't being typed on.

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2);
const shift = (iso, n) => {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

class Journal {
  constructor(el, send) {
    this.el = el;
    this.send = send;
    this.date = null;
    this.timer = null;
    this.turning = false;
  }

  update(data) {
    this.data = data;
    if (!data.open) {
      this.date = null;
      this.renderCover();
      return;
    }
    const newPage = data.date !== this.date;
    if (!this.el.querySelector(".jn-book") || newPage) this.renderBook();
    else {
      // Same page: refresh the bits around the writing, never the writing itself while typing.
      this.el.querySelector(".jn-left").innerHTML = this.leftHtml();
      if (document.activeElement !== this.area && this.root().activeElement !== this.area) this.area.value = data.text || "";
      this.bindLeft();
    }
    this.date = data.date;
  }

  root() { return this.el.getRootNode(); }

  // ---------- Closed ----------

  renderCover() {
    this.el.innerHTML = `
      <div class="jn-closed">
        <div class="jn-cover" role="img" aria-label="Journal">
          <div class="jn-cover-in"><div class="jn-cover-title">Journal</div>
          <div class="jn-cover-sub">${esc(this.data.title || "")}</div></div>
        </div>
        <button class="jn-open-btn">Open journal</button>
      </div>`;
    const open = () => {
      const cover = this.el.querySelector(".jn-cover");
      cover.classList.add("opening");                     // the cover swings open, then the book shows
      setTimeout(() => this.send("open", { open: true }), 650);
    };
    this.el.querySelector(".jn-open-btn").addEventListener("click", open);
    this.el.querySelector(".jn-cover").addEventListener("click", open);
  }

  // ---------- Open ----------

  leftHtml() {
    const d = this.data;
    const hours = (field, label, what) => `
      <div class="jn-rate" role="group" aria-label="${label}">
        <span>${label}</span>
        <button class="jn-step" data-field="${field}" data-step="-0.5" aria-label="Half an hour less ${what}">−</button>
        <b class="jn-sleep">${d[field] == null ? "–" : `${+d[field]} h`}</b>
        <button class="jn-step" data-field="${field}" data-step="0.5" aria-label="Half an hour more ${what}">+</button>
      </div>`;
    const amount = (field, label, unit, step, max) => `
      <div class="jn-rate" role="group" aria-label="${label}">
        <span>${label}</span>
        <button class="jn-step" data-field="${field}" data-step="-${step}" data-max="${max}" aria-label="Less ${label.toLowerCase()}">−</button>
        <b class="jn-sleep">${d[field] == null ? "–" : `${+d[field]} ${esc(unit)}`}</b>
        <button class="jn-step" data-field="${field}" data-step="${step}" data-max="${max}" aria-label="More ${label.toLowerCase()}">+</button>
      </div>`;
    // The user's own trackers. − on a blank day records 0, so a clean day is different from one not logged.
    const tracker = (t) => `
      <div class="jn-rate" role="group" aria-label="${esc(t.name)}">
        <span title="${esc(t.name)}${t.unit ? ` (${esc(t.unit)})` : ""}">${esc(t.name)}</span>
        <button class="jn-track" data-id="${esc(t.id)}" data-step="-${t.step}" aria-label="${esc(t.name)}: less">−</button>
        <b class="jn-sleep">${t.value == null ? "–" : `${+t.value}${t.unit ? ` ${esc(t.unit)}` : ""}`}</b>
        <button class="jn-track" data-id="${esc(t.id)}" data-step="${t.step}" aria-label="${esc(t.name)}: more">+</button>
      </div>`;
    const trackers = (d.trackers || []).map(tracker).join("");
    const tick = (kind, id, done, text) => `
      <label class="jn-tick"><input type="checkbox" data-kind="${kind}" data-id="${esc(id)}" ${done ? "checked" : ""}>
        <span>${esc(text)}</span></label>`;
    const habits = (d.habits || []).map((h) => tick("habit", h.id, h.done, h.name)).join("");
    const sessions = (d.sessions || []).map((s) => tick("session", s.id, s.done, s.title + (s.km ? ` · ${s.km} km` : ""))).join("");
    return `
      <div class="jn-left-in">
        <div class="jn-day">${esc(d.title)}</div>
        ${d.showSleep || d.showWater ? `<div class="jn-block">
          ${d.showSleep ? hours("sleep", "Sleep", "sleep") : ""}
          ${d.showWater ? amount("water", "Water", d.waterUnit || "L", d.waterStep || 0.25, d.waterMax || 15) : ""}
        </div>` : ""}
        ${trackers ? `<div class="jn-block"><div class="jn-label">Tracking</div>${trackers}</div>` : ""}
        ${sessions ? `<div class="jn-block"><div class="jn-label">Training</div>${sessions}</div>` : ""}
        <div class="jn-block"><div class="jn-label">Habits</div>
          ${habits || `<div class="jn-none">No habits yet (add them under the book).</div>`}</div>
        ${d.notice ? `<div class="jn-notice">${esc(d.notice)}</div>` : ""}
        <div class="jn-tip"><b>"Buy milk"</b> → that day's to-dos · <b>^Meal prep^</b> → that week's</div>
        <div class="jn-left-nav">
          <button class="jn-prev" aria-label="Previous day">‹ ${esc(d.prevTitle || "")}</button>
        </div>
      </div>`;
  }

  renderBook() {
    const d = this.data;
    const atToday = d.date >= d.today;
    this.el.innerHTML = `
      <div class="jn-book${this.date === null ? " just-opened" : ""}">
        <div class="jn-left">${this.leftHtml()}</div>
        <div class="jn-right">
          <div class="jn-head">${esc(d.title)}</div>
          <textarea class="jn-text" aria-label="Journal for ${esc(d.title)}" placeholder="${esc(d.prompt || "Dear diary…")}"
            spellcheck="true">${esc(d.text || "")}</textarea>
          <div class="jn-foot">
            <button class="jn-close">Close journal</button>
            ${atToday ? "" : `<button class="jn-today">Today</button>`}
            <button class="jn-next" ${atToday ? "disabled" : ""} aria-label="Next day">›</button>
          </div>
        </div>
      </div>`;
    this.area = this.el.querySelector(".jn-text");
    this.area.addEventListener("input", () => {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.save(false), 800);     // keep the words safe while typing
    });
    this.area.addEventListener("blur", () => this.save(true));
    this.el.querySelector(".jn-next").addEventListener("click", () => this.turn(1));
    this.el.querySelector(".jn-close").addEventListener("click", () => {
      this.save(true);
      this.send("open", { open: false });
    });
    const today = this.el.querySelector(".jn-today");
    if (today) today.addEventListener("click", () => this.go(this.data.today, 1));
    this.bindLeft();
    // Arrow keys turn pages when not typing.
    this.el.querySelector(".jn-book").addEventListener("keydown", (e) => {
      if (e.target === this.area) return;
      if (e.key === "ArrowLeft") this.turn(-1);
      if (e.key === "ArrowRight") this.turn(1);
    });
  }

  bindLeft() {
    const left = this.el.querySelector(".jn-left");
    const prev = left.querySelector(".jn-prev");
    if (prev) prev.addEventListener("click", () => this.turn(-1));
    // Changes show at once (redrawn here), then go to Python.
    const redraw = () => { left.innerHTML = this.leftHtml(); this.bindLeft(); };
    left.querySelectorAll(".jn-step").forEach((b) => b.addEventListener("click", () => {
      const field = b.dataset.field, old = this.data[field], step = +b.dataset.step;
      // Sleep starts from 7 h on the first press; the rest from 0.
      const value = old == null ? (field === "sleep" ? 7 : Math.max(0, step))
                                : Math.max(0, Math.min(+b.dataset.max || 24, Math.round((+old + step) * 100) / 100));
      this.data[field] = value;
      redraw();
      this.send("log", { date: this.data.date, field, value });
    }));
    left.querySelectorAll(".jn-track").forEach((b) => b.addEventListener("click", () => {
      const t = (this.data.trackers || []).find((x) => x.id === b.dataset.id);
      if (!t) return;
      const step = +b.dataset.step;
      t.value = t.value == null ? Math.max(0, step) : Math.max(0, Math.round((+t.value + step) * 1000) / 1000);
      redraw();
      this.send("track", { date: this.data.date, id: t.id, value: t.value });
    }));
    left.querySelectorAll(".jn-tick input").forEach((box) => box.addEventListener("change", () => {
      const list = box.dataset.kind === "habit" ? this.data.habits : this.data.sessions;
      const item = list.find((x) => String(x.id) === box.dataset.id);
      if (item) item.done = box.checked;
      if (box.dataset.kind === "habit") this.send("habit", { date: this.data.date, id: +box.dataset.id, done: box.checked });
      else this.send("session", { id: box.dataset.id, done: box.checked });
    }));
  }

  save(final) {
    clearTimeout(this.timer);
    if (!this.area || !this.date) return;
    this.send("save", { date: this.date, text: this.area.value, final });
  }

  turn(dir) {
    if (dir > 0 && this.data.date >= this.data.today) return;
    this.go(shift(this.data.date, dir), dir);
  }

  // Turn the page: a sheet sweeps over (forwards from the right, back from the left), then the new day shows.
  go(date, dir) {
    if (this.turning) return;
    this.save(true);
    this.turning = true;
    const book = this.el.querySelector(".jn-book");
    const sheet = document.createElement("div");
    sheet.className = `jn-sheet ${dir > 0 ? "fwd" : "back"}`;
    book.appendChild(sheet);
    setTimeout(() => {
      this.send("nav", { date });
      this.turning = false;
      setTimeout(() => sheet.remove(), 200);
    }, 450);
  }
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const el = parentElement.querySelector(".jn-root");
  if (!el.__journal) el.__journal = new Journal(el, (name, value) => setTriggerValue(name, { ...value, nonce: uid() }));
  el.__journal.update(data);
}

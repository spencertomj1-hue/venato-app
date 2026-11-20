// Month calendar for the Daily log page. A day with a journal entry is marked; sleep and water show
// too when switched on; clicking a day selects it.
//
// Python passes { month: "YYYY-MM", today, selected, days: {iso: {notes: true, sleep?, water?}} }
// (sleep and water only when they are switched on).
// Triggers back to Python:  select {date, nonce}   nav {dir: -1 | 0 | 1, nonce}

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2);
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const ICON = {
  sleep: '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>',
  water: '<svg viewBox="0 0 24 24"><path d="M12 3s6 6.6 6 11a6 6 0 0 1-12 0c0-4.4 6-11 6-11z"/></svg>',
  note: '<svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6z"/><path d="M9 12h6M9 16h4"/></svg>',
};

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".cal-root");
  const send = (name, value) => setTriggerValue(name, { ...value, nonce: uid() });

  const [y, m] = data.month.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const firstDow = data.weekStart === "Sunday" ? 0 : 1;               // weeks start on Monday, or Sunday
  const start = new Date(y, m - 1, 1 - ((first.getDay() - firstDow + 7) % 7));   // that day on/before the 1st
  const waterUnit = data.waterUnit || "L";
  const title = first.toLocaleDateString("en-GB", { month: "long", year: "numeric" });

  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const key = iso(d);
    const e = data.days[key] || {};
    const cls = ["cell"];
    if (d.getMonth() !== m - 1) cls.push("other");
    if (key === data.today) cls.push("today");
    if (key === data.selected) cls.push("selected");
    if (key > data.today) cls.push("future");
    if (e.notes) cls.push("has-entry");
    // What a screen reader says for the day, e.g. "Friday 30 October: slept 7.5 hours, has a journal entry".
    const said = [d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }),
      [e.sleep != null && `slept ${+e.sleep} hours`, e.water != null && `drank ${+e.water} ${waterUnit === "L" ? "litres" : waterUnit}`, e.notes && "has a journal entry"].filter(Boolean).join(", ") || "nothing logged"]
      .join(": ");
    const stat = (kind, value, extra = "") =>
      value == null ? "" : `<span class="stat ${kind}" ${extra}>${ICON[kind]}${esc(value)}</span>`;
    cells.push(`
      <button class="${cls.join(" ")}" data-date="${key}" aria-label="${esc(said)}"
        aria-pressed="${key === data.selected}"${key === data.today ? ' aria-current="date"' : ""}>
        <span class="num">${d.getDate()}${e.notes ? `<i class="note" title="Journal entry">${ICON.note}</i>` : ""}</span>
        <span class="stats">
          ${stat("sleep", e.sleep == null ? null : `${+e.sleep}h`)}
          ${stat("water", e.water == null ? null : `${+e.water}${waterUnit === "L" ? "L" : " oz"}`)}
        </span>
      </button>`);
  }

  root.innerHTML = `
    <div class="cal-head">
      <div class="cal-title">${title}</div>
      <div class="cal-nav">
        <button data-nav="-1" title="Previous month" aria-label="Previous month">‹</button>
        <button data-nav="0">Today</button>
        <button data-nav="1" title="Next month" aria-label="Next month">›</button>
      </div>
      <div class="cal-key">
        <span class="stat note">${ICON.note}journal</span>
        ${data.showSleep ? `<span class="stat sleep">${ICON.sleep}sleep</span>` : ""}
        ${data.showWater ? `<span class="stat water">${ICON.water}water</span>` : ""}
      </div>
    </div>
    <div class="cal-grid" role="group" aria-label="${title}">
      ${(data.weekdays || ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]).map((n) => `<div class="dow">${n}</div>`).join("")}
      ${cells.join("")}
    </div>`;

  root.querySelectorAll("[data-nav]").forEach((b) => (b.onclick = () => send("nav", { dir: +b.dataset.nav })));
  root.querySelectorAll(".cell").forEach((b) => (b.onclick = () => {
    root.querySelectorAll(".cell.selected").forEach((c) => c.classList.remove("selected"));
    b.classList.add("selected");                       // instant feedback
    send("select", { date: b.dataset.date });
  }));
}

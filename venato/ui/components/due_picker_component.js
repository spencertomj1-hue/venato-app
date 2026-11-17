// A goal's deadline: a field that opens a small calendar. The months scroll (from this month on);
// the handy deadlines are marked on their days (2 weeks from now, end of the month, a month from now,
// end of the year, a year from now), and shortcuts under it pick the end of the year or a year from now.
//
// Python passes { value: "YYYY-MM-DD", today, months, weekStart: "Monday" | "Sunday", weekdays: [...],
//                 marks: [{date, label}], shortcuts: [{date, label}], label }.
// Trigger back to Python:  pick {date, nonce}

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2);
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const nice = (s, opts = {}) => parse(s).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", ...opts });

// "in 3 weeks", "tomorrow", "in 4 months"
function fromNow(today, day) {
  const days = Math.round((parse(day) - parse(today)) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days < 14) return `in ${days} days`;
  if (days < 60) return `in ${Math.round(days / 7)} weeks`;
  if (days >= 358 && days <= 372) return "in a year";
  if (days < 548) return `in ${Math.round(days / 30.4)} months`;
  return `in ${(days / 365).toFixed(1).replace(/\.0$/, "")} years`;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".dp-root");
  const marks = Object.fromEntries((data.marks || []).map((m) => [m.date, m.label]));
  const firstDow = data.weekStart === "Sunday" ? 0 : 1;
  const today = parse(data.today);

  const months = [];
  for (let k = 0; k < data.months; k++) {
    const first = new Date(today.getFullYear(), today.getMonth() + k, 1);
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - ((first.getDay() - firstDow + 7) % 7));
    const cells = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      if (i >= 35 && d.getMonth() !== first.getMonth()) break;          // no empty sixth row
      if (d.getMonth() !== first.getMonth()) { cells.push(`<span class="pad"></span>`); continue; }
      const key = iso(d);
      const past = key < data.today;
      const mark = marks[key];
      const cls = ["day", past && "past", key === data.today && "today", key === data.value && "sel", mark && "mark"].filter(Boolean);
      const said = nice(key, { weekday: "long", month: "long" }) + (mark ? `, ${mark}` : "");
      cells.push(`<button class="${cls.join(" ")}" data-date="${key}" ${past ? "disabled" : ""} aria-label="${esc(said)}"` +
        `${mark ? ` title="${esc(mark)}"` : ""} aria-pressed="${key === data.value}">${d.getDate()}</button>`);
    }
    months.push(`<section class="month" data-month="${iso(first).slice(0, 7)}">` +
      `<h4>${esc(first.toLocaleDateString("en-GB", { month: "long", year: "numeric" }))}</h4>` +
      `<div class="grid">${data.weekdays.map((w) => `<span class="wd">${esc(w.slice(0, 2))}</span>`).join("")}${cells.join("")}</div></section>`);
  }

  const wasOpen = root.dataset.open === "1";
  root.innerHTML = `
    <button class="field" aria-expanded="${wasOpen}" aria-haspopup="dialog">
      <span class="lbl">${esc(data.label || "Deadline")}</span>
      <span class="val">${esc(nice(data.value))}</span>
      <span class="rel">${esc(fromNow(data.today, data.value))}</span>
      <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/></svg>
    </button>
    <div class="pop" role="dialog" aria-label="Pick a deadline" ${wasOpen ? "" : "hidden"}>
      <div class="key">${(data.marks || []).map((m) => `<button class="kchip" data-jump="${m.date}" title="${esc(nice(m.date))}"><i></i>${esc(m.label)}</button>`).join("")}</div>
      <div class="scroll">${months.join("")}</div>
      <div class="short">${(data.shortcuts || []).map((s) => `<button class="sc" data-date="${s.date}">${esc(s.label)}<small>${esc(nice(s.date, { weekday: undefined }))}</small></button>`).join("")}</div>
    </div>`;

  const field = root.querySelector(".field"), pop = root.querySelector(".pop"), scroll = root.querySelector(".scroll");
  const scrollTo = (day, smooth) => {
    const sec = scroll.querySelector(`[data-month="${day.slice(0, 7)}"]`);
    const btn = scroll.querySelector(`[data-date="${day}"]`);
    // The day's month from its top, or (when the day sits low in it) far enough down to show the day.
    const top = sec ? Math.max(sec.offsetTop, btn ? btn.offsetTop + btn.offsetHeight - scroll.clientHeight + 8 : 0) : 0;
    scroll.scrollTo({ top, behavior: smooth ? "smooth" : "auto" });
    if (btn && smooth) { btn.classList.add("flash"); setTimeout(() => btn.classList.remove("flash"), 900); }
  };
  const setOpen = (open) => {
    root.dataset.open = open ? "1" : "";
    pop.hidden = !open;
    field.setAttribute("aria-expanded", String(open));
    if (open) { scrollTo(data.value, false); (scroll.querySelector(".sel") || scroll.querySelector(".day:not(.past)")).focus({ preventScroll: true }); }
  };
  if (wasOpen) scrollTo(data.value, false);
  field.addEventListener("click", () => setOpen(pop.hidden));
  root.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { setOpen(false); field.focus(); } });
  pop.addEventListener("click", (e) => {
    const jump = e.target.closest("[data-jump]");
    if (jump) { scrollTo(jump.dataset.jump, true); return; }
    const b = e.target.closest("[data-date]");
    if (!b || b.disabled) return;
    root.dataset.open = "";
    setTriggerValue("pick", { date: b.dataset.date, nonce: uid() });
  });
}

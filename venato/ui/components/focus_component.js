// The live Focus timer. On the Focus page it's a big stopwatch dial: press it to start, press it
// again to stop and save. A timer counts down, the stopwatch counts up; the ring shows progress.
// On Home it's a small dial beside a name box. Idle, the ring fills to today's total against the daily aim and
// pressing it starts a stopwatch with the box's name; running, the ring sweeps once an hour round the time and
// pressing it stops and logs (pause and cancel are on the Focus page). The dial fits the tile's height.
//
// Python passes { state: "idle" | "running" | "paused", kind, label, planned (seconds or null),
// elapsed (seconds when drawn), drawnAt (ms), compact }. The time runs in the database, so
// this only draws it: buttons send an "action" trigger ({name, at}), and when a timer reaches
// zero it sends {name: "done"} once, beeps, and Python logs it. Pressing the idle dial sends
// {name: "start"}: Python reads the label and mode from the controls below it (Home sends {name, label}).
// Home also passes today (seconds focused today), aim (seconds) and last (the last name used).

const instances = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".fc-root");
  let t = instances.get(root);
  if (!t) {
    t = new FocusTimer(root);
    instances.set(root, t);
  }
  t.send = (name, extra) => setTriggerValue("action", { name, at: Date.now(), ...extra });
  t.update(data);
  return () => { t.stop(); t.unfit(); };
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// Today's total on the idle dial: "45m", "1h 35m", "4h".
const short = (secs) => {
  const m = Math.floor(secs / 60), h = Math.floor(m / 60);
  return h ? (m % 60 ? `${h}h ${m % 60}m` : `${h}h`) : `${m}m`;
};
const hours = (secs) => `${Math.round(secs / 1800) / 2} h`;
const DIAL_MIN = 44, DIAL_MAX = 128;     // px: Home's dial shrinks to the tile's height between these

const fmt = (secs) => {
  secs = Math.max(0, Math.round(secs));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
};

const R = 52, C = 2 * Math.PI * R;
const ticks = () => Array.from({ length: 60 }, (_, i) => {
  const major = i % 5 === 0, a = (i / 60) * 2 * Math.PI;
  const r1 = major ? 54.5 : 55.5, r2 = 58;
  const p = (r) => [(60 + r * Math.sin(a)).toFixed(2), (60 - r * Math.cos(a)).toFixed(2)];
  const [x1, y1] = p(r1), [x2, y2] = p(r2);
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${major ? "major" : ""}"/>`;
}).join("");

class FocusTimer {
  constructor(root) {
    this.root = root;
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (!b) return;
      let act = b.dataset.act;
      if (act === "toggle") {
        const d = this.data;
        act = d.state === "idle" ? "start" : d.kind === "break" ? "skip" : "stop";
      }
      b.classList.add("pressed");
      this.send(act, this.homeStart(act));
    });
    root.addEventListener("keydown", (e) => {          // Enter in Home's name box starts, like pressing the dial
      if (e.key === "Enter" && e.target.matches(".fc-name")) this.root.querySelector(".fc-dial")?.click();
    });
  }

  // Home's start carries the name typed beside the dial.
  homeStart(act) {
    return act === "start" && this.data.compact ? { label: this.root.querySelector(".fc-name")?.value || "" } : {};
  }

  // Home: the dial is as big as the tile has room for (DIAL_MIN..DIAL_MAX). On a narrow window, where Home
  // scrolls and the tile is as tall as what's in it, it's a fixed 96px.
  fit() {
    const host = this.root.getRootNode().host || this.root;
    const card = host.closest && host.closest('[class*="st-key-hw_"]');     // the tile's card (fixed height)
    let size = 96;
    if (card && matchMedia("(min-width: 1001px)").matches) {
      const pad = parseFloat(getComputedStyle(card).paddingBottom) || 0;
      const room = Math.floor(card.getBoundingClientRect().bottom - this.root.getBoundingClientRect().top - pad - 4);
      if (room > 0) size = Math.max(DIAL_MIN, Math.min(DIAL_MAX, room));
    }
    this.root.style.setProperty("--dial", `${size}px`);
    this.root.classList.toggle("fc-tiny", size < 84);
  }

  unfit() {
    this.resizeObs?.disconnect();
    this.resizeObs = null;
    removeEventListener("venato:flip-settled", this.onSettle);
  }

  update(data) {
    this.data = data;
    this.doneSent = false;
    this.render();
    clearInterval(this.timer);
    if (data.state === "running") this.timer = setInterval(() => this.tick(), 1000);
  }

  stop() { clearInterval(this.timer); }

  seconds() {
    const d = this.data;
    const el = (d.elapsed || 0) + (d.state === "running" ? (Date.now() - d.drawnAt) / 1000 : 0);
    return { el, left: d.planned == null ? null : d.planned - el };
  }

  tick() {
    const { left } = this.seconds();
    this.paint();
    if (left !== null && left <= 0 && !this.doneSent) {
      this.doneSent = true;
      this.beep();
      this.send("done");
    }
  }

  beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.35, 0.7].forEach((when) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
        g.gain.setValueAtTime(0.0001, ctx.currentTime + when);
        g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + when + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + when + 0.25);
        o.start(ctx.currentTime + when); o.stop(ctx.currentTime + when + 0.3);
      });
    } catch (e) { /* no sound: the notification still shows */ }
  }

  render() {
    const d = this.data;
    if (d.compact) return this.renderCompact();
    const idle = d.state === "idle", paused = d.state === "paused", isBreak = d.kind === "break";
    const hint = idle ? "Tap to start" : paused ? "Paused · tap to stop" : isBreak ? "Tap to skip" : "Tap to stop";
    const aria = idle ? "Start" : isBreak ? "Skip the break" : "Stop and save";
    const btn = (act, label) => `<button data-act="${act}" class="fc-small">${label}</button>`;
    this.root.innerHTML = `
      <div class="fc big ${d.state} ${isBreak ? "break" : ""}">
        <div class="fc-watch">
          <span class="fc-crown" aria-hidden="true"></span>
          <button class="fc-dial" data-act="toggle" aria-label="${aria}">
            <svg class="fc-ring" viewBox="0 0 120 120" aria-hidden="true">
              <g class="ticks">${ticks()}</g>
              <circle cx="60" cy="60" r="${R}" class="track"/><circle cx="60" cy="60" r="${R}" class="fill"/>
            </svg>
            <span class="fc-mid">
              <span class="fc-kind"></span>
              <span class="fc-time" role="timer" aria-live="off"></span>
              <span class="fc-label"></span>
              <span class="fc-hint">${hint}</span>
            </span>
          </button>
        </div>
        <div class="fc-btns">
          ${idle ? "" : (paused ? btn("resume", "Resume") : btn("pause", "Pause")) + btn("cancel", "Cancel")}
        </div>
      </div>`;
    this.root.querySelector(".fc-kind").textContent =
      isBreak ? "Break" : d.planned == null ? "Stopwatch" : "Timer";
    this.root.querySelector(".fc-label").textContent = idle ? "" : d.label;
    this.paint();
  }

  renderCompact() {
    const d = this.data;
    const idle = d.state === "idle", paused = d.state === "paused", isBreak = d.kind === "break";
    const typed = this.root.querySelector(".fc-name");      // keep what's being typed across a redraw
    const name = typed ? typed.value : d.last || "";
    const hadFocus = typed && typed === (this.root.getRootNode().activeElement || document.activeElement);
    const today = d.today || 0, aim = d.aim || 0;
    const aria = idle ? `Start a stopwatch. ${short(today)} focused today of a ${hours(aim)} aim`
      : isBreak ? "Skip the break" : "Stop and save";
    const side = idle
      ? `<input class="fc-name" type="text" placeholder="What are you on?" aria-label="What are you on?" value="${esc(name)}">
         <span class="fc-hint">Press the dial to start</span>`
      : `<span class="fc-on">${isBreak ? "Break" : "On"}</span>
         <strong class="fc-label"></strong>
         <span class="fc-hint">${paused ? "Paused · " : ""}Started ${esc(d.started || "")}</span>`;
    this.root.innerHTML = `
      <div class="fc compact ${d.state} ${isBreak ? "break" : ""}">
        <button class="fc-dial" data-act="toggle" aria-label="${aria}">
          <svg class="fc-ring" viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r="${R}" class="track"/><circle cx="60" cy="60" r="${R}" class="fill"/>
          </svg>
          <span class="fc-mid">
            <span class="fc-time" ${idle ? "" : 'role="timer" aria-live="off"'}></span>
            <span class="fc-sub">${idle ? "today" : isBreak ? "Skip" : "Stop"}</span>
          </span>
        </button>
        <div class="fc-side">${side}</div>
      </div>`;
    if (!idle) this.root.querySelector(".fc-label").textContent = d.label;
    if (hadFocus) this.root.querySelector(".fc-name")?.focus();
    if (!this.resizeObs) {                              // fit the dial to the tile, now and when it changes
      this.onSettle = () => this.fit();
      addEventListener("venato:flip-settled", this.onSettle);
      this.resizeObs = new ResizeObserver(() => this.fit());
      this.resizeObs.observe(document.documentElement);
    }
    this.fit();
    this.paint();
  }

  paint() {
    const d = this.data;
    const timeEl = this.root.querySelector(".fc-time");
    if (!timeEl) return;
    const { el, left } = this.seconds();
    const homeIdle = d.compact && d.state === "idle";
    timeEl.textContent = homeIdle ? short(d.today || 0) : left === null ? fmt(el) : fmt(left);
    const ring = this.root.querySelector(".fill");
    // Stopwatch: the ring goes round once a minute, like a second hand (on Home once an hour). Timer: it
    // fills to the end. Home idle: today's total against the daily aim.
    const lap = d.compact ? 3600 : 60;
    const frac = homeIdle ? Math.min(1, (d.today || 0) / (d.aim || 1)) : d.state === "idle" ? 0
      : left === null ? (el % lap) / lap : Math.min(1, el / d.planned);
    if (frac < (this.lastFrac ?? 0)) {              // wrapped round: jump back instead of sweeping backwards
      ring.style.transition = "none";
      ring.style.strokeDasharray = `0 ${C.toFixed(1)}`;
      void ring.getBoundingClientRect();
      ring.style.transition = "";
    }
    this.lastFrac = frac;
    ring.style.strokeDasharray = `${(frac * C).toFixed(1)} ${C.toFixed(1)}`;
    ring.style.strokeOpacity = frac * C >= 2 ? "" : "0";   // no lone round-cap dot near zero
  }
}

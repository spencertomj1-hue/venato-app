// The live Focus timer. On the Focus page it's a big stopwatch dial: press it to start, press it
// again to stop and save. A timer counts down, the stopwatch counts up; the ring shows progress.
// On Home it's the small version (a ring, the time, the name and Stop; pause and cancel are on the Focus page).
//
// Python passes { state: "idle" | "running" | "paused", kind, label, planned (seconds or null),
// elapsed (seconds when drawn), drawnAt (ms), compact }. The time runs in the database, so
// this only draws it: buttons send an "action" trigger ({name, at}), and when a timer reaches
// zero it sends {name: "done"} once, beeps, and Python logs it. Pressing the idle dial sends
// {name: "start"}: Python reads the label and mode from the controls below it.

const instances = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".fc-root");
  let t = instances.get(root);
  if (!t) {
    t = new FocusTimer(root);
    instances.set(root, t);
  }
  t.send = (name) => setTriggerValue("action", { name, at: Date.now() });
  t.update(data);
  return () => t.stop();
}

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
      this.send(act);
    });
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
    if (d.state === "idle") { this.root.innerHTML = ""; return; }
    const paused = d.state === "paused", isBreak = d.kind === "break";
    const btn = (act, label, primary) => `<button data-act="${act}" class="${primary ? "primary" : ""}">${label}</button>`;
    this.root.innerHTML = `
      <div class="fc compact ${isBreak ? "break" : ""}">
        <svg class="fc-ring" viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="${R}" class="track"/><circle cx="60" cy="60" r="${R}" class="fill"/>
        </svg>
        <div class="fc-mid">
          <div class="fc-time" role="timer" aria-live="off"></div>
          <div class="fc-label"></div>
        </div>
        <div class="fc-btns">
          ${isBreak ? btn("skip", "Skip break", true) : btn("stop", "Stop", true)}
        </div>
      </div>`;
    this.root.querySelector(".fc-label").textContent =
      `${d.label}${paused ? " · paused" : ""}`;
    this.paint();
  }

  paint() {
    const d = this.data;
    const timeEl = this.root.querySelector(".fc-time");
    if (!timeEl) return;
    const { el, left } = this.seconds();
    timeEl.textContent = left === null ? fmt(el) : fmt(left);
    const ring = this.root.querySelector(".fill");
    // Stopwatch: the ring goes round once a minute, like a second hand. Timer: it fills to the end.
    const frac = d.state === "idle" ? 0 : left === null ? (el % 60) / 60 : Math.min(1, el / d.planned);
    if (frac < (this.lastFrac ?? 0)) {              // wrapped round: jump back instead of sweeping backwards
      ring.style.transition = "none";
      ring.style.strokeDasharray = `0 ${C.toFixed(1)}`;
      void ring.getBoundingClientRect();
      ring.style.transition = "";
    }
    this.lastFrac = frac;
    ring.style.strokeDasharray = `${(frac * C).toFixed(1)} ${C.toFixed(1)}`;
  }
}

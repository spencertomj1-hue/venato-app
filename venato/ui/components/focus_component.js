// The live Focus timer: counts down (Pomodoro) or up (stopwatch) once a second, with a ring
// showing progress, and Pause / Resume / Stop / Skip buttons.
//
// Python passes { state: "idle" | "running" | "paused", kind, label, planned (seconds or null),
// elapsed (seconds when drawn), drawnAt (ms), compact }. The time runs in the database, so
// this only draws it: buttons send an "action" trigger ({name, at}), and when a timer reaches
// zero it sends {name: "done"} once, beeps, and Python logs it.

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

class FocusTimer {
  constructor(root) {
    this.root = root;
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (b) this.send(b.dataset.act);
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
    const el = d.elapsed + (d.state === "running" ? (Date.now() - d.drawnAt) / 1000 : 0);
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
    if (d.state === "idle") { this.root.innerHTML = ""; return; }
    const paused = d.state === "paused";
    const isBreak = d.kind === "break";
    const btn = (act, label, primary) => `<button data-act="${act}" class="${primary ? "primary" : ""}">${label}</button>`;
    this.root.innerHTML = `
      <div class="fc ${d.compact ? "compact" : ""} ${isBreak ? "break" : ""}">
        <svg class="fc-ring" viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="52" class="track"/><circle cx="60" cy="60" r="52" class="fill"/>
        </svg>
        <div class="fc-mid">
          <div class="fc-time" role="timer" aria-live="off"></div>
          <div class="fc-label"></div>
        </div>
        <div class="fc-btns">
          ${paused ? btn("resume", "Resume", true) : btn("pause", "Pause")}
          ${isBreak ? btn("skip", "Skip break", !paused) : btn("stop", d.planned == null ? "Stop and save" : "Finish now", !paused)}
          ${btn("cancel", "Cancel")}
        </div>
      </div>`;
    this.root.querySelector(".fc-label").textContent =
      `${isBreak ? "" : d.planned == null ? "Tracking · " : "Focus · "}${d.label}${paused ? " · paused" : ""}`;
    this.paint();
  }

  paint() {
    const d = this.data;
    const timeEl = this.root.querySelector(".fc-time");
    if (!timeEl) return;
    const { el, left } = this.seconds();
    timeEl.textContent = left === null ? fmt(el) : fmt(left);
    const ring = this.root.querySelector(".fill");
    const c = 2 * Math.PI * 52;
    const frac = left === null ? (el % 3600) / 3600 : Math.min(1, el / d.planned);
    ring.style.strokeDasharray = `${(frac * c).toFixed(1)} ${c.toFixed(1)}`;
  }
}

// Home's widgets glide to their new place when they move or change size ("FLIP"), instead of jumping.
// While a script run is in progress Streamlit paints several half-built layouts (rows rebuilt column by
// column, the same keyed container present twice: the new node and the stale old one). So: while the app
// is busy, every `.st-key-hw_*` node is pinned to where that widget was before the run (an inline transform,
// no motion); when the run ends, each one glides from there to its final box (200 ms ease-out). Reduced
// motion: no pins, no glides (instant moves).
// Also, in arrange mode: tapping a widget anywhere that isn't a control presses its pick-up / drop button,
// and the icon-only buttons get spoken names (aria-label) from Python.
export default function ({ data }) {
  window.__venatoHome = data || {};
  if (window.__venatoFlip) { window.__venatoFlipLabel && window.__venatoFlipLabel(); return; }
  window.__venatoFlip = true;
  const doc = document;
  const SEL = '[class*="st-key-hw_"]';
  const keyOf = (el) => (el.className.match(/st-key-(hw_[\w-]+)/) || [])[1];
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const app = () => doc.querySelector('[data-testid="stApp"]');
  const busy = () => { const s = app()?.getAttribute("data-test-script-state") || ""; return /running|rerun/i.test(s) && !/not/i.test(s); };
  const origin = () => (doc.querySelector('[data-testid="stMainBlockContainer"]') || doc.body).getBoundingClientRect();
  const flips = (el) => el.getAnimations().filter((a) => a.id === "flip");
  // a flying widget is drawn over the others with the page colour behind it (cards are see-through)
  const bg = () => getComputedStyle(app() || doc.body).backgroundColor || "#fff";
  const DUR = 200, EASE = "cubic-bezier(.2,.7,.3,1)";
  let last = new Map();     // key -> settled layout box, relative to the main block (scroll-proof)
  let hold = null;          // key -> box each widget is pinned to while a run is in progress
  const pinned = new Set(); // nodes we put an inline transform on

  const box = (el, o) => { const r = el.getBoundingClientRect(); return { x: r.left - o.left, y: r.top - o.top, w: r.width, h: r.height }; };
  // Every keyed node (duplicates included) with its on-screen box and its real layout box.
  function measure() {
    const o = origin(), out = [];
    for (const el of doc.querySelectorAll(SEL)) {
      const k = keyOf(el); if (!k) continue;
      const vis = box(el, o), running = flips(el);
      const tf = el.style.transform; if (tf) el.style.transform = "";
      const t = running.map((a) => a.currentTime); running.forEach((a) => (a.currentTime = 1e6));
      const lay = (tf || running.length) ? box(el, o) : vis;
      running.forEach((a, i) => (a.currentTime = t[i])); if (tf) el.style.transform = tf;
      out.push({ k, el, vis, lay, moving: running.length > 0 || !!tf });
    }
    return out;
  }
  const inv = (from, to) => `translate(${from.x - to.x}px,${from.y - to.y}px) scale(${from.w / to.w},${from.h / to.h})`;
  const same = (a, b) => Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) < 1 && Math.abs(a.w - b.w) < 1 && Math.abs(a.h - b.h) < 1;

  function glide(el, from, to) {
    if (reduce.matches || to.w < 2 || to.h < 2 || same(from, to)) return null;
    const a = el.animate([{ transformOrigin: "0 0", transform: inv(from, to), zIndex: 5, backgroundColor: bg() },
                          { transformOrigin: "0 0", transform: "none", zIndex: 5, backgroundColor: bg() }], { duration: DUR, easing: EASE });
    a.id = "flip";
    return a;
  }
  function unpinAll() { for (const el of pinned) { el.style.transform = ""; el.style.transformOrigin = ""; } pinned.clear(); }

  // Spoken names for the arrange bar's icon buttons ({button key: name}).
  function label() {
    const names = (window.__venatoHome || {}).labels || {};
    for (const [k, name] of Object.entries(names)) {
      for (const b of doc.querySelectorAll(`.st-key-${CSS.escape(k)} button`))
        if (b.getAttribute("aria-label") !== name) b.setAttribute("aria-label", name);
    }
  }
  window.__venatoFlipLabel = label;

  function tick() {
    label();
    const now = measure();
    if (busy()) {
      if (!hold) {                           // run just started: freeze everyone where they are on screen
        hold = new Map();
        for (const n of now) if (!hold.has(n.k)) hold.set(n.k, n.moving ? n.vis : (last.get(n.k) || n.lay));
        for (const n of now) flips(n.el).forEach((a) => a.cancel());
      }
      if (reduce.matches) return;
      for (const n of now) {                 // pin every node of a held widget (new + stale twin overlap exactly)
        const h = hold.get(n.k); if (!h || n.lay.w < 2) continue;
        n.el.style.transformOrigin = "0 0";
        n.el.style.transform = same(h, n.lay) ? "" : inv(h, n.lay);
        pinned.add(n.el);
      }
      return;
    }
    // idle: a run finished (glide from the held boxes), or something else moved (glide from the last boxes)
    const from = hold || null; hold = null;
    unpinAll();
    const fresh = measure(), seen = new Set(), glides = [];
    for (const n of fresh) {
      if (seen.has(n.k)) continue; seen.add(n.k);
      const target = from ? from.get(n.k) : last.get(n.k);       // where it was / was heading
      if (!target || same(target, n.lay)) continue;              // unchanged (a running glide just carries on)
      const p = from ? target : (n.moving ? n.vis : target);     // start from where it is on screen
      flips(n.el).forEach((a) => a.cancel());
      const a = glide(n.el, p, n.lay);
      if (a) glides.push(a.finished.catch(() => {}));
    }
    for (const n of fresh) last.set(n.k, n.lay);   // keep keys that vanished (a widget switched off, then on)
    // Everything has landed: widgets that measure themselves (the timetable) can do so again.
    if (from || glides.length) Promise.all(glides).then(() => dispatchEvent(new Event("venato:flip-settled")));
  }
  let queued = false;
  const schedule = () => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; tick(); }); } };
  new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "data-test-script-state"] });
  addEventListener("resize", () => { if (!busy()) for (const n of measure()) last.set(n.k, n.lay); });

  // Arrange mode: a tap on a widget (not on one of its controls) picks it up, or drops the one picked up there.
  doc.addEventListener("click", (e) => {
    if (!(window.__venatoHome || {}).arranging || !e.isTrusted) return;
    const CONTROLS = 'button, a, input, textarea, select, label, summary, [role="button"], [role="checkbox"], [role="switch"], [role="tab"], [contenteditable="true"]';
    const path = e.composedPath();         // (into a component's shadow DOM too)
    if (path.some((n) => n instanceof Element && n.matches(CONTROLS))) return;
    const card = path.find((n) => n instanceof Element && n.matches(SEL)), k = card && keyOf(card);
    if (!k) return;
    const pick = doc.querySelector(`.st-key-hwpick_${CSS.escape(k.slice(3))} button`);
    if (pick) pick.click();
  }, true);
  tick();
}

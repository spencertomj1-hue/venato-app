// Home's widgets glide to their new place when they move or change size ("FLIP"), instead of jumping.
// While a script run is in progress Streamlit paints several half-built layouts (rows rebuilt column by
// column, the same keyed container present twice: the new node and the stale old one). So: while the app
// is busy, every `.st-key-hw_*` node is pinned to where that widget was before the run (an inline transform,
// no motion); when the run ends, each one glides from there to its final box (200 ms ease-out). Reduced
// motion: no pins, no glides (instant moves). Only changes made on Home glide: coming back to Home from another
// page, the tiles just appear where they land. It also sizes Home's grid to the window (fit, below).
// Out of Edit Home, a click on a tile anywhere that isn't one of its controls opens its page (presses the
// tile's title button). In Edit Home, tapping a tile presses its pick-up / drop button, and dragging one onto
// another moves it there (sent to Python as "drop"). Icon-only buttons get spoken names (aria-label) from Python.
export default function ({ data, setTriggerValue }) {
  window.__venatoHome = data || {};
  window.__venatoDrop = (from, to) => setTriggerValue("drop", { from, to, nonce: Math.random().toString(36).slice(2) });
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
  let arriving = true;      // the tiles are appearing (the app opening, or a page change): no glides until they've settled

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
    if (!doc.querySelector(SEL) && !doc.querySelector(".st-key-home_head")) return;   // not on Home: nothing to name
    for (const [k, name] of Object.entries(names)) {
      for (const b of doc.querySelectorAll(`.st-key-${CSS.escape(k)} button`))
        if (b.getAttribute("aria-label") !== name) b.setAttribute("aria-label", name);
    }
  }
  window.__venatoFlipLabel = label;

  // On a laptop-sized window Home is one screen: the grid gets the height left under the header, less the room
  // the page keeps at the bottom (the pinned chat bar). Its rows share it (home.py's CSS); tiles clip.
  const GRID = ".st-key-home_grid", root = doc.documentElement;
  function fit() {
    const g = doc.querySelector(GRID);
    // (Edit Home keeps Home's rows: its "Add a tile" panel beside the grid mustn't change them)
    if (!g || !matchMedia("(min-width: 1001px)").matches || (window.__venatoHome || {}).arranging) return;
    // what sits under the grid (the page's bottom padding, which leaves room for the chat bar, and Streamlit's
    // spacing round the hidden bits after it)
    const page = doc.querySelector('[data-testid="stMainBlockContainer"]');
    const scroller = doc.querySelector('[data-testid="stMain"]');
    const r = g.getBoundingClientRect();
    const below = page ? page.getBoundingClientRect().bottom - r.bottom : (window.__venatoHome || {}).room ?? 20;
    const h = Math.floor(innerHeight - (r.top + (scroller ? scroller.scrollTop : 0)) - below);
    const was = parseFloat(root.style.getPropertyValue("--home-grid-h")) || 0;
    if (Math.abs(was - h) >= 1) root.style.setProperty("--home-grid-h", `${h}px`);
  }

  function tick() {
    label();
    fit();
    const now = measure();
    // Not on Home (another page, or Home is still being drawn): forget where the tiles were, so coming back
    // to Home doesn't glide them in from old places. Only changes made on Home glide.
    if (!now.length) { last = new Map(); hold = null; unpinAll(); arriving = true; return; }
    if (arriving) {                          // tiles drawn by a page change: put them straight where they land
      if (busy()) return;
      arriving = false;
      for (const n of now) last.set(n.k, n.lay);
      dispatchEvent(new Event("venato:flip-settled"));
      return;
    }
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
    // idle: a run on Home finished (an edit): glide from the held boxes. Anything else that moves the tiles
    // (the window, fonts loading, the grid being fitted to the window) just puts them there.
    const from = hold; hold = null;
    unpinAll();
    const fresh = measure(), seen = new Set(), glides = [];
    for (const n of fresh) {
      if (!from || seen.has(n.k)) continue; seen.add(n.k);
      const target = from.get(n.k);                              // where it was
      if (!target || same(target, n.lay)) continue;              // unchanged
      const a = glide(n.el, target, n.lay);
      if (a) glides.push(a.finished.catch(() => {}));
    }
    for (const n of fresh) last.set(n.k, n.lay);   // keep keys that vanished (a widget switched off, then on)
    // Everything has landed: widgets that measure themselves (the timetable) can do so again.
    if (from || glides.length) Promise.all(glides).then(() => dispatchEvent(new Event("venato:flip-settled")));
  }
  let queued = false;
  const schedule = () => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; tick(); }); } };
  new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "data-test-script-state"] });
  addEventListener("resize", () => { fit(); if (!busy()) for (const n of measure()) last.set(n.k, n.lay); });

  const CONTROLS = 'button, a, input, textarea, select, label, summary, [role="button"], [role="checkbox"], [role="switch"], [role="tab"], [role="radio"], [contenteditable="true"], [data-testid="stCheckbox"], [data-baseweb="select"]';
  let dragEnd = 0;         // when a drag last ended: its click is swallowed
  // A tap on a tile (not on one of its controls): Edit Home picks it up / drops the one picked up there;
  // otherwise it opens the tile's page.
  doc.addEventListener("click", (e) => {
    if (!e.isTrusted) return;
    if (Date.now() - dragEnd < 350) { e.preventDefault(); e.stopPropagation(); return; }
    const path = e.composedPath();         // (into a component's shadow DOM too)
    const card = path.find((n) => n instanceof Element && n.matches(SEL)), k = card && keyOf(card);
    if (!k) return;
    const editing = (window.__venatoHome || {}).arranging;
    const hit = path.find((n) => n instanceof Element && n.matches(CONTROLS));
    if (hit && !(editing && card.querySelector(`.st-key-hwc_${CSS.escape(k.slice(3))}`)?.contains(hit))) return;
    const id = CSS.escape(k.slice(3));
    const target = editing ? `.st-key-hwpick_${id} button` : `.st-key-go_tile_${id} button, .st-key-open_tile_${id} button`;
    const b = doc.querySelector(target);
    if (b && !b.contains(e.target)) { e.preventDefault(); b.click(); }
  }, true);

  // Edit Home: drag a tile (by anything but its buttons) onto another to move it there.
  let drag = null;
  const tileAt = (x, y) => doc.elementsFromPoint(x, y).map((el) => el.closest && el.closest(SEL)).find((el) => el && el !== drag?.el);
  doc.addEventListener("pointerdown", (e) => {
    if (!(window.__venatoHome || {}).arranging || e.button !== 0) return;
    const el = e.target.closest && e.target.closest(SEL);
    if (!el || e.target.closest("button, input, textarea, select")) return;
    drag = { el, k: keyOf(el), x: e.clientX, y: e.clientY, on: false, over: null };
  }, true);
  doc.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.on && Math.hypot(dx, dy) < 8) return;
    drag.on = true;
    drag.el.classList.add("vn-dragging");
    drag.el.style.translate = `${dx}px ${dy}px`;
    const over = tileAt(e.clientX, e.clientY);
    if (over !== drag.over) { drag.over?.classList.remove("vn-drop-target"); over?.classList.add("vn-drop-target"); drag.over = over; }
  }, true);
  const endDrag = (e) => {
    if (!drag) return;
    const d = drag; drag = null;
    d.el.classList.remove("vn-dragging"); d.el.style.translate = "";
    d.over?.classList.remove("vn-drop-target");
    if (!d.on) return;
    dragEnd = Date.now();
    const to = d.over && keyOf(d.over);
    if (e.type === "pointerup" && to && to !== d.k && window.__venatoDrop) window.__venatoDrop(d.k.slice(3), to.slice(3));
  };
  doc.addEventListener("pointerup", endDrag, true);
  doc.addEventListener("pointercancel", endDrag, true);
  tick();
}

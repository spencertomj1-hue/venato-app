// Home's widgets glide to their new place when they move or change size ("FLIP"), instead of jumping.
// While a script run is in progress Streamlit paints several half-built layouts (rows rebuilt column by
// column, the same keyed container present twice: the new node and the stale old one). So: while the app
// is busy, every `.st-key-hw_*` node is pinned to where that widget was before the run (an inline transform,
// no motion); when the run ends, each one glides from there to its final box (200 ms ease-out). Reduced
// motion: no pins, no glides (instant moves). Only changes made on Home glide: coming back to Home from another
// page, the tiles just appear where they land. It also sizes Home's grid to the window (fit, below).
// Out of Edit Home, a click on a tile anywhere that isn't one of its controls opens its page (presses the
// tile's title button). In Edit Home a tile is dragged to any cell of the grid: the others make room live and it
// lands where it's let go (its cell is sent to Python as "drop"); its bottom-right grip is dragged to resize it, snapping to the
// sizes it comes in as you go (sent as "resize"; a tap on the grip is a plain click). Icon-only buttons get spoken names (aria-label) from Python.
export default function ({ data, setTriggerValue }) {
  window.__venatoHome = data || {};
  window.__venatoDrop = (key, row, col) => setTriggerValue("drop", { key, row, col, nonce: Math.random().toString(36).slice(2) });
  window.__venatoResize = (key, size) => setTriggerValue("resize", { key, size, nonce: Math.random().toString(36).slice(2) });
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
    if (from && window.__venatoClearOrder) window.__venatoClearOrder();   // Python has drawn the dragged order
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
  const schedule = () => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; tick(); scheduleTrim(); }); } };
  new MutationObserver(schedule).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "data-test-script-state"] });
  addEventListener("resize", () => { fit(); if (!busy()) for (const n of measure()) last.set(n.k, n.lay); });

  // Tiles clip rather than grow. So no row shows half cut off, a row crossing a tile's bottom edge is hidden
  // whole (visibility only: nothing moves). "A row" is the smallest thing that crosses the edge: a button,
  // a checkbox, a line of text, a glance's row; containers are looked into (shadow roots too). The timetable
  // fits itself (timetable_component.js). Only where tiles clip (laptop-sized windows).
  const TRIMMED = new Set(), watched = new WeakSet();
  const ATOM = 'button, input, textarea, select, svg, img, canvas, p, li, label, h1, h2, h3, h4, h5, h6, ' +
    '[data-testid="stCheckbox"], [data-testid="stButton"], [data-testid="stCaptionContainer"], [role="img"], [role="progressbar"]';
  const kidsOf = (el) => [...el.children, ...(el.shadowRoot ? el.shadowRoot.children : [])]
    .filter((c) => !/^(STYLE|SCRIPT|LINK|TEMPLATE)$/.test(c.tagName))
    .flatMap((c) => (getComputedStyle(c).display === "contents" ? kidsOf(c) : [c]));
  const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  function trim() {
    for (const el of TRIMMED) el.style.visibility = el.dataset.vnTrimWas || "";
    for (const el of TRIMMED) delete el.dataset.vnTrimWas;
    TRIMMED.clear();
    if (!matchMedia("(min-width: 1001px)").matches || busy()) return;
    for (const c of doc.querySelectorAll('[class*="st-key-hwc_"]')) {
      if (c.matches(".st-key-hwc_timetable_today")) continue;
      const tile = c.closest(SEL);
      if (!tile || tile.style.transform || flips(tile).length) continue;
      const clip = c.parentElement?.dataset.testid === "stLayoutWrapper" ? c.parentElement : c;
      const edge = clip.getBoundingClientRect().bottom + 0.5;
      const visit = (el) => {
        if (el.shadowRoot && !watched.has(el.shadowRoot)) {
          watched.add(el.shadowRoot);
          new MutationObserver(scheduleTrim).observe(el.shadowRoot, { childList: true, subtree: true });
        }
        const r = el.getBoundingClientRect();
        const below = r.height && r.top >= edge - 0.5;     // cut off already (hidden too: a tick may stick up)
        const kids = kidsOf(el);
        const crosses = r.height && r.bottom > edge;
        if (below || (crosses && (el.matches(ATOM) || ownText(el) || !kids.length))) {   // a row: hide it whole
          el.dataset.vnTrimWas = el.style.visibility; el.style.visibility = "hidden"; TRIMMED.add(el); return;
        }
        kids.forEach(visit);   // fits: a child may still stick out (a positioned tick); crossing: find its rows
      };
      kidsOf(c).forEach(visit);
    }
  }
  let trimTimer = 0;
  function scheduleTrim() { clearTimeout(trimTimer); trimTimer = setTimeout(() => requestAnimationFrame(trim), 60); }
  addEventListener("venato:flip-settled", scheduleTrim);
  addEventListener("resize", scheduleTrim);

  const CONTROLS = 'button, a, input, textarea, select, label, summary, [role="button"], [role="checkbox"], [role="switch"], [role="tab"], [role="radio"], [contenteditable="true"], [data-testid="stCheckbox"], [data-baseweb="select"]';
  let dragEnd = 0;         // when a drag last ended: its click is swallowed
  // A tap on a tile (not on one of its controls) opens its page; in Edit Home it does nothing (tiles are dragged).
  doc.addEventListener("click", (e) => {
    if (!e.isTrusted) return;
    if (Date.now() - dragEnd < 350) { e.preventDefault(); e.stopPropagation(); return; }
    if ((window.__venatoHome || {}).arranging) return;
    const path = e.composedPath();         // (into a component's shadow DOM too)
    const card = path.find((n) => n instanceof Element && n.matches(SEL)), k = card && keyOf(card);
    if (!k || path.find((n) => n instanceof Element && n.matches(CONTROLS))) return;
    const id = CSS.escape(k.slice(3));
    const b = doc.querySelector(`.st-key-go_tile_${id} button, .st-key-open_tile_${id} button`);
    if (b && !b.contains(e.target)) { e.preventDefault(); b.click(); }
  }, true);

  // Edit Home: drag a tile (by anything but its buttons) anywhere on the grid. Its top-left corner snaps to the
  // cell under it; the tiles it would land on swap into the place it left when they fit there, else go to the
  // nearest free place (the same rules as home_layout.move_to, so what you see is what's saved). The others glide
  // there live and the cell it'll land in is outlined. Let go: it settles there and {key, row, col} goes to
  // Python as "drop". The live places stay until Python has redrawn the grid, then they're cleared (tick, above).
  // Its bottom-right grip resizes it the same way (home_layout.resize). Four columns only: narrower, tiles flow.
  const SLIDE = 180;
  const tiles = () => [...doc.querySelectorAll(`.st-key-home_grid > div > ${SEL}`)];
  const itemOf = (t) => t.parentElement;                     // the grid item each tile sits in
  const slides = (el) => el.getAnimations().filter((a) => a.id === "slide");
  let drag = null, sizing = null, placed = false, clearTimer = 0;
  function clearOrder() {
    clearTimeout(clearTimer);
    if (drag || sizing) return;
    for (const t of tiles()) itemOf(t).classList.remove("vn-slot");
    if (!placed) return;
    placed = false;
    for (const t of tiles()) { itemOf(t).style.gridColumn = ""; itemOf(t).style.gridRow = ""; }
  }
  window.__venatoClearOrder = clearOrder;
  const rect = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; };

  // --- the layout rules (a copy of home_layout.py's place / move_to / resize) ---
  // A layout here: {key: {at: [row, col], w, h, size}}, every tile placed.
  const H = () => window.__venatoHome || {};
  const COLS = () => H().columns || 4;
  const spanOf = (k, size) => { const z = ((H().sizes || {})[k] || []).find((s) => s[0] === size); return z ? [z[1], z[2]] : null; };
  function current() {
    const out = {}, at = H().at || {}, size = H().size || {};
    for (const k of Object.keys(at)) {
      const sp = spanOf(k, size[k]) || [1, 1];
      out[k] = { at: [...at[k]], w: Math.min(sp[0], COLS()), h: sp[1], size: size[k] };
    }
    return out;
  }
  const cellsOf = (r, c, w, h) => { const s = []; for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) s.push(`${r + y},${c + x}`); return s; };
  const areaOf = (t, at = t.at) => cellsOf(at[0], at[1], t.w, t.h);
  const hits = (a, taken) => a.some((x) => taken.has(x));
  const reading = (L) => Object.keys(L).sort((a, b) => L[a].at[0] - L[b].at[0] || L[a].at[1] - L[b].at[1]);
  function settle(L, key) {                    // what key now overlaps goes to the nearest free place
    const me = L[key], mine = new Set(areaOf(me));
    const hit = Object.keys(L).filter((k) => k !== key && hits(areaOf(L[k]), mine));
    const taken = new Set(mine);
    for (const k of Object.keys(L)) if (k !== key && !hit.includes(k)) areaOf(L[k]).forEach((x) => taken.add(x));
    let bottom = Math.max(0, ...[...taken].map((x) => +x.split(",")[0] + 1));
    for (const k of reading(L).filter((k) => hit.includes(k))) {
      const t = L[k], [r0, c0] = t.at;
      let best = null, bd = Infinity;
      for (let r = 0; r <= bottom + t.h; r++) for (let c = 0; c <= COLS() - t.w; c++) {
        if (hits(cellsOf(r, c, t.w, t.h), taken)) continue;
        const d = Math.abs(r - r0) + Math.abs(c - c0);
        if (d < bd) { bd = d; best = [r, c]; }       // ties: the first in reading order, as Python's min
      }
      t.at = best;
      areaOf(t).forEach((x) => taken.add(x));
      bottom = Math.max(bottom, best[0] + t.h);
    }
    return L;
  }
  function moveTo(L0, key, row, col) {
    const L = JSON.parse(JSON.stringify(L0)), me = L[key];
    row = Math.max(0, row); col = Math.min(Math.max(0, col), COLS() - me.w);
    const old = me.at;
    if (old[0] === row && old[1] === col) return L;
    me.at = [row, col];
    const mine = new Set(areaOf(me));
    const hit = Object.keys(L).filter((k) => k !== key && hits(areaOf(L[k]), mine));
    const dy = old[0] - row, dx = old[1] - col;
    const moved = Object.fromEntries(hit.map((k) => [k, [L[k].at[0] + dy, L[k].at[1] + dx]]));
    if (hit.length && hit.every((k) => moved[k][0] >= 0 && moved[k][1] >= 0 && moved[k][1] <= COLS() - L[k].w)) {
      const taken = new Set(mine);
      let ok = true;
      for (const k of reading(L0)) {           // the same order Python checks them in (its reading order)
        if (k === key) continue;
        const a = areaOf(L[k], moved[k] || L[k].at);
        if (hits(a, taken)) { ok = false; break; }
        a.forEach((x) => taken.add(x));
      }
      if (ok) { for (const k of hit) L[k].at = moved[k]; return L; }
    }
    return settle(L, key);
  }
  function resizeTo(L0, key, size) {
    const L = JSON.parse(JSON.stringify(L0)), me = L[key], sp = spanOf(key, size);
    me.w = Math.min(sp[0], COLS()); me.h = sp[1]; me.size = size;
    me.at[1] = Math.min(me.at[1], COLS() - me.w);
    return settle(L, key);
  }

  // Show a layout: each tile's grid item put in its place, the others gliding there from where they are.
  function show(L, still) {
    const all = tiles(), seen = new Map(all.map((t) => [t, rect(t)]));
    for (const t of all) {
      const p = L[keyOf(t).slice(3)]; if (!p) continue;
      itemOf(t).style.gridColumn = `${p.at[1] + 1} / span ${p.w}`;
      itemOf(t).style.gridRow = `${p.at[0] + 1} / span ${p.h}`;
    }
    placed = true;
    if (reduce.matches) return;
    for (const t of all) {
      if (t === still) continue;
      const a = seen.get(t), b = rect(t);
      if (Math.abs(a.l - b.l) < 1 && Math.abs(a.t - b.t) < 1) continue;
      slides(t).forEach((x) => x.cancel());
      t.animate([{ transform: `translate(${a.l - b.l}px,${a.t - b.t}px)` }, { transform: "none" }],
                { duration: SLIDE, easing: EASE }).id = "slide";
    }
  }
  // The grid's measurements: columns, a column's width, a row's height, the gap, its top-left corner.
  function grid() {
    const g = doc.querySelector(GRID), cs = g && getComputedStyle(g);
    if (!cs) return null;
    const cols = cs.gridTemplateColumns.split(" ").filter(Boolean), rows = cs.gridTemplateRows.split(" ").filter(Boolean);
    const r = g.getBoundingClientRect();
    return { cols: cols.length, colW: parseFloat(cols[0]) || 0, rowH: parseFloat(rows[0]) || 0,
             gap: parseFloat(cs.columnGap) || 0, rowGap: parseFloat(cs.rowGap) || 0, l: r.left, t: r.top };
  }
  function follow(e) {                                        // the dragged tile under the pointer
    drag.el.style.translate = "";
    const home = rect(drag.el);
    drag.el.style.translate = `${e.clientX - drag.gx - home.l}px ${e.clientY - drag.gy - home.t}px`;
  }

  doc.addEventListener("pointerdown", (e) => {
    if (!H().arranging || e.button !== 0 || busy()) return;
    const el = e.target.closest && e.target.closest(SEL);
    if (!el || e.target.closest("button, input, textarea, select, a")) return;
    const r = el.getBoundingClientRect();
    drag = { el, k: keyOf(el), x: e.clientX, y: e.clientY, gx: e.clientX - r.left, gy: e.clientY - r.top, on: false };
  }, true);
  doc.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.on) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
      const g = grid();
      if (!g || g.cols < COLS() || !current()[drag.k.slice(3)]) { drag = null; return; }   // narrow: tiles flow
      drag.on = true;
      clearTimeout(clearTimer);
      drag.g = g; drag.start = current(); drag.layout = drag.start; drag.cell = drag.start[drag.k.slice(3)].at.join();
      drag.el.classList.add("vn-dragging");
      itemOf(drag.el).classList.add("vn-slot");
      root.classList.add("vn-drag-on");
    }
    e.preventDefault();
    // the cell under the tile's top-left corner (rounded to the nearest)
    const { g } = drag, k = drag.k.slice(3);
    const col = Math.round((e.clientX - drag.gx - g.l) / (g.colW + g.gap));
    const row = Math.round((e.clientY - drag.gy - g.t) / (g.rowH + g.rowGap));
    const rowMax = Math.max(0, ...Object.values(drag.start).map((p) => p.at[0] + p.h));   // up to the spare row
    const at = [Math.min(Math.max(0, row), rowMax), col];
    const L = moveTo(drag.start, k, at[0], at[1]);
    if (L[k].at.join() !== drag.cell) { drag.cell = L[k].at.join(); drag.layout = L; show(L, drag.el); }
    follow(e);
  }, true);
  function endDrag(e) {
    if (!drag) return;
    const d = drag; drag = null;
    root.classList.remove("vn-drag-on");
    if (!d.on) return;
    dragEnd = Date.now();
    const k = d.k.slice(3), cancelled = e.type !== "pointerup";
    const L = cancelled ? d.start : d.layout;
    itemOf(d.el).classList.remove("vn-slot");
    // settle into its cell from where it was let go
    const was = rect(d.el);
    d.el.style.translate = "";
    d.el.classList.remove("vn-dragging");
    show(L, d.el);
    const now = rect(d.el);
    if (!reduce.matches && (Math.abs(was.l - now.l) > 1 || Math.abs(was.t - now.t) > 1)) {
      d.el.animate([{ translate: `${was.l - now.l}px ${was.t - now.t}px`, zIndex: 30 }, { translate: "0px 0px", zIndex: 30 }],
                   { duration: SLIDE, easing: EASE }).id = "slide";
    }
    const to = L[k].at;
    if (!cancelled && to.join() !== d.start[k].at.join() && window.__venatoDrop) {
      for (const n of measure()) last.set(n.k, n.lay);        // the run glides from here, not from before the drag
      window.__venatoDrop(k, to[0], to[1]);
      clearTimer = setTimeout(() => { if (!busy()) clearOrder(); }, 5000);   // in case the run is never seen
    } else clearOrder();
  }
  doc.addEventListener("pointerup", endDrag, true);
  doc.addEventListener("pointercancel", endDrag, true);
  doc.addEventListener("keydown", (e) => { if (drag?.on && e.key === "Escape") { e.preventDefault(); e.stopPropagation(); endDrag(e); } }, true);

  // Edit Home: the grip in a tile's bottom-right corner. Dragged, the tile takes the size (of the ones it comes
  // in) nearest to where the pointer is, the others making room live; let go and it's saved. Under 5px of
  // movement it's a tap: the button's own click (the next size) goes through.
  const GRIP = '[class*="st-key-hwsz_"]';
  doc.addEventListener("pointerdown", (e) => {
    if (!H().arranging || e.button !== 0 || busy() || !e.target.closest) return;
    const grip = e.target.closest(GRIP), el = grip && grip.closest(SEL), k = el && keyOf(el);
    const sizes = k && (H().sizes || {})[k.slice(3)];
    if (!sizes || sizes.length < 2) return;
    const g = grid(); if (!g || g.cols < COLS()) return;     // narrow: tiles flow (the tap still steps the size)
    const start = current(), me = start[k.slice(3)]; if (!me) return;
    const r = el.getBoundingClientRect();
    sizing = { el, k, x: e.clientX, y: e.clientY, l: r.left, t: r.top, g, sizes, start, layout: start,
               from: me.size, now: me.size, on: false };
  }, true);
  doc.addEventListener("pointermove", (e) => {
    if (!sizing) return;
    if (!sizing.on) {
      if (Math.hypot(e.clientX - sizing.x, e.clientY - sizing.y) < 5) return;
      sizing.on = true;
      clearTimeout(clearTimer);
      sizing.el.classList.add("vn-resizing");
      root.classList.add("vn-resize-on");
    }
    e.preventDefault();
    const { g } = sizing;
    // how many columns and rows the pointer reaches (fractional), from the tile's top-left corner
    const w = (e.clientX - sizing.l + g.gap / 2) / (g.colW + g.gap), h = (e.clientY - sizing.t + g.rowGap / 2) / (g.rowH + g.rowGap);
    let best = null, bd = Infinity;
    for (const z of sizing.sizes) {
      if (z[1] > g.cols) continue;
      const d = (z[1] - w) ** 2 + (z[2] - h) ** 2;
      if (d < bd) { bd = d; best = z; }
    }
    if (best && best[0] !== sizing.now) {
      sizing.now = best[0];
      sizing.layout = resizeTo(sizing.start, sizing.k.slice(3), best[0]);
      show(sizing.layout);
    }
  }, true);
  function endResize(e) {
    if (!sizing) return;
    const s = sizing; sizing = null;
    root.classList.remove("vn-resize-on");
    if (!s.on) return;                                       // a tap: the button's click steps the size
    dragEnd = Date.now();                                     // (and its click is swallowed)
    s.el.classList.remove("vn-resizing");
    if (e.type === "pointerup" && s.now !== s.from && window.__venatoResize) {
      for (const n of measure()) last.set(n.k, n.lay);      // the run glides from here, not from before the drag
      window.__venatoResize(s.k.slice(3), s.now);
      clearTimer = setTimeout(() => { if (!busy()) clearOrder(); }, 5000);   // in case the run is never seen
    } else { show(s.start); clearOrder(); }                  // cancelled, or back where it started
  }
  doc.addEventListener("pointerup", endResize, true);
  doc.addEventListener("pointercancel", endResize, true);
  doc.addEventListener("keydown", (e) => {
    if (sizing?.on && e.key === "Escape") { e.preventDefault(); e.stopPropagation(); endResize(e); }
  }, true);
  tick();
}

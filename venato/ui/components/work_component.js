// Start Working: the user's own areas (sections, each in its colour) with their bars, and a
// money pot below. Plain like Home; nothing moves. With three areas the first takes the left
// third and the other two share the right two thirds; otherwise they sit side by side.
//
// Python passes { level, reward, balance, wallet, spent, pots: [{key, name}], levelled, acked,
//                 panels: [{id, name, colour, tracks: [track]}],
//                 bars: {track: {name, verb, count, target, total, weekly}} }.
// Taps and spends show straight away and go to Python as ops (pending until listed in `acked`):
//   {opId, kind: "tap", track, delta}   {opId, kind: "spend", amount, pot, note}

const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "£" + (Math.round(n * 100) / 100).toFixed(n % 1 ? 2 : 0);

let POTS = [];
const potName = (key) => (POTS.find((p) => p.key === key) || { name: key }).name;

const instances = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".sw-root");
  let game = instances.get(root);
  if (!game) {
    game = new Game(root);
    instances.set(root, game);
  }
  game.send = (ops) => setTriggerValue("ops", ops);
  game.update(data);
  return () => {};
}

class Game {
  constructor(root) {
    this.root = root;
    this.pending = [];        // ops not yet acknowledged
    this.sent = [];           // every op sent this session (the trigger value is the whole list)
    this.built = null;        // what the skeleton was drawn for (level and targets)
    this.pot = null;          // the pot picked for spending (a key)
  }

  update(data) {
    const acked = new Set(data.acked || []);
    this.pending = this.pending.filter((op) => !acked.has(op.opId));
    const first = !this.data;
    const levelChanged = this.data && data.level !== this.data.level;
    this.data = data;
    POTS = data.pots || [];
    if (!POTS.some((p) => p.key === this.pot)) this.pot = POTS.length ? POTS[0].key : null;
    const shape = JSON.stringify([data.level, data.panels, Object.values(data.bars).map((b) => [b.name, b.target])]);
    if (this.built !== shape) { this.built = shape; this.build(); }
    this.paint();
    if (data.levelled && (levelChanged || first) && this.celebrated !== data.levelled) {
      this.celebrated = data.levelled;
      this.celebrate(data.levelled);
    }
  }

  // Server data with pending ops applied on top.
  view() {
    const counts = {};
    for (const [tr, b] of Object.entries(this.data.bars)) counts[tr] = b.count;
    let balance = this.data.balance;
    for (const op of this.pending) {
      if (op.kind === "tap") counts[op.track] = Math.max(0, counts[op.track] + op.delta);
      else if (op.kind === "spend") balance -= op.amount;
    }
    return { counts, balance };
  }

  commit(op) {
    op.opId = uid();
    this.pending.push(op);
    this.sent.push(op);
    this.sent = this.sent.slice(-200);
    this.send(this.sent);
    this.paint();
  }

  // ---------- Drawing ----------

  bar(tr, colour) {
    const b = this.data.bars[tr];
    return `
      <div class="sw-bar" data-track="${tr}">
        <div class="sw-name">${esc(b.name)}${b.weekly ? `<span class="sw-tag">this week</span>` : ""}</div>
        <div class="sw-tube">
          <div class="sw-ticks"><span style="bottom:25%"></span><span style="bottom:50%"></span><span style="bottom:75%"></span></div>
          <div class="sw-fill"></div>
          <div class="sw-count"><b class="sw-n">0</b><span class="sw-of">/ ${b.target}</span><em class="sw-pct">0%</em></div>
          <div class="sw-done">✓ Full</div>
        </div>
        <div class="sw-actions">
          <button class="sw-minus" data-track="${tr}" aria-label="One fewer">−</button>
          <button class="sw-plus" data-track="${tr}">+1 · ${esc(b.verb)}</button>
        </div>
        <div class="sw-total">${b.weekly ? "starts again Monday · " : ""}all time: <b class="sw-all">0</b></div>
      </div>`;
  }

  build() {
    const d = this.data;
    const levelBars = d.panels.flatMap((p) => p.tracks).filter((tr) => !d.bars[tr].weekly).length;
    const weekly = d.panels.flatMap((p) => p.tracks).some((tr) => d.bars[tr].weekly);
    const panels = d.panels.map((p) => `
      <section class="sw-panel sw-${p.id}" style="--c:${esc(p.colour)}">
        <h2><i></i>${esc(p.name)}</h2>
        <div class="sw-bars">${p.tracks.map((tr) => this.bar(tr, p.colour)).join("")}</div>
      </section>`).join("");
    this.root.innerHTML = `
      <div class="sw">
        <header class="sw-head">
          <div class="sw-level"><span>Level</span><b>${d.level}</b></div>
          <div class="sw-title"><h1>Start Working</h1>
            <p>${levelBars ? `Fill all ${levelBars} level bar${levelBars === 1 ? "" : "s"} to bank <b>${money(d.reward)}</b>. The targets grow every level` : "No level bars yet"}${weekly ? "; weekly bars start again every Monday and don't count towards the level" : ""}.</p></div>
          <div class="sw-pot"><b class="sw-bal">£0</b><small>in the pot</small></div>
        </header>
        <div class="sw-grid n${Math.min(d.panels.length, 5)}">${panels}</div>
        <section class="sw-wallet">
          <div class="sw-spend">
            <h3>Spend the pot</h3>
            <div class="sw-pots">${(d.pots || []).map((p) => `<button data-pot="${esc(p.key)}">${esc(p.name)}</button>`).join("")
              || `<em class="sw-none">Add what the pot is spent on in Set up.</em>`}</div>
            <div class="sw-row"><span class="sw-cur">£</span><input class="sw-amt" type="number" min="0" step="0.5" value="${d.reward}">
              <input class="sw-note" placeholder="On what? (optional)">
              <button class="sw-go">Spend</button></div>
            <div class="sw-msg"></div>
          </div>
          <div class="sw-ledger"><h3>Pot history</h3><ul class="sw-list"></ul>
            <p class="sw-split"></p></div>
        </section>
        <div class="sw-party"><div class="sw-party-in"><div class="sw-big">Level <b class="sw-lv"></b> done</div>
          <div class="sw-plus5">+${money(d.reward)}</div><p>into the pot. Level <b class="sw-next"></b> starts now.</p>
          <small>Click to close</small></div></div>
      </div>`;
    this.root.querySelectorAll(".sw-plus").forEach((b) => b.addEventListener("click", () => {
      this.commit({ kind: "tap", track: b.dataset.track, delta: 1 });
    }));
    this.root.querySelectorAll(".sw-minus").forEach((b) => b.addEventListener("click", () => {
      if (this.view().counts[b.dataset.track] > 0) this.commit({ kind: "tap", track: b.dataset.track, delta: -1 });
    }));
    this.root.querySelectorAll(".sw-pots button").forEach((b) => b.addEventListener("click", () => {
      this.pot = b.dataset.pot;
      this.paint();
    }));
    this.root.querySelector(".sw-go").addEventListener("click", () => this.spend());
    this.root.querySelector(".sw-note").addEventListener("keydown", (e) => { if (e.key === "Enter") this.spend(); });
    this.root.querySelector(".sw-party").addEventListener("click", () => this.root.querySelector(".sw-party").classList.remove("on"));
  }

  paint() {
    const d = this.data, v = this.view();
    for (const [tr, b] of Object.entries(d.bars)) {
      const el = this.root.querySelector(`.sw-bar[data-track="${tr}"]`);
      if (!el) continue;
      const pct = Math.min(100, (100 * v.counts[tr]) / b.target);
      el.querySelector(".sw-fill").style.height = `${pct}%`;
      el.querySelector(".sw-n").textContent = v.counts[tr];
      el.querySelector(".sw-pct").textContent = `${Math.floor(pct)}%`;
      el.querySelector(".sw-all").textContent = b.total + (v.counts[tr] - b.count);
      el.classList.toggle("full", pct >= 100);
    }
    this.root.querySelector(".sw-bal").textContent = money(v.balance);
    this.root.querySelectorAll(".sw-pots button").forEach((b) => b.classList.toggle("on", b.dataset.pot === this.pot));
    const list = this.root.querySelector(".sw-list");
    list.innerHTML = d.wallet.length ? d.wallet.map((w) => {
      const day = new Date(w.at).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
      const what = w.kind === "earned" ? w.note : `${potName(w.kind)}${w.note ? ": " + w.note : ""}`;
      return `<li class="${w.amount > 0 ? "in" : "out"}"><span>${day}</span><em>${esc(what)}</em><b>${w.amount > 0 ? "+" : "−"}${money(Math.abs(w.amount))}</b></li>`;
    }).join("") : `<li class="none">Nothing yet. Fill the bars to earn your first ${money(d.reward)}.</li>`;
    this.root.querySelector(".sw-split").textContent =
      (d.pots || []).length ? "Spent so far: " + d.pots.map((p) => `${money(d.spent[p.key] || 0)} on ${p.name}`).join(" · ") : "";
  }

  spend() {
    const amt = Math.round(parseFloat(this.root.querySelector(".sw-amt").value) * 100) / 100;
    const msg = this.root.querySelector(".sw-msg");
    const bal = this.view().balance;
    if (!(amt > 0)) { msg.textContent = "Enter an amount."; return; }
    if (!this.pot) { msg.textContent = "Add what the pot is spent on in Set up first."; return; }
    if (amt > bal + 1e-9) { msg.textContent = `Only ${money(bal)} in the pot. Fill more bars!`; return; }
    const note = this.root.querySelector(".sw-note").value.trim();
    this.commit({ kind: "spend", amount: amt, pot: this.pot, note });
    this.root.querySelector(".sw-note").value = "";
    msg.textContent = `Spent ${money(amt)} on ${potName(this.pot)}.`;
  }

  celebrate(level) {
    const party = this.root.querySelector(".sw-party");
    party.querySelector(".sw-lv").textContent = level;
    party.querySelector(".sw-next").textContent = level + 1;
    party.classList.add("on");
  }
}

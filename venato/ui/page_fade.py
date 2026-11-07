"""
A soft transition between pages (and focus rings only for keyboard users): clicking another page in the sidebar fades the main area
to the page colour, and fades the new page in once Streamlit has finished drawing it
(instead of the old page's pieces being swapped out one by one in front of you).
"""

import streamlit as st

_fade = st.components.v2.component(
    "venato_page_fade",
    html="<span hidden></span>",
    js="""
export default function () {
  if (window.__venatoFade) return;
  window.__venatoFade = true;
  const doc = document;
  // Focus rings only for keyboard users: Tab turns them on, a click turns them off (Safari focuses
  // things on a click, so a later key press, e.g. Backspace, drew a grey ring). See appearance.py.
  doc.addEventListener("keydown", (e) => { if (e.key === "Tab") doc.documentElement.classList.add("venato-kbd"); }, true);
  doc.addEventListener("pointerdown", () => doc.documentElement.classList.remove("venato-kbd"), true);
  const veil = doc.createElement("div");
  veil.id = "venato-veil";
  veil.setAttribute("aria-hidden", "true");
  Object.assign(veil.style, { position: "fixed", top: "0", right: "0", bottom: "0", left: "0", zIndex: "999990",
    opacity: "0", pointerEvents: "none", transition: "opacity 110ms ease-out" });
  doc.body.appendChild(veil);
  let shown = false, sawRun = false, safety = null;

  const app = () => doc.querySelector('[data-testid="stApp"]');
  const state = () => app()?.getAttribute("data-test-script-state") || "";
  const busy = () => /running|rerun/i.test(state()) && !/not/i.test(state());

  function show() {
    if (shown) return;
    const sb = doc.querySelector('[data-testid="stSidebar"]');
    const r = sb && sb.getBoundingClientRect();
    veil.style.left = (r && r.width > 40 && r.right > 0 ? r.right : 0) + "px";   // keep the sidebar visible
    veil.style.background = getComputedStyle(app() || doc.body).backgroundColor || "#fff";
    veil.style.transition = "opacity 110ms ease-out";
    veil.style.pointerEvents = "auto";
    veil.style.opacity = "1";
    shown = true; sawRun = busy();
    clearTimeout(safety);
    safety = setTimeout(hide, 6000);            // never leave it up if something goes wrong
    setTimeout(() => { if (shown && !sawRun && !busy()) hide(); }, 1500);   // pressed but didn't change page
  }
  function hide() {
    if (!shown) return;
    shown = false;
    clearTimeout(safety);
    // a moment for the page's own components to draw, then fade the new page in
    setTimeout(() => {
      veil.style.transition = "opacity 200ms ease-in";
      veil.style.opacity = "0";
      veil.style.pointerEvents = "none";
    }, 120);
  }

  // Start on the press (earlier than the click), for a page that isn't the current one.
  doc.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const opt = e.target.closest && e.target.closest('[data-testid="stSidebar"] [data-testid="stRadioOption"]');
    if (opt && opt.getAttribute("data-selected") !== "true" && !opt.querySelector("input:checked")) show();
  }, true);
  // Keyboard (arrow keys on the page list) changes the radio without a press.
  doc.addEventListener("change", (e) => {
    if (e.target.closest && e.target.closest('[data-testid="stSidebar"] [data-testid="stRadio"]')) show();
  }, true);

  // Hide once the rerun has started and then finished.
  new MutationObserver(() => {
    if (!shown) return;
    if (busy()) { sawRun = true; return; }
    if (sawRun) hide();
  }).observe(doc.body, { attributes: true, subtree: true, attributeFilter: ["data-test-script-state"] });
}
""",
)


def render():
    _fade(key="page_fade")

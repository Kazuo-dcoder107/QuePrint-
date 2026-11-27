/* Shared helpers: DOM builder, API client, formatting, dialogs, polling. No innerHTML anywhere (XSS-safe). */
const $ = (s, r = document) => r.querySelector(s);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
/** append that accepts arrays, strings and nulls */
const put = (el, ...kids) => { for (const k of kids.flat(Infinity)) { if (k == null || k === false) continue; el.append(k.nodeType ? k : document.createTextNode(String(k))); } return el; };
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

const Auth = {
  get token() { return localStorage.getItem("qp_token"); },
  get user() { try { return JSON.parse(localStorage.getItem("qp_user")); } catch { return null; } },
  set(token, user) { localStorage.setItem("qp_token", token); localStorage.setItem("qp_user", JSON.stringify(user)); },
  clear() { localStorage.removeItem("qp_token"); localStorage.removeItem("qp_user"); },
};

async function api(path, { method = "GET", body, form, blob } = {}) {
  const headers = {};
  if (Auth.token) headers.Authorization = "Bearer " + Auth.token;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch("/api" + path, { method, headers, body: payload }); }
  catch { throw new Error("Cannot reach the server. Check your connection and try again."); }
  if (res.status === 401 && Auth.token) { Auth.clear(); window.dispatchEvent(new Event("qp:logout")); }
  if (!res.ok) {
    let msg = "Something went wrong (" + res.status + ").";
    try {
      const d = await res.json();
      msg = typeof d.detail === "string" ? d.detail : (d.detail?.[0]?.msg || msg).replace(/^Value error, /, "");
    } catch {}
    throw new Error(msg);
  }
  return blob ? res.blob() : res.json();
}

const BIND = { none: "No binding", staple: "Staple", spiral: "Spiral binding", clear_cover: "Clear cover" };
const bindLabel = (k) => BIND[k] || (k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "));
const STATUS = { draft: "Draft", pending: "Pending", processing: "Processing", ready: "Ready for pickup", completed: "Completed", cancelled: "Cancelled", failed: "Needs attention" };
const badge = (s, label) => h("span", { class: "badge s-" + s }, label || STATUS[s] || s);
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "n/a";
let CURRENCY = "PHP";
const money = (n) => n == null ? "n/a" : new Intl.NumberFormat("en-PH", { style: "currency", currency: CURRENCY }).format(n);
const setCurrency = (c) => { CURRENCY = c || "PHP"; };
const specLine = (j) => [j.paper_size, j.color_mode === "color" ? "color" : "B&W", j.sides === "double" ? "back-to-back" : "single-sided",
  j.copies + (j.copies === 1 ? " copy" : " copies"), j.binding !== "none" ? bindLabel(j.binding).toLowerCase() : null].filter(Boolean).join(", ");
const queueText = (j) => j.queue_position === 0 ? "Printing now" : j.queue_position ? `#${j.queue_position} in the queue` : "";

function toast(msg, err = false) {
  let box = $("#toasts"); if (!box) { box = h("div", { id: "toasts", role: "status", "aria-live": "polite" }); document.body.append(box); }
  const t = h("div", { class: "toast" + (err ? " err" : "") }, msg); box.append(t);
  setTimeout(() => t.remove(), err ? 6000 : 3500);
}

/** Modal dialog. Resolves true when the primary button is pressed. */
function modal({ title, body, ok = "OK", cancel = "Cancel", danger = false, wide = false }) {
  return new Promise((resolve) => {
    const dlg = h("dialog", { "aria-label": title });
    const done = (v) => { dlg.close(); dlg.remove(); resolve(v); };
    dlg.append(h("div", { class: "dlg" }, h("h2", null, title), body,
      h("footer", null,
        cancel && h("button", { class: "btn", type: "button", onclick: () => done(false) }, cancel),
        ok && h("button", { class: "btn " + (danger ? "danger" : "primary"), type: "button", onclick: () => done(true) }, ok))));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
    document.body.append(dlg); dlg.showModal();
  });
}

/** Run fn now and every `ms` while the tab is visible. Returns a stop function. */
function poll(fn, ms) {
  let t, dead = false;
  const tick = async () => { if (dead) return; if (!document.hidden) { try { await fn(); } catch {} } if (!dead) t = setTimeout(tick, ms); };
  tick();
  return () => { dead = true; clearTimeout(t); };
}

function busy(btn, label, fn) {
  const old = btn.textContent; btn.disabled = true; btn.textContent = label;
  return Promise.resolve(fn()).finally(() => { btn.disabled = false; btn.textContent = old; });
}
const field = (label, input, hint) => h("div", null, h("label", { for: input.id }, label), input, hint && h("div", { class: "hint" }, hint));
const toLocalInput = (d) => { const p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
const logo = (name) => h("a", { class: "logo", href: "#" }, h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")), name);

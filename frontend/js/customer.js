(() => {
  const app = $("#app"), top = $("#top");
  const S = { cfg: null, user: Auth.user, stops: [], unread: 0, seen: new Set(), notes: [], panel: false };
  const W = { job: null, done: null, opts: null, est: null };   // new-print wizard state
  const TABS = [["new", "New print"], ["orders", "My orders"], ["track", "Track an order"], ["queue", "Live queue"]];
  const route = () => (location.hash.slice(1) || "new");

  /* ---------- shell ---------- */
  function drawTop() {
    clear(top);
    const r = route();
    const bell = S.user && h("div", { class: "rel bell" },
      h("button", { class: "btn sm", "aria-label": "Notifications", onclick: togglePanel }, "Alerts", S.unread ? h("b", null, S.unread) : null),
      S.panel && h("div", { class: "panel" }, h("ul", null, S.notes.length ? S.notes.map((n) => h("li", { class: n.is_read ? "" : "unread" }, h("div", null, n.message), h("div", { class: "small muted" }, fmtDate(n.created_at)))) : h("li", { class: "muted" }, "No notifications yet."))));
    top.append(logo(S.cfg?.shop_name || "QuePrint"),
      h("nav", { class: "nav", "aria-label": "Main" }, TABS.map(([k, t]) => h("a", { href: "#" + k, class: r === k ? "on" : "", "aria-current": r === k ? "page" : null }, t))),
      h("div", { class: "userbox" }, bell, S.user
        ? [h("span", { class: "small muted" }, S.user.full_name), h("button", { class: "btn sm", onclick: logout }, "Sign out")]
        : h("a", { class: "btn sm", href: "#new" }, "Sign in")));
  }
  function logout() { Auth.clear(); S.user = null; S.notes = []; S.unread = 0; Object.assign(W, { job: null, done: null }); render(); }
  window.addEventListener("qp:logout", () => { S.user = null; render(); });
  async function togglePanel() {
    S.panel = !S.panel; drawTop();
    if (S.panel && S.unread) { try { await api("/notifications/read", { method: "POST" }); S.unread = 0; } catch {} }
  }

  async function pullNotes() {
    if (!S.user) return;
    const rows = await api("/notifications");
    const fresh = rows.filter((n) => !n.is_read && !S.seen.has(n.id));
    if (S.seen.size) fresh.forEach((n) => toast(n.message));
    rows.forEach((n) => S.seen.add(n.id));
    const unread = rows.filter((n) => !n.is_read).length;
    const changed = unread !== S.unread || rows.length !== S.notes.length;
    S.notes = rows; S.unread = S.panel ? 0 : unread;
    if (changed) drawTop();
  }

  function render() {
    S.stops.forEach((s) => s()); S.stops = [];
    S.panel = false; drawTop(); clear(app);
    const v = { new: viewNew, orders: viewOrders, track: viewTrack, queue: viewQueue }[route()] || viewNew;
    v();
    if (S.user) S.stops.push(poll(pullNotes, 8000));
  }
  window.addEventListener("hashchange", render);

  /* ---------- sign in / register ---------- */
  function authCard(why) {
    let mode = "login";
    const box = h("div", { class: "card narrow" });
    const draw = () => {
      clear(box);
      const email = h("input", { id: "em", type: "email", autocomplete: "email", required: true });
      const pw = h("input", { id: "pw", type: "password", autocomplete: mode === "login" ? "current-password" : "new-password", required: true, minlength: 8 });
      const name = h("input", { id: "nm", autocomplete: "name", required: true, minlength: 2 });
      const err = h("p", { class: "small", style: "color:var(--magenta)", role: "alert" });
      const btn = h("button", { class: "btn primary", type: "submit" }, mode === "login" ? "Sign in" : "Create account");
      const form = h("form", { class: "stack", onsubmit: (e) => {
        e.preventDefault(); err.textContent = "";
        busy(btn, "Please wait", async () => {
          try {
            const body = mode === "login" ? { email: email.value, password: pw.value } : { email: email.value, password: pw.value, full_name: name.value };
            const r = await api(mode === "login" ? "/auth/login" : "/auth/register", { method: "POST", body });
            if (r.user.role !== "customer") { Auth.clear(); throw new Error("This page is for customers. Staff sign in on the Staff page."); }
            Auth.set(r.token, r.user); S.user = r.user; render();
          } catch (x) { err.textContent = x.message; }
        });
      } },
        mode === "register" && field("Full name", name),
        field("Email", email), field("Password", pw, mode === "register" ? "At least 8 characters." : null), err, btn);
      box.append(h("h2", null, mode === "login" ? "Sign in to print" : "Create your account"), h("p", { class: "muted" }, why), form,
        h("p", { class: "small" }, mode === "login" ? "New here? " : "Already registered? ",
          h("button", { class: "link", onclick: () => { mode = mode === "login" ? "register" : "login"; draw(); } }, mode === "login" ? "Create an account" : "Sign in")));
    };
    draw(); return box;
  }

  /* ---------- New print wizard ---------- */
  function viewNew() {
    if (!S.user) return app.append(authCard("An account lets you track every order and get an alert when it is ready."));
    if (W.done) return app.append(doneView());
    app.append(W.job ? optionsView() : uploadView());
  }

  function uploadView() {
    const status = h("p", { class: "muted", role: "status" });
    const input = h("input", { type: "file", accept: ".pdf,.docx", id: "file" });
    const zone = h("label", { class: "drop", for: "file" }, h("strong", null, "Choose a PDF or Word file"), h("span", { class: "muted" }, `or drop it here. PDF and DOCX only, up to ${S.cfg.max_upload_mb} MB.`), input);
    const send = async (f) => {
      if (!f) return;
      const ext = f.name.split(".").pop().toLowerCase();
      if (!["pdf", "docx"].includes(ext)) return toast("Only PDF and DOCX files are accepted.", true);
      if (f.size > S.cfg.max_upload_mb * 1048576) return toast(`That file is over ${S.cfg.max_upload_mb} MB.`, true);
      clear(status).append(h("span", { class: "spin" }), " Uploading and checking your file...");
      const fd = new FormData(); fd.append("file", f);
      try {
        W.job = await api("/jobs", { method: "POST", form: fd });
        const m = new Date(Date.now() + (S.cfg.min_pickup_minutes + 30) * 60000); m.setMinutes(Math.ceil(m.getMinutes() / 15) * 15, 0, 0);
        W.opts = { paper_size: Object.keys(S.cfg.pricing.paper_multiplier)[0], color_mode: "bw", sides: "single", copies: 1, binding: "none", notes: "", pickup: toLocalInput(m) };
        render();
      } catch (e) { clear(status).append(e.message); status.style.color = "var(--magenta)"; }
    };
    input.addEventListener("change", () => send(input.files[0]));
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => send(e.dataTransfer.files[0]));
    return h("div", { class: "grid cols" },
      h("section", { class: "card stack" }, h("h1", null, "Send your document, skip the line"),
        h("p", { class: "muted" }, "Upload a file, choose how you want it printed, and pick a time to collect it. We check every file for safety before it reaches the shop."), zone, status),
      h("aside", { class: "card" }, h("h3", null, "Prices"), priceList()));
  }

  function priceList() {
    const p = S.cfg.pricing;
    return h("dl", { class: "kv" },
      h("dt", null, "B&W per page"), h("dd", null, money(p.per_page.bw)), h("dt", null, "Color per page"), h("dd", null, money(p.per_page.color)),
      Object.entries(p.paper_multiplier).filter(([, v]) => v !== 1).map(([k, v]) => [h("dt", null, k + " paper"), h("dd", null, "x" + v)]),
      h("dt", null, "Back-to-back"), h("dd", null, p.duplex_discount_pct + "% off"),
      Object.entries(p.binding).filter(([, v]) => v > 0).map(([k, v]) => [h("dt", null, bindLabel(k)), h("dd", null, money(v) + " per copy")]));
  }

  function optionsView() {
    const o = W.opts, p = S.cfg.pricing, job = W.job;
    const sum = h("div", { class: "stack" });
    let timer;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const e = await api("/estimate", { method: "POST", body: { pages: job.page_count, paper_size: o.paper_size, color_mode: o.color_mode, sides: o.sides, copies: o.copies, binding: o.binding } });
          W.est = e; clear(sum).append(
            h("dl", { class: "kv" }, h("dt", null, "Document"), h("dd", null, job.document_name), h("dt", null, "Pages"), h("dd", null, job.page_count),
              h("dt", null, `Printing (${e.pages * e.copies} pages)`), h("dd", null, money(e.printing)),
              e.duplex_discount > 0 && [h("dt", null, "Back-to-back discount"), h("dd", null, "-" + money(e.duplex_discount))],
              e.binding > 0 && [h("dt", null, "Binding"), h("dd", null, money(e.binding))]),
            h("div", { class: "row between" }, h("span", { class: "muted" }, "Estimated total"), h("span", { class: "total" }, money(e.total))),
            h("p", { class: "hint" }, "You pay at the counter when you collect your order."));
        } catch (x) { clear(sum).append(h("p", { style: "color:var(--magenta)" }, x.message)); }
      }, 200);
    };
    const bind = (el, key, num) => { el.addEventListener("input", () => { o[key] = num ? Math.max(1, Math.min(500, parseInt(el.value) || 1)) : el.value; refresh(); }); return el; };
    const sel = (id, key, opts, label) => { const s = h("select", { id }, opts.map(([v, t]) => h("option", { value: v, selected: o[key] === v }, t))); return field(label, bind(s, key)); };
    const seg = (name, key, opts, label) => h("div", null, h("label", null, label), h("div", { class: "seg", role: "radiogroup", "aria-label": label },
      opts.map(([v, t]) => { const i = h("input", { type: "radio", name, value: v, checked: o[key] === v }); i.addEventListener("change", () => { o[key] = v; refresh(); }); return h("label", null, i, t); })));
    const minPick = toLocalInput(new Date(Date.now() + S.cfg.min_pickup_minutes * 60000));
    const pick = h("input", { id: "pick", type: "datetime-local", min: minPick, value: o.pickup, required: true });
    pick.addEventListener("input", () => { o.pickup = pick.value; });
    const copies = bind(h("input", { id: "cp", type: "number", min: 1, max: 500, value: o.copies, inputmode: "numeric" }), "copies", true);
    const notes = h("textarea", { id: "nt", maxlength: 500, placeholder: "For example: print pages 1 to 5 only, staple top-left." }, o.notes);
    notes.addEventListener("input", () => { o.notes = notes.value; });
    refresh();

    const review = async () => {
      if (!o.pickup || new Date(o.pickup) < new Date(Date.now() + (S.cfg.min_pickup_minutes - 1) * 60000)) return toast(`Choose a pickup time at least ${S.cfg.min_pickup_minutes} minutes from now.`, true);
      const e = W.est; if (!e) return toast("Wait for the estimate to finish.", true);
      const ok = await modal({ title: "Submit this print request?", ok: "Submit request", cancel: "Go back",
        body: h("div", { class: "stack" }, h("dl", { class: "kv" },
          h("dt", null, "Document"), h("dd", null, job.document_name), h("dt", null, "Options"), h("dd", null, specLine({ ...o, binding: o.binding })),
          h("dt", null, "Pickup"), h("dd", null, fmtDate(new Date(o.pickup).toISOString())), h("dt", null, "Estimated total"), h("dd", null, money(e.total))),
          o.notes && h("div", { class: "note-box" }, o.notes), h("p", { class: "small muted" }, "Once submitted, your request joins the queue. You can cancel it until printing starts.")) });
      if (!ok) return;
      try {
        W.done = await api(`/jobs/${job.id}/confirm`, { method: "POST", body: { paper_size: o.paper_size, color_mode: o.color_mode, sides: o.sides, copies: o.copies, binding: o.binding, notes: o.notes, pickup_at: new Date(o.pickup).toISOString() } });
        W.job = null; render();
      } catch (x) { toast(x.message, true); }
    };
    const another = async () => { try { await api(`/jobs/${job.id}/cancel`, { method: "POST" }); } catch {} W.job = null; render(); };

    return h("div", { class: "grid cols" },
      h("section", { class: "card stack" }, h("h1", null, "Choose your print options"),
        h("div", { class: "fields" },
          sel("pp", "paper_size", Object.keys(p.paper_multiplier).map((k) => [k, k]), "Paper size"),
          field("Copies", copies),
          seg("color", "color_mode", [["bw", "Black & white"], ["color", "Color"]], "Color"),
          seg("sides", "sides", [["single", "Single-sided"], ["double", "Back-to-back"]], "Sides"),
          sel("bd", "binding", Object.keys(p.binding).map((k) => [k, bindLabel(k)]), "Binding"),
          field("Pickup date and time", pick, `Earliest: ${S.cfg.min_pickup_minutes} minutes from now.`),
          h("div", { class: "full" }, field("Notes for the shop (optional)", notes))),
        h("div", { class: "row" }, h("button", { class: "btn primary", onclick: review }, "Review and submit"), h("button", { class: "btn", onclick: another }, "Choose a different file"))),
      h("aside", { class: "card" }, h("h3", null, "Your estimate"), sum));
  }

  function ticket(j) {
    return h("div", { class: "ticket" }, h("div", { class: "inks" }, h("i"), h("i"), h("i"), h("i")),
      h("div", { class: "stub stack" }, h("div", { class: "muted small" }, "Tracking code"), h("div", { class: "code" }, j.tracking_code), h("div", null, badge(j.status), " ", h("span", { class: "muted" }, queueText(j)))),
      h("div", { class: "tear" }),
      h("div", { class: "stub" }, h("dl", { class: "kv" }, h("dt", null, "Document"), h("dd", null, j.document_name), h("dt", null, "Options"), h("dd", null, specLine(j)),
        h("dt", null, "Pickup"), h("dd", null, fmtDate(j.pickup_at)), h("dt", null, "Estimated total"), h("dd", null, money(j.total_cost)))));
  }

  function doneView() {
    const j = W.done;
    return h("div", { class: "card narrow stack", style: "max-width:520px" }, h("h1", null, "Request submitted"),
      h("p", { class: "muted" }, "Keep this code. We will alert you here when your order is ready for pickup."), ticket(j),
      h("div", { class: "row" },
        h("button", { class: "btn", onclick: () => navigator.clipboard?.writeText(j.tracking_code).then(() => toast("Code copied")) }, "Copy code"),
        h("a", { class: "btn", href: "#orders" }, "View my orders"),
        h("button", { class: "btn primary", onclick: () => { W.done = null; render(); } }, "Print another file")));
  }

  /* ---------- My orders ---------- */
  function viewOrders() {
    if (!S.user) return app.append(authCard("Sign in to see your orders."));
    const list = h("div"); app.append(h("h1", null, "My orders"), list);
    let last = "";
    S.stops.push(poll(async () => {
      const jobs = await api("/jobs"), sig = JSON.stringify(jobs);
      if (sig === last) return; last = sig; clear(list);
      if (!jobs.length) return list.append(h("div", { class: "card empty" }, "You have no orders yet. ", h("a", { href: "#new" }, "Upload a document"), " to get started."));
      jobs.forEach((j) => list.append(h("div", { class: "card order" },
        h("div", { class: "row between" }, h("span", { class: "mono" }, j.tracking_code), badge(j.status, j.status_label)),
        h("div", null, h("strong", null, j.document_name), h("span", { class: "muted" }, `, ${j.page_count} pages`)),
        h("div", { class: "muted small" }, specLine(j)),
        h("div", { class: "row between" }, h("span", null, j.status === "ready" ? "Ready. Collect at the counter." : (queueText(j) || "Pickup " + fmtDate(j.pickup_at))), h("strong", null, money(j.total_cost))),
        j.status === "pending" && h("div", null, h("button", { class: "btn sm danger", onclick: async () => {
          if (!await modal({ title: "Cancel this order?", body: h("p", null, `${j.tracking_code} will be removed from the queue.`), ok: "Cancel order", cancel: "Keep order", danger: true })) return;
          try { await api(`/jobs/${j.id}/cancel`, { method: "POST" }); last = ""; toast("Order cancelled"); } catch (e) { toast(e.message, true); }
        } }, "Cancel order")))));
    }, 5000));
  }

  /* ---------- Track by code ---------- */
  function viewTrack() {
    const out = h("div"), input = h("input", { id: "tc", placeholder: "QP-XXXXXX", autocapitalize: "characters", autocomplete: "off", maxlength: 12, value: sessionStorage.getItem("qp_code") || "" });
    let stop = null;
    const load = (quiet) => async () => {
      const code = input.value.trim().toUpperCase(); if (!code) return;
      try {
        const t = await api("/track/" + encodeURIComponent(code)); sessionStorage.setItem("qp_code", code);
        const order = ["pending", "processing", "ready", "completed"], idx = order.indexOf(t.status);
        clear(out).append(h("div", { class: "card stack" }, h("div", { class: "row between" }, h("span", { class: "code" }, t.tracking_code), badge(t.status, t.status_label)),
          ["cancelled", "failed"].includes(t.status) ? h("p", null, t.status === "failed" ? "This order needs attention. Please see the shop staff." : "This order was cancelled.") :
            h("ol", { class: "steps" }, order.map((s, i) => h("li", { class: i < idx ? "done" : i === idx ? "done now" : "" }, STATUS[s]))),
          h("p", { class: "total" }, queueText(t) || (t.status === "ready" ? "Ready for pickup" : "")),
          h("dl", { class: "kv" }, h("dt", null, "Pickup time"), h("dd", null, fmtDate(t.pickup_at)), h("dt", null, "Estimated total"), h("dd", null, money(t.total_cost)))));
      } catch (e) { if (!quiet) clear(out).append(h("div", { class: "card", style: "border-color:var(--magenta)" }, e.message)); }
    };
    const go = (e) => { e.preventDefault(); stop?.(); stop = poll(load(false), 6000); S.stops.push(() => stop?.()); };
    app.append(h("h1", null, "Track an order"), h("form", { class: "row", onsubmit: go, style: "margin-bottom:1rem" },
      h("div", { style: "flex:1;min-width:200px" }, h("label", { for: "tc", class: "small" }, "Tracking code"), input), h("button", { class: "btn primary", style: "align-self:flex-end" }, "Check status")), out);
    if (input.value) go({ preventDefault() {} });
  }

  /* ---------- Live queue board ---------- */
  function viewQueue() {
    const body = h("div"); app.append(h("h1", null, "Live queue"), h("p", { class: "muted" }, "Updates every few seconds. Codes are partly hidden for privacy."), body);
    S.stops.push(poll(async () => {
      const b = await api("/board"); clear(body).append(
        h("div", { class: "chips", style: "margin-bottom:1rem" }, [["Waiting", b.waiting], ["Printing", b.printing], ["Ready", b.ready]].map(([t, n]) => h("div", { class: "chip" }, h("b", null, n), t))),
        b.jobs.length ? h("table", { class: "table card" }, h("thead", null, h("tr", null, ["Position", "Order", "Status", "Pages"].map((t) => h("th", null, t)))),
          h("tbody", null, b.jobs.map((j) => h("tr", null, h("td", { "data-label": "Position" }, j.position === 0 ? "Now" : j.position || "-"), h("td", { "data-label": "Order", class: "mono" }, j.code), h("td", { "data-label": "Status" }, badge(j.status, j.status_label)), h("td", { "data-label": "Pages" }, j.pages)))))
          : h("div", { class: "card empty" }, "The queue is empty. Upload a document and you will be first."));
    }, 4000));
  }

  /* ---------- boot ---------- */
  api("/config").then((c) => { S.cfg = c; setCurrency(c.pricing.currency); document.title = c.shop_name + ": print without the line"; render(); })
    .catch((e) => app.append(h("div", { class: "card empty" }, e.message)));
})();

(() => {
  const app = $("#app"), top = $("#top");
  const S = { user: Auth.user, cfg: null, stops: [], tab: "orders", filter: "active" };
  const FILTERS = [["active", "Active"], ["pending", "Pending"], ["processing", "Processing"], ["ready", "Ready"], ["failed", "Needs attention"], ["completed", "Completed"], ["cancelled", "Cancelled"], ["all", "All"]];
  const isAdmin = () => S.user?.role === "admin";
  const tabs = () => [["orders", "Orders"], ...(isAdmin() ? [["pricing", "Pricing and printer"], ["team", "Team"]] : [])];

  function drawTop() {
    put(clear(top), logo((S.cfg?.shop_name || "QuePrint") + " Staff"),
      S.user ? [h("nav", { class: "nav", "aria-label": "Staff" }, tabs().map(([k, t]) => h("a", { href: "#", class: S.tab === k ? "on" : "", onclick: (e) => { e.preventDefault(); S.tab = k; render(); } }, t))),
        h("div", { class: "userbox" }, h("span", { class: "small muted" }, S.user.full_name + " (" + S.user.role + ")"), h("button", { class: "btn sm", onclick: () => { Auth.clear(); S.user = null; render(); } }, "Sign out"))] : null);
  }
  window.addEventListener("qp:logout", () => { S.user = null; render(); });

  function render() {
    S.stops.forEach((s) => s()); S.stops = []; drawTop(); clear(app);
    if (!S.user) return login();
    ({ orders: viewOrders, pricing: viewPricing, team: viewTeam }[S.tab] || viewOrders)();
  }

  /* ---------- login (FR1) ---------- */
  function login() {
    const email = h("input", { id: "e", type: "email", required: true, autocomplete: "username" }), pw = h("input", { id: "p", type: "password", required: true, autocomplete: "current-password" });
    const err = h("p", { class: "small", style: "color:var(--magenta)", role: "alert" }), btn = h("button", { class: "btn primary" }, "Sign in");
    app.append(h("form", { class: "card narrow stack", onsubmit: (e) => {
      e.preventDefault(); err.textContent = "";
      busy(btn, "Please wait", async () => {
        try {
          const r = await api("/auth/login", { method: "POST", body: { email: email.value, password: pw.value } });
          if (r.user.role === "customer") { Auth.clear(); throw new Error("This page is for shop staff. Customers sign in on the main page."); }
          Auth.set(r.token, r.user); S.user = r.user; S.tab = "orders"; render();
        } catch (x) { err.textContent = x.message; }
      });
    } }, h("h1", null, "Staff sign in"), h("p", { class: "muted" }, "Use the account your shop admin created for you."), field("Email", email), field("Password", pw), err, btn));
  }

  /* ---------- Orders dashboard ---------- */
  function viewOrders() {
    const chips = h("div", { class: "chips" }), bar = h("div", { class: "row between", style: "margin:1rem 0" }), list = h("div");
    const sel = h("select", { id: "flt", "aria-label": "Filter orders", style: "width:auto" }, FILTERS.map(([v, t]) => h("option", { value: v, selected: v === S.filter }, t)));
    sel.addEventListener("change", () => { S.filter = sel.value; last = ""; });
    app.append(h("div", { class: "row between" }, h("h1", null, "Print queue")), chips, bar, list);
    let last = "";
    S.stops.push(poll(async () => {
      const [st, jobs] = await Promise.all([api("/staff/stats"), api("/staff/jobs?status=" + S.filter)]);
      const sig = JSON.stringify([st, jobs, S.filter]); if (sig === last) return; last = sig;
      const c = st.counts;
      put(clear(chips), [["Pending", c.pending], ["Processing", c.processing], ["Ready", c.ready], ["Needs attention", c.failed, true]].map(([t, n, w]) => h("div", { class: "chip" + (w && n ? " warn" : "") }, h("b", null, n || 0), t)));
      clear(bar).append(h("div", { class: "row" }, h("label", { for: "flt", class: "small", style: "margin:0" }, "Show"), sel),
        h("span", { class: "small muted" }, "Auto-print " + (st.auto_dispatch ? "on" : "off") + ", printer: " + (st.printer_mode === "cups" ? "connected (CUPS)" : "simulated")));
      clear(list);
      if (!jobs.length) return list.append(h("div", { class: "card empty" }, "No orders here. New requests appear automatically."));
      list.append(h("table", { class: "table card" }, h("thead", null, h("tr", null, ["Queue", "Order", "Customer", "Document", "Options", "Pickup", "Total", "Status", ""].map((t) => h("th", null, t)))),
        h("tbody", null, jobs.map((j) => h("tr", { class: "clickable" + (j.status === "failed" ? " bad" : ""), onclick: () => openTicket(j.id) },
          h("td", { "data-label": "Queue" }, j.queue_position === 0 ? "Now" : j.queue_position || "-"), h("td", { "data-label": "Order", class: "mono" }, j.tracking_code),
          h("td", { "data-label": "Customer" }, j.customer_name), h("td", { "data-label": "Document" }, j.document_name + " (" + j.page_count + "p)"),
          h("td", { "data-label": "Options" }, specLine(j)), h("td", { "data-label": "Pickup" }, fmtDate(j.pickup_at)), h("td", { "data-label": "Total" }, money(j.total_cost)),
          h("td", { "data-label": "Status" }, badge(j.status, j.status_label)),
          h("td", { onclick: (e) => e.stopPropagation() }, primaryAction(j)))))));
    }, 4000));
  }

  const ACTIONS = {
    pending: [["Print now", "print", true], ["Mark processing", "processing"], ["Cancel order", "cancelled", false, true]],
    processing: [["Mark ready", "ready", true], ["Print again", "print"], ["Back to queue", "pending"]],
    failed: [["Retry print", "print", true], ["Back to queue", "pending"], ["Cancel order", "cancelled", false, true]],
    ready: [["Mark collected", "completed", true], ["Cancel order", "cancelled", false, true]],
  };
  async function act(job, kind, closeFn) {
    try {
      if (kind === "cancelled" && !await modal({ title: "Cancel this order?", body: h("p", null, `${job.tracking_code} for ${job.customer_name} will be cancelled and the customer notified.`), ok: "Cancel order", cancel: "Keep order", danger: true })) return;
      if (kind === "print") {
        const r = await api(`/staff/jobs/${job.id}/print`, { method: "POST" });
        r.ok ? toast(`${job.tracking_code} sent to the printer`) : toast("Printer error: " + r.message, true);
      } else { await api(`/staff/jobs/${job.id}/status`, { method: "PATCH", body: { status: kind } }); toast(`${job.tracking_code}: ${STATUS[kind]}`); }
      closeFn?.(); S.stops.forEach((s) => s()); S.stops = []; render();
    } catch (e) { toast(e.message, true); }
  }
  function primaryAction(j) {
    const a = (ACTIONS[j.status] || []).find((x) => x[2]); if (!a) return null;
    return h("button", { class: "btn sm primary", onclick: () => act(j, a[1]) }, a[0]);
  }

  async function openFile(job, which) {
    const w = which === "print" ? window.open("", "_blank") : null;
    try {
      const blob = await api(`/staff/jobs/${job.id}/file?which=${which}`, { blob: true }), url = URL.createObjectURL(blob);
      if (w) w.location = url; else { const a = h("a", { href: url, download: job.document_name }); document.body.append(a); a.click(); a.remove(); }
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { w?.close(); toast(e.message, true); }
  }

  async function openTicket(id) {
    let j; try { j = await api("/staff/jobs/" + id); } catch (e) { return toast(e.message, true); }
    const dlg = h("dialog", { "aria-label": "Job ticket " + j.tracking_code });
    const close = () => { dlg.close(); dlg.remove(); };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
    dlg.append(h("div", { class: "dlg stack" },
      h("div", { class: "row between" }, h("span", { class: "code" }, j.tracking_code), badge(j.status, j.status_label)),
      j.error_message && h("div", { class: "err-box" }, h("strong", null, "Printer message: "), j.error_message),
      j.notes && h("div", { class: "note-box" }, h("strong", null, "Customer notes: "), j.notes),
      h("dl", { class: "kv" },
        h("dt", null, "Customer"), h("dd", null, j.customer_name), h("dt", null, "Email"), h("dd", null, j.customer_email),
        h("dt", null, "Document"), h("dd", null, j.document_name), h("dt", null, "Pages x copies"), h("dd", null, `${j.page_count} x ${j.copies} = ${j.page_count * j.copies}`),
        h("dt", null, "Paper"), h("dd", null, j.paper_size), h("dt", null, "Color"), h("dd", null, j.color_mode === "color" ? "Color" : "Black & white"),
        h("dt", null, "Sides"), h("dd", null, j.sides === "double" ? "Back-to-back" : "Single-sided"), h("dt", null, "Binding"), h("dd", null, bindLabel(j.binding)),
        h("dt", null, "Pickup"), h("dd", null, fmtDate(j.pickup_at)), h("dt", null, "Queue position"), h("dd", null, queueText(j) || "n/a"),
        h("dt", null, "Estimated total"), h("dd", null, money(j.total_cost))),
      h("div", { class: "row" }, h("button", { class: "btn sm", onclick: () => openFile(j, "print") }, "Preview PDF"), h("button", { class: "btn sm", onclick: () => openFile(j, "original") }, "Download original")),
      h("footer", null, h("button", { class: "btn", onclick: close }, "Close"), (ACTIONS[j.status] || []).map(([label, kind, primary, danger]) => h("button", { class: "btn " + (primary ? "primary" : danger ? "danger" : ""), onclick: () => act(j, kind, close) }, label)))));
    document.body.append(dlg); dlg.showModal();
  }

  /* ---------- Admin: pricing + printer ---------- */
  async function viewPricing() {
    const [cfg, st] = await Promise.all([api("/config"), api("/staff/stats")]).catch((e) => { toast(e.message, true); return []; });
    if (!cfg) return;
    const p = cfg.pricing, inputs = {};
    const num = (key, val, label, step = "0.01") => { const i = h("input", { id: "n" + key, type: "number", min: 0, step, value: val, inputmode: "decimal" }); inputs[key] = i; return field(label, i); };
    const form = h("form", { class: "card stack", onsubmit: async (e) => {
      e.preventDefault();
      const body = { currency: p.currency, per_page: { bw: +inputs.bw.value, color: +inputs.color.value }, duplex_discount_pct: +inputs.duplex.value,
        paper_multiplier: Object.fromEntries(Object.keys(p.paper_multiplier).map((k) => [k, +inputs["p_" + k].value])), binding: Object.fromEntries(Object.keys(p.binding).map((k) => [k, +inputs["b_" + k].value])) };
      try { await api("/admin/pricing", { method: "PUT", body }); toast("Prices saved"); } catch (x) { toast(x.message, true); }
    } }, h("h2", null, "Prices"),
      h("div", { class: "fields" }, num("bw", p.per_page.bw, "B&W price per page"), num("color", p.per_page.color, "Color price per page"), num("duplex", p.duplex_discount_pct, "Back-to-back discount (%)", "1")),
      h("h3", null, "Paper size multipliers"), h("div", { class: "fields" }, Object.entries(p.paper_multiplier).map(([k, v]) => num("p_" + k, v, k))),
      h("h3", null, "Binding fee per copy"), h("div", { class: "fields" }, Object.entries(p.binding).filter(([k]) => k !== "none").map(([k, v]) => num("b_" + k, v, bindLabel(k)))),
      h("div", null, h("button", { class: "btn primary" }, "Save prices")));
    inputs.b_none = { value: 0 };
    const auto = h("input", { type: "checkbox", id: "auto", checked: st.auto_dispatch, style: "width:auto;min-height:0;margin-right:.5rem" });
    auto.addEventListener("change", async () => { try { await api("/admin/auto-dispatch", { method: "PUT", body: { enabled: auto.checked } }); toast("Auto-print " + (auto.checked ? "on" : "off")); } catch (x) { toast(x.message, true); auto.checked = !auto.checked; } });
    app.append(h("h1", null, "Pricing and printer"), h("div", { class: "grid cols" }, form,
      h("aside", { class: "card stack" }, h("h2", null, "Printer"),
        h("label", { for: "auto", style: "display:flex;align-items:center" }, auto, "Send the next job to the printer automatically"),
        h("p", { class: "small muted" }, "When on, the oldest confirmed request is sent to the printer without staff action. Turn it off to print manually."),
        h("dl", { class: "kv" }, h("dt", null, "Mode"), h("dd", null, st.printer_mode === "cups" ? "Wireless printer (CUPS)" : "Simulated"))), ));
  }

  /* ---------- Admin: team ---------- */
  async function viewTeam() {
    const list = h("div", { class: "card" });
    const draw = async () => {
      const users = await api("/admin/users"); clear(list).append(h("h2", null, "Staff accounts"), h("table", { class: "table" }, h("thead", null, h("tr", null, ["Name", "Email", "Role", ""].map((t) => h("th", null, t)))),
        h("tbody", null, users.map((u) => h("tr", null, h("td", { "data-label": "Name" }, u.full_name), h("td", { "data-label": "Email" }, u.email), h("td", { "data-label": "Role" }, u.role + (u.is_active ? "" : " (inactive)")),
          h("td", null, u.id !== S.user.id && h("button", { class: "btn sm", onclick: async () => { try { await api("/admin/users/" + u.id, { method: "PATCH", body: { is_active: !u.is_active } }); draw(); } catch (x) { toast(x.message, true); } } }, u.is_active ? "Deactivate" : "Activate")))))));
    };
    const f = { n: h("input", { id: "tn", required: true, minlength: 2 }), e: h("input", { id: "te", type: "email", required: true }), p: h("input", { id: "tp", type: "password", required: true, minlength: 8, autocomplete: "new-password" }),
      r: h("select", { id: "tr" }, h("option", { value: "staff" }, "Staff (operator)"), h("option", { value: "admin" }, "Admin")) };
    const form = h("form", { class: "card stack", onsubmit: async (e) => {
      e.preventDefault();
      try { await api("/admin/users", { method: "POST", body: { full_name: f.n.value, email: f.e.value, password: f.p.value, role: f.r.value } }); toast("Account created"); e.target.reset(); draw(); } catch (x) { toast(x.message, true); }
    } }, h("h2", null, "Add a team member"), field("Full name", f.n), field("Email", f.e), field("Temporary password", f.p, "At least 8 characters."), field("Role", f.r), h("div", null, h("button", { class: "btn primary" }, "Create account")));
    app.append(h("h1", null, "Team"), h("div", { class: "grid cols" }, list, form)); draw().catch((e) => toast(e.message, true));
  }

  api("/config").then((c) => { S.cfg = c; setCurrency(c.pricing.currency); document.title = c.shop_name + " Staff"; render(); }).catch((e) => app.append(h("div", { class: "card empty" }, e.message)));
})();

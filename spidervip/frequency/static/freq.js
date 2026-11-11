(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const mount = () => String(window.SPIDERVIP_MOUNT || "").replace(/\/$/, "");
  const url = (p) => (mount() ? mount() + p : p);
  const fa = (n) => Number(n || 0).toLocaleString("fa-IR");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const state = {
    plan: null,          // summary from /api/plan
    selected: new Set(), // row ids
    rows: new Map(),     // box_index -> rows (lazy)
    open: new Set(),     // expanded sats
    polling: null,
    lastJobId: null,
  };

  // ---------- connection ----------
  function conn() {
    const c = window.SPIDERVIP_CONNECTION;
    if (c && c.host) return { host: c.host, user: c.user || "root", password: c.password == null ? "root" : c.password };
    return { host: $("cHost").value.trim(), user: $("cUser").value.trim() || "root", password: $("cPass").value };
  }
  function initConn() {
    const c = window.SPIDERVIP_CONNECTION;
    if (c && c.host) {
      $("connLabel").textContent = "رسیور: " + c.host;
    } else {
      $("standaloneConn").hidden = false;
      $("cHost").value = "192.168.100.102";
      $("connLabel").textContent = "حالت مستقل";
    }
  }

  // ---------- http ----------
  async function api(path, opts = {}) {
    const res = await fetch(url(path), { headers: { "Content-Type": "application/json" }, ...opts });
    let data = {};
    try { data = await res.json(); } catch (_) { data = { ok: false, error: `پاسخ نامعتبر (HTTP ${res.status})` }; }
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 5000);
  }

  // ---------- ids ----------
  // Row ids are "<box_index>.<c|n|g|s><k>", k = 1..count — so selections can be
  // built per satellite from counts alone, without loading the rows.
  const KIND = { changed: "c", new: "n", gone: "g", skipped: "s" };
  function idsOf(sat, kind) {
    const n = sat.counts[kind] || 0;
    const out = [];
    for (let k = 1; k <= n; k++) out.push(`${sat.box_index}.${KIND[kind]}${k}`);
    return out;
  }
  function selectedCount(sat, kind) {
    return idsOf(sat, kind).filter((id) => state.selected.has(id)).length;
  }
  function storageKey() {
    return state.plan ? "sv-freq-sel:" + state.plan.box.sha256 + ":" + state.plan.created : null;
  }
  function saveSel() {
    const k = storageKey();
    if (!k) return;
    try { localStorage.setItem(k, JSON.stringify([...state.selected])); } catch (_) { /* optional */ }
  }
  function loadSel() {
    const k = storageKey();
    let ids = null;
    try { ids = JSON.parse(localStorage.getItem(k) || "null"); } catch (_) { ids = null; }
    state.selected = new Set(Array.isArray(ids) ? ids : state.plan.default_selected);
  }

  // ---------- render ----------
  function renderPlan() {
    const p = state.plan;
    $("planSection").hidden = !p;
    if (!p) { $("planMeta").textContent = ""; return; }
    const t = p.totals;
    $("kChanged").textContent = fa(t.changed);
    $("kNew").textContent = fa(t.new);
    $("kGone").textContent = fa(t.gone);
    $("kGonePre").textContent = `${fa(t.gone_preselected)} پیش‌انتخاب برای حذف`;
    $("kSats").textContent = fa(t.sats_paired);
    $("kUnmatched").textContent = `${fa(t.sats_unmatched)} بدون جفت · ${fa(t.protected || 0)} TP دارای کانال دست‌نخورده`;
    const src = p.source || {};
    $("planMeta").textContent = `آخرین بررسی: ${p.created.replace("T", " ")} · منبع ساخته‌شده ${src.created ? src.created.replace("T", " ") : "—"} · رسیور ${fa(p.box.sats)} ماهواره / ${fa(p.box.tps)} TP / ${fa(p.box.channels || 0)} کانال`;
    if (!p.box.lamedb_sha256) toast("این برنامه بدون lamedb ساخته شده؛ برای اعمال روی رسیور دوباره «بررسی تغییرات» را بزنید.");
    const w = $("warnings");
    w.innerHTML = (p.warnings || []).map((x) => `<li>${esc(x)}</li>`).join("");
    w.hidden = !(p.warnings || []).length;
    $("unmatchedSummary").textContent = `${fa(p.unmatched.length)} ماهوارهٔ رسیور در منبع جفت ندارند (دست‌نخورده می‌مانند)`;
    $("unmatchedList").innerHTML = p.unmatched
      .slice().sort((a, b) => b.box_count - a.box_count)
      .map((u) => `<li><span class="ltr">${esc(u.position_label)}</span> ${esc(u.name)} <small>(${esc(u.band)} · ${fa(u.box_count)} TP)</small></li>`).join("");
    renderTable();
    renderSelSummary();
  }

  function satMatches(sat, q) {
    if (!q) return true;
    q = q.toLowerCase();
    return sat.name.toLowerCase().includes(q) || (sat.src_name || "").toLowerCase().includes(q) || sat.position_label.toLowerCase().includes(q);
  }

  function renderTable() {
    const p = state.plan;
    const q = $("filter").value.trim();
    const only = $("onlyChanges").checked;
    const body = $("satBody");
    const html = [];
    for (const s of p.sats) {
      const c = s.counts;
      if (only && !(c.changed || c.new || c.gone)) continue;
      if (!satMatches(s, q)) continue;
      const open = state.open.has(s.box_index);
      const guard = c.gone
        ? (s.guard.deletions_preselected
          ? `<span class="fq-badge fq-badge-ok" title="${esc(s.guard.reason)}">پیش‌انتخاب</span>`
          : `<span class="fq-badge fq-badge-warn" title="${esc(s.guard.reason)}">با تصمیم شما</span>`)
        : `<span class="fq-badge">—</span>`;
      html.push(`<tr class="fq-sat${open ? " is-open" : ""}" data-sat="${s.box_index}">
        <th scope="row">${esc(s.name)}
          ${s.pair === "near" ? `<small class="fq-near" title="موقعیت منبع: ${esc(s.src_name)}">جفت نزدیک</small>` : ""}</th>
        <td>${esc(s.band)}</td>
        <td class="num">${fa(s.box_count)} / ${fa(s.src_count)}</td>
        <td class="num">${cell(s, "changed")}</td>
        <td class="num">${cell(s, "new")}</td>
        <td class="num">${cell(s, "gone")}</td>
        <td>${guard}</td>
        <td><button class="fq-btn fq-btn-ghost fq-btn-sm" data-toggle="${s.box_index}" type="button" aria-expanded="${open}">${open ? "بستن" : "جزئیات"}</button></td>
      </tr>`);
      if (open) html.push(`<tr class="fq-detail"><td colspan="8">${detailHtml(s)}</td></tr>`);
    }
    body.innerHTML = html.join("") || `<tr><td colspan="8" class="fq-empty">ماهواره‌ای با این فیلتر نیست.</td></tr>`;
  }

  function cell(sat, kind) {
    const n = sat.counts[kind] || 0;
    if (!n) return "<span class=\"fq-zero\">۰</span>";
    const sel = selectedCount(sat, kind);
    const all = sel === n;
    return `<label class="fq-cell-check"><input type="checkbox" data-satkind="${sat.box_index}:${kind}" ${all ? "checked" : ""} ${sel && !all ? "data-mixed=\"1\"" : ""} />
      <span>${fa(sel)}/${fa(n)}</span></label>`;
  }

  const FIELD_FA = { frequency: "فرکانس", symbol_rate: "SR", system: "سیستم", modulation: "مدولاسیون", fec_inner: "FEC" };
  function tpText(v) {
    if (!v) return "—";
    return `<span class="ltr">${esc(v.freq)} ${esc(v.pol)} · ${esc(v.sr)} · ${esc(v.fec)} · ${esc(v.system)} ${esc(v.mod)}</span>`;
  }
  function detailHtml(sat) {
    const rows = state.rows.get(sat.box_index);
    if (!rows) return `<p class="fq-hint">در حال بارگذاری…</p>`;
    const reason = sat.guard.reason ? `<p class="fq-hint">${esc(sat.guard.reason)}</p>` : "";
    const kindFa = { changed: "اصلاح", new: "جدید", gone: "نبودن در منبع", skipped: "رد شد", protected: "دارای کانال" };
    const tr = rows.map((r) => {
      const changes = Object.entries(r.changes || {}).map(([k]) => FIELD_FA[k] || k).join("، ");
      const notes = [changes, r.note].filter(Boolean).join(" — ");
      const box = (r.kind === "skipped" || r.kind === "protected") ? "" : `<input type="checkbox" data-row="${r.id}" ${state.selected.has(r.id) ? "checked" : ""} aria-label="انتخاب ${esc(r.id)}" />`;
      return `<tr class="k-${r.kind}"><td>${box}</td><td><span class="fq-kind fq-kind-${r.kind}">${kindFa[r.kind]}</span></td>
        <td>${tpText(r.box)}</td><td>${tpText(r.src)}</td><td>${esc(notes)}</td></tr>`;
    }).join("");
    return `${reason}<div class="fq-table-wrap"><table class="fq-table fq-rows"><thead><tr><th></th><th>نوع</th><th>رسیور</th><th>منبع (LyngSat)</th><th>تغییر</th></tr></thead><tbody>${tr}</tbody></table></div>`;
  }

  function renderSelSummary() {
    const p = state.plan;
    if (!p) return;
    let c = 0, n = 0, g = 0;
    for (const s of p.sats) { c += selectedCount(s, "changed"); n += selectedCount(s, "new"); g += selectedCount(s, "gone"); }
    const after = p.box.tps + n - g;
    $("selSummary").innerHTML = `انتخاب فعلی: <b>${fa(c)}</b> اصلاح، <b>${fa(n)}</b> TP جدید، <b>${fa(g)}</b> حذف — تعداد TP رسیور ${fa(p.box.tps)} → <b>${fa(after)}</b>`;
    $("btnDeploy").disabled = !(c || n || g);
    $("btnDownload").disabled = !(c || n || g);
    $("confirmText").textContent = `${fa(c)} اصلاح، ${fa(n)} TP جدید و ${fa(g)} حذف روی رسیور ${conn().host} اعمال شود؟`;
    // reflect mixed state on per-sat checkboxes
    document.querySelectorAll("input[data-mixed]").forEach((el) => { el.indeterminate = true; });
  }

  // ---------- jobs ----------
  const STATE_FA = { running: "در حال اجرا", done: "انجام شد", failed: "ناموفق" };
  const TITLE_FA = { check: "بررسی تغییرات", deploy: "اعمال روی رسیور", rollback: "برگشت به snapshot" };
  function renderJob(job) {
    if (!job) return;
    $("jobCard").hidden = false;
    $("jobTitle").textContent = TITLE_FA[job.kind] || job.kind;
    const b = $("jobState");
    b.textContent = STATE_FA[job.state] || job.state;
    b.className = "fq-badge " + (job.state === "done" ? "fq-badge-ok" : job.state === "failed" ? "fq-badge-err" : "fq-badge-run");
    // collapse consecutive progress lines of the same step
    const lines = [];
    for (const s of job.steps) {
      const last = lines[lines.length - 1];
      if (last && last.step === s.step && last.state === "running" && s.state === "running") lines[lines.length - 1] = s;
      else lines.push(s);
    }
    $("jobLog").innerHTML = lines.map((s) => `<li class="st-${esc(s.state)}"><time>${esc(s.time)}</time> ${esc(s.message)}</li>`).join("");
    const busy = job.state === "running";
    ["btnCheck", "btnDeploy", "btnSnaps"].forEach((id) => { $(id).disabled = busy || (id === "btnDeploy" && !state.plan); });
  }
  async function poll() {
    clearTimeout(state.polling);
    try {
      const { job } = await api("/api/job");
      if (job) renderJob(job);
      if (job && job.state === "running") { state.booted = true; state.polling = setTimeout(poll, 1500); return; }
      if (!state.booted) {
        // Page load: show the last job's log, but do not re-announce it.
        state.booted = true;
        state.lastJobId = job ? job.id : null;
        return;
      }
      if (job && job.id !== state.lastJobId) {
        state.lastJobId = job.id;
        if (job.kind === "check" && job.state === "done") await loadPlan(true);
        if (job.state === "failed") toast(job.error || "عملیات ناموفق بود.");
        if (job.kind !== "check" && job.state === "done") toast("انجام شد.");
      }
    } catch (err) {
      state.polling = setTimeout(poll, 4000);
    }
  }

  async function loadPlan(fresh) {
    const { plan } = await api("/api/plan");
    state.plan = plan;
    state.rows.clear();
    if (fresh) state.open.clear();
    if (plan) loadSel();
    renderPlan();
  }

  async function toggleSat(i) {
    if (state.open.has(i)) { state.open.delete(i); renderTable(); return; }
    state.open.add(i);
    renderTable();
    if (!state.rows.has(i)) {
      try {
        const data = await api(`/api/plan/sat/${i}`);
        state.rows.set(i, data.rows);
      } catch (err) { toast(err.message); state.open.delete(i); }
      renderTable();
    }
  }

  // ---------- events ----------
  $("btnCheck").addEventListener("click", async () => {
    try {
      const { job } = await api("/api/check", { method: "POST", body: JSON.stringify(conn()) });
      state.lastJobId = null;
      renderJob(job);
      poll();
    } catch (err) { toast(err.message); }
  });

  $("filter").addEventListener("input", renderTable);
  $("onlyChanges").addEventListener("change", renderTable);

  document.querySelector(".fq-bulk").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-bulk]");
    if (!btn || !state.plan) return;
    const mode = btn.dataset.bulk;
    const p = state.plan;
    if (mode === "default") state.selected = new Set(p.default_selected);
    else if (mode === "none") state.selected = new Set();
    else {
      for (const s of p.sats) for (const id of idsOf(s, "gone")) {
        if (mode === "allgone") state.selected.add(id); else state.selected.delete(id);
      }
    }
    saveSel(); renderTable(); renderSelSummary();
  });

  $("satBody").addEventListener("click", (ev) => {
    const t = ev.target.closest("button[data-toggle]");
    if (t) toggleSat(Number(t.dataset.toggle));
  });
  $("satBody").addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset.satkind) {
      const [i, kind] = el.dataset.satkind.split(":");
      const sat = state.plan.sats.find((s) => s.box_index === Number(i));
      for (const id of idsOf(sat, kind)) el.checked ? state.selected.add(id) : state.selected.delete(id);
    } else if (el.dataset.row) {
      el.checked ? state.selected.add(el.dataset.row) : state.selected.delete(el.dataset.row);
    } else return;
    saveSel(); renderTable(); renderSelSummary();
  });

  $("btnDownload").addEventListener("click", async () => {
    try {
      const data = await api("/api/build", { method: "POST", body: JSON.stringify({ selected: [...state.selected] }) });
      toast(`فایل ساخته شد: ${fa(data.summary.tps_after)} TP`);
      window.location.href = url("/api/download");
    } catch (err) { toast(err.message); }
  });

  $("btnDeploy").addEventListener("click", () => {
    renderSelSummary();
    $("confirmDlg").showModal();
  });
  $("confirmDlg").addEventListener("close", async () => {
    if ($("confirmDlg").returnValue !== "ok") return;
    try {
      const body = { ...conn(), selected: [...state.selected], reboot_verify: $("rebootVerify").checked };
      const { job } = await api("/api/deploy", { method: "POST", body: JSON.stringify(body) });
      state.lastJobId = null;
      renderJob(job);
      $("jobCard").scrollIntoView({ behavior: "smooth", block: "start" });
      poll();
    } catch (err) { toast(err.message); }
  });

  $("btnSnaps").addEventListener("click", async () => {
    const list = $("snapList");
    list.innerHTML = `<li class="fq-hint">در حال خواندن از رسیور…</li>`;
    try {
      const { snapshots } = await api("/api/snapshots", { method: "POST", body: JSON.stringify(conn()) });
      list.innerHTML = snapshots.length ? snapshots.map((s) => `<li>
          <span class="ltr">${esc(s.name)}</span> <small>${esc(s.info)}</small>
          <span class="fq-snap-actions">
            <button class="fq-btn fq-btn-ghost fq-btn-sm" data-rollback="${esc(s.name)}" data-hard="1" type="button">برگشت</button>
          </span></li>`).join("") : `<li class="fq-hint">هنوز snapshotی روی رسیور نیست.</li>`;
    } catch (err) { list.innerHTML = ""; toast(err.message); }
  });
  $("snapList").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-rollback]");
    if (!b) return;
    const hard = b.dataset.hard === "1";
    const msg = `برگشت به ${b.dataset.rollback}؟ کل پایگاه کانال (live_prog) همان snapshot می‌شود و رسیور راه‌اندازی دوباره می‌شود؛ وضعیت فعلی هم قبلش snapshot می‌شود.`;
    if (!window.confirm(msg)) return;
    try {
      const { job } = await api("/api/rollback", { method: "POST", body: JSON.stringify({ ...conn(), snapshot: b.dataset.rollback, hard }) });
      state.lastJobId = null;
      renderJob(job);
      poll();
    } catch (err) { toast(err.message); }
  });

  // ---------- boot ----------
  initConn();
  loadPlan(false).catch((err) => toast(err.message));
  poll();
})();

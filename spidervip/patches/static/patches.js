(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const mount = () => String(window.SPIDERVIP_MOUNT || "").replace(/\/$/, "");
  const url = (p) => (mount() ? mount() + p : p);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const state = { patches: [], status: {}, busy: null, steps: {}, reports: {} };
  const fa = (n) => Number(n || 0).toLocaleString("fa-IR");

  function reportHtml(r) {
    if (r === undefined) return "";
    if (r === null) return `<p class="pt-note">هنوز گزارشی روی رسیور نیست. اولین اجرا پس از نصب (و تنظیم ساعت) انجام می‌شود؛ یا «اجرای فوری» را بزنید.</p>`;
    const w = r.would_apply || {};
    const src = r.source || {};
    const box = r.box || {};
    const rows = (r.sats || []).slice().sort((a, b) =>
      (b.counts.changed + b.counts.new + b.counts.gone) - (a.counts.changed + a.counts.new + a.counts.gone)).slice(0, 12)
      .map((s) => `<tr><th scope="row">${esc(s.name)}</th><td>${fa(s.counts.changed)}</td><td>${fa(s.counts.new)}</td><td>${fa(s.counts.gone)}${s.deletions_preselected ? "" : " *"}</td></tr>`).join("");
    const sm = r.summary || {};
    const satList = (title, n, tps, list) => (n ? `<details class="pt-sats"><summary><b>${title}:</b> ${fa(n)} ماهواره، ${fa(tps)} TP</summary>
      <p class="ltr">${(list || []).map((s) => `${esc(s.name)} (${fa(s.tps)})`).join(" · ")}</p></details>` : "");
    const RES = {
      applied: `<p class="pt-res pt-ok">اعمال و تأیید شد: ${fa(sm.changed)} اصلاح، ${fa(sm.new)} جدید، ${fa(sm.gone)} حذف، ${fa((sm.sats_added || []).length)} ماهوارهٔ تازه، ${fa((sm.sats_removed || []).length)} ماهوارهٔ حذف‌شده (TP: ${fa(sm.tps_before)} ← ${fa(sm.tps_after)})؛
        ${fa(r.channels_removed)} کانال و ${fa(r.favorite_entries_removed)} خانهٔ Favorite همراه TPهای حذف‌شده رفتند؛ Motor ${fa((r.motor_restored || []).length)} ماهواره برگشت.
        ${r.verified_time ? `تأیید: ${esc(r.verified_time.replace("T", " "))}` : ""}</p>`,
      rolled_back: `<p class="pt-res pt-warn">اعمال شد ولی تأیید نشد و رسیور به snapshot برگشت${r.rollback_ok === false ? " (بررسی برگشت هم مشکل داشت!)" : ""}: ${esc((r.problems || []).join("؛ "))}</p>`,
      error_restored: `<p class="pt-res pt-warn">خطا هنگام اعمال؛ snapshot برگردانده شد: ${esc(r.error || "")}</p>`,
      nothing: `<p class="pt-res pt-ok">تغییری لازم نبود؛ لیست رسیور با منبع هم‌گام است.</p>`,
    };
    const resultLine = r.mode === "apply" ? (RES[r.result] || "") : "";
    const cand = r.candidates;
    const nearbyNote = (t) => (t.nearby && t.nearby.length
      ? ` <span class="pt-near">— ماهوارهٔ همسایه: در منبع روی <span class="ltr">${t.nearby.map((n) => `${esc(n.sat)} (${esc(n.position)}) SR ${esc(n.sr)}`).join("، ")}</span> هست</span>`
      : "");
    const crLine = cand && cand.tps && cand.tps.length ? `<div class="pt-res pt-warn"><b>نامزد حذف (حذف نشدند):</b>
      ${fa(cand.tps.length)} TP دارای کانال در منبع (OpenPLi) نیستند و برای حفظ کانال‌ها دست‌نخورده ماندند. اگر می‌دانید از هوا رفته‌اند،
      از ابزار فرکانس در کنسول حذفشان کنید:
      <ul>${cand.tps.map((t) => `<li><span class="ltr">${esc(t.sat)} — ${esc(t.freq)} ${esc(t.pol)} SR ${esc(t.sr)}</span>${nearbyNote(t)}</li>`).join("")}</ul>
      ${cand.tps.some((t) => t.nearby && t.nearby.length) ? `<p class="pt-meta">«ماهوارهٔ همسایه»: همین فرکانس در منبع روی ماهوارهٔ دیگری در فاصلهٔ کمتر از یک درجه هست.
        دیش آن ماهواره را هم می‌گیرد و اسکن کانال‌ها را زیر این ماهواره ذخیره کرده است؛ یعنی از هوا نرفته‌اند — حذفشان نکنید.</p>` : ""}
      کانال‌ها: ${esc((cand.channels || []).join("، "))}</div>` : "";
    return `<div class="pt-report">
      ${resultLine}
      ${crLine}
      <p><b>آخرین گزارش رسیور:</b> ${esc((r.time || "").replace("T", " "))} · ${fa(r.seconds)} ثانیه ·
        منبع ساخته‌شده ${esc((src.created || "—").replace("T", " "))} · رسیور ${fa(box.tps)} TP / ${fa(box.channels)} کانال</p>
      <p>${r.mode === "apply" ? "برنامهٔ این اجرا" : "اگر اعمال می‌شد"}: <b>${fa(w.changed)}</b> اصلاح، <b>${fa(w.new)}</b> TP جدید، <b>${fa(w.removed)}</b> حذف؛
        ${fa(w.protected)} TP دارای کانال که فقط پارامترشان عوض شده، دست‌نخورده (برای به‌روز کردن، روی رسیور اسکن کنید).</p>
      ${satList("ماهوارهٔ تازه (با USALS)", w.sats_new, w.sats_new_tps, r.new_sats)}
      ${satList("حذف ماهوارهٔ بدون کانال (در منبع نیست)", w.sats_removed, w.sats_removed_tps, r.removed_sats)}
      ${rows ? `<div class="pt-table-wrap"><table class="pt-table"><thead><tr><th>ماهواره</th><th>اصلاح</th><th>جدید</th><th>نبودن در منبع</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="pt-meta">* حذف‌های این ماهواره پیش‌انتخاب نمی‌شوند (منبع ناقص به نظر می‌رسد). ۱۲ ماهوارهٔ پرتغییر نمایش داده شده‌اند.</p>` : ""}
    </div>`;
  }

  function conn() {
    const c = window.SPIDERVIP_CONNECTION;
    if (c && c.host) return { host: c.host, user: c.user || "root", password: c.password == null ? "root" : c.password };
    return { host: $("cHost").value.trim(), user: $("cUser").value.trim() || "root", password: $("cPass").value };
  }
  function initConn() {
    const c = window.SPIDERVIP_CONNECTION;
    if (c && c.host) $("connLabel").textContent = "رسیور: " + c.host;
    else { $("standaloneConn").hidden = false; $("cHost").value = "192.168.100.102"; $("connLabel").textContent = "حالت مستقل"; }
  }
  async function api(path, opts = {}) {
    const res = await fetch(url(path), { headers: { "Content-Type": "application/json" }, ...opts });
    let data = {};
    try { data = await res.json(); } catch (_) { data = { ok: false, error: `پاسخ نامعتبر (HTTP ${res.status})` }; }
    if (!res.ok || data.ok === false) { const e = new Error(data.error || `HTTP ${res.status}`); e.steps = data.steps; throw e; }
    return data;
  }
  function toast(msg) {
    const el = $("toast"); el.textContent = msg; el.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { el.hidden = true; }, 6000);
  }

  function badge(st) {
    if (!st) return `<span class="pt-badge">نامعلوم</span>`;
    if (st.installed && st.running) return `<span class="pt-badge pt-ok">نصب و در حال اجرا</span>`;
    if (st.installed && st.disabled) return `<span class="pt-badge pt-warn">نصب ولی غیرفعال</span>`;
    if (st.installed) return `<span class="pt-badge pt-warn">نصب ولی اجرا نمی‌شود</span>`;
    if (st.partial) return `<span class="pt-badge pt-warn">نیمه‌نصب</span>`;
    return `<span class="pt-badge pt-off">نصب نیست</span>`;
  }

  function render() {
    $("cards").innerHTML = state.patches.map((p) => {
      const st = state.status[p.id];
      const busy = state.busy === p.id;
      const anyBusy = !!state.busy;
      const ver = st && st.installed ? (st.up_to_date ? `<span class="pt-tag pt-ok">به‌روز</span>` : `<span class="pt-tag pt-warn">نسخهٔ قدیمی روی رسیور</span>`) : "";
      const steps = (state.steps[p.id] || []).map((s) => `<li>${esc(s)}</li>`).join("");
      const log = st && st.log && st.log.length ? `<details class="pt-log"><summary>آخرین خطوط گزارش</summary><pre class="ltr">${esc(st.log.join("\n"))}</pre></details>` : "";
      const actions = p.available ? `
          <button class="pt-btn pt-btn-primary" data-act="install" data-id="${p.id}" type="button" ${anyBusy ? "disabled" : ""}>
            ${busy && state.action === "install" ? "در حال نصب…" : (st && st.installed ? (st.up_to_date ? "نصب دوباره" : "به‌روزرسانی") : "نصب")}</button>
          <button class="pt-btn pt-btn-ghost" data-act="remove" data-id="${p.id}" type="button" ${anyBusy || !(st && (st.installed || st.partial)) ? "disabled" : ""}>
            ${busy && state.action === "remove" ? "در حال حذف…" : "حذف (Uninstall)"}</button>
          ${p.can_run ? `<button class="pt-btn pt-btn-ghost" data-act="run" data-id="${p.id}" type="button" ${anyBusy || !(st && st.installed) ? "disabled" : ""}>اجرای فوری</button>` : ""}
          ${p.has_report ? `<button class="pt-btn pt-btn-ghost" data-act="report" data-id="${p.id}" type="button" ${anyBusy || !(st && st.installed) ? "disabled" : ""}>نمایش گزارش</button>` : ""}`
        : `<p class="pt-note">${esc(p.note)}</p>`;
      return `<article class="pt-card${p.available ? "" : " is-soon"}">
        <div class="pt-card-head">
          <h2>${esc(p.title)}</h2>
          ${p.available ? badge(st) : `<span class="pt-badge">به‌زودی</span>`} ${ver}
        </div>
        <p class="pt-summary">${esc(p.summary)}</p>
        ${p.details && p.details.length ? `<ul class="pt-details">${p.details.map((d) => {
          const i = d.indexOf(": ");
          return i > 0 && i < 20 ? `<li><b>${esc(d.slice(0, i))}:</b> ${esc(d.slice(i + 2))}</li>` : `<li>${esc(d)}</li>`;
        }).join("")}</ul>` : ""}
        ${p.tech && p.tech.length ? `<details class="pt-tech"><summary>جزئیات فنی</summary><ul>${p.tech.map((d) => `<li>${esc(d).replace(/(\/[\w.*\/-]+)/g, '<bdi dir="ltr">$1</bdi>')}</li>`).join("")}</ul></details>` : ""}
        ${st && st.running ? `<p class="pt-meta">شناسهٔ فرایند: <span class="ltr">${esc(st.running)}</span></p>` : ""}
        <div class="pt-actions">${actions}</div>
        ${steps ? `<ol class="pt-steps">${steps}</ol>` : ""}
        ${reportHtml(state.reports[p.id])}
        ${log}
      </article>`;
    }).join("");
  }

  async function refresh() {
    $("btnRefresh").disabled = true;
    $("statusMeta").textContent = "در حال خواندن از رسیور…";
    try {
      const data = await api("/api/status", { method: "POST", body: JSON.stringify(conn()) });
      state.status = data.status || {};
      $("statusMeta").textContent = "وضعیت خوانده شد: " + new Date().toLocaleTimeString("fa-IR");
    } catch (err) {
      $("statusMeta").textContent = "";
      toast("خواندن وضعیت ناموفق بود: " + err.message);
    } finally {
      $("btnRefresh").disabled = false;
      render();
    }
  }

  async function showReport(id) {
    state.busy = id; state.action = "report"; render();
    try {
      const data = await api("/api/report", { method: "POST", body: JSON.stringify({ ...conn(), id }) });
      state.reports[id] = data.report;
    } catch (err) { toast(err.message); }
    finally { state.busy = null; render(); }
  }

  async function act(action, id) {
    if (action === "report") return showReport(id);
    const p = state.patches.find((x) => x.id === id);
    if (action === "run") {
      if (!window.confirm(`«${p.title}» همین حالا روی رسیور اجرا شود؟ اگر حالت آن «اعمال» باشد، لیست به‌روز و رسیور راه‌اندازی دوباره می‌شود (حدود ۲ دقیقه)؛ بعد «نمایش گزارش» را بزنید.`)) return;
      state.busy = id; state.action = "run"; render();
      try {
        const data = await api("/api/run", { method: "POST", body: JSON.stringify({ ...conn(), id }) });
        state.steps[id] = data.steps || [];
        toast("اجرا روی رسیور شروع شد.");
      } catch (err) { toast(err.message); }
      finally { state.busy = null; render(); }
      return;
    }
    const q = action === "install" ? `«${p.title}» روی رسیور نصب شود؟` : `«${p.title}» از رسیور حذف شود؟ فایل‌ها و اجرای خودکارش پاک می‌شوند.`;
    if (!window.confirm(q)) return;
    state.busy = id; state.action = action; state.steps[id] = [];
    render();
    try {
      const data = await api(`/api/${action}`, { method: "POST", body: JSON.stringify({ ...conn(), id }) });
      state.status[id] = data.status;
      state.steps[id] = data.steps || [];
      toast(action === "install" ? "نصب شد." : "حذف شد.");
    } catch (err) {
      state.steps[id] = (err.steps || []).concat(["خطا: " + err.message]);
      toast(err.message);
    } finally {
      state.busy = null;
      render();
    }
  }

  $("cards").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-act]");
    if (b && !b.disabled) act(b.dataset.act, b.dataset.id);
  });
  $("btnRefresh").addEventListener("click", refresh);

  initConn();
  api("/api/patches").then((d) => { state.patches = d.patches; render(); refresh(); }).catch((e) => toast(e.message));
})();

(() => {
  const $ = (id) => document.getElementById(id);

  function setPill(online, label) {
    const pill = $("connPill");
    pill.classList.remove("online", "offline", "checking");
    pill.classList.add(online ? "online" : "offline");
    pill.textContent = label || (online ? "وضعیت: آنلاین" : "وضعیت: آفلاین");
  }

  function readForm() {
    return {
      host: $("connHost").value.trim(),
      user: $("connUser").value.trim(),
      password: $("connPass").value,
      simulate: !!$("connSimulate").checked,
    };
  }

  function fillForm(conn) {
    if (!conn) return;
    if (conn.host != null) $("connHost").value = conn.host;
    if (conn.user != null) $("connUser").value = conn.user;
    if (conn.password != null) $("connPass").value = conn.password;
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
    return data;
  }

  function showStatus(text, ok) {
    const el = $("connStatus");
    el.textContent = text || "";
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("err", ok === false);
  }

  async function refresh() {
    setPill(false, "وضعیت: در حال بررسی…");
    $("connPill").classList.add("checking");
    try {
      const data = await api("/api/connection");
      fillForm(data.connection);
      const probe = data.probe || {};
      setPill(!!probe.online, probe.online ? "وضعیت: آنلاین" : "وضعیت: آفلاین");
      showStatus(probe.label || "", !!probe.online);
    } catch (err) {
      setPill(false, "وضعیت: خطا");
      showStatus(String(err.message || err), false);
    }
  }

  $("btnProbe").addEventListener("click", async () => {
    showStatus("در حال تست…", null);
    try {
      const data = await api("/api/connection/probe", {
        method: "POST",
        body: JSON.stringify(readForm()),
      });
      const probe = data.probe || {};
      setPill(!!probe.online, probe.online ? "وضعیت: آنلاین" : "وضعیت: آفلاین");
      showStatus(probe.label || "", !!probe.online);
    } catch (err) {
      setPill(false, "وضعیت: خطا");
      showStatus(String(err.message || err), false);
    }
  });

  $("btnSaveConn").addEventListener("click", async () => {
    showStatus("در حال ذخیره و اعمال…", null);
    try {
      const data = await api("/api/connection", {
        method: "POST",
        body: JSON.stringify(readForm()),
      });
      fillForm(data.connection);
      const probe = data.probe || {};
      setPill(!!probe.online, probe.online ? "وضعیت: آنلاین" : "وضعیت: آفلاین");
      const ch = data.channels && data.channels.status ? data.channels.status.label : "";
      showStatus((probe.label || "ذخیره شد") + (ch ? " — " + ch : ""), !!probe.online || !!readForm().simulate);
    } catch (err) {
      setPill(false, "وضعیت: خطا");
      showStatus(String(err.message || err), false);
    }
  });

  refresh();
})();

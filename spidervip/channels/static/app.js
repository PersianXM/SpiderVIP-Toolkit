(() => {
  const state = {
    channels: [],
    favorites: [],
    activeFav: null,
    pendingBackup: null,
    dragKind: null, // "channel" | "favorite"
    selectedFavRefs: new Set(),
    lastFavClickIndex: null,
    selectedChannelRefs: new Set(),
    lastChannelClickIndex: null,
    visibleChannelRefs: [],
    dragGroupRefs: [],
  };

  const $ = (id) => document.getElementById(id);
  const toast = (msg) => {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 3200);
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
    return data;
  }

  function confirmDialog(title, text) {
    return new Promise((resolve) => {
      const dlg = $("confirmDialog");
      $("confirmTitle").textContent = title;
      $("confirmText").textContent = text;
      dlg.showModal();
      dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true });
    });
  }

  function channelMap() {
    const m = {};
    for (const c of state.channels) m[c.ref] = c;
    return m;
  }

  function satelliteLabel(c) {
    const name = (c.satellite || "").trim();
    const pos = (c.orbital_position || "").trim();
    if (name && pos && name !== pos) return `${name} (${pos})`;
    return name || pos || "Unknown";
  }

  /** Match Enigma-style service refs across bouquet vs lamedb formatting. */
  function serviceIdentity(ref) {
    if (!ref) return null;
    const parts = String(ref).split(":");
    if (parts.length < 7) return null;
    try {
      return [3, 4, 5, 6].map((i) => parseInt(parts[i], 16)).join("|");
    } catch (_) {
      return null;
    }
  }

  /** Favorite list names that already include this channel. */
  function favoriteNamesForChannel(channelRef, favIndex) {
    const names = [];
    const seen = new Set();
    const add = (list) => {
      for (const n of list || []) {
        if (!seen.has(n)) {
          seen.add(n);
          names.push(n);
        }
      }
    };
    add(favIndex.byRef.get(channelRef));
    const key = serviceIdentity(channelRef);
    if (key) add(favIndex.byKey.get(key));
    return names;
  }

  function buildFavoriteIndex() {
    const byRef = new Map();
    const byKey = new Map();
    const remember = (ref, favName) => {
      if (!ref) return;
      if (!byRef.has(ref)) byRef.set(ref, []);
      if (!byRef.get(ref).includes(favName)) byRef.get(ref).push(favName);
      const key = serviceIdentity(ref);
      if (!key) return;
      if (!byKey.has(key)) byKey.set(key, []);
      if (!byKey.get(key).includes(favName)) byKey.get(key).push(favName);
    };
    for (const fav of state.favorites) {
      for (const ref of fav.channel_refs || []) remember(ref, fav.name);
      for (const ch of fav.channels || []) remember(ch.ref, fav.name);
    }
    return { byRef, byKey };
  }

  function updateChannelSelectionUI() {
    const count = state.selectedChannelRefs.size;
    const label = $("chSelCount");
    if (label) {
      label.textContent = count
        ? `${count} selected — drag any selected row to Favorites`
        : "Multi-select, then drag together to Favorites";
    }
    document.querySelectorAll(".channel-item").forEach((row) => {
      const on = state.selectedChannelRefs.has(row.dataset.ref);
      row.classList.toggle("selected", on);
      const cb = row.querySelector(".ch-check");
      if (cb) cb.checked = on;
    });
  }

  function renderChannels() {
    const q = $("search").value.trim().toLowerCase();
    const sat = $("satFilter").value;
    const hd = $("hdFilter").value;
    const list = $("channelList");
    list.innerHTML = "";

    const filtered = state.channels.filter((c) => {
      if ((c.service_type || "TV").toLowerCase() === "radio") return false;
      if (sat && c.satellite !== sat && c.orbital_position !== sat) return false;
      if (hd === "1" && !c.is_hd) return false;
      if (hd === "0" && c.is_hd) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        String(c.number).includes(q) ||
        (c.satellite || "").toLowerCase().includes(q) ||
        (c.orbital_position || "").toLowerCase().includes(q)
      );
    });

    state.visibleChannelRefs = filtered.map((c) => c.ref);
    state.selectedChannelRefs = new Set(
      [...state.selectedChannelRefs].filter((r) => state.visibleChannelRefs.includes(r))
    );

    $("channelCount").textContent = `${filtered.length} TV channels`;

    const favIndex = buildFavoriteIndex();
    const groups = {};
    for (const c of filtered) {
      const key = satelliteLabel(c);
      (groups[key] ||= []).push(c);
    }

    let flatIndex = 0;
    for (const [satellite, channels] of Object.entries(groups).sort()) {
      const h = document.createElement("div");
      h.className = "muted";
      h.style.padding = "10px 8px 6px";
      h.textContent = `${satellite} · ${channels.length}`;
      list.appendChild(h);

      for (const c of channels) {
        const idx = flatIndex;
        flatIndex += 1;
        const favNames = favoriteNamesForChannel(c.ref, favIndex);
        const inFav = favNames.length > 0;
        const heartTitle = inFav ? `In favorites: ${favNames.join(", ")}` : "";
        const row = document.createElement("div");
        row.className = "list-item channel-item" + (state.selectedChannelRefs.has(c.ref) ? " selected" : "");
        row.draggable = true;
        row.dataset.ref = c.ref;
        row.dataset.index = String(idx);
        row.title = inFav
          ? `${heartTitle}. Select multiple, then drag to Favorites`
          : "Select multiple, then drag to Favorites";
        row.innerHTML = `
          <input class="ch-check" type="checkbox" ${state.selectedChannelRefs.has(c.ref) ? "checked" : ""} title="Select" />
          <div class="num">${c.number || "–"}</div>
          <div class="meta">
            <strong>
              ${escapeHtml(c.name)}
              ${inFav ? `<span class="fav-heart" title="${escapeAttr(heartTitle)}" aria-label="${escapeAttr(heartTitle)}">♥</span>` : ""}
            </strong>
            <div class="tags">
              <span class="tag sat">${escapeHtml(satelliteLabel(c))}</span>
              ${c.is_hd ? '<span class="tag hd">HD</span>' : '<span class="tag">SD</span>'}
              ${c.frequency ? `<span class="tag">${escapeHtml(String(c.frequency))} ${escapeHtml(c.polarization || "")}</span>` : ""}
              ${inFav ? `<span class="tag fav">${escapeHtml(favNames.length === 1 ? favNames[0] : favNames.length + " lists")}</span>` : ""}
            </div>
          </div>
        `;

        const toggleSelect = (additive, range) => {
          if (range && state.lastChannelClickIndex != null) {
            const start = Math.min(state.lastChannelClickIndex, idx);
            const end = Math.max(state.lastChannelClickIndex, idx);
            if (!additive) state.selectedChannelRefs = new Set();
            for (let i = start; i <= end; i += 1) {
              state.selectedChannelRefs.add(state.visibleChannelRefs[i]);
            }
          } else if (additive) {
            if (state.selectedChannelRefs.has(c.ref)) state.selectedChannelRefs.delete(c.ref);
            else state.selectedChannelRefs.add(c.ref);
          } else {
            if (state.selectedChannelRefs.has(c.ref) && state.selectedChannelRefs.size === 1) {
              state.selectedChannelRefs = new Set();
            } else {
              state.selectedChannelRefs = new Set([c.ref]);
            }
          }
          state.lastChannelClickIndex = idx;
          updateChannelSelectionUI();
        };

        row.querySelector(".ch-check").addEventListener("click", (e) => {
          e.stopPropagation();
          toggleSelect(true, e.shiftKey);
        });
        row.addEventListener("click", (e) => {
          if (e.target.classList.contains("ch-check")) return;
          toggleSelect(e.ctrlKey || e.metaKey, e.shiftKey);
        });

        row.addEventListener("dragstart", (e) => {
          if (!state.selectedChannelRefs.has(c.ref)) {
            state.selectedChannelRefs = new Set([c.ref]);
            updateChannelSelectionUI();
          }
          const group = state.visibleChannelRefs.filter((r) => state.selectedChannelRefs.has(r));
          state.dragKind = "channel";
          state.dragGroupRefs = group;
          row.classList.add("dragging");
          document.querySelectorAll(".channel-item").forEach((el) => {
            if (state.selectedChannelRefs.has(el.dataset.ref)) el.classList.add("dragging");
          });
          e.dataTransfer.setData("text/plain", group.join("\n"));
          e.dataTransfer.setData("application/x-spidervip-channel", c.ref);
          e.dataTransfer.setData("application/x-spidervip-channels", JSON.stringify(group));
          e.dataTransfer.effectAllowed = "copy";
        });
        row.addEventListener("dragend", () => {
          document.querySelectorAll(".channel-item.dragging").forEach((el) => el.classList.remove("dragging"));
          state.dragKind = null;
          state.dragGroupRefs = [];
          $("favDropZone").classList.remove("drag-over");
        });
        list.appendChild(row);
      }
    }
    updateChannelSelectionUI();
  }

  function fillSatFilter() {
    const sel = $("satFilter");
    const current = sel.value;
    const sats = [...new Set(
      state.channels
        .filter((c) => (c.service_type || "TV").toLowerCase() !== "radio")
        .map((c) => c.satellite)
        .filter(Boolean)
    )].sort();
    sel.innerHTML = `<option value="">All satellites</option>` +
      sats.map((s) => `<option value="${escapeAttr(s)}">${escapeHtml(s)}</option>`).join("");
    sel.value = current;
  }

  function moveSelectedGroup(refs, selectedSet, direction) {
    const selected = refs.filter((r) => selectedSet.has(r));
    if (!selected.length) return refs;
    const indices = refs
      .map((r, i) => (selectedSet.has(r) ? i : -1))
      .filter((i) => i >= 0);
    const others = refs.filter((r) => !selectedSet.has(r));
    if (direction === "up") {
      if (indices[0] === 0) return refs;
      let at = 0;
      for (let i = 0; i < indices[0] - 1; i += 1) {
        if (!selectedSet.has(refs[i])) at += 1;
      }
      return others.slice(0, at).concat(selected, others.slice(at));
    }
    const after = indices[indices.length - 1] + 1;
    if (after >= refs.length) return refs;
    let at = 0;
    for (let i = 0; i <= after; i += 1) {
      if (!selectedSet.has(refs[i])) at += 1;
    }
    return others.slice(0, at).concat(selected, others.slice(at));
  }

  /** Channels moved/removed by row controls: whole selection if the clicked row is selected. */
  function jumpGroupFor(channelRefs, ref) {
    if (state.selectedFavRefs.has(ref) && state.selectedFavRefs.size > 1) {
      const group = channelRefs.filter((r) => state.selectedFavRefs.has(r));
      if (group.length) return group;
      // Selection may use display refs; fall back to DOM order of selected rows.
      const fromDom = [...document.querySelectorAll(".fav-item")]
        .map((el) => el.dataset.ref)
        .filter((r) => state.selectedFavRefs.has(r));
      if (fromDom.length) return fromDom;
    }
    return channelRefs.includes(ref) ? [ref] : [ref];
  }

  function groupAtEdge(channelRefs, group, edge) {
    if (!group.length) return true;
    if (edge === "top") {
      return channelRefs.slice(0, group.length).join("\0") === group.join("\0");
    }
    return channelRefs.slice(-group.length).join("\0") === group.join("\0");
  }

  function updateFavDockStates(channelRefs) {
    document.querySelectorAll(".fav-item").forEach((row) => {
      const ref = row.dataset.ref;
      const group = jumpGroupFor(channelRefs, ref);
      const multi = group.length > 1;
      const topBtn = row.querySelector("[data-top]");
      const bottomBtn = row.querySelector("[data-bottom]");
      const removeBtn = row.querySelector("[data-rm]");
      if (topBtn) {
        topBtn.disabled = groupAtEdge(channelRefs, group, "top");
        topBtn.title = multi ? `Move ${group.length} selected to top` : "Move to top";
        topBtn.setAttribute("aria-label", topBtn.title);
      }
      if (bottomBtn) {
        bottomBtn.disabled = groupAtEdge(channelRefs, group, "bottom");
        bottomBtn.title = multi ? `Move ${group.length} selected to bottom` : "Move to bottom";
        bottomBtn.setAttribute("aria-label", bottomBtn.title);
      }
      if (removeBtn) {
        removeBtn.title = multi ? `Remove ${group.length} selected` : "Remove";
        removeBtn.setAttribute("aria-label", removeBtn.title);
      }
    });
  }

  function updateFavSelectionUI() {
    const count = state.selectedFavRefs.size;
    const label = $("favSelCount");
    if (label) {
      label.textContent = count
        ? `${count} selected — jump top/bottom, remove, drag, or ↑ / ↓`
        : "Multi-select, then jump, remove, drag, or use ↑ / ↓";
    }
    document.querySelectorAll(".fav-item").forEach((row) => {
      const on = state.selectedFavRefs.has(row.dataset.ref);
      row.classList.toggle("selected", on);
      const cb = row.querySelector(".fav-check");
      if (cb) cb.checked = on;
    });
    const fav = state.favorites.find((f) => f.id === state.activeFav);
    if (fav) updateFavDockStates(fav.channel_refs);
  }

  async function persistFavoriteOrder(favId, refs) {
    await api(`/api/favorites/${encodeURIComponent(favId)}/reorder`, {
      method: "POST",
      body: JSON.stringify({ channel_refs: refs }),
    });
    await refresh();
  }

  function renderFavorites() {
    const tabs = $("favTabs");
    tabs.innerHTML = "";
    const tvFavorites = state.favorites.filter((f) => !String(f.id).endsWith("_radio"));
    if (!tvFavorites.length) {
      state.activeFav = null;
      state.selectedFavRefs = new Set();
      state.lastFavClickIndex = null;
      $("favChannels").innerHTML = `<p class="muted empty-fav" style="padding:12px">No favorites yet. Create one, then drag TV channels here.</p>`;
      updateFavSelectionUI();
      return;
    }
    if (!state.activeFav || !tvFavorites.find((f) => f.id === state.activeFav)) {
      state.activeFav = tvFavorites[0].id;
      state.selectedFavRefs = new Set();
      state.lastFavClickIndex = null;
    }

    for (const f of tvFavorites) {
      const tab = document.createElement("button");
      tab.className = "tab" + (f.id === state.activeFav ? " active" : "");
      tab.innerHTML = `${escapeHtml(f.name)}<span class="count">${f.count ?? f.channel_refs.length}</span>`;
      tab.addEventListener("click", () => {
        if (state.activeFav !== f.id) {
          state.selectedFavRefs = new Set();
          state.lastFavClickIndex = null;
        }
        state.activeFav = f.id;
        renderFavorites();
      });
      tab.addEventListener("dblclick", async () => {
        const name = prompt("Rename favorite", f.name);
        if (!name) return;
        await api(`/api/favorites/${encodeURIComponent(f.id)}/rename`, {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        await refresh();
      });
      tabs.appendChild(tab);
    }

    const del = document.createElement("button");
    del.className = "ghost compact";
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      const fav = tvFavorites.find((f) => f.id === state.activeFav);
      if (!fav) return;
      if (!(await confirmDialog("Delete favorite", `Delete “${fav.name}”? This cannot be undone.`))) return;
      await api(`/api/favorites/${encodeURIComponent(fav.id)}`, { method: "DELETE" });
      state.activeFav = null;
      state.selectedFavRefs = new Set();
      await refresh();
    });
    tabs.appendChild(del);

    const fav = tvFavorites.find((f) => f.id === state.activeFav);
    const box = $("favChannels");
    box.innerHTML = "";
    const resolved = fav.channels || [];
    const rows = resolved.length
      ? resolved
      : fav.channel_refs.map((ref) => ({ ref, name: ref }));
    // Drop selection entries that no longer exist
    state.selectedFavRefs = new Set(
      [...state.selectedFavRefs].filter((r) => fav.channel_refs.includes(r))
    );
    if (!fav.channel_refs.length) {
      box.innerHTML = `<p class="muted empty-fav" style="padding:12px">Drop TV channels here to build “${escapeHtml(fav.name)}”.</p>`;
      updateFavSelectionUI();
      return;
    }

    rows.forEach((c, idx) => {
      const ref = c.ref;
      const row = document.createElement("div");
      row.className = "fav-item" + (state.selectedFavRefs.has(ref) ? " selected" : "");
      row.draggable = true;
      row.dataset.ref = ref;
      row.dataset.index = String(idx);
      row.innerHTML = `
        <input class="fav-check" type="checkbox" ${state.selectedFavRefs.has(ref) ? "checked" : ""} title="Select for group move" />
        <div class="num">${c.number || idx + 1}</div>
        <div class="meta">
          <strong>${escapeHtml(c.name || ref)}</strong>
          <div class="tags">
            <span class="tag sat">${escapeHtml(satelliteLabel(c))}</span>
            ${c.is_hd ? '<span class="tag hd">HD</span>' : ""}
            ${c.unresolved ? '<span class="tag">unresolved</span>' : ""}
          </div>
        </div>
        <div class="fav-actions">
          <button class="fav-act top" type="button" title="Move to top" data-top="${escapeAttr(ref)}" aria-label="Move to top">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="M3 2h10v1.75H3z"/>
              <path fill="currentColor" d="M8 4.6 3.9 8.7h2.35V14h3.5V8.7h2.35z"/>
            </svg>
          </button>
          <button class="fav-act bottom" type="button" title="Move to bottom" data-bottom="${escapeAttr(ref)}" aria-label="Move to bottom">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="M8 11.4 12.1 7.3H9.75V2H6.25v5.3H3.9z"/>
              <path fill="currentColor" d="M3 12.25h10V14H3z"/>
            </svg>
          </button>
          <button class="fav-act remove" type="button" title="Remove" data-rm="${escapeAttr(ref)}" aria-label="Remove">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="m4.05 3.15-.9.9L7.1 8l-3.95 3.95.9.9L8 8.9l3.95 3.95.9-.9L8.9 8l3.95-3.95-.9-.9L8 7.1z"/>
            </svg>
          </button>
        </div>
      `;

      const toggleSelect = (additive, range) => {
        if (range && state.lastFavClickIndex != null) {
          const start = Math.min(state.lastFavClickIndex, idx);
          const end = Math.max(state.lastFavClickIndex, idx);
          if (!additive) state.selectedFavRefs = new Set();
          for (let i = start; i <= end; i += 1) {
            state.selectedFavRefs.add(rows[i].ref);
          }
        } else if (additive) {
          if (state.selectedFavRefs.has(ref)) state.selectedFavRefs.delete(ref);
          else state.selectedFavRefs.add(ref);
        } else {
          if (state.selectedFavRefs.has(ref) && state.selectedFavRefs.size === 1) {
            state.selectedFavRefs = new Set();
          } else {
            state.selectedFavRefs = new Set([ref]);
          }
        }
        state.lastFavClickIndex = idx;
        updateFavSelectionUI();
      };

      row.querySelector(".fav-check").addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSelect(true, e.shiftKey);
      });
      row.addEventListener("click", (e) => {
        if (e.target.closest(".fav-actions") || e.target.classList.contains("fav-check")) return;
        toggleSelect(e.ctrlKey || e.metaKey, e.shiftKey);
      });

      row.querySelector("[data-top]").addEventListener("click", async (e) => {
        e.stopPropagation();
        const group = jumpGroupFor(fav.channel_refs, ref);
        const selected = new Set(group);
        const others = fav.channel_refs.filter((r) => !selected.has(r));
        const next = group.concat(others);
        if (next.join("\0") === fav.channel_refs.join("\0")) return;
        await persistFavoriteOrder(fav.id, next);
      });
      row.querySelector("[data-bottom]").addEventListener("click", async (e) => {
        e.stopPropagation();
        const group = jumpGroupFor(fav.channel_refs, ref);
        const selected = new Set(group);
        const others = fav.channel_refs.filter((r) => !selected.has(r));
        const next = others.concat(group);
        if (next.join("\0") === fav.channel_refs.join("\0")) return;
        await persistFavoriteOrder(fav.id, next);
      });
      row.querySelector("[data-rm]").addEventListener("click", async (e) => {
        e.stopPropagation();
        e.preventDefault();
        const group = jumpGroupFor(fav.channel_refs, ref);
        if (!group.length) {
          toast("Nothing to remove");
          return;
        }
        try {
          await api(`/api/favorites/${encodeURIComponent(fav.id)}/remove`, {
            method: "POST",
            body: JSON.stringify({ channel_refs: group }),
          });
          group.forEach((r) => state.selectedFavRefs.delete(r));
          state.selectedFavRefs.delete(ref);
          toast(
            group.length > 1
              ? `Removed ${group.length} channels`
              : "Removed from favorites"
          );
          await refresh();
        } catch (err) {
          toast(err.message || "Remove failed");
        }
      });
      row.addEventListener("dragstart", (e) => {
        if (!state.selectedFavRefs.has(ref)) {
          state.selectedFavRefs = new Set([ref]);
          updateFavSelectionUI();
        }
        state.dragKind = "favorite";
        state.dragGroupRefs = fav.channel_refs.filter((r) => state.selectedFavRefs.has(r));
        row.classList.add("dragging");
        document.querySelectorAll(".fav-item").forEach((el) => {
          if (state.selectedFavRefs.has(el.dataset.ref) && el !== row) {
            el.classList.add("drag-hidden");
          }
        });
        e.dataTransfer.setData("text/plain", ref);
        e.dataTransfer.setData(
          "application/x-spidervip-fav-group",
          JSON.stringify(state.dragGroupRefs)
        );
        e.dataTransfer.effectAllowed = "move";
      });
      row.addEventListener("dragend", async () => {
        row.classList.remove("dragging");
        const primary = ref;
        const group = state.dragGroupRefs.length
          ? state.dragGroupRefs
          : [primary];
        const selected = new Set(group);
        const visible = [...box.querySelectorAll(".fav-item:not(.drag-hidden)")];
        const visibleRefs = visible.map((el) => el.dataset.ref);
        const at = Math.max(0, visibleRefs.indexOf(primary));
        const others = fav.channel_refs.filter((r) => !selected.has(r));
        // Map primary slot among visible (others + primary) onto others insert index
        let insertAt = 0;
        for (let i = 0; i < at; i += 1) {
          if (!selected.has(visibleRefs[i])) insertAt += 1;
        }
        const next = others.slice(0, insertAt).concat(group, others.slice(insertAt));
        document.querySelectorAll(".fav-item.drag-hidden").forEach((el) => {
          el.classList.remove("drag-hidden");
        });
        state.dragKind = null;
        state.dragGroupRefs = [];
        if (next.join("\0") !== fav.channel_refs.join("\0")) {
          await persistFavoriteOrder(fav.id, next);
        } else {
          updateFavSelectionUI();
        }
      });
      row.addEventListener("dragover", (e) => {
        if (state.dragKind !== "favorite") return;
        e.preventDefault();
        const dragging = box.querySelector(".fav-item.dragging");
        if (!dragging || dragging === row || row.classList.contains("drag-hidden")) return;
        const rect = row.getBoundingClientRect();
        const after = e.clientY > rect.top + rect.height / 2;
        box.insertBefore(dragging, after ? row.nextSibling : row);
      });
      box.appendChild(row);
    });
    updateFavSelectionUI();
  }

  function setupFavoriteDropZone() {
    const zone = $("favDropZone");
    zone.addEventListener("dragover", (e) => {
      if (state.dragKind !== "channel") return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      if (state.dragKind === "favorite") return;
      let refs = [];
      try {
        refs = JSON.parse(e.dataTransfer.getData("application/x-spidervip-channels") || "[]");
      } catch (_) {
        refs = [];
      }
      if (!refs.length) {
        const one =
          e.dataTransfer.getData("application/x-spidervip-channel") ||
          e.dataTransfer.getData("text/plain");
        if (one) refs = one.split("\n").map((s) => s.trim()).filter(Boolean);
      }
      if (!refs.length) return;
      if (!state.activeFav) {
        toast("Create or select a Favorites list first");
        return;
      }
      try {
        await api(`/api/favorites/${encodeURIComponent(state.activeFav)}/add_many`, {
          method: "POST",
          body: JSON.stringify({ channel_refs: refs }),
        });
        toast(`Added ${refs.length} channel${refs.length > 1 ? "s" : ""}`);
        await refresh();
      } catch (err) {
        toast(err.message);
      }
    });
  }

  async function refresh() {
    const data = await api("/api/state");
    state.channels = (data.channels || []).filter(
      (c) => (c.service_type || "TV").toLowerCase() !== "radio"
    );
    state.favorites = (data.favorites || []).filter((f) => !String(f.id).endsWith("_radio"));
    state.motorProfile = data.motor_profile || null;
    $("banner").hidden = false;
    $("banner").textContent = data.persistence_warning || "";
    if (data.apply) {
      $("applyStatus").textContent = `${data.apply.status}: ${data.apply.message}`;
      $("applySteps").innerHTML = (data.apply.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
      const st = applyStageFromStatus(data.apply.status, data.apply.message);
      if (st.filled || st.current || st.failed) setApplyProgress(st);
    }
    fillSatFilter();
    renderChannels();
    renderFavorites();
    loadUpdates();
    updateConnectionStatus();
  }

  function setConnectionDot({ online, label }) {
    const el = $("connStatus");
    el.classList.remove("online", "offline", "checking");
    el.classList.add(online ? "online" : "offline");
    el.title = label || (online ? "Receiver connected" : "Receiver disconnected");
  }

  async function updateConnectionStatus() {
    const el = $("connStatus");
    el.classList.remove("online", "offline");
    el.classList.add("checking");
    el.title = "Checking receiver connection…";
    try {
      const data = await api("/api/receiver/status");
      setConnectionDot({
        online: !!data.online,
        label: data.label || "",
      });
    } catch (_) {
      setConnectionDot({ online: false, label: "Receiver disconnected" });
    }
  }

  async function loadUpdates() {
    try {
      const data = await api("/api/updates");
      const box = $("updateList");
      if (!data.updates?.length) {
        box.textContent = "No updates in catalog.";
        return;
      }
      box.innerHTML = "";
      for (const u of data.updates) {
        const el = document.createElement("div");
        el.className = "update-item";
        el.innerHTML = `
          <strong>${escapeHtml(u.title)} · v${escapeHtml(u.version)}</strong>
          <div class="muted">${escapeHtml(u.changelog || "")}</div>
          <div class="row" style="margin-top:8px">
            <button class="ghost compact" data-preview>Preview</button>
            <button class="primary compact" data-apply>Apply Update</button>
          </div>
        `;
        el.querySelector("[data-preview]").addEventListener("click", async () => {
          const preview = await api("/api/updates/preview", {
            method: "POST",
            body: JSON.stringify({ url: u.url }),
          });
          toast(`Update ${preview.diff.update_version}: +${preview.diff.favorites_added.length} / -${preview.diff.favorites_removed.length} favorites`);
        });
        el.querySelector("[data-apply]").addEventListener("click", async () => {
          if (!(await confirmDialog("Apply online update", `Apply “${u.title}” v${u.version}? A safety backup will be created first.`))) return;
          await api("/api/updates/apply", { method: "POST", body: JSON.stringify({ url: u.url }) });
          toast("Update applied to workspace");
          await refresh();
        });
        box.appendChild(el);
      }
    } catch (err) {
      $("updateList").textContent = err.message;
    }
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/`/g, ""); }

  $("search").addEventListener("input", renderChannels);
  $("satFilter").addEventListener("change", renderChannels);
  $("hdFilter").addEventListener("change", renderChannels);

  $("btnNewFav").addEventListener("click", async () => {
    const name = prompt("Favorite name", "My Favorites");
    if (!name) return;
    const res = await api("/api/favorites", { method: "POST", body: JSON.stringify({ name }) });
    state.activeFav = res.favorite.id;
    await refresh();
  });

  document.querySelectorAll("[data-sort]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!state.activeFav) return;
      await api(`/api/favorites/${encodeURIComponent(state.activeFav)}/sort`, {
        method: "POST",
        body: JSON.stringify({ key: btn.dataset.sort }),
      });
      await refresh();
    });
  });

  $("btnFavSelectAll").addEventListener("click", () => {
    const fav = state.favorites.find((f) => f.id === state.activeFav);
    if (!fav) return;
    state.selectedFavRefs = new Set(fav.channel_refs || []);
    updateFavSelectionUI();
  });

  $("btnFavClearSel").addEventListener("click", () => {
    state.selectedFavRefs = new Set();
    state.lastFavClickIndex = null;
    updateFavSelectionUI();
  });

  $("btnChSelectAll").addEventListener("click", () => {
    state.selectedChannelRefs = new Set(state.visibleChannelRefs);
    updateChannelSelectionUI();
  });

  $("btnChClearSel").addEventListener("click", () => {
    state.selectedChannelRefs = new Set();
    state.lastChannelClickIndex = null;
    updateChannelSelectionUI();
  });

  async function moveFavoriteSelection(direction) {
    const fav = state.favorites.find((f) => f.id === state.activeFav);
    if (!fav || !state.selectedFavRefs.size) {
      toast("Select one or more favorite channels first");
      return;
    }
    const next = moveSelectedGroup(fav.channel_refs, state.selectedFavRefs, direction);
    if (next.join("\0") === fav.channel_refs.join("\0")) return;
    await persistFavoriteOrder(fav.id, next);
  }

  $("btnFavMoveUp").addEventListener("click", () => moveFavoriteSelection("up"));
  $("btnFavMoveDown").addEventListener("click", () => moveFavoriteSelection("down"));

  $("btnBackup").addEventListener("click", async () => {
    const res = await api("/api/backup", { method: "POST", body: "{}" });
    toast(`Backup saved: ${res.filename}`);
  });

  $("restoreFile").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    let payload;
    try { payload = JSON.parse(text); }
    catch { toast("Invalid JSON file"); return; }
    try {
      const res = await api("/api/backup/preview", { method: "POST", body: JSON.stringify(payload) });
      state.pendingBackup = payload;
      $("restorePreview").hidden = false;
      $("restorePreview").textContent =
        `v${res.preview.format_version} · ${res.preview.favorite_count} favorites · ${res.preview.channel_count} channels\n` +
        (res.preview.favorites || []).map((f) => `• ${f.name} (${f.count})`).join("\n");
      $("btnRestore").disabled = false;
    } catch (err) {
      state.pendingBackup = null;
      $("btnRestore").disabled = true;
      $("restorePreview").hidden = false;
      $("restorePreview").textContent = err.message;
    }
  });

  $("btnRestore").addEventListener("click", async () => {
    if (!state.pendingBackup) return;
    if (!(await confirmDialog("Restore backup", "Replace local favorites (and channels) with this backup?"))) return;
    await api("/api/backup/restore", { method: "POST", body: JSON.stringify(state.pendingBackup) });
    toast("Backup restored into workspace");
    await refresh();
  });

  function applyStageFromStatus(status, message) {
    const s = String(status || "").toLowerCase();
    const m = String(message || "").toLowerCase();
    if (s.includes("fail")) return { filled: 0, current: 0, failed: true };
    if (s.includes("completed")) return { filled: 5, current: 0, failed: false };
    if (s.includes("reboot")) return { filled: 3, current: 4, failed: false };
    if (s.includes("verif")) {
      // Post-commit verify vs post-reboot verify
      if (m.includes("reboot") || m.includes("settle") || m.includes("after reboot")) {
        return { filled: 4, current: 5, failed: false };
      }
      return { filled: 2, current: 3, failed: false };
    }
    if (s.includes("upload")) return { filled: 1, current: 2, failed: false };
    if (s.includes("apply")) return { filled: 2, current: 3, failed: false };
    if (s.includes("validat") || s.includes("prepar") || s.includes("load")) {
      return { filled: 0, current: 1, failed: false };
    }
    if (s.includes("idle") || !s) return { filled: 0, current: 0, failed: false };
    return { filled: 0, current: 1, failed: false };
  }

  function setApplyProgress(stage) {
    const bar = $("applyProgress");
    if (!bar) return;
    bar.hidden = false;
    const filled = stage.filled || 0;
    const current = stage.current || 0;
    const failed = !!stage.failed;
    bar.querySelectorAll(".apply-seg").forEach((el) => {
      const n = Number(el.getAttribute("data-seg"));
      el.classList.remove("on", "current", "fail");
      if (failed && current && n === current) {
        el.classList.add("fail");
      } else if (n <= filled) {
        el.classList.add("on");
      } else if (n === current) {
        el.classList.add("current");
      }
    });
  }

  function hideApplyProgress() {
    const bar = $("applyProgress");
    if (!bar) return;
    bar.hidden = true;
    bar.querySelectorAll(".apply-seg").forEach((el) => {
      el.classList.remove("on", "current", "fail");
    });
  }

  async function pollApplyProgress(stopFlag) {
    while (!stopFlag.done) {
      try {
        const data = await api("/api/state");
        const pipe = data.pipeline || {};
        const status = pipe.status || "";
        const message = pipe.message || "";
        if (status && status !== "Idle") {
          $("applyStatus").textContent = `${status}: ${message}`;
          setApplyProgress(applyStageFromStatus(status, message));
        }
        if (Array.isArray(pipe.steps) && pipe.steps.length) {
          $("applySteps").innerHTML = pipe.steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("");
        }
      } catch (_) {
        // ignore transient poll errors while apply runs
      }
      await new Promise((r) => setTimeout(r, 800));
    }
  }

  $("btnPull").addEventListener("click", async () => {
    if (!(await confirmDialog("Pull from receiver", "Replace the local workspace with TV channels and favorites from the receiver?"))) return;
    $("applyStatus").textContent = "Loading: pulling from receiver…";
    try {
      const res = await api("/api/receiver/pull", { method: "POST", body: "{}" });
      toast(`Pulled ${res.channel_count} channels, ${res.favorite_count} favorites`);
      await refresh();
    } catch (err) {
      toast(err.message);
    }
  });

  $("btnApply").addEventListener("click", async () => {
    if (!(await confirmDialog(
      "Apply to receiver",
      "This uploads Favorites, commits them into live_prog, restores Motor settings, "
      + "then reboots to verify. Continue?"
    ))) return;
    $("btnApply").disabled = true;
    $("applyStatus").textContent = "Preparing…";
    $("applySteps").innerHTML = "";
    setApplyProgress({ filled: 0, current: 1, failed: false });
    const stopFlag = { done: false };
    const poller = pollApplyProgress(stopFlag);
    try {
      const res = await api("/api/receiver/apply", {
        method: "POST",
        body: JSON.stringify({ reboot: true }),
      });
      stopFlag.done = true;
      await poller;
      const report = res.report || {};
      $("applyStatus").textContent = `${report.status}: ${report.message}`;
      $("applySteps").innerHTML = (report.steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
      if (String(report.status || "").toLowerCase().includes("completed") && report.verified !== false) {
        setApplyProgress({ filled: 5, current: 0, failed: false });
      } else {
        setApplyProgress({ filled: 0, current: 3, failed: true });
      }
      toast(report.message || report.status);
    } catch (err) {
      stopFlag.done = true;
      await poller;
      $("applyStatus").textContent = `Failed: ${err.message}`;
      setApplyProgress({ filled: 0, current: 3, failed: true });
      toast(err.message);
    } finally {
      $("btnApply").disabled = false;
    }
  });

  setupFavoriteDropZone();
  refresh().catch((err) => toast(err.message));
  setInterval(updateConnectionStatus, 8000);
})();

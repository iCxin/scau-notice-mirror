(() => {
  "use strict";

  const state = {
    items: [],
    sourceNames: {},
    terms: [],
    q: "",
    source: "all",
    range: "all",
    contentOnly: false,
    sort: "date",
    page: 0,
    pageSize: 30,
    filtered: [],
    loadingMore: false,
  };

  const detailCache = new Map();
  const $ = (sel) => document.querySelector(sel);

  const listEl = $("#list");
  const emptyEl = $("#empty");
  const emptyTextEl = $("#emptyText");
  const moreBtn = $("#moreBtn");
  const moreWrap = document.querySelector(".more-wrap");
  const countEl = $("#resultCount");
  const activeQueryEl = $("#activeQuery");
  const headerMeta = $("#headerMeta");
  const footerMeta = $("#footerMeta");
  const qInput = $("#q");
  const clearBtn = $("#clearBtn");
  const sourceChips = $("#sourceChips");
  const rangeChips = $("#rangeChips");
  const contentOnly = $("#contentOnly");
  const sortSelect = $("#sort");
  const dialog = $("#detail");
  const detailMeta = $("#detailMeta");
  const detailBody = $("#detailBody");

  /* ---------- 工具 ---------- */

  const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  function escapeHtml(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, (ch) => ESC_MAP[ch]);
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlight(text, terms) {
    const escaped = escapeHtml(text);
    if (!terms.length) return escaped;
    const pattern = terms
      .slice()
      .sort((a, b) => b.length - a.length)
      .map(escapeRegExp)
      .join("|");
    if (!pattern) return escaped;
    try {
      return escaped.replace(new RegExp(`(${pattern})`, "gi"), "<mark>$1</mark>");
    } catch (err) {
      return escaped;
    }
  }

  function cmpDateDesc(a, b) {
    if (!a.d && !b.d) return 0;
    if (!a.d) return 1;
    if (!b.d) return -1;
    return b.d.localeCompare(a.d);
  }

  function inRange(dateStr) {
    if (state.range === "all") return true;
    if (!dateStr) return false;
    const days = Number(state.range);
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - days + 1);
    const value = new Date(`${dateStr}T00:00:00`);
    return value >= start;
  }

  function scoreOf(item, terms) {
    let score = 0;
    for (const term of terms) {
      if (item._t.includes(term)) score += 12;
      if (item._x.includes(term)) score += 2;
    }
    if (terms.length && item._t.includes(state.q.toLowerCase())) score += 8;
    return score;
  }

  function snippetFor(item, terms) {
    const text = item.x || "";
    if (!text) return "";
    if (!terms.length) {
      return text.length > 130 ? `${text.slice(0, 130)}…` : text;
    }
    const lower = text.toLowerCase();
    let pos = -1;
    for (const term of terms) {
      const found = lower.indexOf(term);
      if (found >= 0 && (pos < 0 || found < pos)) pos = found;
    }
    if (pos < 0) return text.length > 130 ? `${text.slice(0, 130)}…` : text;
    const start = Math.max(0, pos - 50);
    const end = Math.min(text.length, start + 150);
    return `${start > 0 ? "…" : ""}${text.slice(start, end)}${end < text.length ? "…" : ""}`;
  }

  function sourceTag(item) {
    const name = state.sourceNames[item.s] || item.c || "通知";
    return `<span class="tag src-${escapeHtml(item.s)}">${escapeHtml(name)}</span>`;
  }

  function statusTag(item) {
    if (item.st === "login_required") return '<span class="tag flag-login">需登录</span>';
    if (item.st === "removed") return '<span class="tag flag-off">原文已下线</span>';
    if (item.a > 0) return `<span class="tag flag-pdf">附件 ${item.a}</span>`;
    return "";
  }

  /* ---------- 数据加载 ---------- */

  async function init() {
    bindEvents();
    try {
      const res = await fetch("data/index.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const sources = data.sources || [];
      sources.forEach((source) => {
        state.sourceNames[source.key] = source.name;
      });

      state.items = (data.items || []).map((item) => ({
        ...item,
        _t: (item.t || "").toLowerCase(),
        _x: (item.x || "").toLowerCase(),
      }));

      buildSourceChips(sources, data.count || 0);
      updateMeta(data);
      applyFilters();
    } catch (err) {
      countEl.textContent = "数据加载失败";
      activeQueryEl.textContent = "请确认 docs/data/index.json 已生成";
      emptyEl.hidden = false;
      emptyTextEl.textContent = "暂时读不到镜像数据，请稍后刷新";
      console.error(err);
    }
  }

  function buildSourceChips(sources, total) {
    const chips = [
      `<button type="button" class="chip active" data-source="all">全部<span class="num">${total}</span></button>`,
    ];
    sources.forEach((source) => {
      if (!source.count) return;
      chips.push(
        `<button type="button" class="chip" data-source="${escapeHtml(source.key)}">` +
          `${escapeHtml(source.name)}<span class="num">${source.count}</span></button>`
      );
    });
    sourceChips.innerHTML = chips.join("");
  }

  function updateMeta(data) {
    const generated = data.generated_at ? data.generated_at.slice(0, 16).replace("T", " ") : "未知";
    headerMeta.innerHTML = `共 <b>${data.count || 0}</b> 条通知<br>更新于 ${escapeHtml(generated)}`;
    footerMeta.textContent = `最后更新：${generated} · 数据每日自动抓取`;
  }

  /* ---------- 筛选与渲染 ---------- */

  function applyFilters() {
    const terms = state.terms;
    const scored = [];

    for (const item of state.items) {
      if (state.source !== "all" && item.s !== state.source) continue;
      if (state.contentOnly && !item.h) continue;
      if (!inRange(item.d)) continue;

      let matched = true;
      for (const term of terms) {
        if (!item._t.includes(term) && !item._x.includes(term)) {
          matched = false;
          break;
        }
      }
      if (!matched) continue;

      scored.push({ item, score: terms.length ? scoreOf(item, terms) : 0 });
    }

    if (terms.length && state.sort === "relevance") {
      scored.sort((a, b) => b.score - a.score || cmpDateDesc(a.item, b.item));
    } else {
      scored.sort((a, b) => cmpDateDesc(a.item, b.item) || b.score - a.score);
    }

    state.filtered = scored.map((entry) => entry.item);
    state.page = 0;
    listEl.innerHTML = "";
    renderCount();

    if (!state.filtered.length) {
      moreBtn.hidden = true;
      emptyEl.hidden = false;
      emptyTextEl.textContent = state.q ? `没有找到包含“${state.q}”的通知` : "没有符合筛选条件的通知";
      return;
    }

    emptyEl.hidden = true;
    renderPage();
  }

  function renderCount() {
    const total = state.items.length;
    if (state.q || state.source !== "all" || state.range !== "all" || state.contentOnly) {
      countEl.innerHTML = `找到 <b>${state.filtered.length}</b> 条匹配结果 <span class="muted">/ 共 ${total} 条</span>`;
    } else {
      countEl.innerHTML = `共 <b>${total}</b> 条已归档通知`;
    }
    const parts = [];
    if (state.q) parts.push(`关键词：${state.q}`);
    if (state.source !== "all") parts.push(`来源：${state.sourceNames[state.source] || state.source}`);
    if (state.range !== "all") parts.push(`时间：近 ${state.range} 天`);
    if (state.contentOnly) parts.push("仅看有正文");
    activeQueryEl.textContent = parts.join(" · ");
  }

  function renderPage() {
    const start = state.page * state.pageSize;
    const end = Math.min(start + state.pageSize, state.filtered.length);
    const fragment = document.createDocumentFragment();

    for (let i = start; i < end; i += 1) {
      fragment.appendChild(cardNode(state.filtered[i]));
    }
    listEl.appendChild(fragment);
    state.page += 1;

    const hasMore = end < state.filtered.length;
    moreBtn.hidden = !hasMore;
    moreBtn.textContent = `加载更多（还有 ${state.filtered.length - end} 条）`;
  }

  function cardNode(item) {
    const li = document.createElement("li");
    li.className = "card";
    li.dataset.id = item.i;
    li.tabIndex = 0;
    li.setAttribute("role", "button");

    const [year, month, day] = item.d ? item.d.split("-") : ["", "", ""];
    const dateBlock = item.d
      ? `<div class="card-date"><span class="d">${escapeHtml(month)}-${escapeHtml(day)}</span>` +
        `<span class="y">${escapeHtml(year)}</span></div>`
      : '<div class="card-date"><span class="d">—</span></div>';

    const snippet = snippetFor(item, state.terms);
    const snippetHtml = snippet ? `<p class="card-snippet">${highlight(snippet, state.terms)}</p>` : "";

    li.innerHTML =
      dateBlock +
      '<div class="card-main">' +
      `<div class="card-tags">${sourceTag(item)}${statusTag(item)}</div>` +
      `<h2 class="card-title">${highlight(item.t, state.terms)}</h2>` +
      snippetHtml +
      `<div class="card-foot"><span>${escapeHtml(item.c || "")}</span>` +
      `<span class="open">查看详情 →</span></div>` +
      "</div>";
    return li;
  }

  function loadMore() {
    if (state.loadingMore) return;
    if (state.page * state.pageSize >= state.filtered.length) return;
    state.loadingMore = true;
    renderPage();
    state.loadingMore = false;
  }

  /* ---------- 详情 ---------- */

  function noticeFor(data) {
    switch (data.status) {
      case "login_required":
        return "该通知原文需校内统一身份认证登录，本站仅归档标题与发布日期。";
      case "link_generic":
        return "该通知在原站的链接为栏目入口，可能无法直达文章，请以原站检索结果为准。";
      case "removed":
        return "该通知已从原站下线，本站仅保留标题与发布日期供检索。";
      case "forbidden":
        return "原站限制了该页面的访问，暂时无法镜像正文。";
      case "error":
        return "抓取原文时出现网络错误，可稍后重试或前往原站查看。";
      case "empty_content":
        return data.attachments && data.attachments.length
          ? "该通知正文以附件形式发布，请打开下方附件查看完整内容。"
          : "原文暂未提供可提取的正文内容。";
      default:
        return "";
    }
  }

  function fileExt(url) {
    const match = /\.([a-z0-9]{2,5})(?:\?|$)/i.exec(url || "");
    return match ? match[1].toUpperCase() : "FILE";
  }

  function renderDetail(data) {
    const title = data.title || "（无标题）";
    const metaParts = [
      `<span class="tag src-${escapeHtml(data.source || "")}">${escapeHtml(data.source_name || "")}</span>`,
      `<span>${escapeHtml(data.date || "日期未知")}</span>`,
      `<span>${escapeHtml(data.channel || "")}</span>`,
    ];
    detailMeta.innerHTML = metaParts.join("");

    const notice = noticeFor(data);
    const noticeHtml = notice ? `<div class="notice-bar">${escapeHtml(notice)}</div>` : "";

    let bodyHtml = "";
    if (data.content_html) {
      bodyHtml = `<div class="article-body">${data.content_html}</div>`;
    } else if (data.content_text) {
      bodyHtml = `<div class="article-body"><p>${escapeHtml(data.content_text.slice(0, 2000))}</p></div>`;
    }

    const attachments = Array.isArray(data.attachments) ? data.attachments : [];
    let attachHtml = "";
    if (attachments.length) {
      const rows = attachments
        .map(
          (file) =>
            `<li><a href="${escapeHtml(file.url)}" target="_blank" rel="noopener noreferrer">` +
            `<span class="ext">${escapeHtml(fileExt(file.url))}</span>` +
            `<span class="name">${escapeHtml(file.name || "附件")}</span>` +
            `<span>↓</span></a></li>`
        )
        .join("");
      attachHtml =
        `<div class="detail-attachments"><h3>附件（${attachments.length}）</h3>` +
        `<ul class="attachment-list">${rows}</ul></div>`;
    }

    const actions = data.url
      ? `<div class="detail-actions"><a class="btn-primary" href="${escapeHtml(data.url)}" ` +
        `target="_blank" rel="noopener noreferrer">前往原站查看 ↗</a></div>`
      : "";

    detailBody.innerHTML =
      `<h2 class="detail-title">${escapeHtml(title)}</h2>` +
      noticeHtml +
      (bodyHtml || `<div class="detail-empty">暂无正文内容。</div>`) +
      attachHtml +
      actions;
    detailBody.scrollTop = 0;
  }

  async function openDetail(id) {
    const item = state.items.find((entry) => entry.i === id);
    if (!item) return;
    detailMeta.innerHTML = "";
    detailBody.innerHTML = '<div class="detail-loading">正在读取归档内容…</div>';
    dialog.showModal();

    try {
      let data = detailCache.get(id);
      if (!data) {
        const res = await fetch(`data/items/${encodeURIComponent(id)}.json`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data = await res.json();
        detailCache.set(id, data);
      }
      renderDetail(data);
    } catch (err) {
      detailBody.innerHTML =
        `<h2 class="detail-title">${escapeHtml(item.t)}</h2>` +
        '<div class="notice-bar">详情文件读取失败，请稍后重试。</div>' +
        `<div class="detail-actions"><a class="btn-primary" href="${escapeHtml(item.u)}" ` +
        `target="_blank" rel="noopener noreferrer">前往原站查看 ↗</a></div>`;
      console.error(err);
    }
  }

  /* ---------- 事件 ---------- */

  function bindEvents() {
    let timer = 0;
    qInput.addEventListener("input", () => {
      window.clearTimeout(timer);
      clearBtn.hidden = !qInput.value;
      timer = window.setTimeout(() => {
        updateQuery(qInput.value);
      }, 140);
    });

    qInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        window.clearTimeout(timer);
        updateQuery(qInput.value);
      }
    });

    clearBtn.addEventListener("click", () => {
      qInput.value = "";
      clearBtn.hidden = true;
      updateQuery("");
      qInput.focus();
    });

    $("#hotTerms").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-term]");
      if (!button) return;
      qInput.value = button.dataset.term;
      clearBtn.hidden = false;
      updateQuery(button.dataset.term);
    });

    sourceChips.addEventListener("click", (event) => {
      const button = event.target.closest(".chip[data-source]");
      if (!button) return;
      state.source = button.dataset.source;
      sourceChips.querySelectorAll(".chip").forEach((chip) => chip.classList.remove("active"));
      button.classList.add("active");
      applyFilters();
    });

    rangeChips.addEventListener("click", (event) => {
      const button = event.target.closest(".chip[data-range]");
      if (!button) return;
      state.range = button.dataset.range;
      rangeChips.querySelectorAll(".chip").forEach((chip) => chip.classList.remove("active"));
      button.classList.add("active");
      applyFilters();
    });

    contentOnly.addEventListener("change", () => {
      state.contentOnly = contentOnly.checked;
      applyFilters();
    });

    sortSelect.addEventListener("change", () => {
      state.sort = sortSelect.value;
      applyFilters();
    });

    moreBtn.addEventListener("click", loadMore);

    listEl.addEventListener("click", (event) => {
      const card = event.target.closest(".card");
      if (card) openDetail(card.dataset.id);
    });

    listEl.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const card = event.target.closest(".card");
      if (card) {
        event.preventDefault();
        openDetail(card.dataset.id);
      }
    });

    $("#detailClose").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && !isTyping(event.target)) {
        event.preventDefault();
        qInput.focus();
        qInput.select();
      }
    });

    // 滚动接近底部时自动加载下一页
    let ticking = false;
    window.addEventListener(
      "scroll",
      () => {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(() => {
          ticking = false;
          const remain = document.body.scrollHeight - (window.scrollY + window.innerHeight);
          if (remain < 600) loadMore();
        });
      },
      { passive: true }
    );

    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) loadMore();
        },
        { rootMargin: "600px 0px" }
      );
      observer.observe(moreWrap);
    }
  }

  function isTyping(target) {
    if (!target) return false;
    const tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
  }

  function updateQuery(value) {
    state.q = (value || "").trim();
    state.terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    applyFilters();
  }

  init();
})();

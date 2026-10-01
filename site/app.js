(() => {
  "use strict";

  const VERDICTS = {
    strong_match: "Strong",
    possible: "Possible",
    no_match: "No match",
    over_budget: "Over budget",
    unassessed: "Not assessed",
  };
  const DEAL_TYPES = {
    walls_and_business: "Walls and business",
    business_only: "Business only",
    walls_only: "Walls only",
    share_sale: "Share sale",
  };
  const NEW_DAYS = 7;
  const DAY_MS = 86400000;

  const state = { opportunities: [], signals: [], runs: [], meta: {}, filter: "good", query: "", sort: "score" };
  const $ = (id) => document.getElementById(id);

  const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
  const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris", timeZoneName: "short",
  });

  // ---- helpers -----------------------------------------------------------

  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "className") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function safeUrl(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
    } catch {
      return null;
    }
  }

  function euros(value) {
    if (typeof value !== "number" || !isFinite(value)) return null;
    const sign = value < 0 ? "−" : "";
    const amount = Math.abs(value);
    if (amount >= 1e6) return `${sign}€${(amount / 1e6).toFixed(amount >= 1e8 ? 0 : 1).replace(/\.0$/, "")}m`;
    if (amount >= 1e3) return `${sign}€${Math.round(amount / 1e3)}k`;
    return `${sign}€${Math.round(amount)}`;
  }

  function parseDate(value) {
    if (!value) return null;
    const date = new Date(value.length === 10 ? `${value}T12:00:00Z` : value);
    return isNaN(date) ? null : date;
  }

  function formatDate(value) {
    const date = parseDate(value);
    return date ? dateFormat.format(date) : "";
  }

  function isNew(opportunity, now) {
    const first = parseDate(opportunity.first_seen);
    return first !== null && now - first < NEW_DAYS * DAY_MS;
  }

  async function loadJson(path, fallback) {
    try {
      const response = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
      return response.ok ? await response.json() : fallback;
    } catch {
      return fallback;
    }
  }

  // ---- opportunities -----------------------------------------------------

  function searchText(o) {
    const a = o.assessment || {};
    return [o.title, o.location, o.source, a.commune, a.departement, a.region, a.broker, a.summary_en, o.why_found]
      .filter(Boolean).join(" ").toLowerCase();
  }

  function visibleOpportunities() {
    const query = state.query.trim().toLowerCase();
    const filtered = state.opportunities.filter((o) => {
      if (state.filter === "strong" && o.verdict !== "strong_match") return false;
      if (state.filter === "good" && !["strong_match", "possible"].includes(o.verdict)) return false;
      return !query || searchText(o).includes(query);
    });
    const price = (o) => (o.assessment && typeof o.assessment.asking_price_eur === "number" ? o.assessment.asking_price_eur : Infinity);
    const sorters = {
      score: (a, b) => (b.score ?? -1) - (a.score ?? -1) || String(b.first_seen).localeCompare(String(a.first_seen)),
      newest: (a, b) => String(b.first_seen).localeCompare(String(a.first_seen)) || (b.score ?? -1) - (a.score ?? -1),
      price: (a, b) => price(a) - price(b) || (b.score ?? -1) - (a.score ?? -1),
    };
    return filtered.sort(sorters[state.sort] || sorters.score);
  }

  function facts(o) {
    const a = o.assessment || {};
    const items = [];
    if (a.keys) items.push(h("li", {}, h("strong", { text: a.keys }), " rooms"));
    if (a.stars) items.push(h("li", {}, h("span", { className: "stars", "aria-label": `${a.stars} stars`, text: "★".repeat(a.stars) })));
    if (DEAL_TYPES[a.deal_type]) items.push(h("li", { text: DEAL_TYPES[a.deal_type] }));
    const price = euros(a.asking_price_eur);
    if (price) items.push(h("li", {}, h("strong", { text: price }), " asking"));
    else if (a.price_on_request) items.push(h("li", { text: "Price on request" }));
    else if (o.asking_price_text) items.push(h("li", { text: o.asking_price_text }));
    const perKey = euros(o.price_per_key_eur);
    if (perKey) items.push(h("li", { text: `${perKey} per room` }));
    const revenue = euros(a.revenue_eur);
    if (revenue) items.push(h("li", { text: `Revenue ${revenue}${a.figures_year ? ` (${a.figures_year})` : ""}` }));
    const ebitda = euros(a.ebitda_eur);
    if (ebitda) items.push(h("li", { text: `EBITDA ${ebitda}` }));
    if (a.listing_status === "under_offer_or_sold") items.push(h("li", {}, h("strong", { text: "Under offer or sold" })));
    return items;
  }

  function discussLink(o) {
    const repo = state.meta.repository;
    if (o.team && safeUrl(o.team.issue_url)) {
      const comments = o.team.comments ? ` (${o.team.comments})` : "";
      return h("a", { href: o.team.issue_url, target: "_blank", rel: "noopener noreferrer", text: `Team discussion${comments}` });
    }
    if (!repo) return null;
    const body = [
      `Listing: ${o.url}`,
      `Dashboard: ${location.origin}${location.pathname}#${o.id}`,
      "",
      (o.assessment && o.assessment.summary_en) || o.why_found || "",
      "",
      "Set the team status with a label such as `status: shortlist`, `status: contacted` or `status: rejected`.",
    ].join("\n");
    const params = new URLSearchParams({ title: `[${o.id}] ${o.title}`, body });
    return h("a", { href: `https://github.com/${repo}/issues/new?${params}`, target: "_blank", rel: "noopener noreferrer", text: "Discuss with the team" });
  }

  function detailSection(title, items, className) {
    if (!items || !items.length) return null;
    return h("div", {}, h("h3", { text: title }), h("ul", { className }, items.map((item) => h("li", { text: item }))));
  }

  function renderCard(o, now) {
    const template = $("card-template").content.firstElementChild.cloneNode(true);
    const a = o.assessment;
    template.id = o.id;
    template.classList.add(`verdict-${o.verdict}`);
    template.querySelector(".score-value").textContent = o.score ?? "–";
    template.querySelector(".score-label").textContent = VERDICTS[o.verdict] || o.verdict;

    const link = template.querySelector(".card-title a");
    link.textContent = o.title;
    const href = safeUrl(o.url);
    if (href) link.href = href;

    const place = a ? [a.commune, a.departement].filter(Boolean).join(", ") || o.location : o.location;
    const meta = template.querySelector(".card-meta");
    meta.append([place, o.source, `found ${formatDate(o.first_seen)}`].filter(Boolean).join(" · "));
    if (isNew(o, now)) meta.append(h("span", { className: "badge-new", text: "NEW" }));

    template.querySelector(".facts").append(...facts(o));
    template.querySelector(".summary").textContent = (a && a.summary_en) || o.why_found || "";

    const actions = template.querySelector(".card-actions");
    if (o.team && o.team.status) actions.append(h("span", { className: `status status-${o.team.status.replace(/[^a-z-]/g, "")}`, text: o.team.status }));
    const discuss = discussLink(o);
    if (discuss) actions.append(discuss);
    actions.append(h("span", { className: "card-id", text: o.id }));

    const more = template.querySelector(".more");
    if (!a) {
      more.remove();
      return template;
    }
    more.querySelector(".more-grid").append(
      ...[
        detailSection("Why it fits", a.reasons),
        detailSection("Red flags", a.red_flags),
        detailSection("Missing information", a.missing_information),
        detailSection("Questions for the broker", a.questions_for_broker),
        detailSection("From the listing", a.evidence_quotes, "quotes"),
      ].filter(Boolean),
    );
    const briefNote = a.brief_version && a.brief_version !== state.meta.brief_version ? " (an older version of the brief)" : "";
    const pageNote = a.page_was_read === false ? " The listing page could not be read, so this assessment is based on search results only." : "";
    more.querySelector(".provenance").textContent =
      `Assessed ${formatDate(a.assessed_at)} by ${a.model || "Claude"} against brief ${a.brief_version || "?"}${briefNote}. ` +
      `Seen ${o.times_seen} time${o.times_seen === 1 ? "" : "s"}, last on ${formatDate(o.last_seen)}.${pageNote}`;
    return template;
  }

  function renderOpportunities() {
    const container = $("opportunities");
    const list = visibleOpportunities();
    const now = Date.now();
    container.replaceChildren();
    $("result-line").textContent = state.opportunities.length
      ? `Showing ${list.length} of ${state.opportunities.length} hotels`
      : "";
    if (!state.opportunities.length) {
      container.append(
        h("div", { className: "empty" },
          h("h2", { text: state.runs.length ? "No hotels found yet" : "No results yet" }),
          h("p", { text: "The agent runs every morning and adds what it finds here." }),
          h("p", { text: "To start a run now, open the repository on GitHub, go to Actions, choose “Daily hotel scout” and select “Run workflow”." })),
      );
      return;
    }
    if (!list.length) {
      container.append(h("div", { className: "empty" }, h("p", { text: "Nothing matches these filters. Try “Everything” or clear the search." })));
      return;
    }
    container.append(...list.map((o) => renderCard(o, now)));
  }

  // ---- signals and runs ----------------------------------------------------

  function renderSignals() {
    const body = $("signals");
    body.replaceChildren();
    if (!state.signals.length) {
      body.append(h("tr", {}, h("td", { colspan: 6, text: "No hotel-related notices yet." })));
      return;
    }
    const kinds = { insolvency: "Insolvency", sale: "Business sale" };
    for (const s of state.signals) {
      const notice = [s.notice, s.judgment].filter(Boolean).join(" · ");
      const url = safeUrl(s.url);
      body.append(
        h("tr", {},
          h("td", { className: "date", text: formatDate(s.date) }),
          h("td", {}, h("span", { className: `kind kind-${kinds[s.kind] ? s.kind : "other"}`, text: kinds[s.kind] || s.family || "Other" })),
          h("td", { text: s.company }),
          h("td", { text: [s.town, s.departement].filter(Boolean).join(", ") }),
          h("td", { text: s.activity }),
          h("td", {}, url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: notice || "View notice" }) : notice),
        ),
      );
    }
  }

  function renderRuns() {
    const body = $("runs");
    body.replaceChildren();
    if (!state.runs.length) {
      body.append(h("tr", {}, h("td", { colspan: 6, text: "No runs yet." })));
      return;
    }
    for (const run of state.runs) {
      const usage = run.usage || {};
      const notes = (run.errors && run.errors.length ? run.errors.join(" · ") : run.explorer_notes) || "OK";
      body.append(
        h("tr", {},
          h("td", { className: "date", text: run.started_at ? dateTimeFormat.format(new Date(run.started_at)) : "" }),
          h("td", { className: "num", text: (run.new_opportunities || []).length }),
          h("td", { className: "num", text: run.assessed ?? 0 }),
          h("td", { className: "num", text: usage.web_searches ?? 0 }),
          h("td", { className: "num", text: `$${(usage.estimated_cost_usd || 0).toFixed(2)}` }),
          h("td", { text: notes.length > 240 ? `${notes.slice(0, 240)}…` : notes }),
        ),
      );
    }
  }

  // ---- page ----------------------------------------------------------------

  function renderSummary() {
    const now = Date.now();
    const count = (verdict) => state.opportunities.filter((o) => o.verdict === verdict).length;
    $("kpi-strong").textContent = count("strong_match");
    $("kpi-possible").textContent = count("possible");
    $("kpi-new").textContent = state.opportunities.filter((o) => isNew(o, now)).length;
    $("kpi-signals").textContent = state.signals.length;
    $("count-opportunities").textContent = state.opportunities.length ? `(${state.opportunities.length})` : "";
    $("count-signals").textContent = state.signals.length ? `(${state.signals.length})` : "";
    const budget = euros(state.meta.budget_eur);
    if (budget) $("budget").textContent = budget;
    const updated = parseDate(state.meta.updated_at);
    $("updated").textContent = updated ? `Updated ${dateTimeFormat.format(updated)}` : "Not run yet";

    const repo = state.meta.repository;
    const footer = $("footer-links");
    footer.replaceChildren();
    if (repo) {
      footer.append(
        h("a", { href: `https://github.com/${repo}/blob/HEAD/config/brief.md`, target: "_blank", rel: "noopener noreferrer", text: "What the agent looks for" }),
        " · ",
        h("a", { href: `https://github.com/${repo}`, target: "_blank", rel: "noopener noreferrer", text: "Source and settings on GitHub" }),
      );
    }
  }

  function selectTab(name) {
    for (const tab of ["opportunities", "signals", "runs"]) {
      const selected = tab === name;
      $(`tab-${tab}`).setAttribute("aria-selected", String(selected));
      $(`panel-${tab}`).hidden = !selected;
    }
  }

  function setFilter(filter) {
    state.filter = filter;
    for (const name of ["good", "strong", "all"]) $(`filter-${name}`).setAttribute("aria-pressed", String(name === filter));
    renderOpportunities();
  }

  function followHash() {
    const target = decodeURIComponent(location.hash.slice(1));
    if (target === "signals" || target === "runs") return selectTab(target);
    const opportunity = state.opportunities.find((o) => o.id === target);
    if (!opportunity) return;
    selectTab("opportunities");
    if (!visibleOpportunities().includes(opportunity)) setFilter("all");
    const card = $(target);
    if (card) {
      const details = card.querySelector("details");
      if (details) details.open = true;
      card.scrollIntoView({ block: "start" });
    }
  }

  function wireControls() {
    for (const tab of ["opportunities", "signals", "runs"]) $(`tab-${tab}`).addEventListener("click", () => selectTab(tab));
    for (const name of ["good", "strong", "all"]) $(`filter-${name}`).addEventListener("click", () => setFilter(name));
    $("search").addEventListener("input", (event) => {
      state.query = event.target.value;
      renderOpportunities();
    });
    $("sort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderOpportunities();
    });
    window.addEventListener("hashchange", followHash);
  }

  async function start() {
    wireControls();
    const [opportunities, signals, runs] = await Promise.all([
      loadJson("data/opportunities.json", { opportunities: [] }),
      loadJson("data/signals.json", { signals: [] }),
      loadJson("data/runs.json", { runs: [] }),
    ]);
    state.meta = opportunities;
    state.opportunities = opportunities.opportunities || [];
    state.signals = signals.signals || [];
    state.runs = runs.runs || [];
    renderSummary();
    renderOpportunities();
    renderSignals();
    renderRuns();
    followHash();
  }

  start();
})();

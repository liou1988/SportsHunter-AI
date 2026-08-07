const state = {
  loading: false,
  optimizer: null,
  periodDays: 30,
  periodOptions: [3, 7, 15, 30],
  recommendationItems: [],
  recommendationSort: "confidence",
  recommendationSignalFilter: "all",
  recommendationLeagueFilter: "all",
  recommendationTimeFilter: "all",
};

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function refreshDashboard() {
  if (state.loading) return;
  state.loading = true;
  setBusy(true);
  try {
    const payload = await fetchJson(`/api/dashboard/summary?period_days=${encodeURIComponent(state.periodDays)}`);
    renderSummary(payload);
  } catch (error) {
    setFooter(`刷新失败：${error.message}`);
  } finally {
    state.loading = false;
    setBusy(false);
  }
}

async function runEvaluation() {
  setFooter(`正在生成近 ${state.periodDays} 天复盘报告...`);
  try {
    const payload = await fetchJson(`/api/dashboard/evaluation/run?period_days=${encodeURIComponent(state.periodDays)}`, { method: "POST" });
    renderEvaluationReport(payload.report || {});
    await refreshDashboard();
  } catch (error) {
    setFooter(`\u751f\u6210\u590d\u76d8\u5931\u8d25\uff1a${error.message}`);
  }
}

async function checkTelegramAlerts() {
  setFooter("正在检查 Telegram 推荐推送...");
  try {
    const payload = await fetchJson("/api/telegram/alerts/check", { method: "POST" });
    setFooter(`推送检查完成：评估 ${payload.evaluated_count || 0} 场，新增推送 ${payload.pushed_count || 0} 场`);
    await refreshDashboard();
  } catch (error) {
    setFooter(`推送检查失败：${error.message}`);
  }
}

async function checkDataQuality() {
  setFooter("正在检查数据源质量...");
  $("data-quality-button").disabled = true;
  try {
    const payload = await fetchJson("/api/dashboard/data-quality/check", { method: "POST" });
    renderDataQuality(payload);
    setFooter(`数据源检查完成：今日 ${payload.fixtures_count || 0} 场，盘口样本 ${payload.odds_sample_size || 0} 场`);
  } catch (error) {
    $("data-quality-health").textContent = "检查失败";
    $("data-quality-health").className = "bad";
    setFooter(`数据源检查失败：${error.message}`);
  } finally {
    $("data-quality-button").disabled = false;
  }
}

async function applyOptimizerSuggestions() {
  if (!state.optimizer || !state.optimizer.can_apply) {
    setFooter("当前没有可应用的模型优化建议。");
    return;
  }
  $("apply-optimizer-button").disabled = true;
  setFooter("正在应用模型优化建议...");
  try {
    const payload = await fetchJson("/api/model/optimizer/apply", { method: "POST" });
    setFooter(payload.message || "模型优化建议已处理。");
    await refreshDashboard();
  } catch (error) {
    setFooter(`应用模型优化建议失败：${error.message}`);
  } finally {
    $("apply-optimizer-button").disabled = false;
  }
}

function renderSummary(payload) {
  const provider = payload.provider || {};
  const database = payload.database || {};
  const recommendations = payload.recommendations || {};
  const reports = payload.reports || {};
  const analytics = payload.analytics || {};
  const optimizer = payload.model_optimizer || {};
  const counts = database.counts || {};
  state.periodOptions = normalizePeriodOptions(payload.period_options || state.periodOptions);
  state.periodDays = normalizePeriodDays(payload.period_days || analytics.period_days || state.periodDays);
  renderPeriodControls();

  $("provider-health").textContent = translateHealth(provider.health);
  $("provider-health").className = statusClass(provider.health);
  $("recommendation-count").textContent = recommendations.count ?? "--";
  $("fixture-count").textContent = counts.fixtures ?? "--";
  $("prediction-count").textContent = counts.predictions ?? "--";
  $("result-count").textContent = counts.match_results ?? "--";
  $("learning-count").textContent = counts.learning_records ?? "--";

  renderDetails("provider-details", [
    ["数据源", translateProvider(provider.provider)],
    ["状态", translateHealth(provider.health)],
    ["延迟", formatSeconds(provider.latency)],
    ["最后更新", formatTime(provider.last_update)],
    ["异常", provider.error || "无"],
  ]);

  renderDetails("database-details", [
    ["状态", translateHealth(database.health)],
    ["比赛", counts.fixtures],
    ["预测", counts.predictions],
    ["赛果", counts.match_results],
    ["赔率快照", counts.odds_snapshots],
    ["学习记录", counts.learning_records],
    ["异常", database.error || "无"],
  ]);

  state.recommendationItems = recommendations.items || [];
  populateRecommendationFilters(state.recommendationItems);
  renderRecommendations(state.recommendationItems);
  renderLatestPredictions(database.latest_predictions || []);
  renderAnalytics(analytics);
  renderOptimizer(optimizer);

  const daily = (reports.evaluation_report && reports.evaluation_report.content)
    ? reports.evaluation_report
    : (reports.daily_report || {});
  renderEvaluationReportFromMarkdown(daily.content || "");
  setFooter(`最后刷新：${formatTime(payload.generated_at)}`);
}

function normalizePeriodOptions(options) {
  const values = (Array.isArray(options) ? options : [])
    .map((value) => Number(value))
    .filter((value) => [3, 7, 15, 30].includes(value));
  return values.length ? [...new Set(values)] : [3, 7, 15, 30];
}

function normalizePeriodDays(value) {
  const number = Number(value);
  return state.periodOptions.includes(number) ? number : 30;
}

function renderPeriodControls() {
  document.querySelectorAll("[data-period-control]").forEach((root) => {
    root.innerHTML = state.periodOptions.map((days) => `
      <button
        class="period-button ${days === state.periodDays ? "active" : ""}"
        type="button"
        data-period-days="${days}"
        aria-pressed="${days === state.periodDays ? "true" : "false"}"
        title="近 ${days} 天"
      >${days}天</button>
    `).join("");
  });
  const summaryLink = $("dashboard-summary-link");
  if (summaryLink) {
    summaryLink.href = `/api/dashboard/summary?period_days=${encodeURIComponent(state.periodDays)}`;
  }
}

function updatePeriodCaptions(periodDays) {
  const caption = $("model-performance-caption");
  if (caption) {
    caption.textContent = `近 ${periodDays} 天已结算推荐的命中率、收益和信心校准`;
  }
}



function renderEvaluationReportFromMarkdown(markdown) {
  if (!String(markdown || "").trim()) {
    renderEvaluationReport({});
    return;
  }
  renderEvaluationReport(parseEvaluationMarkdown(markdown));
}

function renderEvaluationReport(report) {
  const root = $("daily-report");
  const hasReport = report && (
    report.markdown ||
    report.settled_count !== undefined ||
    (report.overview || []).length ||
    (report.wins || []).length ||
    (report.losses || []).length
  );
  if (!hasReport) {
    root.innerHTML = `<p class="muted">\u6682\u65e0\u590d\u76d8\u62a5\u544a\u3002\u70b9\u51fb\u201c\u751f\u6210\u590d\u76d8\u201d\u540e\u4f1a\u663e\u793a\u5df2\u7ed3\u7b97\u6bd4\u8d5b\u7684\u7ed3\u6784\u5316\u5206\u6790\u3002</p>`;
    return;
  }

  const metrics = report.metrics || {};
  root.innerHTML = `
    <div class="review-summary-grid">
      ${renderReviewMetric("\u590d\u76d8\u65e5\u671f", report.date || report.report_date || "-")}
      ${renderReviewMetric("\u5df2\u7ed3\u7b97", `${formatNumber(report.settled_count)} \u573a`)}
      ${renderReviewMetric("\u5b66\u4e60\u8bb0\u5f55", `${formatNumber(report.learning_records_created)} \u6761`)}
      ${renderReviewMetric("ROI", formatPercent(metrics.roi), metricClass(metrics.roi, 0, true))}
      ${renderReviewMetric("Hunter\u547d\u4e2d", formatPercent(metrics.hunter_hit_rate), metricClass(metrics.hunter_hit_rate, 0.6))}
      ${renderReviewMetric("\u4fe1\u53f7\u547d\u4e2d", formatPercent(metrics.signal_hit_rate), metricClass(metrics.signal_hit_rate, 0.6))}
      ${renderReviewMetric("\u98ce\u63a7\u6709\u6548", formatPercent(metrics.risk_effectiveness), metricClass(metrics.risk_effectiveness, 0.5))}
      ${renderReviewMetric("\u4fe1\u5fc3\u8bef\u5dee", formatNumber(metrics.confidence_calibration_error), metricClass(metrics.confidence_calibration_error, 0.18, false, true))}
    </div>
    ${renderReviewSection("\u6838\u5fc3\u7ed3\u8bba", report.overview, "review-section-wide")}
    <div class="review-two-column">
      ${renderReviewSection("\u547d\u4e2d\u539f\u56e0", report.wins, "", true)}
      ${renderReviewSection("\u672a\u547d\u4e2d\u539f\u56e0", report.losses, "", true)}
    </div>
    <div class="review-two-column">
      ${renderReviewSection("\u4fe1\u5fc3\u6821\u51c6", report.confidence_notes)}
      ${renderReviewSection("\u98ce\u9669\u5206\u5c42", report.risk_notes)}
    </div>
    ${renderReviewRateSection("\u8054\u8d5b\u8868\u73b0", metrics.by_league || {})}
    ${renderReviewRateSection("\u76d8\u53e3\u8868\u73b0", metrics.by_market || {})}
    ${renderReviewSection("\u6a21\u5757\u8d21\u732e", report.module_contributions, "review-section-wide")}
    ${renderReviewSection("\u8c03\u6574\u5efa\u8bae", report.module_notes, "review-section-wide review-advice")}
    ${report.markdown ? `<details class="review-raw"><summary>\u67e5\u770b\u539f\u59cb\u62a5\u544a</summary><pre>${escapeHtml(report.markdown)}</pre></details>` : ""}
  `;
}

function renderReviewMetric(label, value, className = "") {
  return `
    <div class="review-metric ${className}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value || "-")}</strong>
    </div>
  `;
}

function renderReviewSection(title, items, className = "", matchRows = false) {
  const list = normalizeList(items);
  const body = list.length
    ? list.map((item) => matchRows ? renderReviewMatchRow(item) : `<li>${escapeHtml(item)}</li>`).join("")
    : `<li class="muted">\u6682\u65e0\u6570\u636e\u3002</li>`;
  return `
    <section class="review-section ${className}">
      <h3>${escapeHtml(title)}</h3>
      <ul>${body}</ul>
    </section>
  `;
}

function renderReviewMatchRow(item) {
  const parts = String(item).split("|").map((part) => part.trim()).filter(Boolean);
  const title = parts.shift() || item;
  const reason = parts.length ? parts.pop() : "";
  return `
    <li class="review-match-row">
      <strong>${escapeHtml(title)}</strong>
      ${parts.length ? `<div class="review-tags">${parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("")}</div>` : ""}
      ${reason ? `<p>${escapeHtml(reason)}</p>` : ""}
    </li>
  `;
}

function renderReviewRateSection(title, rates) {
  const entries = Object.entries(rates || {});
  const body = entries.length
    ? entries.map(([name, value]) => {
        const width = Math.max(3, Math.min(100, Number(value || 0) * 100));
        return `
          <div class="review-rate-row">
            <span>${escapeHtml(name)}</span>
            <div class="bar-track"><span style="width:${width}%"></span></div>
            <strong>${formatPercent(value)}</strong>
          </div>
        `;
      }).join("")
    : `<p class="muted">\u6682\u65e0\u6570\u636e\u3002</p>`;
  return `
    <section class="review-section review-section-wide">
      <h3>${escapeHtml(title)}</h3>
      <div class="review-rate-list">${body}</div>
    </section>
  `;
}

function parseEvaluationMarkdown(markdown) {
  const report = {
    markdown,
    overview: [],
    wins: [],
    losses: [],
    confidence_notes: [],
    risk_notes: [],
    module_contributions: [],
    module_notes: [],
    metrics: { by_league: {}, by_market: {} },
  };
  const sectionMap = {
    "\u6838\u5fc3\u7ed3\u8bba": "overview",
    "\u547d\u4e2d\u539f\u56e0": "wins",
    "\u672a\u547d\u4e2d\u539f\u56e0": "losses",
    "\u4fe1\u5fc3\u6821\u51c6": "confidence_notes",
    "\u98ce\u9669\u5206\u5c42": "risk_notes",
    "\u6a21\u5757\u8d21\u732e": "module_contributions",
    "\u8c03\u6574\u5efa\u8bae": "module_notes",
  };
  let section = "";
  String(markdown || "").split(/\r?\n/).forEach((line) => {
    const text = line.trim();
    if (!text) return;
    if (text.startsWith("## ")) {
      section = text.replace(/^##\s+/, "");
      return;
    }
    if (!text.startsWith("- ")) return;
    const item = text.slice(2).trim();
    if (item.startsWith("\u65e5\u671f\uff1a")) report.date = item.replace("\u65e5\u671f\uff1a", "").trim();
    else if (item.startsWith("\u5df2\u7ed3\u7b97\u9884\u6d4b\uff1a")) report.settled_count = parseLooseNumber(item);
    else if (item.startsWith("\u65b0\u589e\u5b66\u4e60\u8bb0\u5f55\uff1a")) report.learning_records_created = parseLooseNumber(item);
    else if (item.startsWith("Hunter \u8bc4\u5206\u547d\u4e2d\u7387\uff1a")) report.metrics.hunter_hit_rate = parseLoosePercent(item);
    else if (item.startsWith("\u4fe1\u53f7\u547d\u4e2d\u7387\uff1a")) report.metrics.signal_hit_rate = parseLoosePercent(item);
    else if (item.startsWith("\u98ce\u9669\u63a7\u5236\u6709\u6548\u6027\uff1a")) report.metrics.risk_effectiveness = item.includes("\u6682\u65e0") ? null : parseLoosePercent(item);
    else if (item.startsWith("\u4fe1\u5fc3\u6821\u51c6\u8bef\u5dee\uff1a")) report.metrics.confidence_calibration_error = parseLooseNumber(item);
    else if (item.startsWith("ROI:")) report.metrics.roi = parseLoosePercent(item);
    else if (section === "\u8054\u8d5b\u8868\u73b0") assignRate(report.metrics.by_league, item);
    else if (section === "\u76d8\u53e3\u8868\u73b0") assignRate(report.metrics.by_market, item);
    else if (sectionMap[section]) report[sectionMap[section]].push(item);
  });
  return report;
}

function assignRate(target, item) {
  const [name, value] = String(item).split("\uff1a");
  if (!name || value === undefined) return;
  target[translateLeagueName(name.trim())] = parseLoosePercent(value);
}

function parseLooseNumber(value) {
  const match = String(value).match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function parseLoosePercent(value) {
  const number = parseLooseNumber(value);
  return number === null ? null : number / 100;
}

function normalizeList(items) {
  return Array.isArray(items) ? items.filter(Boolean) : [];
}

function metricClass(value, threshold, higherIsBetter = true, lowerIsBetter = false) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (Number.isNaN(number)) return "";
  if (lowerIsBetter) return number <= threshold ? "good" : "warn";
  return (higherIsBetter ? number >= threshold : number > threshold) ? "good" : "warn";
}

function renderOptimizer(payload) {
  state.optimizer = payload;
  $("optimizer-status").textContent = payload.status_label || "--";
  $("optimizer-status").className = payload.status === "ready" ? "good" : (payload.status === "stable" ? "good" : "warn");
  $("optimizer-sample").textContent = `${formatNumber(payload.sample_count)} / ${formatNumber(payload.min_recommended_sample)}`;
  $("optimizer-hit-rate").textContent = formatPercent(payload.hit_rate);
  $("optimizer-confidence-error").textContent = formatNumber(payload.confidence_error);
  $("apply-optimizer-button").disabled = !payload.can_apply;

  const warnings = payload.warnings || [];
  $("optimizer-warnings").innerHTML = warnings.length
    ? warnings.map((item) => `<p>${escapeHtml(item)}</p>`).join("")
    : `<p>暂无额外风险提示。</p>`;

  const suggestions = payload.suggestions || [];
  const root = $("optimizer-suggestions");
  if (!suggestions.length) {
    root.innerHTML = `<p class="muted">当前权重暂不需要调整。</p>`;
    return;
  }
  root.innerHTML = suggestions.map((item) => `
    <div class="optimizer-row">
      <div>
        <strong>${escapeHtml(item.label || item.module)}</strong>
        <span>${escapeHtml(item.reason || "-")}</span>
        <small>${escapeHtml(item.evidence || "-")}</small>
      </div>
      <div class="optimizer-change ${item.delta > 0 ? "good" : "bad"}">
        <strong>${formatSignedNumber(item.delta)}</strong>
        <small>${formatNumber(item.current_weight)} → ${formatNumber(item.suggested_weight)}</small>
      </div>
    </div>
  `).join("");
}

function renderAnalytics(analytics) {
  const performance = analytics.performance || {};
  const periodDays = Number(performance.period_days || analytics.period_days || state.periodDays);
  updatePeriodCaptions(periodDays);
  $("settled-count").textContent = performance.settled_count ?? "--";
  $("hit-rate").textContent = formatPercent(performance.hit_rate);
  $("roi").textContent = formatPercent(performance.roi);
  $("roi").className = Number(performance.roi || 0) >= 0 ? "good" : "bad";
  $("calibration-error").textContent = formatNumber(performance.calibration_error);

  renderTrend(analytics.prediction_trend || []);
  renderBarList("signal-chart", analytics.signal_distribution || [], {
    label: (item) => item.signal_label || translateSignal(item.signal),
    value: (item) => item.count,
    meta: (item) => `均分 ${formatNumber(item.avg_score)} · 信心 ${formatNumber(item.avg_confidence)}`,
  });
  renderBarList("risk-chart", analytics.risk_distribution || [], {
    label: (item) => item.risk_label || item.risk_level || "-",
    value: (item) => item.count,
    meta: (item) => `平均风险 ${formatNumber(item.avg_risk_score)}`,
  });
  renderBarList("module-errors", (performance.module_errors || []).slice(0, 6), {
    label: (item) => item.label || item.module || "-",
    value: (item) => item.count,
    meta: (item) => `平均比分误差 ${formatNumber(item.avg_score_error)}`,
    empty: "暂无明显模块偏差。",
  });
  renderBarList("market-performance", performance.market_performance || [], {
    label: (item) => item.label || translateMarket(item.market),
    value: (item) => item.hit_rate,
    meta: (item) => `${formatNumber(item.wins)} / ${formatNumber(item.count)} 场`,
    percentValue: true,
    empty: "暂无盘口复盘数据。",
  });
  renderRankList("league-performance", performance.league_performance || []);
}

function renderTrend(items) {
  const root = $("prediction-trend");
  root.classList.toggle("empty-state", !items.length);
  if (!items.length) {
    root.style.gridTemplateColumns = "";
    root.innerHTML = `<p class="muted">暂无趋势数据。</p>`;
    return;
  }
  root.style.gridTemplateColumns = `repeat(${items.length}, minmax(18px, 1fr))`;
  const max = Math.max(1, ...items.map((item) => Number(item.count || 0)));
  root.innerHTML = items.map((item) => {
    const height = Math.max(6, Math.round((Number(item.count || 0) / max) * 96));
    return `
      <div class="trend-bar" title="${escapeHtml(formatDateShort(item.date))}：${formatNumber(item.count)} 场">
        <span style="height:${height}px"></span>
        <small>${escapeHtml(formatDateShort(item.date))}</small>
      </div>
    `;
  }).join("");
}

function renderBarList(id, items, options) {
  const root = $(id);
  root.classList.toggle("empty-state", !items.length);
  if (!items.length) {
    root.innerHTML = `<p class="muted">${escapeHtml(options.empty || "暂无数据。")}</p>`;
    return;
  }
  const max = Math.max(
    1,
    ...items.map((item) => Number(options.percentValue ? item.hit_rate || 0 : options.value(item) || 0))
  );
  root.innerHTML = items.map((item) => {
    const raw = Number(options.percentValue ? item.hit_rate || 0 : options.value(item) || 0);
    const width = options.percentValue ? Math.round(raw * 100) : Math.round((raw / max) * 100);
    const valueText = options.percentValue ? formatPercent(raw) : formatNumber(raw);
    return `
      <div class="bar-row">
        <div class="bar-head">
          <strong>${escapeHtml(options.label(item))}</strong>
          <span>${valueText}</span>
        </div>
        <div class="bar-track"><span style="width:${Math.max(3, width)}%"></span></div>
        <small>${escapeHtml(options.meta ? options.meta(item) : "")}</small>
      </div>
    `;
  }).join("");
}

function renderRankList(id, items) {
  const root = $(id);
  if (!items.length) {
    root.innerHTML = `<p class="muted">暂无联赛复盘数据。</p>`;
    return;
  }
  root.innerHTML = items.map((item, index) => `
    <div class="rank-row">
      <span>${index + 1}</span>
      <div>
        <strong>${escapeHtml(translateLeagueName(item.league || "-"))}</strong>
        <small>${formatNumber(item.wins)}胜 ${formatNumber(item.losses)}负 · ROI ${formatPercent(item.roi)}</small>
      </div>
      <strong>${formatPercent(item.hit_rate)}</strong>
    </div>
  `).join("");
}

function renderDataQuality(payload) {
  const health = payload.health || "unknown";
  $("data-quality-health").textContent = translateHealth(health);
  $("data-quality-health").className = statusClass(health);

  renderDetails("data-quality-details", [
    ["数据源", translateProvider(payload.provider)],
    ["来源", formatSourceList(payload.sources_checked || payload.source)],
    ["检查日期", formatDateKey(payload.today)],
    ["今日比赛", payload.fixtures_count],
    ["覆盖联赛", payload.leagues_count],
    ["盘口样本", payload.odds_sample_size],
    ["有盘口比赛", payload.fixtures_with_odds],
    ["检查耗时", formatSeconds(payload.latency)],
    ["跳过联赛", formatCount(payload.leagues_skipped)],
    ["异常数量", (payload.errors || []).length],
  ]);
  renderCoverage(payload.odds_coverage || {});
  renderQualityFixtures(payload.sample_fixtures || [], payload.errors || []);
}

function renderCoverage(coverage) {
  const root = $("data-quality-coverage");
  const labels = [
    ["european", "欧赔"],
    ["asian_handicap", "亚盘"],
    ["totals", "大小球"],
  ];
  root.innerHTML = labels.map(([key, label]) => {
    const item = coverage[key] || {};
    return `
      <div class="coverage-item">
        <span>${label}覆盖率</span>
        <strong>${formatPercent(item.ratio)}</strong>
        <small>${formatNumber(item.fixtures)} 场</small>
      </div>
    `;
  }).join("");
}

function renderQualityFixtures(fixtures, errors) {
  const root = $("data-quality-fixtures");
  const fixtureRows = fixtures.slice(0, 6).map((item) => `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(item.match || "-")}</strong>
        <span>${escapeHtml(translateLeagueName(item.league || "-"))} · ${escapeHtml(item.status_label || translateFixtureStatus(item.status))}</span>
      </div>
      <div class="list-meta">
        <span>${escapeHtml(formatMarketList(item.odds_markets || []))}</span>
        <small>${formatTime(item.kickoff)}</small>
      </div>
    </div>
  `);
  const errorRows = errors.slice(0, 4).map((item) => `
    <div class="list-row error-row">
      <div>
        <strong>${escapeHtml(translateStage(item.stage || "异常"))}</strong>
        <span>${escapeHtml(item.error || item)}</span>
      </div>
    </div>
  `);
  if (!fixtureRows.length && !errorRows.length) {
    root.innerHTML = `<p class="muted">暂无质量检查样本。</p>`;
    return;
  }
  root.innerHTML = [...fixtureRows, ...errorRows].join("");
}

function renderRecommendations(items) {
  const body = $("recommendations-body");
  const filteredItems = filterRecommendations(items);
  $("recommendation-count").textContent = filteredItems.length;
  renderRecommendationSummary(filteredItems, items.length);
  if (!filteredItems.length) {
    body.innerHTML = `<tr><td colspan="7">&#24403;&#21069;&#31579;&#36873;&#26465;&#20214;&#19979;&#26242;&#26080;&#25512;&#33616;&#12290;</td></tr>`;
    return;
  }
  const sortedItems = sortRecommendations(filteredItems);
  body.innerHTML = sortedItems.map((item) => {
    const score = item.score_prediction || {};
    const total = item.total_goals || {};
    const handicap = item.handicap || {};
    return `
      <tr>
        <td>
          <strong>${escapeHtml(item.match || "-")}</strong>
          <small>${escapeHtml(translateLeagueName(item.league || "-"))}</small>
        </td>
        <td class="time-cell">
          <strong>${escapeHtml(formatKickoffShort(item.kickoff))}</strong>
          <small>${escapeHtml(formatKickoffDistance(item.kickoff, item.fixture_status))}</small>
        </td>
        <td>
          <span class="badge">${escapeHtml(item.signal_label || translateSignal(item.signal))}</span>
          <small>仓位 ${escapeHtml(formatStake(item.stake))}</small>
        </td>
        <td>
          <strong>${formatNumber(item.hunter_score)}</strong>
          <small>信心 ${formatNumber(item.confidence)}</small>
        </td>
        <td>${escapeHtml(score.text || "-")}</td>
        <td>
          ${escapeHtml(total.label || "-")}
          <small>${formatEdge(total.edge)}</small>
        </td>
        <td>
          ${escapeHtml(handicap.label || "-")}
          <small>${formatEdge(handicap.edge)}</small>
        </td>
      </tr>
    `;
  }).join("");
}

function renderRecommendationSummary(items, totalCount) {
  const root = $("recommendation-summary");
  if (!root) return;
  const counts = items.reduce((acc, item) => {
    const signal = String(item.signal || "UNKNOWN");
    acc[signal] = (acc[signal] || 0) + 1;
    return acc;
  }, {});
  const nextItem = sortRecommendations(items)[0];
  const nextText = nextItem ? `${formatKickoffShort(nextItem.kickoff)} ${itemMatchText(nextItem)}` : "\u65e0";
  root.innerHTML = [
    `<span>\u5f53\u524d\u7b5b\u9009 ${items.length} / ${totalCount} \u573a</span>`,
    `<span>\u63a8\u8350 ${Number(counts.STRONG_BUY || 0) + Number(counts.BUY || 0)} \u573a</span>`,
    `<span>\u89c2\u5bdf ${counts.WATCH || 0} \u573a</span>`,
    `<span>\u8df3\u8fc7 ${counts.PASS || 0} \u573a</span>`,
    `<span>\u6700\u8fd1\u5f00\u8d5b\uff1a${escapeHtml(nextText)}</span>`,
  ].join("");
}

function itemMatchText(item) {
  return item.match || "-";
}

function populateRecommendationFilters(items) {
  const leagues = [...new Set(items.map((item) => item.league).filter(Boolean))]
    .sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
  syncSelectOptions("recommendation-league-filter", [
    { value: "all", label: "\u5168\u90e8\u8054\u8d5b" },
    ...leagues.map((league) => ({ value: league, label: league })),
  ], "all");
}

function syncSelectOptions(id, options, fallback) {
  const select = $(id);
  if (!select) return;
  const current = select.value || fallback;
  select.innerHTML = options
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
    .join("");
  select.value = options.some((option) => option.value === current) ? current : fallback;
  if (id === "recommendation-league-filter") state.recommendationLeagueFilter = select.value;
}

function filterRecommendations(items) {
  return items.filter((item) => {
    if (state.recommendationSignalFilter !== "all" && item.signal !== state.recommendationSignalFilter) return false;
    if (state.recommendationLeagueFilter !== "all" && item.league !== state.recommendationLeagueFilter) return false;
    return matchesRecommendationTimeFilter(item.kickoff);
  });
}

function matchesRecommendationTimeFilter(kickoff) {
  if (state.recommendationTimeFilter === "all") return true;
  const date = new Date(kickoff || 0);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  if (state.recommendationTimeFilter === "today" || state.recommendationTimeFilter === "beijingToday") {
    return beijingDateKey(date) === beijingDateKey(now);
  }
  if (state.recommendationTimeFilter === "upcoming") return date.getTime() >= now.getTime();
  return true;
}

function beijingDateKey(date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function localDateKey(date) {
  return beijingDateKey(date);
}

function currentRecommendationRows() {
  return sortRecommendations(filterRecommendations(state.recommendationItems));
}

function exportCurrentRecommendations() {
  const items = currentRecommendationRows();
  if (!items.length) {
    setFooter("\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6ca1\u6709\u53ef\u5bfc\u51fa\u7684\u63a8\u8350\u3002");
    return;
  }
  const columns = [
    ["\u8054\u8d5b", (item) => item.league],
    ["\u6bd4\u8d5b", (item) => item.match],
    ["\u5f00\u8d5b\u65f6\u95f4", (item) => formatKickoffFull(item.kickoff)],
    ["\u4fe1\u53f7", (item) => item.signal_label || translateSignal(item.signal)],
    ["Hunter\u8bc4\u5206", (item) => item.hunter_score],
    ["\u4fe1\u5fc3", (item) => item.confidence],
    ["\u4ed3\u4f4d", (item) => formatStake(item.stake)],
    ["\u6bd4\u5206\u9884\u6d4b", (item) => (item.score_prediction || {}).text],
    ["\u5927\u5c0f\u7403", (item) => (item.total_goals || {}).label],
    ["\u8ba9\u7403", (item) => (item.handicap || {}).label],
    ["\u63a8\u8350\u7406\u7531", (item) => item.reason],
  ];
  const csv = [
    columns.map(([header]) => csvCell(header)).join(","),
    ...items.map((item) => columns.map(([, getter]) => csvCell(getter(item) ?? "-")).join(",")),
  ].join("\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `sportshunter_filtered_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setFooter(`\u5df2\u5bfc\u51fa ${items.length} \u573a\u5f53\u524d\u7b5b\u9009\u63a8\u8350\u3002`);
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function sortRecommendations(items) {
  const signalPriority = { STRONG_BUY: 5, BUY: 4, WATCH: 3, PASS: 2, BLOCK: 1 };
  return [...items].sort((a, b) => {
    if (state.recommendationSort === "hunter") {
      return compareNumbers(b.hunter_score, a.hunter_score)
        || compareNumbers(b.confidence, a.confidence)
        || compareDatesDesc(a.created_at, b.created_at);
    }
    if (state.recommendationSort === "kickoff") {
      return compareDatesAsc(a.kickoff, b.kickoff)
        || compareNumbers(b.confidence, a.confidence)
        || compareNumbers(b.hunter_score, a.hunter_score);
    }
    if (state.recommendationSort === "signal") {
      return compareNumbers(signalPriority[b.signal] || 0, signalPriority[a.signal] || 0)
        || compareNumbers(b.confidence, a.confidence)
        || compareNumbers(b.hunter_score, a.hunter_score);
    }
    return compareNumbers(b.confidence, a.confidence)
      || compareNumbers(b.hunter_score, a.hunter_score)
      || compareDatesDesc(a.created_at, b.created_at);
  });
}

function compareNumbers(left, right) {
  const leftNumber = Number(left || 0);
  const rightNumber = Number(right || 0);
  return leftNumber - rightNumber;
}

function compareDatesAsc(left, right) {
  return Date.parse(left || 0) - Date.parse(right || 0);
}

function compareDatesDesc(left, right) {
  return Date.parse(right || 0) - Date.parse(left || 0);
}

function renderLatestPredictions(items) {
  const root = $("latest-predictions");
  if (!items.length) {
    root.innerHTML = `<p class="muted">暂无归档预测。</p>`;
    return;
  }
  root.innerHTML = items.map((item) => `
    <div class="list-row">
      <div>
        <strong>${escapeHtml(item.fixture || "-")}</strong>
        <span>${escapeHtml(translateLeagueName(item.league || "-"))} · ${formatTime(item.created_at)}</span>
      </div>
      <div class="list-meta">
        <span class="badge">${escapeHtml(item.signal_label || translateSignal(item.signal))}</span>
        <small>Hunter ${formatNumber(item.hunter_score)}</small>
      </div>
    </div>
  `).join("");
}

function renderDetails(id, rows) {
  const root = $(id);
  root.innerHTML = rows.map(([label, value]) => `
    <div>
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(formatDetailValue(value))}</dd>
    </div>
  `).join("");
}

function setBusy(isBusy) {
  $("refresh-button").disabled = isBusy;
}

function setFooter(text) {
  $("last-updated").textContent = text;
}

function statusClass(value) {
  if (value === "ok" || value === true) return "good";
  if (value === "warning" || value === "unknown" || value === "not_ready") return "warn";
  return "bad";
}

function translateHealth(value) {
  const map = {
    ok: "正常",
    true: "正常",
    warning: "注意",
    down: "异常",
    false: "异常",
    unknown: "未知",
    not_ready: "未就绪",
  };
  return map[String(value)] || value || "--";
}

function translateProvider(value) {
  const map = {
    free: "免费真实数据源",
    mock: "开发模拟数据源",
    api: "商业 API 数据源",
  };
  return map[String(value)] || value || "--";
}

function translateSignal(value) {
  const map = {
    STRONG_BUY: "强烈推荐",
    BUY: "推荐",
    WATCH: "观察",
    PASS: "跳过",
    BLOCK: "风控拦截",
  };
  return map[String(value)] || value || "-";
}

function translateLeagueName(value) {
  const text = String(value || "").trim();
  const map = {
    "Argentine Liga Profesional de Futbol": "\u963f\u6839\u5ef7\u7532\u7ea7\u8054\u8d5b",
    "Argentine Primera Nacional": "\u963f\u6839\u5ef7\u4e59\u7ea7\u8054\u8d5b",
    "Brazilian Serie A": "\u5df4\u897f\u7532\u7ea7\u8054\u8d5b",
    "Brazilian Serie B": "\u5df4\u897f\u4e59\u7ea7\u8054\u8d5b",
    "English Premier League": "\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b",
    "UEFA Champions League Qualifying": "\u6b27\u6d32\u51a0\u519b\u8054\u8d5b\u8d44\u683c\u8d5b",
    "UEFA Europa League Qualifying": "\u6b27\u8db3\u8054\u6b27\u6d32\u8054\u8d5b\u8d44\u683c\u8d5b",
    "UEFA Europa Conference League Qualifying": "\u6b27\u8db3\u8054\u6b27\u6d32\u534f\u4f1a\u8054\u8d5b\u8d44\u683c\u8d5b",
    "Colombian Primera A": "\u54e5\u4f26\u6bd4\u4e9a\u7532\u7ea7\u8054\u8d5b",
    "Liga de Expansion MX": "\u58a8\u897f\u54e5\u6269\u5c55\u8054\u8d5b",
    "Major League Soccer": "\u7f8e\u56fd\u804c\u4e1a\u8db3\u7403\u5927\u8054\u76df",
    "USL Championship": "\u7f8e\u56fd\u8db3\u7403\u51a0\u519b\u8054\u8d5b",
    "American USL Championship": "\u7f8e\u56fd\u8db3\u7403\u51a0\u519b\u8054\u8d5b",
    "USL League One": "\u7f8e\u56fd\u8db3\u7403\u7532\u7ea7\u8054\u8d5b",
    "American USL League One": "\u7f8e\u56fd\u8db3\u7403\u7532\u7ea7\u8054\u8d5b",
  };
  return map[text] || text || "-";
}

function translateFixtureStatus(value) {
  const map = {
    scheduled: "未开赛",
    live: "进行中",
    finished: "已结束",
    postponed: "已延期",
    cancelled: "已取消",
    unknown: "未知",
  };
  return map[String(value)] || value || "-";
}

function translateMarket(value) {
  const map = {
    european: "欧赔",
    asian_handicap: "亚盘",
    totals: "大小球",
  };
  return map[String(value)] || value;
}

function translateStage(value) {
  const map = {
    fixtures: "赛程采集",
    odds: "赔率采集",
    provider_debug: "数据源调试",
  };
  return map[String(value)] || value;
}

function formatSourceList(value) {
  const map = {
    espn: "ESPN",
    thesportsdb: "TheSportsDB",
    free: "免费数据源",
    mock: "模拟源",
  };
  const values = Array.isArray(value) ? value : String(value || "").split(",");
  return values.filter(Boolean).map((item) => map[String(item)] || item).join("、") || "-";
}

function formatMarketList(markets) {
  if (!markets.length) return "暂无盘口";
  return markets.map(translateMarket).join("、");
}

function formatDateKey(value) {
  const text = String(value || "");
  if (/^\d{8}$/.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  }
  return value || "-";
}

function formatDateShort(value) {
  const text = String(value || "");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return `${text.slice(5, 7)}/${text.slice(8, 10)}`;
  }
  return text || "-";
}

function formatCount(value) {
  if (Array.isArray(value)) return `${value.length} 个`;
  return value ?? "-";
}

function formatSeconds(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return `${number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")} 秒`;
}

function formatKickoffDistance(value, status) {
  const label = translateFixtureStatus(status);
  if (String(status || "").toLowerCase() === "live") return label || "\u8fdb\u884c\u4e2d";
  const date = new Date(value || 0);
  if (Number.isNaN(date.getTime())) return label || "\u5317\u4eac\u65f6\u95f4";
  const minutes = Math.round((date.getTime() - Date.now()) / 60000);
  if (minutes < -15) return label && label !== status ? label : "\u5df2\u5f00\u8d5b";
  if (minutes <= 0) return "\u5373\u5c06\u5f00\u8d5b";
  if (minutes < 60) return `\u8ddd\u5f00\u8d5b ${minutes} \u5206\u949f`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  if (hours < 24) return restMinutes ? `\u8ddd\u5f00\u8d5b ${hours}\u5c0f\u65f6${restMinutes}\u5206` : `\u8ddd\u5f00\u8d5b ${hours}\u5c0f\u65f6`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `\u8ddd\u5f00\u8d5b ${days}\u5929${restHours}\u5c0f\u65f6` : `\u8ddd\u5f00\u8d5b ${days}\u5929`;
}

function formatKickoffFull(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatKickoffShort(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function formatSignedNumber(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return String(value || "-");
  const formatted = formatNumber(Math.abs(number));
  return `${number >= 0 ? "+" : "-"}${formatted}`;
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "\u6682\u65e0";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return `${(number * 100).toFixed(0)}%`;
}

function formatStake(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return Number.isInteger(number) ? `${number}U` : `${number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}U`;
}

function formatEdge(value) {
  if (value === null || value === undefined || value === "") return "";
  return `差值 ${formatNumber(value)}`;
}

function formatDetailValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join("、") : "-";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function handlePeriodControlClick(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const button = target.closest("[data-period-days]");
  if (!button) return;
  const nextPeriod = Number(button.dataset.periodDays);
  if (!state.periodOptions.includes(nextPeriod) || nextPeriod === state.periodDays) return;
  state.periodDays = nextPeriod;
  renderPeriodControls();
  refreshDashboard();
}

document.addEventListener("click", handlePeriodControlClick);
$("refresh-button").addEventListener("click", refreshDashboard);
$("data-quality-button").addEventListener("click", checkDataQuality);
$("evaluation-button").addEventListener("click", runEvaluation);
$("telegram-button").addEventListener("click", checkTelegramAlerts);
$("apply-optimizer-button").addEventListener("click", applyOptimizerSuggestions);
$("recommendation-sort").addEventListener("change", (event) => {
  state.recommendationSort = event.target.value || "confidence";
  renderRecommendations(state.recommendationItems);
});
$("recommendation-signal-filter").addEventListener("change", (event) => {
  state.recommendationSignalFilter = event.target.value || "all";
  renderRecommendations(state.recommendationItems);
});
$("recommendation-league-filter").addEventListener("change", (event) => {
  state.recommendationLeagueFilter = event.target.value || "all";
  renderRecommendations(state.recommendationItems);
});
$("recommendation-time-filter").addEventListener("change", (event) => {
  state.recommendationTimeFilter = event.target.value || "all";
  renderRecommendations(state.recommendationItems);
});
$("recommendation-export-button").addEventListener("click", exportCurrentRecommendations);
renderPeriodControls();
refreshDashboard();

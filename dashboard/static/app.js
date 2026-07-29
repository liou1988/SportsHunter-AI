const state = {
  loading: false,
  optimizer: null,
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
    const payload = await fetchJson("/api/dashboard/summary");
    renderSummary(payload);
  } catch (error) {
    setFooter(`刷新失败：${error.message}`);
  } finally {
    state.loading = false;
    setBusy(false);
  }
}

async function runEvaluation() {
  setFooter("\u6b63\u5728\u751f\u6210\u590d\u76d8\u62a5\u544a...");
  try {
    const payload = await fetchJson("/api/dashboard/evaluation/run", { method: "POST" });
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

  renderRecommendations(recommendations.items || []);
  renderLatestPredictions(database.latest_predictions || []);
  renderAnalytics(analytics);
  renderOptimizer(optimizer);

  const daily = reports.daily_report || {};
  renderEvaluationReportFromMarkdown(daily.content || "");
  setFooter(`最后刷新：${formatTime(payload.generated_at)}`);
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
    else if (item.startsWith("\u98ce\u9669\u63a7\u5236\u6709\u6548\u6027\uff1a")) report.metrics.risk_effectiveness = parseLoosePercent(item);
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
  target[name.trim()] = parseLoosePercent(value);
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
    root.innerHTML = `<p class="muted">暂无趋势数据。</p>`;
    return;
  }
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
        <strong>${escapeHtml(item.league || "-")}</strong>
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
        <span>${escapeHtml(item.league || "-")} · ${escapeHtml(item.status_label || translateFixtureStatus(item.status))}</span>
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
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6">暂无归档推荐，点击“检查推送”后会自动写入。</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const score = item.score_prediction || {};
    const total = item.total_goals || {};
    const handicap = item.handicap || {};
    return `
      <tr>
        <td>
          <strong>${escapeHtml(item.match || "-")}</strong>
          <small>${escapeHtml(item.league || "-")}</small>
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
        <span>${escapeHtml(item.league || "-")} · ${formatTime(item.created_at)}</span>
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

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
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
  if (value === null || value === undefined || value === "") return "-";
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

$("refresh-button").addEventListener("click", refreshDashboard);
$("data-quality-button").addEventListener("click", checkDataQuality);
$("evaluation-button").addEventListener("click", runEvaluation);
$("telegram-button").addEventListener("click", checkTelegramAlerts);
$("apply-optimizer-button").addEventListener("click", applyOptimizerSuggestions);
refreshDashboard();

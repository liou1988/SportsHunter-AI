const state = {
  loading: false,
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
    $("last-updated").textContent = `刷新失败：${error.message}`;
  } finally {
    state.loading = false;
    setBusy(false);
  }
}

async function runEvaluation() {
  setFooter("正在生成日报...");
  try {
    const payload = await fetchJson("/api/dashboard/evaluation/run", { method: "POST" });
    $("daily-report").textContent = payload.report.markdown || "暂无日报";
    await refreshDashboard();
  } catch (error) {
    setFooter(`生成日报失败：${error.message}`);
  }
}

async function checkTelegramAlerts() {
  setFooter("正在检查 Telegram 推送...");
  try {
    const payload = await fetchJson("/api/telegram/alerts/check", { method: "POST" });
    setFooter(`Telegram 检查完成：评估 ${payload.evaluated_count || 0} 场，推送 ${payload.pushed_count || 0} 场`);
    await refreshDashboard();
  } catch (error) {
    setFooter(`Telegram 检查失败：${error.message}`);
  }
}

async function checkDataQuality() {
  setFooter("正在检查数据源质量...");
  $("data-quality-button").disabled = true;
  try {
    const payload = await fetchJson("/api/dashboard/data-quality/check", { method: "POST" });
    renderDataQuality(payload);
    setFooter(`数据质量检查完成：今日 ${payload.fixtures_count || 0} 场，赔率样本 ${payload.odds_sample_size || 0} 场`);
  } catch (error) {
    $("data-quality-health").textContent = "失败";
    $("data-quality-health").className = "bad";
    setFooter(`数据质量检查失败：${error.message}`);
  } finally {
    $("data-quality-button").disabled = false;
  }
}

function renderSummary(payload) {
  const provider = payload.provider || {};
  const database = payload.database || {};
  const recommendations = payload.recommendations || {};
  const reports = payload.reports || {};
  const counts = database.counts || {};

  $("provider-health").textContent = provider.health || "--";
  $("provider-health").className = provider.health === "ok" ? "good" : "bad";
  $("recommendation-count").textContent = recommendations.count ?? "--";
  $("prediction-count").textContent = counts.predictions ?? "--";
  $("learning-count").textContent = counts.learning_records ?? "--";

  renderDetails("provider-details", {
    provider: provider.provider,
    health: provider.health,
    latency: provider.latency,
    last_update: provider.last_update,
    error: provider.error || "-",
  });

  renderDetails("database-details", {
    health: database.health,
    fixtures: counts.fixtures,
    predictions: counts.predictions,
    match_results: counts.match_results,
    odds_snapshots: counts.odds_snapshots,
    learning_records: counts.learning_records,
  });

  renderRecommendations(recommendations.items || []);
  renderLatestPredictions(database.latest_predictions || []);

  const daily = reports.daily_report || {};
  $("daily-report").textContent = daily.content || "暂无已生成日报。";
  setFooter(`最后刷新：${formatTime(payload.generated_at)}`);
}

function renderDataQuality(payload) {
  const health = payload.health || "unknown";
  $("data-quality-health").textContent = translateHealth(health);
  $("data-quality-health").className = health === "ok" ? "good" : (health === "warning" ? "warn" : "bad");

  renderDetails("data-quality-details", {
    provider: payload.provider,
    source: payload.source,
    today: payload.today,
    fixtures_count: payload.fixtures_count,
    leagues_count: payload.leagues_count,
    odds_sample_size: payload.odds_sample_size,
    fixtures_with_odds: payload.fixtures_with_odds,
    latency: payload.latency,
    sources_checked: payload.sources_checked,
    leagues_checked: payload.leagues_checked,
    leagues_skipped: payload.leagues_skipped,
    errors: (payload.errors || []).length,
  });
  renderCoverage(payload.odds_coverage || {});
  renderQualityFixtures(payload.sample_fixtures || [], payload.errors || []);
}

function renderCoverage(coverage) {
  const root = $("data-quality-coverage");
  const labels = {
    european: "欧赔",
    totals: "大小球",
    asian_handicap: "亚盘",
  };
  root.innerHTML = Object.entries(labels).map(([key, label]) => {
    const item = coverage[key] || {};
    return `
      <div class="coverage-item">
        <span>${label}</span>
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
        <span>${escapeHtml(item.league || "-")}</span>
      </div>
      <div>
        <span>${escapeHtml((item.odds_markets || []).join(", ") || "无盘口")}</span>
      </div>
    </div>
  `);
  const errorRows = errors.slice(0, 4).map((item) => `
    <div class="list-row error-row">
      <div>
        <strong>${escapeHtml(item.stage || "error")}</strong>
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
    body.innerHTML = `<tr><td colspan="6">暂无已归档推荐，点击“检查推送”后会自动写入</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const score = item.score_prediction || {};
    const total = item.total_goals || {};
    const handicap = item.handicap || {};
    return `
      <tr>
        <td>${escapeHtml(item.match || "-")}<br><small>${escapeHtml(item.league || "-")}</small></td>
        <td><span class="badge">${escapeHtml(item.signal || "-")}</span><br><small>${escapeHtml(item.stake || "-")}</small></td>
        <td>${formatNumber(item.hunter_score)}<br><small>${formatNumber(item.confidence)}</small></td>
        <td>${escapeHtml(score.text || "-")}</td>
        <td>${escapeHtml(total.label || "-")}<br><small>${formatNumber(total.edge)}</small></td>
        <td>${escapeHtml(handicap.label || "-")}<br><small>${formatNumber(handicap.edge)}</small></td>
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
        <span>${escapeHtml(item.league || "-")}</span>
      </div>
      <div>
        <span class="badge">${escapeHtml(item.signal || "-")}</span>
        <span>${formatNumber(item.hunter_score)}</span>
      </div>
    </div>
  `).join("");
}

function renderDetails(id, values) {
  const root = $(id);
  root.innerHTML = Object.entries(values).map(([key, value]) => `
    <div>
      <dt>${escapeHtml(key)}</dt>
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

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return `${(number * 100).toFixed(0)}%`;
}

function formatDetailValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function translateHealth(value) {
  const map = {
    ok: "正常",
    warning: "警告",
    down: "异常",
    unknown: "未知",
    not_ready: "未就绪",
  };
  return map[value] || value || "--";
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
refreshDashboard();

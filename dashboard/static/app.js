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
      <dd>${escapeHtml(value ?? "-")}</dd>
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

$("refresh-button").addEventListener("click", refreshDashboard);
$("evaluation-button").addEventListener("click", runEvaluation);
$("telegram-button").addEventListener("click", checkTelegramAlerts);
refreshDashboard();

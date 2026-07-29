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
    setFooter(`刷新失败：${error.message}`);
  } finally {
    state.loading = false;
    setBusy(false);
  }
}

async function runEvaluation() {
  setFooter("正在生成复盘报告...");
  try {
    const payload = await fetchJson("/api/dashboard/evaluation/run", { method: "POST" });
    $("daily-report").textContent = payload.report.markdown || "暂无复盘报告";
    await refreshDashboard();
  } catch (error) {
    setFooter(`生成复盘失败：${error.message}`);
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

function renderSummary(payload) {
  const provider = payload.provider || {};
  const database = payload.database || {};
  const recommendations = payload.recommendations || {};
  const reports = payload.reports || {};
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

  const daily = reports.daily_report || {};
  $("daily-report").textContent = daily.content || "暂无已生成复盘报告。";
  setFooter(`最后刷新：${formatTime(payload.generated_at)}`);
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
refreshDashboard();

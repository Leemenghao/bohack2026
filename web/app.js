const $ = (selector) => document.querySelector(selector);
const themePreference = window.matchMedia("(prefers-color-scheme: dark)");
let savedTheme = window.desktopThemePreference;
try { savedTheme ??= localStorage.getItem("bohack.theme"); } catch { /* storage unavailable */ }

function renderTheme() {
  const theme = savedTheme === "light" || savedTheme === "dark"
    ? savedTheme : themePreference.matches ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  $("#theme-toggle").setAttribute("aria-checked", String(theme === "dark"));
  $("#theme-label").textContent = theme === "dark" ? "深色" : "浅色";
  if (!savedTheme) window.webkit?.messageHandlers?.themePreference?.postMessage(`system-${theme}`);
}

renderTheme();
themePreference.addEventListener("change", renderTheme);
$("#theme-toggle").addEventListener("click", () => {
  savedTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("bohack.theme", savedTheme); } catch { /* storage unavailable */ }
  window.webkit?.messageHandlers?.themePreference?.postMessage(savedTheme);
  renderTheme();
});

const sidebar = $("#history");
const sidebarToggle = $("#sidebar-toggle");
const narrowWindow = window.matchMedia("(max-width: 760px)");
let sidebarPreference = window.desktopSidebarPreference;
try { sidebarPreference ??= localStorage.getItem("bohack.sidebar"); } catch { /* storage unavailable */ }

function renderSidebar() {
  sidebar.hidden = sidebarPreference ? sidebarPreference === "hidden" : narrowWindow.matches;
  sidebarToggle.setAttribute("aria-expanded", String(!sidebar.hidden));
  sidebarToggle.title = sidebar.hidden ? "显示侧栏" : "隐藏侧栏";
}

renderSidebar();
narrowWindow.addEventListener("change", renderSidebar);
sidebarToggle.addEventListener("click", () => {
  sidebarPreference = sidebar.hidden ? "shown" : "hidden";
  try { localStorage.setItem("bohack.sidebar", sidebarPreference); } catch { /* storage unavailable */ }
  window.webkit?.messageHandlers?.sidebarPreference?.postMessage(sidebarPreference);
  renderSidebar();
});

const inspector = $("#details-panel");
const workspace = $(".workspace");
const divider = $("#pane-divider");
const stackedPanes = matchMedia("(max-width: 760px)");
let conversationShare = 55;
let inspectorOpener;

function setPaneShare(value) {
  conversationShare = Math.min(70, Math.max(30, Math.round(value)));
  workspace.style.setProperty("--conversation-share", conversationShare + "%");
  divider.setAttribute("aria-valuenow", String(conversationShare));
}

function syncDividerOrientation() {
  divider.setAttribute("aria-orientation", stackedPanes.matches ? "horizontal" : "vertical");
}

syncDividerOrientation();
stackedPanes.addEventListener("change", syncDividerOrientation);
divider.addEventListener("pointerdown", (event) => {
  if (event.button === 0) divider.setPointerCapture(event.pointerId);
});
divider.addEventListener("pointermove", (event) => {
  if (!divider.hasPointerCapture(event.pointerId)) return;
  const bounds = workspace.getBoundingClientRect();
  setPaneShare(stackedPanes.matches
    ? 100 * (event.clientY - bounds.top) / bounds.height
    : 100 * (event.clientX - bounds.left) / bounds.width);
});
divider.addEventListener("keydown", (event) => {
  const [decrease, increase] = stackedPanes.matches ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
  if (![decrease, increase, "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  setPaneShare(event.key === "Home" ? 30 : event.key === "End" ? 70
    : conversationShare + (event.key === increase ? 5 : -5));
});
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const MODEL = "deepseek-flash";
const HISTORY_KEY = "bohack.recent-runs";
const HISTORY_MAX = 5;
const HISTORY_PAGE_SIZE = 12;
const SVG_NS = "http://www.w3.org/2000/svg";

let experiments = [];
let selected = 0;
let activeRun = "";
let runStatus = "idle";
let cloudBudgetLimit = 0;
let memoryRunId = "";
let runStartedLabel = "";
let isHistorical = false;
let runQuestion = "";
let viewVersion = 0;
let pendingFollowUp = false;
let currentTurn = null;
let initialAttachments = [];
const statusLabels = { running: "运行中", complete: "已完成", failed: "失败", interrupted: "已中断", cancelled: "已取消", stopped: "已停止" };

function renderContext() {
  $("#run-question").replaceChildren(...renderMarkdown(runQuestion));
  const parts = isHistorical ? [`历史运行 ${activeRun}`] : ["本地实验不限次数", `模型 ${MODEL}`];
  if (cloudBudgetLimit) parts.push(`云端 ≤ ${cloudBudgetLimit} 次`);
  if (memoryRunId) parts.push(`参考上次 ${memoryRunId}`);
  if (!isHistorical && runStartedLabel) parts.push(`开始 ${runStartedLabel}`);
  $("#context").hidden = false;
  $("#context").textContent = parts.join(" · ");
}
let startedAt = 0;
let clock = null;

/* ---------- primitives ---------- */

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function icon(pathData, className = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", className);
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", pathData);
  svg.append(path);
  return svg;
}

const ICON_CHART = "M4 19V5M4 19h16M8 15l3.2-4.4L14 14l2.8-3.6L19 13";
const ICON_ALERT = "M12 9v4m0 3.5h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z";

function emptyState(text) {
  const box = element("div", "", "empty-state");
  box.append(icon(ICON_CHART), element("p", text));
  return box;
}

function statCard(label, value, unit) {
  const card = element("div", "", "stat");
  const valueNode = element("div", "", "stat-value");
  valueNode.append(document.createTextNode(value));
  if (unit) valueNode.append(element("small", unit));
  card.append(element("div", label, "stat-label"), valueNode);
  return card;
}

/* ---------- network ---------- */

class RequestError extends Error {
  constructor(message, { kind = "http", status = 0, detail = "" } = {}) {
    super(message);
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new RequestError(error.message, { kind: "network", detail: error.message });
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    throw new RequestError(data?.error || `HTTP ${response.status}`, {
      kind: "http",
      status: response.status,
      detail: data?.error || "",
    });
  }
  if (!data) throw new RequestError("服务返回了无法解析的响应。", { kind: "http", status: response.status });
  return data;
}

function describeError(error) {
  if (error.kind === "network") {
    return {
      title: "无法连接到研究服务",
      detail: "本机服务可能没有启动或已经退出。确认 python web_server.py 正在运行后重试。",
      raw: error.detail || error.message,
      retry: true,
    };
  }
  if (error.status === 404) {
    return {
      title: "该运行记录已失效",
      detail: "服务重启后内存中的运行记录会被清空。请重新发起一次研究。",
      raw: error.detail || "",
      retry: true,
    };
  }
  if (error.kind === "run") {
    return { title: "研究运行失败", detail: error.message, raw: error.detail || "", retry: true };
  }
  if (error.status) {
    return {
      title: `研究运行失败（HTTP ${error.status}）`,
      detail: "后端返回了错误状态，通常是模型配置或测速环境的问题。",
      raw: error.detail || error.message,
      retry: true,
    };
  }
  return { title: "研究运行失败", detail: error.message, raw: "", retry: true };
}

/* ---------- status & progress ---------- */

function setStatus(state, text) {
  runStatus = state;
  $("#cancel-run").hidden = state !== "running" || !activeRun;
  $("#status").dataset.state = state;
  $("#status").textContent = text;
  updateFollowUp();
}

function updateFollowUp() {
  const hasNewerTurn = serverRuns.some((run) => run.parent_id === activeRun);
  $("#follow-up").hidden = !activeRun || hasNewerTurn || $("#status").textContent === "读取中";
  $("#follow-up-send").disabled = runStatus === "running" || pendingFollowUp;
  $("#follow-up-send").setAttribute("aria-label", pendingFollowUp ? "发送中" : "发送");
  $("#retry-turn").hidden = $("#follow-up").hidden || !currentTurn ||
    !["failed", "interrupted", "cancelled", "stopped"].includes(runStatus);
}

function tickClock() {
  if (runStatus !== "running") return;
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const done = experiments.filter((entry) => entry.result).length;
  $("#progress-text").textContent = `已完成 ${done} 轮实验 · 已用时 ${seconds} 秒`;
  $("#progress-fill").parentElement.hidden = true;
}

function startClock() {
  startedAt = Date.now();
  stopClock();
  $("#progress").hidden = false;
  tickClock();
  clock = setInterval(tickClock, 1000);
}

function stopClock() {
  if (clock) clearInterval(clock);
  clock = null;
  $("#progress").hidden = true;
}

/* ---------- history ---------- */

function loadHistory() {
  try {
    const list = JSON.parse(localStorage.getItem(HISTORY_KEY));
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function saveHistory(list) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_MAX)));
  } catch {
    /* storage disabled: history is an enhancement, ignore */
  }
}

function rememberRun(run) {
  const list = loadHistory().filter((entry) => entry.id !== run.id);
  list.unshift(run);
  saveHistory(list);
  renderHistory();
}

function timeLabel(timestamp) {
  const date = new Date(timestamp);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

let serverRuns = [];
let runsById = new Map();
let historyLimit = HISTORY_PAGE_SIZE;
let showArchived = false;
let threadMessages = new Map();

function historyEntries(search = false) {
  const query = search ? $("#history-search").value.trim().toLocaleLowerCase() : "";
  const parents = new Set(serverRuns.map((run) => run.parent_id));
  const list = serverRuns.length ? serverRuns.filter((run) => {
    return search ? Boolean(run.archived) === showArchived && (!query ||
      [run.question, run.title].some((text) => text?.toLocaleLowerCase().includes(query)))
      : !parents.has(run.id) && !run.archived;
  }).map((run) => ({
    id: run.id,
    question: search ? run.question : run.title || conversationTurns(run.id)[0]?.question || "（未记录问题）",
    at: new Date(run.created_at).getTime(),
    status: run.status,
  })) : showArchived && search ? [] : loadHistory();
  return query && !serverRuns.length ? list.filter((entry) => entry.question.toLocaleLowerCase().includes(query)) : list;
}

function conversationTurns(id) {
  const seen = new Set();
  const turns = [];
  while (id && !seen.has(id) && runsById.has(id)) {
    const turn = runsById.get(id);
    seen.add(id);
    turns.unshift(turn);
    id = turn.parent_id;
  }
  return turns;
}

function latestTurn(id) {
  return serverRuns.find((run) => conversationTurns(run.id).some((turn) => turn.id === id))?.id || id;
}

function renderConversation(id) {
  const latest = latestTurn(id);
  const earlier = conversationTurns(id).slice(0, -1);
  const container = $("#conversation-turns");
  const expanded = container.dataset.activeRun === id
    ? new Set([...container.querySelectorAll("details[open][data-turn]")].map((node) => node.dataset.turn))
    : new Set();
  const records = earlier.map((turn, index) => {
    const row = element("details", "", "previous-turn");
    row.dataset.turn = turn.id;
    row.open = expanded.has(turn.id);
    row.append(element("summary", `第 ${index + 1} 轮 · ${historyTitle(turn.question)}`));
    const saved = threadMessages.get(turn.id);
    const button = element("button", `第 ${index + 1} 轮 · ${statusLabels[turn.status] || "运行记录"} · 查看详情`, "view-button");
    button.type = "button";
    button.addEventListener("click", () => openRun(turn.id));
    const message = element("div", "", "user-message markdown-content");
    message.append(...renderMarkdown(turn.question));
    row.append(message);
    if (saved?.answer) {
      const answer = element("div", "", "assistant-answer");
      answer.append(...renderMarkdown(saved.answer));
      row.append(answer);
    }
    row.append(button);
    return row;
  });
  if (latest !== id) {
    const button = element("button", "返回最新一轮", "view-button");
    button.type = "button";
    button.addEventListener("click", () => openRun(latest));
    records.push(button);
  }
  container.dataset.activeRun = id;
  container.replaceChildren(...records);
}

function historyTitle(question) {
  const text = question.trim().replace(/\s+/g, " ");
  const firstSentence = text.split(/[。！？!?；;]|\.(?=\s|$)/, 1)[0].trim() || text;
  const characters = Array.from(firstSentence);
  return characters.length > 24 ? `${characters.slice(0, 24).join("").trimEnd()}…` : firstSentence;
}

function renderHistory(search = false) {
  const list = historyEntries(search);
  const target = search ? $("#history-search-results") : $("#history-list");
  if (!list.length) {
    target.replaceChildren(element("p", search ? "没有匹配的记录" : "暂无研究记录", "muted"));
    return;
  }
  const selectedThread = latestTurn(activeRun);
  const selectedIndex = list.findIndex((entry) => entry.id === selectedThread);
  if (!search) historyLimit = Math.max(historyLimit, selectedIndex + 1);
  const buttons = list.slice(0, search ? list.length : historyLimit).map((entry) => {
    const button = element("button", "", "history-item");
    button.type = "button";
    button.dataset.runId = entry.id;
    if (entry.id === selectedThread) button.setAttribute("aria-current", "true");
    button.title = entry.question;
    const question = historyTitle(entry.question);
    const meta = element("span", "", "history-meta");
    if (statusLabels[entry.status]) {
      const status = element("span", statusLabels[entry.status], "history-status");
      status.dataset.state = entry.status;
      meta.append(status);
    }
    button.append(element("span", question, "history-question"), meta);
    button.addEventListener("click", () => {
      if (search) $("#history-search-dialog").close();
      void openRun(entry.id);
    });
    const turn = runsById.get(entry.id);
    if (!turn?.session_id) return button;
    const row = element("div", "", "history-row");
    const archive = element("button", "", "icon-button archive-session");
    archive.type = "button";
    archive.title = turn.archived ? "恢复会话" : "归档会话";
    archive.setAttribute("aria-label", archive.title);
    archive.append(icon("M4 4h16v4H4z M6 8v12h12V8 M10 12h4"));
    archive.addEventListener("click", () => updateSession(entry.id, { archived: !turn.archived }));
    const openMenu = (x, y) => {
      sessionTarget = entry.id;
      const menu = $("#session-context");
      menu.style.left = Math.min(x, innerWidth - 120) + "px";
      menu.style.top = Math.min(y, innerHeight - 60) + "px";
      menu.showPopover();
      $("#rename-session").focus();
    };
    button.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openMenu(event.clientX, event.clientY);
    });
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
      event.preventDefault();
      const rect = button.getBoundingClientRect();
      openMenu(rect.left, rect.bottom);
    });
    row.append(button, archive);
    return row;
  });
  if (!search && list.length > historyLimit) {
    const more = element("button", `更多历史（${list.length - historyLimit}）`, "view-button history-more");
    more.type = "button";
    more.addEventListener("click", () => {
      const next = historyLimit;
      historyLimit += HISTORY_PAGE_SIZE;
      renderHistory();
      $("#history-list").children[next]?.focus();
    });
    buttons.push(more);
  }
  target.replaceChildren(...buttons);
}

async function loadServerHistory() {
  try {
    const data = await request("/api/runs");
    serverRuns = Array.isArray(data.runs) ? data.runs : [];
  } catch {
    // A transient error should not clear the history already displayed.
  }
  runsById = new Map(serverRuns.map((run) => [run.id, run]));
  renderHistory();
  if ($("#history-search-dialog").open) renderHistory(true);
  if (activeRun) renderConversation(activeRun);
  updateFollowUp();
}

let sessionTarget = "";
async function updateSession(id, changes) {
  const turn = runsById.get(id);
  if (!turn?.session_id) return false;
  const error = $("#rename-dialog").open ? $("#rename-error") : $("#session-error");
  error.hidden = true;
  try {
    await request(`/api/sessions/${turn.session_id}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    await loadServerHistory();
    return true;
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
    return false;
  }
}

async function openRun(id) {
  const version = ++viewVersion;
  stopClock();
  $(".workspace").hidden = false;
  hideInspector();
  document.body.classList.add("in-conversation");
  $("#research").hidden = true;
  runQuestion = "";
  activeRun = id;
  currentTurn = null;
  threadMessages = new Map();
  $("#assistant-answer").hidden = true;
  $("#assistant-answer").replaceChildren();
  $("#hint").hidden = true;
  $("#run-error").hidden = true;
  $("#report-node").hidden = true;
  $("#follow-up").reset();
  $("#run-attachments").replaceChildren();
  $("#session-error").hidden = true;
  $("#follow-up-error").hidden = true;
  renderConversation(id);
  $("#conversation").scrollTop = 0;
  $("#resource-usage").hidden = true;
  $("#resource-link").hidden = true;
  $("#cancel-run").disabled = false;
  selected = 0;
  experiments = [];
  isHistorical = true;
  cloudBudgetLimit = 0;
  memoryRunId = "";
  renderContext();
  $("#report-tab").disabled = true;
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = "完成可看";
  showView(false);
  setStatus("running", "读取中");
  const selectedThread = latestTurn(id);
  for (const button of $("#history-list").querySelectorAll("[data-run-id]")) {
    if (button.dataset.runId === selectedThread) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
  renderTimeline([]);
  try {
    const session = runsById.get(id);
    const [run, thread] = await Promise.all([
      request(`/api/runs/${id}`),
      session?.session_id ? request(`/api/sessions/${session.session_id}`).catch(() => null) : null,
    ]);
    if (version !== viewVersion) return;
    currentTurn = run;
    renderRunAttachments(run.attachments);
    threadMessages = new Map((thread?.turns || []).map((turn) => [turn.id, turn]));
    renderConversation(id);
    runQuestion = run.question || "";
    renderContext();
    setStatus(run.status, statusLabels[run.status]);
    renderTimeline(run.events || []);
    renderResources(run.resources);
    if (run.result) renderTurnResult(run.result);
    if (run.status === "running") $("#conversation").scrollTop = $("#conversation").scrollHeight;
    if (["failed", "interrupted", "cancelled", "stopped"].includes(run.status)) {
      $("#hint").textContent = run.error || "研究已停止，已保存可用记录。";
      $("#hint").hidden = false;
      return;
    }
    if (run.status === "complete") {
      setStatus("complete", "已完成");
      return;
    }
    setStatus("running", "运行中");
    startClock();
    await follow(id, version, run);
    if (version === viewVersion) stopClock();
  } catch (error) {
    if (version !== viewVersion) return;
    stopClock();
    failRun(error);
  }
}

/* ---------- views ---------- */

function showView(report) {
  $("#evidence-tab").setAttribute("aria-pressed", String(!report));
  $("#report-tab").setAttribute("aria-pressed", String(report));
  $("#evidence").hidden = report;
  $("#result").hidden = !report;
  syncUrl();
}

function syncUrl() {
  const params = new URLSearchParams(location.search);
  if (experiments.length) params.set("exp", String(selected + 1));
  params.set("view", $("#result").hidden ? "evidence" : "report");
  window.history.replaceState(null, "", `${location.pathname}?${params}`);
}

function experimentTitle(experiment, index) {
  if (experiment.task === "kernel") return `实验 ${index + 1} · 算子${experiment.suite === "validation" ? "复核" : "优化"}`;
  if (experiment.task === "classification") {
    return `实验 ${index + 1} · 分类（划分种子 ${experiment.split_seed}）`;
  }
  const workload = experiment.workload === "shared" ? "共享长前缀" : "不同前缀";
  return `实验 ${index + 1} · ${workload}`;
}

function renderRetrieval(group, fetched) {
  const details = element("details", "", "retrieval");
  const summary = element("summary", "", "retrieval-summary");
  summary.append(
    element("span", group.query || "未命名查询", "retrieval-query"),
    element("span", group.error ? "检索失败" : `${group.sources.length} 条`, "retrieval-count"),
  );
  details.append(summary);
  const list = element("ul", "", "retrieval-list");
  for (const hit of group.sources) {
    const entry = element("li");
    const link = element("a", hit.title || hit.id || "未命名来源");
    if (/^https?:\/\//i.test(hit.url)) {
      link.href = hit.url;
      link.target = "_blank";
      link.rel = "noopener";
    } else {
      link.href = "#";
      link.addEventListener("click", (event) => event.preventDefault());
    }
    const meta = element("span", "", "retrieval-meta");
    if (fetched.has(hit.id)) {
      const source = fetched.get(hit.id);
      const saved = element("a", source.content_kind === "paper_abstract" ? "已保存摘要" : "已保存正文", "retrieval-read");
      if (source.artifact) saved.href = `/api/runs/${activeRun}/${source.artifact}`;
      saved.target = "_blank";
      saved.rel = "noopener";
      meta.append(saved);
    }
    if (hit.kind) meta.append(element("span", hit.kind, "retrieval-kind"));
    entry.append(link, meta);
    list.append(entry);
  }
  details.append(list);
  return details;
}

function selectExperiment(index) {
  selected = index;
  for (const button of $("#events").querySelectorAll("[data-experiment-index]")) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.experimentIndex) === selected));
  }
  renderEvidence();
  showView(false);
  revealInspector();
}

function hideInspector(restoreFocus = false) {
  inspector.hidden = true;
  divider.hidden = true;
  if (restoreFocus && inspectorOpener?.isConnected) inspectorOpener.focus({ preventScroll: true });
  inspectorOpener = null;
}

function revealInspector() {
  if (!inspector.contains(document.activeElement)) inspectorOpener = document.activeElement;
  inspector.hidden = false;
  divider.hidden = false;
  ($("#result").hidden ? $("#evidence-tab") : $("#report-tab")).focus({ preventScroll: true });
}

const milestoneLabels = { plan: "研究计划", hypothesis: "待验证假设", verification: "验证决定", revision: "结论修正", decision: "预算决策", memory: "会话记忆" };
const decisionLabels = { retest: "复测", change_direction: "换验证方向", finish: "结束并生成报告" };
const timelineGroups = {
  preparation: "研究准备",
  search: "资料检索",
  experiment: "实验",
  decision: "结果与判断",
};
const milestoneGroups = {
  plan: "preparation", hypothesis: "preparation",
  verification: "decision", revision: "decision", decision: "decision", memory: "decision",
};

function renderMilestone(event) {
  const node = element("details", "", "milestone");
  let title = milestoneLabels[event.stage];
  if (event.stage === "decision") title += " · " + (decisionLabels[event.action] || event.action);
  node.append(element("summary", title), element("p", event.summary, "muted"));
  if (event.stage === "memory") {
    node.append(element("p", `适用条件：${event.conditions} · 模型提炼，未经人工审核，仅当前会话可用。`, "muted"));
  }
  if (event.stage === "decision") {
    const remaining = event.remaining_cost_cny == null ? "未设金额阈值" : "剩余约 ¥" + event.remaining_cost_cny.toFixed(4);
    node.append(element("p", event.evidence_gap, "muted"),
                element("p", `${remaining} · 报告预留约 ¥${event.report_reserve_cny.toFixed(4)} · 剩余模型调用 ${event.remaining_calls} 次`, "muted"));
    const parameters = event.parameters;
    if (parameters?.split_seed != null) {
      node.append(element("p", `补测划分种子 ${parameters.split_seed}`, "muted"));
    } else if (parameters?.workload) {
      const workload = parameters.workload === "shared" ? "共享长前缀" : "不同前缀";
      node.append(element("p", `补测配置 ${workload} · ${parameters.cache_first ? "先开后关" : "先关后开"}`, "muted"));
    }
  }
  for (const id of event.experiment_ids || []) {
    const index = experiments.findIndex((entry) => entry.experiment_id === id);
    if (index < 0) continue;
    const button = element("button", `查看${experimentTitle(experiments[index], index)}`, "view-button");
    button.type = "button";
    button.setAttribute("aria-controls", "details-panel");
    button.addEventListener("click", () => selectExperiment(index));
    node.append(button);
  }
  return node;
}

function renderTimeline(events) {
  const previousExperiment = experiments[selected];
  experiments = [];
  const searches = new Map();
  const fetched = new Map();
  const nodes = [];
  function searchGroup(query) {
    if (!searches.has(query)) {
      const group = { query, sources: [] };
      searches.set(query, group);
      nodes.push({ kind: "search", group });
    }
    return searches.get(query);
  }
  for (const event of events) {
    if (event.type === "started") {
      nodes.push({ kind: "experiment", index: experiments.length });
      experiments.push({ ...event, result: null });
    } else if (event.type === "search") {
      searchGroup(event.query || "").error = event.error;
    } else if (event.type === "progress" && milestoneGroups[event.stage]) {
      nodes.push({ kind: milestoneGroups[event.stage], event });
    } else if (event.type === "experiment_failed") {
      const pending = experiments.find((entry) => entry.experiment_id === event.experiment_id);
      if (pending) pending.failure = event;
    } else if (event.type === "completed") {
      const pending = experiments.find((entry) => !entry.result && (
        event.experiment_id ? entry.experiment_id === event.experiment_id
          : entry.workload === event.workload && entry.cache_first === event.cache_first && entry.reason === event.reason
      ));
      if (pending) pending.result = event;
    } else if (event.type === "source" || event.type === "retrieval") {
      // Backends emit either one event per source (`source`) or one per query (`retrieval`).
      const group = searchGroup(event.query || "");
      for (const item of event.results || [event]) {
        group.sources.push({
          id: item.source_id || item.id || "",
          title: item.title || "",
          url: item.url || "",
          kind: item.kind || "",
        });
      }
    } else if (event.type === "source_fetched") {
      if (event.source_id) fetched.set(event.source_id, event);
    } else if (event.type === "budget") {
      cloudBudgetLimit = Number(event.limit_calls) || 0;
      renderContext();
    } else if (event.type === "memory") {
      memoryRunId = event.run_id || "";
      renderContext();
    }
  }
  const timeline = $("#events");
  const previous = [...timeline.querySelectorAll("[data-timeline-node]")];
  const focused = previous.findIndex((node) => node.contains(document.activeElement));
  const controls = "summary, button, a";
  const focusedControl = focused < 0 ? -1
    : [...previous[focused].querySelectorAll(controls)].indexOf(document.activeElement);
  const expandedGroups = new Set([...timeline.querySelectorAll(".timeline-group[open]")].map((node) => node.dataset.start));
  const groups = [];
  for (const [position, { kind, group, event, index }] of nodes.entries()) {
    let section = groups.at(-1);
    if (section?.dataset.kind !== kind) {
      section = element("details", "", "timeline-group");
      section.dataset.kind = kind;
      section.dataset.start = position;
      section.open = expandedGroups.has(String(position));
      section.append(element("summary", timelineGroups[kind], "timeline-group-title"));
      groups.push(section);
    }
    if (group || event) {
      const node = group ? renderRetrieval(group, fetched) : renderMilestone(event);
      node.dataset.timelineNode = position;
      node.open = previous[position]?.open ?? false;
      section.append(node);
      continue;
    }
    const entry = experiments[index];
    const button = element("button", "", "experiment");
    button.type = "button";
    button.dataset.timelineNode = position;
    button.dataset.experimentIndex = index;
    button.setAttribute("aria-pressed", String(index === selected));
    button.setAttribute("aria-controls", "details-panel");
    const head = element("span", "", "experiment-head");
    head.append(
      element("span", experimentTitle(entry, index), "experiment-title"),
      element("span", entry.result ? "已完成" : entry.failure ? "失败/已停止" : runStatus === "running" ? "测量中" : "未完成", "experiment-state"),
    );
    button.append(head);
    button.addEventListener("click", () => selectExperiment(index));
    section.append(button);
  }
  timeline.replaceChildren(...groups);
  if (focused >= 0) {
    const node = timeline.querySelector(`[data-timeline-node="${focused}"]`);
    (focusedControl < 0 ? node : node?.querySelectorAll(controls)[focusedControl])?.focus({ preventScroll: true });
  }
  const experiment = experiments[selected];
  if (!previousExperiment || !experiment || previousExperiment.experiment_id !== experiment.experiment_id ||
      previousExperiment.result !== experiment.result || previousExperiment.failure !== experiment.failure) {
    renderEvidence();
  }
}

function renderEvidence() {
  const panel = $("#evidence");
  const experiment = experiments[selected];
  if (!experiment) {
    panel.replaceChildren(emptyState("从对话中选择一轮实验，查看实测结果。"));
    return;
  }

  const order = experiment.cache_first ? "先开后关" : "先关后开";
  const head = element("div", "", "evidence-head");
  head.append(element("h3", experimentTitle(experiment, selected)));
  const classification = experiment.task === "classification";
  if (experiment.task === "prefix_cache") head.append(element("span", order, "tag"));
  panel.replaceChildren(head, element("p", experiment.reason, "reason"));
  if (experiment.failure) {
    panel.append(element("p", `实验未完成：${experiment.failure.error || experiment.failure.status}。资源记录已保存。`));
    return;
  }
  if (!experiment.result) {
    panel.append(element("p", runStatus === "running" ? "实验运行中…" : "该实验没有返回结果。", "muted"));
    return;
  }

  const evidence = experiment.result;
  if (evidence.resources) {
    const usage = evidence.resources;
    const memory = usage.peak_process_rss_bytes == null ? "未计量" : `${number.format(usage.peak_process_rss_bytes / 1024 / 1024)} MiB`;
    panel.append(element("p", `耗时 ${number.format(usage.elapsed_seconds)} 秒 · CPU ${usage.cpu_seconds == null ? "未计量" : number.format(usage.cpu_seconds) + " 秒"} · 最大单进程峰值内存 ${memory}`, "context"));
  }
  const stats = evidence.summary;
  if (experiment.task === "kernel") {
    panel.append(element("p", stats.correct ? "数值检查通过" : "数值检查未通过", "tag"));
    if (stats.error) panel.append(element("p", stats.error));
    const wrapper = element("div", "", "table-scroll");
    const table = element("table");
    const header = table.createTHead().insertRow();
    for (const label of ["输入规模", "基线 ms", "候选 ms", "加速比", "最大误差"]) header.append(element("th", label));
    for (const item of stats.cases || []) {
      const row = table.insertRow();
      for (const value of [item.shape.join(" × "), item.baseline_ms?.toFixed(4) ?? "—",
                          item.candidate_ms?.toFixed(4) ?? "—", item.speedup?.toFixed(2) ?? "—",
                          item.max_abs_error?.toExponential(2) ?? "未通过"]) row.append(element("td", value));
    }
    wrapper.append(table);
    const source = element("details");
    source.append(element("summary", "候选代码"), element("pre", evidence.code || ""));
    panel.append(wrapper, source, element("p", stats.method || "", "muted"));
  } else if (classification) panel.append(classificationTable(stats));
  else panel.append(...prefixCacheEvidence(stats));

  const raw = element("a", "打开原始实验记录 ↗");
  raw.href = `/api/runs/${activeRun}/${evidence.artifact.split("/").pop()}`;
  raw.target = "_blank";
  raw.rel = "noopener";
  const replay = element("details");
  replay.append(element("summary", "复跑命令"));
  const shell = element("div", "", "pre-wrap");
  const code = element("pre", evidence.reproduce_from_project_root);
  const copy = element("button", "复制", "copy");
  copy.type = "button";
  copy.addEventListener("click", () => copyText(evidence.reproduce_from_project_root, copy, code));
  shell.append(code, copy);
  replay.append(shell);
  panel.append(raw, replay);
}

function prefixCacheEvidence(stats) {
  const drop = 1 - stats.median_ttft_ms_on / Math.max(stats.median_ttft_ms_off, 1);

  const chart = element("figure", "", "chart");
  const chartHead = element("div", "", "chart-head");
  chartHead.append(
    element("h4", "首 token 延迟 · TTFT 中位数"),
    element("span", `${drop >= 0 ? "↓" : "↑"} ${Math.abs(drop * 100).toFixed(1)}%${drop >= 0 ? " 更快" : " 更慢"}`, drop >= 0 ? "delta" : "delta up"),
  );
  chart.append(chartHead);
  const maximum = Math.max(stats.median_ttft_ms_off, stats.median_ttft_ms_on, 1);
  for (const [label, value, style] of [
    ["关缓存", stats.median_ttft_ms_off, ""],
    ["开缓存", stats.median_ttft_ms_on, "on"],
  ]) {
    const row = element("div", "", "bar-row");
    const track = element("div", "", "bar-track");
    track.setAttribute("aria-hidden", "true");
    const bar = element("div", "", `bar ${style}`);
    bar.style.width = `${(value / maximum) * 100}%`;
    track.append(bar);
    row.append(element("span", label, "bar-label"), track, element("span", `${number.format(value)} ms`, "bar-value"));
    chart.append(row);
  }

  const diff = stats.median_ttft_ms_on - stats.median_ttft_ms_off;
  const metrics = element("div", "", "stats");
  metrics.append(
    statCard("缓存命中（中位数）", number.format(stats.median_cached_tokens_on), "token"),
    statCard("输出文本一致", `${stats.matching_texts} / ${stats.requests_per_arm}`, "条"),
    statCard("每组请求数", String(stats.requests_per_arm), "条"),
    statCard("TTFT 差值", `${diff <= 0 ? "−" : "+"}${number.format(Math.abs(diff))}`, "ms"),
  );

  return [chart, metrics];
}

function classificationTable(stats) {
  const wrapper = element("div", "", "table-scroll");
  const table = element("table");
  const header = table.createTHead().insertRow();
  for (const label of ["少数类指标", "默认", "类别加权"]) header.append(element("th", label));
  const body = table.createTBody();
  for (const [label, key] of [["召回率", "recall"], ["精确率", "precision"], ["F1", "f1"], ["误报数", "false_positives"]]) {
    const row = body.insertRow();
    row.append(element("th", label));
    for (const arm of [stats.unweighted, stats.balanced]) {
      const value = key === "false_positives" ? arm.confusion_matrix[0][1] : `${number.format(arm[key] * 100)}%`;
      row.append(element("td", value));
    }
  }
  wrapper.append(table);
  return wrapper;
}

function renderFailure(info) {
  const panel = $("#run-error");
  const block = element("div", "", "state-block");
  block.append(
    icon(ICON_ALERT, "state-icon"),
    element("h3", info.title, "state-title"),
    element("p", info.detail, "state-detail"),
  );
  const actions = element("div", "", "state-actions");
  const retry = element("button", "重试", "secondary");
  retry.type = "button";
  retry.addEventListener("click", () => {
    if (!activeRun) {
      void beginRun(runQuestion);
    } else if (!$("#follow-up").hidden) {
      $("#follow-up-question").value = runQuestion;
      $("#follow-up-question").focus();
    }
  });
  actions.append(retry);
  block.append(actions);
  if (info.raw) {
    const details = element("details", "", "state-raw");
    details.append(element("summary", "技术详情"), element("pre", info.raw));
    block.append(details);
  }
  panel.replaceChildren(block);
  panel.hidden = false;
}

function failRun(error) {
  setStatus("failed", "运行失败");
  const info = describeError(error);
  $("#hint").hidden = false;
  $("#hint").textContent = "研究未完成，已保存的资源和过程仍可查看。";
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = $("#report-tab").disabled ? "未生成" : "部分记录";
  renderFailure(info);
}

async function copyText(text, button, codeNode) {
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch {
    copied = legacyCopy(text);
  }
  if (copied) {
    button.textContent = "已复制";
  } else if (codeNode) {
    const range = document.createRange();
    range.selectNodeContents(codeNode);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    button.textContent = "已选中 · 按 Ctrl+C";
  } else {
    button.textContent = "复制失败";
  }
  setTimeout(() => { button.textContent = "复制"; }, 2400);
}

function legacyCopy(text) {
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

/* ---------- markdown ---------- */

function appendInline(node, text) {
  const tokens = /\x60[^\x60\n]+\x60|\[[^\]\n]+\]\([^\s)]+\)|https?:\/\/[^\s<>]+|\*\*[^*\n]+\*\*|\*[^*\n]+\*/g;
  let cursor = 0;
  for (const match of text.matchAll(tokens)) {
    node.append(document.createTextNode(text.slice(cursor, match.index)));
    const part = match[0];
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link || /^https?:\/\//.test(part)) {
      const href = link ? link[2] : part.replace(/[.,;!?，。；！？]+$/, "");
      let url;
      try { url = new URL(href); } catch { /* invalid links stay plain text */ }
      if (url && ["https:", "http:"].includes(url.protocol)) {
        const anchor = element("a", link ? link[1] : href);
        anchor.href = url.href;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        node.append(anchor);
        if (!link) node.append(document.createTextNode(part.slice(href.length)));
      } else node.append(document.createTextNode(part));
    } else if (part.startsWith("**")) node.append(appendInline(element("strong"), part.slice(2, -2)));
    else if (part.startsWith("*")) node.append(appendInline(element("em"), part.slice(1, -1)));
    else node.append(element("code", part.slice(1, -1)));
    cursor = match.index + part.length;
  }
  node.append(document.createTextNode(text.slice(cursor)));
  return node;
}

function renderMarkdown(markdown) {
  const nodes = [];
  const segments = markdown.trim().split(/^```[^\n]*\n([\s\S]*?)^```[ \t]*$/gm);
  for (const [index, segment] of segments.entries()) {
    if (index % 2) {
      nodes.push(element("pre", segment.trimEnd()));
      continue;
    }
    for (const block of segment.trim().split(/\n[ \t]*\n/).filter(Boolean)) {
      const lines = block.split("\n");
      if (lines.length > 1 && /^\s*\|?\s*:?-{3}/.test(lines[1]) && lines[1].includes("|")) {
        const wrapper = element("div", "", "table-scroll");
        const table = element("table");
        const head = table.createTHead();
        const body = table.createTBody();
        for (const [position, line] of [lines[0], ...lines.slice(2)].entries()) {
          const row = (position ? body : head).insertRow();
          for (const cell of line.trim().replace(/^\||\|$/g, "").split("|")) {
            row.append(appendInline(element(position ? "td" : "th"), cell.trim()));
          }
        }
        wrapper.append(table);
        nodes.push(wrapper);
      } else {
        let list;
        for (const line of lines) {
          const item = line.match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
          if (item) {
            const tag = item[2] ? "ol" : "ul";
            if (list?.localName !== tag) {
              list = element(tag);
              if (item[2]) list.start = Number(item[2]);
              nodes.push(list);
            }
            list.append(appendInline(element("li"), item[3]));
            continue;
          }
          list = null;
          const heading = line.match(/^#{1,6}\s+(.+)$/);
          nodes.push(appendInline(element(heading ? "h3" : "p"), heading ? heading[1] : line));
        }
      }
    }
  }
  return nodes;
}

function renderResources(resources) {
  const node = $("#resource-usage");
  if (!resources) return;
  node.hidden = false;
  const label = `已知费用 ¥${resources.estimated_cost_cny.toFixed(3)} · ${resources.experiments} 次实验${resources.unknown_cost_actions ? " · 部分费用未知" : ""}`;
  if (node.textContent !== label) node.textContent = label;
  $("#resource-link").dataset.runId = activeRun;
  $("#resource-link").hidden = !activeRun;
}

function renderReport(result) {
  renderResources(result.resources);
  const { input_tokens, output_tokens } = result.usage;
  $("#usage").textContent = `${number.format(result.elapsed_seconds)} 秒 · 输入 ${number.format(input_tokens)} token · 输出 ${number.format(output_tokens)} token`;
  $("#report-link").href = `/api/runs/${activeRun}/report.md`;
  $("#export-link").href = `/api/runs/${activeRun}/export`;
  $("#report").replaceChildren(...renderMarkdown(result.report));
  $("#report-experiments").replaceChildren(...experiments.flatMap((entry, index) => {
    if (!entry.result) return [];
    const button = element("button", `查看${experimentTitle(entry, index)}`);
    button.type = "button";
    button.addEventListener("click", () => selectExperiment(index));
    return [button];
  }));
  $("#report-tab").disabled = false;
  $("#report-hint").hidden = true;
  $("#report-node").hidden = false;
}

function renderTurnResult(result) {
  if (result.mode === "chat" && result.answer) {
    const answer = $("#assistant-answer");
    answer.replaceChildren(...renderMarkdown(result.answer));
    answer.hidden = false;
    renderResources(result.resources);
    $("#report-hint").textContent = "本轮为问答";
    if (runStatus === "running") {
      const conversation = $("#conversation");
      conversation.scrollTop = conversation.scrollHeight;
    }
    return;
  }
  renderReport(result);
}

/* ---------- run ---------- */

async function follow(id, version, initial) {
  let events = initial?.events || [];
  let cursor = initial?.event_count ?? events.length;
  while (version === viewVersion) {
    const run = await request(`/api/runs/${id}?after=${cursor}`);
    if (version !== viewVersion) return;
    // Older local servers return the full history and omit the cursor.
    const newEvents = run.event_count == null ? run.events.slice(cursor) : run.events;
    cursor = run.event_count ?? run.events.length;
    if (newEvents.some((event) => event.type !== "resources")) {
      events = events.concat(newEvents.filter((event) => event.type !== "resources"));
      const conversation = $("#conversation");
      const nearBottom = conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 60;
      $("#hint").hidden = true;
      renderTimeline(events);
      tickClock();
      if (nearBottom) conversation.scrollTop = conversation.scrollHeight;
    }
    renderResources(run.resources);
    currentTurn = { ...currentTurn, ...run };
    if (run.result) renderTurnResult(run.result);
    if (["cancelled", "stopped"].includes(run.status)) {
      setStatus(run.status, statusLabels[run.status]);
      void loadServerHistory();
      return run;
    }
    if (run.status === "failed" || run.status === "interrupted") {
      throw new RequestError(run.error || "研究运行失败", { kind: "run", detail: run.error || "" });
    }
    if (run.status === "complete") {
      setStatus("complete", "已完成");
      void loadServerHistory();
      if (!events.length && !run.result?.answer) {
        $("#hint").hidden = false;
        $("#hint").textContent = "本次研究未返回实测记录。";
      }
      return run;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

async function beginRun(question, attachments = initialAttachments) {
  if (!question || $("#start").disabled) return;
  initialAttachments = attachments;
  renderRunAttachments(attachments);
  const version = ++viewVersion;
  stopClock();
  runQuestion = question;
  $(".workspace").hidden = false;
  hideInspector();
  document.body.classList.add("in-conversation");
  $("#research").hidden = true;
  cloudBudgetLimit = 0;
  memoryRunId = "";
  isHistorical = false;
  runStartedLabel = timeLabel(Date.now());
  activeRun = "";
  currentTurn = null;
  $("#assistant-answer").hidden = true;
  $("#assistant-answer").replaceChildren();
  currentTurn = null;
  $("#assistant-answer").hidden = true;
  $("#conversation-turns").replaceChildren();
  $("#report-node").hidden = true;
  $("#resource-usage").hidden = true;
  $("#resource-link").hidden = true;
  experiments = [];
  selected = 0;
  $("#start").disabled = true;
  $("#report-tab").disabled = true;
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = "完成可看";
  $("#context").hidden = false;
  renderContext();
  $("#hint").hidden = false;
  $("#run-error").hidden = true;
  $("#hint").textContent = "正在规划首轮实验…";
  showView(false);
  setStatus("running", "运行中");
  renderTimeline([]);
  startClock();
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, attachments, mode: $("#initial-mode").value,
        max_cost_cny: $("#cost-budget").value ? Number($("#cost-budget").value) : null }),
    });
    if (version !== viewVersion) return;
    activeRun = run.id;
    updateFollowUp();
    $("#cancel-run").hidden = false;
    $("#cancel-run").disabled = false;
    $("#research").hidden = true;
    rememberRun({ id: run.id, question, at: Date.now() });
    void loadServerHistory();
    await follow(run.id, version);
  } catch (error) {
    if (version === viewVersion) failRun(error);
  } finally {
    if (version === viewVersion) stopClock();
    $("#start").disabled = false;
  }
}

function renderRunAttachments(attachments = []) {
  $("#run-attachments").replaceChildren(...attachments.map(({ name }) => element("li", name)));
}

function setupComposer(form, sendId, modeId, budgetId, defaultMode) {
  const tools = form.querySelector(".composer-tools");
  tools.append($("#composer-tools").content.cloneNode(true));
  const textarea = form.querySelector("textarea");
  const files = tools.querySelector(".attachment-input");
  const list = tools.querySelector(".attachments");
  const error = tools.querySelector(".attachment-error");
  const mode = tools.querySelector("select");
  const budget = tools.querySelector('input[type="number"]');
  const settings = tools.querySelector(".composer-settings");
  const settingsButton = tools.querySelector(".settings-button");
  const send = tools.querySelector(".send-button");
  let filesToSend = [];
  let selection = 0;

  send.id = sendId;
  mode.id = modeId;
  mode.value = defaultMode;
  mode.options[mode.selectedIndex].defaultSelected = true;
  budget.id = budgetId;
  settings.id = `${form.id}-settings`;
  settingsButton.setAttribute("popovertarget", settings.id);

  const renderMode = () => { tools.querySelector(".composer-mode").textContent = mode.selectedOptions[0].textContent; };
  function useAttachments(next) {
    filesToSend = next;
    list.hidden = !next.length;
    list.replaceChildren(...next.map(({ name }, index) => {
      const item = element("li", name);
      const remove = element("button", "×", "icon-button");
      remove.type = "button";
      remove.setAttribute("aria-label", `移除 ${name}`);
      remove.addEventListener("click", () => useAttachments(filesToSend.filter((_, slot) => slot !== index)));
      item.append(remove);
      return item;
    }));
  }

  tools.querySelector(".attach").addEventListener("click", () => files.click());
  files.addEventListener("change", async () => {
    const picked = Array.from(files.files);
    const version = ++selection;
    files.value = "";
    if (!picked.length) return;
    error.hidden = true;
    const attach = tools.querySelector(".attach");
    attach.disabled = true;
    try {
      const next = [];
      if (filesToSend.length + picked.length > 3) throw new Error("每轮最多添加 3 个文本附件。");
      for (const file of picked) {
        if (!/\.(txt|md|csv|json)$/i.test(file.name) || file.size > 12_000 || file.name.length > 160) {
          throw new Error("仅支持 TXT、MD、CSV、JSON；每份最多 3,000 字。");
        }
        const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
        if (!content.trim() || content.includes("\0") || Array.from(content).length > 3000) {
          throw new Error("请添加非空的 UTF-8 文本，每份最多 3,000 字。");
        }
        next.push({ name: file.name, content });
      }
      if (version === selection) useAttachments([...filesToSend, ...next]);
    } catch (failure) {
      if (version !== selection) return;
      error.textContent = failure instanceof TypeError ? "无法读取文件，请使用 UTF-8 文本。" : failure.message;
      error.hidden = false;
    } finally {
      attach.disabled = false;
    }
  });
  form.addEventListener("submit", (event) => {
    if (!tools.querySelector(".attach").disabled) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  });
  form.addEventListener("reset", () => {
    selection++;
    useAttachments([]);
    error.hidden = true;
    if (settings.matches(":popover-open")) settings.hidePopover();
    queueMicrotask(renderMode);
  });
  mode.addEventListener("change", renderMode);
  budget.addEventListener("invalid", () => {
    if (!settings.matches(":popover-open")) settings.showPopover();
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!event.repeat && !send.disabled) form.requestSubmit(send);
  });
  renderMode();
  return { useAttachments, attachments: () => filesToSend };
}

const composers = {
  initial: setupComposer($("#research"), "start", "initial-mode", "cost-budget", "research"),
  followUp: setupComposer($("#follow-up"), "follow-up-send", "follow-up-mode", "follow-up-budget", "chat"),
};

/* ---------- wiring ---------- */

$("#new-research").addEventListener("click", () => {
  ++viewVersion;
  stopClock();
  activeRun = "";
  initialAttachments = [];
  $("#resource-usage").hidden = true;
  $("#resource-link").hidden = true;
  hideInspector();
  $(".workspace").hidden = true;
  document.body.classList.remove("in-conversation");
  $("#research").hidden = false;
  $("#research").reset();
  $("#question").focus();
  void loadServerHistory();
});

$("#cancel-run").addEventListener("click", async () => {
  const id = activeRun;
  $("#cancel-run").disabled = true;
  try {
    await request(`/api/runs/${id}/cancel`, { method: "POST" });
    $("#hint").hidden = false;
    $("#hint").textContent = "正在停止；已发出的云端请求返回后将保存用量。";
  } catch (error) {
    $("#hint").hidden = false;
    $("#hint").textContent = error.message;
    $("#cancel-run").disabled = false;
  }
});

$("#evidence-tab").addEventListener("click", () => showView(false));
$("#report-tab").addEventListener("click", () => showView(true));
$("#close-details").addEventListener("click", () => hideInspector(true));
inspector.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !event.defaultPrevented) hideInspector(true);
});
$("#report-node").addEventListener("click", () => {
  showView(true);
  revealInspector();
});

const historyDialog = $("#history-search-dialog");
$("#open-history-search").addEventListener("click", () => {
  renderHistory(true);
  historyDialog.showModal();
});
$("#close-history-search").addEventListener("click", () => historyDialog.close());
$("#history-search").addEventListener("input", () => renderHistory(true));
$("#history-archive").addEventListener("click", () => {
  showArchived = !showArchived;
  $("#history-archive").setAttribute("aria-pressed", String(showArchived));
  renderHistory(true);
});
$("#rename-session").addEventListener("click", () => {
  $("#session-context").hidePopover();
  const turn = runsById.get(sessionTarget);
  $("#session-title").value = turn.title || historyTitle(conversationTurns(sessionTarget)[0]?.question || turn.question);
  $("#rename-error").hidden = true;
  $("#rename-dialog").showModal();
  $("#session-title").select();
});
$("#cancel-rename").addEventListener("click", () => $("#rename-dialog").close());
$("#session-title-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("#session-title").value.trim();
  if (title && await updateSession(sessionTarget, { title })) $("#rename-dialog").close();
});

$("#retry-turn").addEventListener("click", () => {
  $("#follow-up-question").value = currentTurn.question || runQuestion;
  $("#follow-up-mode").value = currentTurn.mode || "research";
  $("#follow-up-budget").value = currentTurn.max_cost_cny ?? "";
  composers.followUp.useAttachments(currentTurn.attachments || []);
  $("#follow-up").requestSubmit();
});

$("#follow-up").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#follow-up-question").value.trim();
  if (!question || !activeRun || pendingFollowUp || runStatus === "running") return;
  const parentId = activeRun;
  const version = viewVersion;
  const budget = $("#follow-up-budget").value;
  const mode = $("#follow-up-mode").value;
  const attachments = composers.followUp.attachments();
  const error = $("#follow-up-error");
  pendingFollowUp = true;
  error.hidden = true;
  updateFollowUp();
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode, attachments,
        parent_id: parentId, max_cost_cny: budget ? Number(budget) : null }),
    });
    await loadServerHistory();
    if (version === viewVersion) void openRun(run.id);
  } catch (failure) {
    if (version === viewVersion) {
      error.textContent = failure.message;
      error.hidden = false;
    }
  } finally {
    pendingFollowUp = false;
    updateFollowUp();
  }
});

$("#research").addEventListener("submit", (event) => {
  event.preventDefault();
  beginRun($("#question").value.trim(), composers.initial.attachments());
});

loadServerHistory();

const $ = (selector) => document.querySelector(selector);
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const MODEL = "deepseek-flash";
const HISTORY_KEY = "bohack.recent-runs";
const HISTORY_MAX = 5;
const SVG_NS = "http://www.w3.org/2000/svg";

let experiments = [];
let selected = 0;
let activeRun = "";
let runStatus = "idle";
let runBudget = 3;
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
  $("#status").dataset.state = state;
  $("#status").textContent = text;
}

function tickClock() {
  if (runStatus !== "running") return;
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const done = experiments.filter((entry) => entry.result).length;
  $("#progress-text").textContent = `第 ${Math.min(done + 1, runBudget)} / ${runBudget} 轮 · 已用时 ${seconds} 秒`;
  $("#progress-fill").style.width = `${(done / runBudget) * 100}%`;
}

function startClock(budget) {
  runBudget = budget;
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

function renderHistory() {
  const list = loadHistory();
  const section = $("#history");
  if (!list.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  $("#history-list").replaceChildren(...list.map((entry) => {
    const button = element("button", "", "history-item");
    button.type = "button";
    const question = entry.question.length > 26 ? `${entry.question.slice(0, 26)}…` : entry.question;
    button.append(element("span", timeLabel(entry.at), "history-time"), element("span", question, "history-question"));
    button.addEventListener("click", () => openRun(entry.id));
    return button;
  }));
}

async function openRun(id) {
  activeRun = id;
  selected = 0;
  experiments = [];
  $("#report-tab").disabled = true;
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = "完成可看";
  showView(false);
  setStatus("running", "读取中");
  try {
    const run = await request(`/api/runs/${id}`);
    renderTimeline(run.events || []);
    if (run.status === "failed") {
      throw new RequestError(run.error || "研究运行失败", { kind: "run" });
    }
    if (run.status === "complete") {
      setStatus("complete", "已完成");
      renderReport(run.result);
      return;
    }
    setStatus("running", "运行中");
    startClock(Number($("#budget").value));
    await follow(id);
    stopClock();
  } catch (error) {
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
  const workload = experiment.workload === "shared" ? "共享长前缀" : "不同前缀";
  return `实验 ${index + 1} · ${workload}`;
}

function renderRetrievals(list) {
  const box = $("#retrievals");
  if (!list.length) {
    box.replaceChildren();
    return;
  }
  box.replaceChildren(...list.map((item) => {
    const details = element("details", "", "retrieval");
    const summary = element("summary", "", "retrieval-summary");
    summary.append(
      element("span", "检索来源", "retrieval-label"),
      element("span", item.query, "retrieval-query"),
      element("span", `${item.results.length} 条`, "retrieval-count"),
    );
    details.append(summary);
    const list_node = element("ul", "", "retrieval-list");
    for (const hit of item.results) {
      const entry = element("li");
      const link = element("a", hit.title);
      if (hit.url) {
        link.href = hit.url;
        link.target = "_blank";
        link.rel = "noopener";
      } else {
        link.href = "#";
        link.addEventListener("click", (event) => event.preventDefault());
      }
      entry.append(link, element("span", hit.kind || hit.publisher || "", "retrieval-kind"));
      list_node.append(entry);
    }
    details.append(list_node);
    return details;
  }));
}

function selectExperiment(index) {
  selected = index;
  for (const [position, button] of [...$("#events").children].entries()) {
    button.setAttribute("aria-pressed", String(position === selected));
  }
  renderEvidence();
  showView(false);
}

function renderTimeline(events) {
  experiments = [];
  const retrievals = [];
  for (const event of events) {
    if (event.type === "started") {
      experiments.push({ ...event, result: null });
    } else if (event.type === "completed") {
      const pending = experiments.find((entry) => !entry.result && entry.workload === event.workload && entry.cache_first === event.cache_first && entry.reason === event.reason);
      if (pending) pending.result = event;
    } else if (event.type === "retrieval") {
      retrievals.push(event);
    }
  }
  renderRetrievals(retrievals);
  const timeline = $("#events");
  const focused = [...timeline.children].indexOf(document.activeElement);
  timeline.replaceChildren(...experiments.map((entry, index) => {
    const button = element("button", "", "experiment");
    button.type = "button";
    button.setAttribute("aria-pressed", String(index === selected));
    const head = element("span", "", "experiment-head");
    head.append(
      element("span", String(index + 1).padStart(2, "0"), "experiment-index"),
      element("span", experimentTitle(entry, index), "experiment-title"),
      element("span", entry.result ? "已完成" : runStatus === "failed" ? "未完成" : "测量中", "experiment-state"),
    );
    button.append(head, element("span", entry.reason, "experiment-reason"));
    button.addEventListener("click", () => selectExperiment(index));
    return button;
  }));
  if (focused >= 0) timeline.children[focused]?.focus({ preventScroll: true });
  renderEvidence();
}

function renderEvidence() {
  const panel = $("#evidence");
  const experiment = experiments[selected];
  if (!experiment) {
    panel.replaceChildren(emptyState("选择左侧任意一轮实验，查看缓存开关的实测对照。"));
    return;
  }

  const order = experiment.cache_first ? "先开后关" : "先关后开";
  const head = element("div", "", "evidence-head");
  head.append(element("h3", experimentTitle(experiment, selected)), element("span", order, "tag"));
  panel.replaceChildren(head, element("p", experiment.reason, "reason"));
  if (!experiment.result) {
    panel.append(element("p", runStatus === "failed" ? "该实验没有返回结果。" : "正在测量首 token 延迟…", "muted"));
    return;
  }

  const evidence = experiment.result;
  const stats = evidence.summary;
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

  const raw = element("a", "打开原始实验记录 ↗");
  raw.href = `/api/runs/${activeRun}/${evidence.artifact.split("/").pop()}`;
  raw.target = "_blank";
  raw.rel = "noopener";
  const actions = element("div", "", "link-row");
  actions.append(raw);

  const replay = element("details");
  replay.append(element("summary", "复跑命令"));
  const shell = element("div", "", "pre-wrap");
  const code = element("pre", evidence.reproduce_from_project_root);
  shell.append(code);
  const copy = element("button", "复制", "copy");
  copy.type = "button";
  copy.addEventListener("click", () => copyText(evidence.reproduce_from_project_root, copy, code));
  shell.append(copy);
  replay.append(shell);

  panel.append(chart, metrics, actions, replay);
}

function renderFailure(info) {
  const panel = $("#evidence");
  const block = element("div", "", "state-block");
  block.append(
    icon(ICON_ALERT, "state-icon"),
    element("h3", info.title, "state-title"),
    element("p", info.detail, "state-detail"),
  );
  const actions = element("div", "", "state-actions");
  const retry = element("button", "重试", "secondary");
  retry.type = "button";
  retry.addEventListener("click", () => beginRun($("#question").value.trim(), Number($("#budget").value)));
  actions.append(retry);
  block.append(actions);
  if (info.raw) {
    const details = element("details", "", "state-raw");
    details.append(element("summary", "技术详情"), element("pre", info.raw));
    block.append(details);
  }
  panel.replaceChildren(block);
  showView(false);
}

function failRun(error) {
  setStatus("failed", "运行失败");
  const info = describeError(error);
  $("#hint").hidden = false;
  $("#hint").textContent = "本次运行未产生结果，右侧可重试。";
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = "未生成";
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
  for (const [index, part] of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).entries()) {
    if (index % 2 === 0) node.append(document.createTextNode(part));
    else if (part.startsWith("**")) node.append(element("strong", part.slice(2, -2)));
    else node.append(element("code", part.slice(1, -1)));
  }
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
        for (const line of lines) {
          const heading = line.match(/^#{1,6}\s+(.+)$/);
          nodes.push(appendInline(element(heading ? "h3" : "p"), heading ? heading[1] : line));
        }
      }
    }
  }
  return nodes;
}

function renderReport(result) {
  const { input_tokens, output_tokens } = result.usage;
  $("#usage").textContent = `${number.format(result.elapsed_seconds)} 秒 · 输入 ${number.format(input_tokens)} token · 输出 ${number.format(output_tokens)} token`;
  $("#report-link").href = `/api/runs/${activeRun}/report.md`;
  $("#report").replaceChildren(...renderMarkdown(result.report));
  $("#report-experiments").replaceChildren(...experiments.flatMap((entry, index) => {
    if (!entry.result) return [];
    const button = element("button", `查看${experimentTitle(entry, index)}`);
    button.type = "button";
    button.addEventListener("click", () => {
      selectExperiment(index);
      $("#evidence-tab").focus();
    });
    return [button];
  }));
  $("#report-tab").disabled = false;
  $("#report-hint").hidden = true;
}

/* ---------- run ---------- */

async function follow(id) {
  let displayed = 0;
  while (true) {
    const run = await request(`/api/runs/${id}`);
    if (run.events.length !== displayed) {
      $("#hint").hidden = true;
      renderTimeline(run.events);
      displayed = run.events.length;
      tickClock();
    }
    if (run.status === "failed") {
      throw new RequestError(run.error || "研究运行失败", { kind: "run", detail: run.error || "" });
    }
    if (run.status === "complete") {
      renderReport(run.result);
      setStatus("complete", "已完成");
      if (!run.events.length) {
        $("#hint").hidden = false;
        $("#hint").textContent = "本次研究未返回实测记录。";
      }
      return run;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

async function beginRun(question, budget) {
  if (!question) return;
  runBudget = budget;
  activeRun = "";
  experiments = [];
  selected = 0;
  $("#start").disabled = true;
  $("#report-tab").disabled = true;
  $("#report-hint").hidden = false;
  $("#report-hint").textContent = "完成可看";
  $("#context").hidden = false;
  $("#context").textContent = `预算 ${budget} 次 · 模型 ${MODEL} · 开始 ${timeLabel(Date.now())}`;
  $("#hint").hidden = false;
  $("#hint").textContent = "正在规划首轮实验…";
  showView(false);
  setStatus("running", "运行中");
  renderTimeline([]);
  $("#events").replaceChildren();
  startClock(budget);
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_experiments: budget }),
    });
    activeRun = run.id;
    rememberRun({ id: run.id, question, at: Date.now() });
    await follow(run.id);
  } catch (error) {
    failRun(error);
  } finally {
    stopClock();
    $("#start").disabled = false;
  }
}

/* ---------- wiring ---------- */

$("#evidence-tab").addEventListener("click", () => showView(false));
$("#report-tab").addEventListener("click", () => showView(true));

$("#research").addEventListener("submit", (event) => {
  event.preventDefault();
  beginRun($("#question").value.trim(), Number($("#budget").value));
});

renderHistory();

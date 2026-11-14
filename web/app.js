const $ = (selector) => document.querySelector(selector);
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
let experiments = [];
let selected = 0;
let activeRun = "";
let runStatus = "idle";

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function setStatus(state, text) {
  runStatus = state;
  $("#status").dataset.state = state;
  $("#status").textContent = text;
}

function showView(report) {
  $("#evidence-tab").setAttribute("aria-pressed", String(!report));
  $("#report-tab").setAttribute("aria-pressed", String(report));
  $("#evidence").hidden = report;
  $("#result").hidden = !report;
}

function experimentTitle(experiment, index) {
  if (experiment.task === "classification") {
    return `实验 ${index + 1} · 分类（划分种子 ${experiment.split_seed}）`;
  }
  const workload = experiment.workload === "shared" ? "共享长前缀" : "不同前缀";
  return `实验 ${index + 1} · ${workload}`;
}

function selectExperiment(index) {
  selected = index;
  for (const button of $("#events").querySelectorAll("[data-experiment-index]")) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.experimentIndex) === selected));
  }
  renderEvidence();
  showView(false);
}

const milestoneLabels = { plan: "研究计划", hypothesis: "待验证假设", verification: "验证决定", revision: "结论修正" };

function renderMilestone(event) {
  const node = element("details", "", "milestone");
  const title = event.type === "search" ? "检索资料" : milestoneLabels[event.stage];
  const description = event.type === "search"
    ? `${event.query} · ${event.error ? "检索失败" : `找到 ${event.count} 条`}`
    : event.summary;
  node.append(element("summary", title), element("p", description, "muted"));
  for (const id of event.experiment_ids || []) {
    const index = experiments.findIndex((entry) => entry.experiment_id === id);
    if (index < 0) continue;
    const button = element("button", `查看${experimentTitle(experiments[index], index)}`, "view-button");
    button.type = "button";
    button.addEventListener("click", () => selectExperiment(index));
    node.append(button);
  }
  return node;
}

function renderTimeline(events) {
  experiments = [];
  const nodes = [];
  for (const event of events) {
    if (event.type === "started") {
      nodes.push({ experimentIndex: experiments.length });
      experiments.push({ ...event, result: null });
    } else if (event.type === "search" || (event.type === "progress" && milestoneLabels[event.stage])) {
      nodes.push({ event });
    } else if (event.type === "completed") {
      const pending = experiments.find((entry) => !entry.result && (
        event.experiment_id ? entry.experiment_id === event.experiment_id
          : entry.workload === event.workload && entry.cache_first === event.cache_first && entry.reason === event.reason
      ));
      if (pending) pending.result = event;
    }
  }
  const timeline = $("#events");
  const focused = [...timeline.children].indexOf(document.activeElement);
  const expanded = [...timeline.children].map((node) => node.open);
  timeline.replaceChildren(...nodes.map(({ event, experimentIndex: index }, position) => {
    if (event) {
      const node = renderMilestone(event);
      node.open = Boolean(expanded[position]);
      return node;
    }
    const entry = experiments[index];
    const button = element("button", "", "experiment");
    button.type = "button";
    button.dataset.experimentIndex = index;
    button.setAttribute("aria-pressed", String(index === selected));
    const title = element("span", experimentTitle(entry, index), "experiment-title");
    title.append(element("small", entry.result ? "已完成" : runStatus === "running" ? "测量中" : "未完成"));
    button.append(title, element("span", entry.reason, "experiment-reason"));
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
    panel.replaceChildren(element("p", "选择一轮实验，查看实测对照。", "empty muted"));
    return;
  }
  const order = experiment.cache_first ? "先开后关" : "先关后开";
  const classification = experiment.task === "classification";
  const title = experimentTitle(experiment, selected);
  panel.replaceChildren(element("h3", classification ? title : `${title} · ${order}`), element("p", experiment.reason, "reason"));
  if (!experiment.result) {
    panel.append(element("p", runStatus === "running" ? "实验运行中…" : "该实验没有返回结果。", "muted"));
    return;
  }

  const evidence = experiment.result;
  panel.append(...(classification ? [classificationTable(evidence.summary)] : prefixCacheEvidence(evidence.summary)));
  const raw = element("a", "打开原始实验记录 ↗");
  raw.href = `/api/runs/${activeRun}/${evidence.artifact.split("/").pop()}`;
  raw.target = "_blank";
  raw.rel = "noopener";
  const replay = element("details");
  replay.append(element("summary", "复跑命令"), element("pre", evidence.reproduce_from_project_root));
  panel.append(raw, replay);
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

function prefixCacheEvidence(stats) {
  const chart = element("figure", "", "chart");
  chart.append(element("h4", "首 token 延迟（TTFT 中位数）"));
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
    row.append(element("span", label), track, element("strong", `${number.format(value)} ms`));
    chart.append(row);
  }

  const metrics = element("dl", "", "metrics");
  for (const [label, value] of [
    ["缓存命中中位数", `${number.format(stats.median_cached_tokens_on)} token`],
    ["输出文本一致", `${stats.matching_texts} / ${stats.requests_per_arm} 条`],
  ]) {
    const metric = element("div");
    metric.append(element("dt", label), element("dd", value));
    metrics.append(metric);
  }

  return [chart, metrics];
}

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
}

const statusLabels = { running: "运行中", complete: "已完成", failed: "运行失败", interrupted: "已中断" };
const historyTime = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });
let viewVersion = 0;

function historyTitle(question) {
  const text = question.trim().replace(/\s+/g, " ");
  const firstSentence = text.split(/[。！？!?；;]|\.(?=\s|$)/, 1)[0].trim() || text;
  const characters = Array.from(firstSentence);
  return characters.length > 24 ? `${characters.slice(0, 24).join("").trimEnd()}…` : firstSentence;
}

async function refreshHistory() {
  const hint = $("#history-hint");
  try {
    const history = await request("/api/runs");
    $("#history-list").replaceChildren(...history.map((run) => {
      const button = element("button");
      button.type = "button";
      button.title = run.question;
      if (run.id === activeRun) button.setAttribute("aria-current", "true");
      button.append(
        element("span", historyTitle(run.question), "history-title"),
        element("small", `${historyTime.format(new Date(run.created_at))} · ${statusLabels[run.status]}`),
      );
      button.addEventListener("click", () => openRun(run.id));
      return button;
    }));
    hint.hidden = history.length > 0;
    hint.textContent = "暂无研究记录";
  } catch {
    hint.hidden = false;
    hint.textContent = "无法载入研究历史";
  }
}

function renderSources(events) {
  const sources = new Map();
  for (const event of events) {
    if (event.type === "source_fetched" || (event.type === "source" && !sources.has(event.source_id))) {
      sources.set(event.source_id, event);
    }
  }
  $("#sources").hidden = sources.size === 0;
  $("#source-list").replaceChildren(...Array.from(sources.values(), (source) => {
    const item = element("li");
    const link = element("a", source.title);
    if (/^https?:\/\//i.test(source.url)) link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener";
    item.append(link);
    if (source.type === "source_fetched") {
      const saved = element("a", source.content_kind === "paper_abstract" ? "查看摘要记录" : "查看正文记录");
      saved.href = `/api/runs/${activeRun}/${source.artifact}`;
      saved.target = "_blank";
      saved.rel = "noopener";
      item.append(document.createTextNode(" · "), saved);
    }
    return item;
  }));
}

function openWorkspace(question, text) {
  $(".workspace").hidden = false;
  $("#report-tab").disabled = true;
  $("#context").hidden = !question;
  $("#context").textContent = question;
  $("#hint").hidden = false;
  $("#hint").textContent = text;
  selected = 0;
  showView(false);
  setStatus("running", statusLabels.running);
  renderTimeline([]);
  renderSources([]);
}

function showRunError(message) {
  setStatus("failed", statusLabels.failed);
  $("#hint").hidden = false;
  $("#hint").textContent = message;
}

async function openRun(id, question = "") {
  const version = ++viewVersion;
  activeRun = id;
  $("#research").hidden = true;
  openWorkspace(question, "正在载入研究过程…");
  void refreshHistory();
  let displayed = -1;
  try {
    while (version === viewVersion) {
      const run = await request(`/api/runs/${id}`);
      if (version !== viewVersion) return;
      setStatus(run.status, statusLabels[run.status]);
      $("#context").textContent = run.question;
      $("#context").hidden = !run.question;
      if (run.events.length !== displayed || run.status !== "running") {
        renderTimeline(run.events);
        renderSources(run.events);
        displayed = run.events.length;
      }
      $("#hint").hidden = experiments.length > 0;
      $("#hint").textContent = run.error || (run.status === "running" ? "正在规划实验…" : "本次研究未返回实测记录。");
      if (run.error) $("#hint").hidden = false;
      if (run.status === "complete" && run.result) {
        renderReport(run.result);
        const report = element("button", "查看研究报告", "experiment");
        report.type = "button";
        report.addEventListener("click", () => showView(true));
        $("#events").append(report);
      }
      if (run.status !== "running") {
        void refreshHistory();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
  } catch (error) {
    if (version === viewVersion) showRunError(error.message);
  }
}

$("#new-research").addEventListener("click", () => {
  ++viewVersion;
  activeRun = "";
  $(".workspace").hidden = true;
  $("#research").hidden = false;
  $("#research").reset();
  $("#question").focus();
  void refreshHistory();
});

$("#evidence-tab").addEventListener("click", () => showView(false));
$("#report-tab").addEventListener("click", () => showView(true));

$("#budget").addEventListener("invalid", () => {
  $(".research-settings").open = true;
});

$("#research").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value.trim();
  const budget = Number($("#budget").value);
  $("#start").disabled = true;
  const version = ++viewVersion;
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_experiments: budget }),
    });
    if (version === viewVersion) void openRun(run.id, question);
    else void refreshHistory();
  } catch (error) {
    if (version === viewVersion) {
      openWorkspace(question, "");
      showRunError(error.message);
    }
  } finally {
    $("#start").disabled = false;
  }
});

void refreshHistory();

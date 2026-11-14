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

const SVG_NS = "http://www.w3.org/2000/svg";

function icon(pathData) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", pathData);
  svg.append(path);
  return svg;
}

function emptyState(text) {
  const box = element("div", "", "empty-state");
  box.append(icon("M4 19V5M4 19h16M8 15l3.2-4.4L14 14l2.8-3.6L19 13"), element("p", text));
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

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "已复制";
  } catch {
    button.textContent = "复制失败";
  }
  setTimeout(() => { button.textContent = "复制"; }, 1600);
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
  const workload = experiment.workload === "shared" ? "共享长前缀" : "不同前缀";
  return `实验 ${index + 1} · ${workload}`;
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
  for (const event of events) {
    if (event.type === "started") {
      experiments.push({ ...event, result: null });
    } else if (event.type === "completed") {
      const pending = experiments.find((entry) => !entry.result && entry.workload === event.workload && entry.cache_first === event.cache_first && entry.reason === event.reason);
      if (pending) pending.result = event;
    }
  }
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
    element("span", `${drop >= 0 ? "↓" : "↑"} ${Math.abs(drop * 100).toFixed(1)}%`, drop >= 0 ? "delta" : "delta up"),
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
  shell.append(element("pre", evidence.reproduce_from_project_root));
  const copy = element("button", "复制", "copy");
  copy.type = "button";
  copy.addEventListener("click", () => copyText(evidence.reproduce_from_project_root, copy));
  shell.append(copy);
  replay.append(shell);

  panel.append(chart, metrics, actions, replay);
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

async function follow(id) {
  let displayed = 0;
  while (true) {
    const run = await request(`/api/runs/${id}`);
    if (run.events.length !== displayed) {
      $("#hint").hidden = true;
      renderTimeline(run.events);
      displayed = run.events.length;
    }
    if (run.status === "failed") {
      setStatus("failed", "运行失败");
      renderTimeline(run.events);
      throw new Error(run.error);
    }
    if (run.status === "complete") {
      renderReport(run.result);
      setStatus("complete", "已完成");
      if (!run.events.length) $("#hint").textContent = "本次研究未返回实测记录。";
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

$("#evidence-tab").addEventListener("click", () => showView(false));
$("#report-tab").addEventListener("click", () => showView(true));

$("#research").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("#question").value.trim();
  const budget = Number($("#budget").value);
  $("#start").disabled = true;
  $("#report-tab").disabled = true;
  $("#context").hidden = false;
  $("#context").textContent = question;
  $("#hint").hidden = false;
  $("#hint").textContent = "正在规划首轮实验…";
  selected = 0;
  showView(false);
  setStatus("running", "运行中");
  renderTimeline([]);
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_experiments: budget }),
    });
    activeRun = run.id;
    await follow(run.id);
  } catch (error) {
    setStatus("failed", "运行失败");
    $("#hint").hidden = false;
    $("#hint").textContent = error.message;
  } finally {
    $("#start").disabled = false;
  }
});

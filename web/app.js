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
    const title = element("span", experimentTitle(entry, index), "experiment-title");
    title.append(element("small", entry.result ? "已完成" : runStatus === "failed" ? "未完成" : "测量中"));
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
    panel.replaceChildren(element("p", "选择一轮实验，查看缓存开关的实测对照。", "empty muted"));
    return;
  }
  const order = experiment.cache_first ? "先开后关" : "先关后开";
  panel.replaceChildren(element("h3", `${experimentTitle(experiment, selected)} · ${order}`), element("p", experiment.reason, "reason"));
  if (!experiment.result) {
    panel.append(element("p", runStatus === "failed" ? "该实验没有返回结果。" : "正在测量首 token 延迟…", "muted"));
    return;
  }

  const evidence = experiment.result;
  const stats = evidence.summary;
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

  const raw = element("a", "打开原始实验记录 ↗");
  raw.href = `/api/runs/${activeRun}/${evidence.artifact.split("/").pop()}`;
  raw.target = "_blank";
  raw.rel = "noopener";
  const replay = element("details");
  replay.append(element("summary", "复跑命令"), element("pre", evidence.reproduce_from_project_root));
  panel.append(chart, metrics, raw, replay);
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

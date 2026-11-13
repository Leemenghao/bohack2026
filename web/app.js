const $ = (selector) => document.querySelector(selector);
const form = $("#research");
const statusLabel = $("#status");
const resultPanel = $("#result");
const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function setStatus(state, text) {
  statusLabel.dataset.state = state;
  statusLabel.textContent = text;
}

function renderEvents(id, events) {
  const cards = [];
  for (const event of events) {
    const workload = event.workload === "shared" ? "共享长前缀" : "不同前缀";
    const order = event.cache_first ? "先开后关" : "先关后开";
    if (event.type === "started") {
      const card = element("article", "", "experiment");
      card.append(element("h3", `实验 ${cards.length + 1} · ${workload} · ${order}`));
      card.append(element("p", event.reason, "reason"), element("p", "正在测量…", "muted"));
      cards.push(card);
      continue;
    }
    const card = cards.find((item) => !item.dataset.complete);
    if (!card) continue;
    card.dataset.complete = "true";
    card.lastElementChild.remove();
    const s = event.summary;
    const metrics = element("dl", "", "metrics");
    for (const [label, value] of [
      ["首 token 延迟 · 关 → 开", `${number.format(s.median_ttft_ms_off)} → ${number.format(s.median_ttft_ms_on)} ms`],
      ["缓存命中", `${number.format(s.median_cached_tokens_on)} token`],
      ["文本一致", `${s.matching_texts} / ${s.requests_per_arm}`],
    ]) {
      const metric = element("div", "");
      metric.append(element("dt", label), element("dd", value));
      metrics.append(metric);
    }
    const link = element("a", "原始记录");
    link.href = `/api/runs/${id}/${event.artifact.split("/").pop()}`;
    link.target = "_blank";
    link.rel = "noopener";
    const replay = element("details", "");
    replay.append(element("summary", "复跑命令"), element("pre", event.reproduce_from_project_root));
    card.append(metrics, link, replay);
  }
  $("#events").replaceChildren(...cards);
}

function renderReport(id, result) {
  const { input_tokens, output_tokens } = result.usage;
  $("#usage").textContent = `${number.format(result.elapsed_seconds)} 秒 · 输入 ${number.format(input_tokens)} token · 输出 ${number.format(output_tokens)} token`;
  $("#report-link").href = `/api/runs/${id}/report.md`;
  $("#report").replaceChildren(...result.report.trim().split(/\n\s*\n/).map((block) => {
    const heading = block.match(/^#{1,6}\s+(.+)$/);
    return heading ? element("h3", heading[1]) : element("p", block);
  }));
  resultPanel.hidden = false;
}

async function follow(id) {
  let displayed = 0;
  while (true) {
    const run = await request(`/api/runs/${id}`);
    if (run.events.length !== displayed) {
      $("#hint").hidden = true;
      renderEvents(id, run.events);
      displayed = run.events.length;
    }
    if (run.status === "failed") throw new Error(run.error);
    if (run.status === "complete") {
      renderReport(id, run.result);
      setStatus("complete", "已完成");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#start").disabled = true;
  resultPanel.hidden = true;
  $("#events").replaceChildren();
  $("#hint").hidden = false;
  $("#hint").textContent = "正在规划首轮实验…";
  setStatus("running", "运行中");
  try {
    const run = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: $("#question").value.trim(), max_experiments: Number($("#budget").value) }),
    });
    await follow(run.id);
  } catch (error) {
    setStatus("failed", "运行失败");
    $("#hint").hidden = false;
    $("#hint").textContent = error.message;
  } finally {
    $("#start").disabled = false;
  }
});

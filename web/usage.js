(() => {
  const dialog = document.querySelector("#usage-dialog");
  const content = document.querySelector("#usage-content");
  const message = document.querySelector("#usage-message");
  const select = document.querySelector("#usage-turn");
  let request;
  const node = (tag, text, className = "") => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    result.className = className;
    return result;
  };
  const number = (v) => v == null ? "未计量" : Number(v).toLocaleString("zh-CN");
  const seconds = (v) => v == null ? "未计量" : `${Number(v).toFixed(2)} 秒`;
  const money = (v) => v == null ? "未知" : `¥${Number(v).toFixed(4)}`;
  const stages = {plan: "规划", hypothesis: "假设", evidence: "资料检索", experiment: "实验", verification: "验证", revision: "修正", decision: "决策"};
  const statuses = {completed: "完成", running: "进行中", failed: "失败", timeout: "超时", interrupted: "已中断", empty: "无结果"};

  function render(data) {
    const summary = data.summary;
    const cards = node("div", undefined, "usage-cards");
    for (const [label, value] of [
      [summary.unknown_cost_actions ? "已知费用 · 部分未知" : "估算费用", money(summary.estimated_cost_cny)],
      ["模型 token", number(summary.usage.input_tokens + summary.usage.output_tokens)],
      ["研究耗时", seconds(summary.elapsed_seconds)], ["实验", `${summary.experiments} 次`],
    ]) {
      const card = node("div"); card.append(node("span", label), node("strong", value)); cards.append(card);
    }
    const experiments = node("section", undefined, "usage-section");
    experiments.append(node("h3", "实验"));
    const rows = data.entries.filter((entry) => entry.kind === "experiment");
    if (!rows.length) experiments.append(node("p", "这一轮没有实验记录。", "muted"));
    rows.forEach((entry, index) => {
      const detail = node("details", undefined, "usage-experiment");
      const heading = node("summary");
      const label = {kernel: "算子优化", classification: "分类实验", prefix_cache: "前缀缓存"}[entry.task] || "实验";
      heading.append(node("span", `${String(index + 1).padStart(2, "0")}  ${label}`),
        node("span", `${statuses[entry.status] || entry.status} · ${seconds(entry.elapsed_seconds)}`, "muted"));
      const metrics = node("dl", undefined, "usage-metrics");
      const execution = entry.execution;
      for (const [key, value] of [
        ["执行位置", execution ? `${execution.kind === "local" ? "本机" : execution.kind} · ${execution.host} · ${execution.architecture}` : "历史记录未记录执行位置"],
        ["CPU 时间", seconds(entry.cpu_seconds)],
        ["峰值内存", entry.peak_process_rss_bytes == null ? "未计量" : `${(entry.peak_process_rss_bytes / 1024 ** 2).toFixed(1)} MB`],
        ["GPU 时间", "未计量"], ["实验 ID", entry.experiment_id],
      ]) metrics.append(node("dt", key), node("dd", value));
      detail.append(heading, node("p", entry.reason || "", "muted"), metrics);
      experiments.append(detail);
    });
    experiments.append(node("p", "CPU 时间与墙钟耗时含义不同；峰值内存为单进程高水位。模型 token 按调用记录，尚未归因到单个实验。", "usage-note"));
    const calls = node("details", undefined, "usage-section usage-calls");
    const entries = data.entries.filter((entry) => ["model", "search", "fetch"].includes(entry.kind));
    calls.append(node("summary", `模型与检索 · ${entries.length} 次调用`));
    const table = node("table");
    const head = node("tr");
    ["调用 / 阶段", "Token", "耗时", "估算费用"].forEach((value) => head.append(node("th", value)));
    const thead = node("thead"); thead.append(head); table.append(thead);
    const body = node("tbody");
    for (const entry of entries) {
      const row = node("tr");
      const cell = node("td");
      cell.append(node("strong", entry.kind === "model" ? entry.model : entry.kind === "search" ? "搜索" : "抓取"),
        node("small", `${stages[entry.stage] || entry.stage} · ${statuses[entry.status] || entry.status}`));
      const tokens = entry.kind === "model" ? `入 ${number(entry.input_tokens)} / 出 ${number(entry.output_tokens)}\n缓存命中 ${number(entry.cached_tokens)}` : "—";
      row.append(cell, node("td", tokens), node("td", seconds(entry.elapsed_seconds)), node("td", money(entry.estimated_cost_cny)));
      body.append(row);
    }
    table.append(body);
    const scroll = node("div", undefined, "usage-table-scroll"); scroll.append(table); calls.append(scroll);
    const notes = node("p", data.pricing?.basis || "费用为估算，非实际账单。", "usage-note");
    if (data.entries.some((entry) => entry.kind === "model" && entry.input_tokens == null)) {
      notes.append(" 部分模型调用未返回 token 用量，概览只合计已知部分。");
    }
    content.replaceChildren(cards, experiments, calls, notes);
  }

  async function load() {
    request?.abort();
    request = new AbortController();
    message.textContent = "正在读取用量…";
    content.replaceChildren();
    const download = document.querySelector("#usage-download");
    download.hidden = true;
    try {
      const response = await fetch(`/api/runs/${select.value}/resources.json`, {signal: request.signal});
      if (!response.ok) throw new Error("这一轮还没有用量记录。");
      const data = await response.json();
      render(data); message.textContent = "";
      download.href = `/api/runs/${select.value}/resources.json`;
      download.hidden = false;
    } catch (error) { if (error.name !== "AbortError") message.textContent = error.message; }
  }
  document.querySelector("#resource-link").addEventListener("click", async (event) => {
    const id = event.currentTarget.dataset.runId;
    if (!id) return;
    select.replaceChildren(new Option("当前轮次", id));
    document.querySelector("#usage-subtitle").textContent = "按轮次查看模型费用与实验资源";
    dialog.showModal();
    void load();
    try {
      const history = await (await fetch("/api/runs")).json();
      if (!dialog.open || select.value !== id) return;
      const sessionId = history.runs.find((run) => run.id === id)?.session_id;
      if (!sessionId) return;
      const turns = history.runs.filter((run) => run.session_id === sessionId).reverse();
      if (turns.length) {
        select.replaceChildren(...turns.map((turn, index) => new Option(`第 ${index + 1} 轮 · ${turn.question.slice(0, 36)}`, turn.id)));
        select.value = id;
      }
    } catch { /* Current turn remains available even if the history request fails. */ }
  });
  select.addEventListener("change", load);
  document.querySelector("#refresh-usage").addEventListener("click", load);
  dialog.querySelector(".close-dialog").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => request?.abort());
})();

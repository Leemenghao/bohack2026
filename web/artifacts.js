(() => {
  const dialog = document.querySelector("#artifact-dialog");
  const content = document.querySelector("#artifact-content");
  const read = document.querySelector("#artifact-reading");
  const raw = document.querySelector("#artifact-raw");
  const labels = {summary: "测量结果", configuration: "实验配置", resources: "资源使用", environment: "运行环境",
    requests: "请求记录", cases: "输入规模与结果", samples_ms: "采样耗时 ms", code: "候选代码", reason: "实验目的",
    content: "资料正文", sources: "检索结果", query: "检索词", status: "状态", task: "任务", experiment_id: "实验 ID",
    code_sha256: "代码指纹", reproduce_from_project_root: "复跑命令", execution: "执行环境", measurement: "测量设置",
    suite: "测试集", artifact: "记录位置", candidate: "候选文件", budget: "预算快照", correct: "数值检查",
    dtype: "数据类型", warmups: "预热轮数", repeats: "配对复测轮数", calls_per_sample: "每次采样调用数",
    cpu_seconds: "CPU 秒数", elapsed_seconds: "经过秒数", peak_process_rss_bytes: "最大单进程峰值内存 bytes"};
  let text = "", filename = "", request;
  const node = (tag, value, cls = "") => {
    const result = document.createElement(tag); if (value != null) result.textContent = value;
    result.className = cls; return result;
  };
  function describe(value, depth = 0) {
    if (value == null || typeof value !== "object") return node("span", value == null ? "未记录" : String(value));
    const box = node("div", null, "record-fields");
    const entries = Array.isArray(value) ? value.map((item, index) => [`第 ${index + 1} 项`, item]) : Object.entries(value);
    const add = ([key, item]) => {
      if (item && typeof item === "object") {
        const detail = node("details", null, "record-group");
        detail.append(node("summary", `${labels[key] || key}${Array.isArray(item) ? ` · ${item.length} 项` : ""}`));
        detail.addEventListener("toggle", () => {
          if (detail.open && detail.childElementCount === 1) detail.append(depth < 10 ? describe(item, depth + 1) : node("pre", JSON.stringify(item, null, 2)));
        });
        box.append(detail);
      } else if (["code", "content", "reproduce_from_project_root"].includes(key)) {
        const section = node("section", null, "record-text"); section.append(node("h3", labels[key]));
        if (key === "content") section.append(...renderMarkdown(String(item || "")));
        else section.append(node("pre", key === "reproduce_from_project_root" ? currentReplayCommand(item) : item));
        box.append(section);
      } else {
        const row = node("div", null, "record-field");
        row.append(node("span", labels[key] || key, "muted"), describe(item, depth + 1)); box.append(row);
      }
    };
    entries.slice(0, 30).forEach(add);
    if (entries.length > 30) {
      const more = node("button", `显示剩余 ${entries.length - 30} 项`, "view-button"); more.type = "button";
      more.addEventListener("click", () => { more.remove(); entries.slice(30).forEach(add); }); box.append(more);
    }
    return box;
  }
  function render(asRaw) {
    read.setAttribute("aria-pressed", String(!asRaw)); raw.setAttribute("aria-pressed", String(asRaw));
    if (asRaw || filename.endsWith(".py")) content.replaceChildren(node("pre", text));
    else if (filename.endsWith(".json")) {
      try { content.replaceChildren(describe(JSON.parse(text))); }
      catch { content.replaceChildren(node("pre", text)); }
    } else content.replaceChildren(...renderMarkdown(text));
  }
  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[href]");
    if (!link || link.hasAttribute("download")) return;
    const url = new URL(link.href, location.href);
    const match = url.pathname.match(/^\/api\/runs\/[a-f0-9]{12}\/((?:(?:experiment|search|source|memory)-[a-f0-9]{8}\.json)|(?:candidate-[a-f0-9]{8}\.py)|report\.md|resources\.json|summary\.json|session-summary\.json)$/);
    if (url.origin !== location.origin || !match) return;
    event.preventDefault(); request?.abort(); request = new AbortController();
    filename = match[1]; text = "";
    document.querySelector("#artifact-title").textContent = filename === "report.md" ? "报告原文" : filename.startsWith("source-") ? "资料记录" : "原始记录";
    document.querySelector("#artifact-filename").textContent = filename;
    const download = document.querySelector("#artifact-download"); download.href = url.href; download.download = filename;
    content.replaceChildren(node("p", "正在读取记录…", "muted"));
    read.disabled = raw.disabled = true;
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(url.pathname, {signal: request.signal});
      if (!response.ok) throw new Error("未找到这份记录，请返回会话刷新后重试。");
      text = await response.text(); render(false); read.disabled = raw.disabled = false;
    } catch (error) { if (error.name !== "AbortError") content.replaceChildren(node("p", error.message)); }
  });
  read.addEventListener("click", () => render(false)); raw.addEventListener("click", () => render(true));
  dialog.querySelector(".close-dialog").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => request?.abort());
})();

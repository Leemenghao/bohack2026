(() => {
  const dialog = document.querySelector("#preferences-dialog");
  const form = document.querySelector("#preferences-form");
  const field = (id) => document.getElementById(id);
  const message = field("preferences-message");
  let saved;

  function keyStatus(kind) {
    const section = saved?.[kind];
    let text = "新地址需要配置对应密钥；不会沿用其他地址的密钥。";
    if (section?.base_url === field(`${kind}-url`).value.replace(/\/$/, "")) {
      text = section.key_source === "keychain" ? "已保存在 macOS 钥匙串" : section.key_source.startsWith("env:")
        ? `可使用 ${section.key_source.slice(4)}；保存时转存钥匙串` : "尚未配置密钥";
    }
    field(`${kind}-key-status`).textContent = text;
  }

  function render(config) {
    saved = config;
    for (const kind of ["model", "search"]) {
      field(`${kind}-url`).value = config[kind].base_url;
      field(`${kind}-key`).value = "";
      keyStatus(kind);
    }
    field("model-name").value = config.model.name;
    field("review-name").value = config.model.review_name || "";
    for (const [suffix, key] of [["input", "input"], ["output", "output"], ["cache", "cache_read"]]) {
      field(`price-${suffix}`).value = config.model.prices?.[key] ?? "";
      field(`review-price-${suffix}`).value = config.model.review_prices?.[key] ?? "";
    }
  }

  document.querySelector("#open-preferences").addEventListener("click", async () => {
    dialog.showModal();
    message.textContent = "正在读取设置…";
    form.querySelector("button[type=submit]").disabled = true;
    try {
      const response = await fetch("/api/settings");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      render(data);
      message.textContent = "";
      form.querySelector("button[type=submit]").disabled = false;
    } catch (error) { message.textContent = error.message || "设置读取失败，请重试。"; }
  });
  dialog.querySelector(".close-dialog").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { field("model-key").value = ""; field("search-key").value = ""; });
  for (const kind of ["model", "search"]) field(`${kind}-url`).addEventListener("input", () => keyStatus(kind));
  dialog.querySelectorAll("[data-preset]").forEach((button) => button.addEventListener("click", () => {
    const official = button.dataset.preset === "deepseek";
    field("model-url").value = official ? "https://api.deepseek.com" : "https://aiping.cn/api/v1";
    field("model-name").value = official ? "deepseek-flash" : "DeepSeek-V4.1-Flash-1017";
    field("review-name").value = official ? "deepseek-v4-pro" : "DeepSeek-V4-Pro-0813";
    field("model-key").value = "";
    for (const suffix of ["input", "output", "cache"]) field(`price-${suffix}`).value = "";
    for (const suffix of ["input", "output", "cache"]) field(`review-price-${suffix}`).value = "";
    keyStatus("model");
    if (!official) field("model-key-status").textContent = "保存时可转存本机 .env 中的 AIPING_API_KEY；请按服务商填写模型 ID。";
  }));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = ["input", "output", "cache"].map((suffix) => field(`price-${suffix}`).value);
    const reviewValues = ["input", "output", "cache"].map((suffix) => field(`review-price-${suffix}`).value);
    if ([values, reviewValues].some((items) => items.some(Boolean) && items.some((v) => v === ""))) {
      message.textContent = "请完整填写三项单价，或全部留空。";
      return;
    }
    const payload = {};
    for (const kind of ["model", "search"]) payload[kind] = {
      base_url: field(`${kind}-url`).value.trim(), api_key: field(`${kind}-key`).value.trim(),
    };
    payload.model.name = field("model-name").value.trim();
    payload.model.review_name = field("review-name").value.trim();
    payload.model.review_prices = reviewValues.some(Boolean) ? { input: +reviewValues[0], output: +reviewValues[1], cache_read: +reviewValues[2] } : null;
    payload.model.prices = values.some(Boolean) ? { input: +values[0], output: +values[1], cache_read: +values[2] } : null;
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    message.textContent = "正在保存…";
    try {
      const response = await fetch("/api/settings", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      render(data);
      message.textContent = data.model.key_configured ? "已保存，下次研究将使用新连接。" : "连接已保存，请补充模型密钥后再开始研究。";
    } catch (error) { message.textContent = error.message || "保存失败，请重试。"; }
    finally {
      field("model-key").value = ""; field("search-key").value = "";
      payload.model.api_key = ""; payload.search.api_key = "";
      submit.disabled = false;
    }
  });
})();

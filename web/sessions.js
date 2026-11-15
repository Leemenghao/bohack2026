(() => {
  const dialog = document.querySelector("#session-summary-dialog");
  const content = document.querySelector("#session-summary-content");
  const message = document.querySelector("#session-summary-message");
  const share = document.querySelector("#session-share");
  const generate = document.querySelector("#generate-session-summary");
  let session, latest;
  document.querySelector("#view-session-summary").addEventListener("click", async () => {
    document.querySelector("#session-context").hidePopover();
    const turn = runsById.get(sessionTarget);
    if (!turn?.session_id) return;
    session = turn.session_id;
    message.textContent = "正在读取摘要…"; content.replaceChildren();
    share.disabled = generate.disabled = true;
    dialog.showModal();
    try {
      const result = await request(`/api/sessions/${session}/summary`);
      latest = result.latest_run_id;
      share.checked = !!result.shared;
      content.replaceChildren(...renderMarkdown(result.content || "这个会话还没有摘要。生成时会新增一轮模型调用，并记录用量。"));
      document.querySelector("#session-summary-meta").textContent = result.content
        ? `${result.model} · ${new Date(result.updated_at).toLocaleString()}${result.stale ? " · 尚未覆盖最新一轮" : ""}` : "仅当前会话可见，开启共享后其他会话才能查阅。";
      generate.textContent = result.content ? "更新摘要" : "生成摘要";
      share.disabled = false; generate.disabled = !latest;
      message.textContent = "";
    } catch (error) { message.textContent = error.message; }
  });
  share.addEventListener("change", async () => {
    share.disabled = true;
    try {
      await request(`/api/sessions/${session}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({shared:share.checked})});
      message.textContent = share.checked ? "已开启跨会话只读共享。" : "已关闭共享，后续读取将被拒绝。";
      await loadServerHistory();
    } catch (error) { share.checked = !share.checked; message.textContent = error.message; }
    finally { share.disabled = false; }
  });
  generate.addEventListener("click", async () => {
    generate.disabled = true;
    try {
      const run = await request("/api/runs", {method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({question:"更新会话摘要", parent_id:latest, mode:"summary", cloud_budget:1})});
      dialog.close();
      await loadServerHistory();
      await openRun(run.id);
    } catch (error) { message.textContent = error.message; generate.disabled = false; }
  });
  dialog.querySelector(".close-dialog").addEventListener("click", () => dialog.close());
})();

(async () => {
  const c = window.APP_CONFIG, L = c.LEVEL, authed = L >= 3;
  const $ = id => document.getElementById(id), log = $("log"), err = $("err");
  $("level").textContent = "Level " + L;
  let chatId = null, history = [];

  const add = (text, me) => { const d = document.createElement("div"); d.className = "msg" + (me ? " me" : ""); d.textContent = text; log.append(d); log.scrollTop = log.scrollHeight; return d; };
  async function api(path, method, body) {
    const h = {"Content-Type": "application/json"};
    if (authed) h.Authorization = "Bearer " + Auth.token();
    const r = await fetch(c.API_URL + path, {method, headers: h, body: body ? JSON.stringify(body) : undefined});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Request failed (" + r.status + ")");
    return data;
  }

  if (authed) {
    try { await Auth.handleRedirect(); } catch (e) { err.textContent = e.message; }
    const ok = !!Auth.token();
    $("login").hidden = ok; $("logout").hidden = !ok; $("form").hidden = !ok;
    $("login").onclick = Auth.login; $("logout").onclick = Auth.logout;
    if (!ok) { add("Sign in to start chatting.", false); return; }
  }
  if (L === 3 || L === 6) {
    $("side").hidden = false;
    const refresh = async () => { const {chats} = await api("/chats", "GET"); $("chats").innerHTML = "";
      chats.forEach(ch => { const li = document.createElement("li"); li.textContent = ch.title || ch.chatId;
        li.onclick = async () => { chatId = ch.chatId; log.innerHTML = ""; (await api("/chats/" + chatId, "GET")).messages.forEach(m => add(m.content, m.role === "user")); };
        $("chats").append(li); }); };
    $("new").onclick = () => { chatId = null; log.innerHTML = ""; };
    refresh().catch(e => err.textContent = e.message);
    window.refreshChats = refresh;
  }

  async function send(text) {
    if (L === 1) return (await api("/chat", "POST", {question: text})).answer;
    if (L === 2) { history.push({role: "user", content: text});
      const a = (await api("/chat", "POST", {messages: history.slice(-12)})).answer; history.push({role: "assistant", content: a}); return a; }
    if (L === 3 || L === 6) { const d = await api("/chat", "POST", {chatId, message: text}); const isNew = !chatId; chatId = d.chatId; if (isNew) window.refreshChats(); return d.answer; }
    if (L === 4) { const d = await api("/ask", "POST", {question: text});
      return d.answer + (d.sources.length ? "\n\nSources:\n" + d.sources.map(s => `[${s.n}] ${s.source}`).join("\n") : ""); }
    if (L === 5) { const d = await api("/agent", "POST", {message: text}); window._pending = d.pendingActions; return d.answer; }
    return (await api("/v1/chat", "POST", {message: text})).answer;                      // L7
  }

  $("form").onsubmit = async e => {
    e.preventDefault(); err.textContent = "";
    const text = $("box").value.trim(); if (!text) return;
    $("box").value = ""; add(text, true); $("send").disabled = true;
    const pend = add("...", false);
    try {
      pend.textContent = await send(text);
      if (L === 5 && window._pending && window._pending.length) window._pending.forEach(p => {
        const b = document.createElement("button"); b.className = "pending"; b.textContent = `Approve: ${p.tool} (${p.args.subject})`;
        b.onclick = async () => { b.disabled = true; try { const r = await api("/agent/approve", "POST", {actionId: p.actionId}); add("Ticket opened: " + r.ticketId, false); } catch (x) { err.textContent = x.message; } };
        pend.append(document.createElement("br"), b); });
    } catch (x) { pend.remove(); err.textContent = x.message; }
    $("send").disabled = false;
  };
})();

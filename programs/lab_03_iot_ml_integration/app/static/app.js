"use strict";

const state = {
  config: null,
  account: null,
  role: "guest",
  devices: [],
  samples: [],
  lastPrediction: null,
  provider: null,
};

const $ = (id) => document.getElementById(id);
const short = (value, left = 10, right = 8) => value ? `${value.slice(0, left)}…${value.slice(-right)}` : "-";

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function toast(message, kind = "") {
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.textContent = message;
  $("toast-container").append(item);
  window.setTimeout(() => item.remove(), 4800);
}

function setNotice(id, message, kind = "") {
  const element = $(id);
  element.className = `notice ${kind}`;
  element.textContent = message;
  element.classList.remove("hidden");
}

function setNetworkPill(text, kind) {
  const pill = $("network-pill");
  pill.textContent = text;
  pill.className = `pill ${kind}`;
}

function currentRole() {
  if (!state.account || !state.config) return "guest";
  const address = state.account.toLowerCase();
  const roles = state.config.roles;
  if (address === roles.admin.toLowerCase()) return "admin";
  if (address === roles.owner.toLowerCase() || state.devices.some((d) => d.owner_address.toLowerCase() === address)) return "owner";
  if (address === roles.auditor.toLowerCase()) return "auditor";
  return "viewer";
}

function roleLabel(role) {
  return ({ admin: "АДМІНІСТРАТОР", owner: "ВЛАСНИК", auditor: "АУДИТОР", viewer: "ЛИШЕ ЧИТАННЯ", guest: "НЕ ПІД'ЄДНАНО" })[role] || "КОРИСТУВАЧ";
}

function updateRoleUI() {
  state.role = currentRole();
  $("wallet-info").classList.toggle("hidden", !state.account);
  $("connect-wallet").classList.toggle("hidden", Boolean(state.account));
  $("wallet-address").textContent = state.account ? short(state.account, 7, 5) : "";
  $("role-pill").textContent = roleLabel(state.role);
  $("role-pill").className = `pill ${state.role === "admin" ? "blue" : state.role === "owner" ? "success" : ""}`;
  const allowed = ["admin", "owner"].includes(state.role);
  document.querySelectorAll(".owner-only").forEach((item) => item.classList.toggle("hidden", !allowed));
  document.querySelectorAll("[data-view='devices'], [data-view='decision']").forEach((item) => {
    item.classList.toggle("hidden", !allowed);
  });
  if (!allowed && ["devices", "decision"].includes(document.querySelector(".view.active")?.id?.replace("view-", ""))) {
    showView("audit");
  }
}

function showView(name) {
  if (["devices", "decision"].includes(name) && !["admin", "owner"].includes(state.role)) {
    toast("Для цієї сторінки потрібен гаманець власника або адміністратора.", "error");
    return;
  }
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  if (name === "audit") refreshAudit();
  if (name === "devices") refreshDevices();
  if (name === "integrity") refreshIntegrityOptions();
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => showView(item.dataset.view)));
  document.querySelectorAll("[data-open]").forEach((item) => item.addEventListener("click", () => showView(item.dataset.open)));
}

async function switchToRequiredNetwork() {
  if (!window.ethereum) throw new Error("Не знайдено браузерний гаманець EIP-1193, наприклад MetaMask.");
  const chainId = `0x${Number(state.config.expected_chain_id).toString(16)}`;
  const current = await window.ethereum.request({ method: "eth_chainId" });
  if (current.toLowerCase() === chainId.toLowerCase()) return;
  try {
    await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] });
  } catch (error) {
    if (error.code !== 4902) throw error;
    await window.ethereum.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId,
        chainName: "Hardhat Local IoT IDS",
        nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
        rpcUrls: ["http://127.0.0.1:8545"],
      }],
    });
  }
}

async function connectWallet() {
  if (!window.ethereum) {
    toast("Установіть або ввімкніть MetaMask і додайте Hardhat Local (31337).", "error");
    return;
  }
  try {
    state.provider = window.ethereum;
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    if (!accounts.length) throw new Error("Гаманець не повернув адресу.");
    state.account = accounts[0];
    await switchToRequiredNetwork();
    const chain = await window.ethereum.request({ method: "eth_chainId" });
    setNetworkPill(`CONNECTED · ${Number.parseInt(chain, 16)}`, "success");
    await refreshDevices();
    updateRoleUI();
    toast(`Гаманець під'єднано: ${short(state.account)}.`, "success");
    await refreshAll();
  } catch (error) {
    state.account = null;
    updateRoleUI();
    toast(error.message || "Не вдалося під'єднати гаманець.", "error");
  }
}

async function walletTransaction(action, payload) {
  if (!state.account || !window.ethereum) throw new Error("Спочатку під'єднайте гаманець.");
  if (state.role === "auditor" || state.role === "viewer" || state.role === "guest") {
    throw new Error("Поточний гаманець не має ролі власника або адміністратора.");
  }
  setNetworkPill("ОЧІКУЄ ПІДПИСУ", "warn");
  const prepared = await api("/transactions/prepare", {
    method: "POST",
    body: JSON.stringify({ action, sender: state.account, payload }),
  });
  const txHash = await window.ethereum.request({
    method: "eth_sendTransaction",
    params: [{ from: state.account, to: prepared.to, data: prepared.data }],
  });
  setNetworkPill("ТРАНЗАКЦІЯ В МЕРЕЖІ", "warn");
  await waitForReceipt(txHash);
  const confirmed = await api("/transactions/confirm", {
    method: "POST",
    body: JSON.stringify({ action, tx_hash: txHash, extra: prepared.extra }),
  });
  setNetworkPill(`CONNECTED · ${state.config.expected_chain_id}`, "success");
  return confirmed;
}

async function waitForReceipt(txHash, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const receipt = await window.ethereum.request({ method: "eth_getTransactionReceipt", params: [txHash] });
    if (receipt) {
      if (Number.parseInt(receipt.status, 16) !== 1) throw new Error("Транзакція відхилена смартконтрактом або не має прав.");
      return receipt;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 600));
  }
  throw new Error("Транзакція ще не підтверджена. Перевірте журнал блокчейну.");
}

async function renderDevices() {
  const body = $("device-table");
  if (!state.devices.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty-cell">Пристроїв ще не зареєстровано.</td></tr>';
  } else {
    body.innerHTML = state.devices.map((device) => `
      <tr>
        <td class="device-name-cell"><strong>${escapeHtml(device.local_name)}</strong><small>${escapeHtml(device.owner_address)}</small></td>
        <td class="hash-cell">${escapeHtml(device.device_id)}</td>
        <td class="hash-cell">${escapeHtml(short(device.owner_address, 8, 6))}</td>
        <td><span class="pill ${device.state === "Quarantined" ? "error" : "success"}">${escapeHtml(device.state)}</span></td>
        <td>${device.state === "Quarantined" && state.account?.toLowerCase() === device.owner_address.toLowerCase()
          ? `<button class="table-action" data-release="${escapeHtml(device.device_id)}">Зняти карантин</button>` : "-"}</td>
      </tr>`).join("");
    body.querySelectorAll("[data-release]").forEach((button) => button.addEventListener("click", async () => {
      try {
        const result = await walletTransaction("release_quarantine", { device_id: button.dataset.release });
        toast(`Карантин знято. Tx ${short(result.tx_hash)}.`, "success");
        await refreshAll();
      } catch (error) { toast(error.message, "error"); }
    }));
  }
  const selectors = ["grant-device", "gateway-device", "inference-device", "integrity-flow"];
  for (const id of selectors) {
    const select = $(id);
    if (!select) continue;
    const previous = select.value;
    if (id === "integrity-flow") {
      const preds = await api("/predictions?limit=100").catch(() => []);
      select.innerHTML = '<option value="">Оберіть рішення</option>' + preds.map((pred) => `<option value="${escapeHtml(pred.flow_id)}">${escapeHtml(short(pred.flow_id, 12, 6))} · ${escapeHtml(pred.status)}</option>`).join("");
    } else {
      select.innerHTML = state.devices.map((device) => `<option value="${escapeHtml(device.device_id)}">${escapeHtml(device.local_name)} · ${escapeHtml(device.state)}</option>`).join("") || '<option value="">Спочатку зареєструйте пристрій</option>';
    }
    if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
  }
  if (state.config) $("actor-address").value ||= state.config.roles.actor;
  if (state.config) $("gateway-actor").value ||= state.config.roles.actor;
  $("device-count").textContent = String(state.devices.length);
}

async function refreshDevices() {
  try {
    state.devices = await api("/devices");
    updateRoleUI();
    await renderDevices();
  } catch (error) {
    $("device-table").innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function loadSamples() {
  state.samples = await api("/demo-flows");
  const select = $("demo-sample");
  select.innerHTML = state.samples.map((sample) => `<option value="${escapeHtml(sample.sample_id)}">${escapeHtml(sample.display_name)}</option>`).join("");
  select.addEventListener("change", renderFeaturePreview);
  renderFeaturePreview();
}

function selectedSample() {
  return state.samples.find((sample) => sample.sample_id === $("demo-sample").value) || null;
}

function renderFeaturePreview() {
  const sample = selectedSample();
  if (!sample) { $("feature-preview").textContent = "Немає зразків у відкладеній вибірці."; return; }
  const features = Object.entries(sample.features).slice(0, 8);
  $("feature-preview").innerHTML = `<div class="preview-title">16 ознак · мітки та IP вилучені</div><div class="feature-grid">${features.map(([name, value]) => `<div><span>${escapeHtml(name)}</span><strong>${value === null ? "-" : escapeHtml(String(value))}</strong></div>`).join("")}<div class="feature-more">+ ще ${Object.keys(sample.features).length - features.length} ознак</div></div>`;
}

function renderDecision(result) {
  state.lastPrediction = result;
  const isAttack = result.is_attack;
  const explanations = result.explanations || [];
  const tx = result.transaction_url
    ? `<a class="tx-link" href="${escapeHtml(result.transaction_url)}" target="_blank" rel="noreferrer">${escapeHtml(short(result.tx_hash, 16, 10))} ↗</a>`
    : `<span class="mono">${escapeHtml(short(result.tx_hash, 16, 10))}</span>`;
  $("decision-result").innerHTML = `
    <div class="decision-banner ${isAttack ? "attack" : "normal"}"><div class="decision-symbol">${isAttack ? "!" : "✓"}</div><div><strong>${escapeHtml(result.result)}</strong><small>${isAttack ? "Порог карантину досягнуто" : "Інциденту не виявлено"}</small></div><span class="pill ${isAttack ? "error" : "success"}">${isAttack ? "ATTACK" : "NORMAL"}</span></div>
    <div class="confidence-row"><span>Імовірність атаки</span><strong>${(result.confidence * 100).toFixed(2)} %</strong></div>
    <div class="progress"><span style="width:${Math.max(1, Math.min(100, result.confidence * 100))}%"></span></div>
    <div class="result-details">
      <div class="result-detail"><span>Модель / версія</span><span>${escapeHtml(result.model_name)} · ${result.model_version}</span></div>
      <div class="result-detail"><span>Статус транзакції</span><span><span class="pill success">${escapeHtml(result.status)}</span></span></div>
      <div class="result-detail"><span>Стан пристрою в EVM</span><span>${escapeHtml(result.device_status || "-")}</span></div>
      <div class="result-detail"><span>Device ID</span><span class="mono">${escapeHtml(short(result.device_id, 14, 8))}</span></div>
      <div class="result-detail"><span>Input SHA-256</span><span class="mono">${escapeHtml(short(result.input_hash, 14, 8))}</span></div>
      <div class="result-detail"><span>Transaction hash</span><span>${tx}</span></div>
      <div class="result-detail"><span>Блок</span><span>${result.block_number ?? "-"}</span></div>
      <div class="result-detail"><span>Сигнатурне правило</span><span>${result.signature_rule_attack ? "Атака" : "Нормально"}</span></div>
    </div>
    <div class="section-subheading">SHAP: фактори цього рішення</div>
    <ul class="explanation-list">${explanations.map((item) => `<li><strong>${escapeHtml(item.feature)}</strong><span class="explanation-value ${item.contribution > 0 ? "positive" : "negative"}">${item.contribution > 0 ? "+" : ""}${Number(item.contribution).toFixed(4)}</span><small>${escapeHtml(item.direction)} · значення ${item.value === null ? "пропущене" : escapeHtml(String(item.value))}</small></li>`).join("")}</ul>
  `;
}

async function runInference(event) {
  event.preventDefault();
  if (!state.account) { toast("Під'єднайте гаманець перед аналізом потоку.", "error"); return; }
  const sample = selectedSample();
  const deviceId = $("inference-device").value;
  if (!sample || !deviceId) { toast("Оберіть зареєстрований пристрій і тестовий потік.", "error"); return; }
  const submitButton = $("inference-form").querySelector("button[type='submit']");
  if (submitButton.disabled) return;
  submitButton.disabled = true;
  $("inference-status").className = "notice warn";
  $("inference-status").textContent = "Оракул обчислює прогноз і надсилає транзакцію...";
  $("inference-status").classList.remove("hidden");
  try {
    const result = await api("/inference", {
      method: "POST",
      body: JSON.stringify({
        flow_id: crypto.randomUUID(),
        device_id: deviceId,
        features: sample.features,
        signature_context: sample.signature_context,
      }),
    });
    setNotice("inference-status", `Рішення записане в блок ${result.block_number}. Transaction: ${result.tx_hash}`, "success");
    renderDecision(result);
    await refreshAll();
  } catch (error) {
    setNotice("inference-status", error.message, "error");
    toast(error.message, "error");
  } finally {
    submitButton.disabled = false;
  }
}

function eventSummary(event) {
  const args = event.args || {};
  switch (event.event_name) {
    case "DecisionRecorded":
      return `${args.attack ? "attack" : "normal"} · ${(Number(args.confidence || 0) / 100).toFixed(2)} % · model v${args.modelVersion}`;
    case "DeviceQuarantined":
      return `Карантин · incident #${args.incidentId}`;
    case "QuarantineReleased":
      return `Знято власником ${short(args.owner, 8, 5)}`;
    case "DeviceRegistered":
      return `Власник ${short(args.owner, 8, 5)} · metadata hash ${short(args.metadataHash, 9, 5)}`;
    case "OwnerChanged":
      return `${short(args.oldOwner, 8, 5)} → ${short(args.newOwner, 8, 5)}`;
    case "AccessGranted":
      return `Оператор ${short(args.actor, 8, 5)} · expiry ${new Date(Number(args.validUntil) * 1000).toLocaleString("uk-UA")}`;
    case "AccessRevoked":
      return `Оператор ${short(args.actor, 8, 5)}`;
    case "ModelRegistered":
      return `Модель v${args.version} · hash ${short(args.modelHash, 10, 6)}`;
    case "OracleChanged":
      return `${short(args.oldOracle, 8, 5)} → ${short(args.newOracle, 8, 5)}`;
    case "Paused": return "Запис нових рішень призупинено";
    case "Unpaused": return "Запис рішень відновлено";
    default: return "Контрактна подія";
  }
}

async function refreshAudit() {
  try {
    const result = await api("/audit?limit=100");
    const events = result.events || [];
    $("audit-count").textContent = `${events.length} подій · mirror ${result.mirror_count ?? 0}`;
    $("decision-count").textContent = String(events.filter((item) => item.event_name === "DecisionRecorded").length);
    $("recent-decisions").innerHTML = events.filter((item) => item.event_name === "DecisionRecorded").slice(0, 4).map((item) => {
      const args = item.args || {};
      const attack = Boolean(args.attack);
      return `<div class="decision-row"><strong>${attack ? "Атака" : "Нормальний потік"} · v${escapeHtml(String(args.modelVersion ?? "-"))}</strong><span class="result-tag ${attack ? "attack" : "normal"}">${attack ? "ATTACK" : "NORMAL"}</span><small>Block ${item.block_number} · ${escapeHtml(short(item.device_id, 12, 7))}</small><span class="mono">${escapeHtml(short(item.tx_hash, 14, 9))}</span></div>`;
    }).join("") || '<div class="empty-state">Ще немає рішень у блокчейні.</div>';
    $("audit-table").innerHTML = events.map((item) => {
      const args = item.args || {};
      const device = item.device_id ? short(item.device_id, 12, 7) : (args.version ? `v${args.version}` : "-");
      const detail = eventSummary(item);
      const url = state.config?.explorer_base_url ? `${state.config.explorer_base_url}/tx/${item.tx_hash}` : null;
      const tx = url ? `<a class="tx-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(short(item.tx_hash, 15, 9))} ↗</a>` : `<span class="mono">${escapeHtml(short(item.tx_hash, 15, 9))}</span>`;
      return `<tr><td>${item.block_number}</td><td class="event-name">${escapeHtml(item.event_name)}</td><td class="mono">${escapeHtml(device)}</td><td>${escapeHtml(detail)}</td><td>${tx}</td></tr>`;
    }).join("") || '<tr><td colspan="5" class="empty-cell">Подій поки немає.</td></tr>';
    $("audit-source").textContent = `Джерело: contract event logs · блок ${state.config?.start_block ?? "-"} → latest`;
  } catch (error) {
    $("audit-table").innerHTML = `<tr><td colspan="5" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function refreshIntegrityOptions() {
  const predictions = await api("/predictions?limit=100").catch(() => []);
  const select = $("integrity-flow");
  const previous = select.value;
  select.innerHTML = predictions.map((prediction) => `<option value="${escapeHtml(prediction.flow_id)}">${escapeHtml(short(prediction.flow_id, 14, 6))} · ${prediction.status}</option>`).join("") || '<option value="">Ще немає оброблених потоків</option>';
  if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
}

async function loadIntegrityPayload() {
  const flowId = $("integrity-flow").value;
  if (!flowId) return;
  const stored = await api(`/integrity/${encodeURIComponent(flowId)}`);
  $("integrity-json").value = JSON.stringify(stored.payload, null, 2);
  $("integrity-result").className = "integrity-result";
  $("integrity-result").innerHTML = `Очікуваний хеш з транзакції:<code>${escapeHtml(stored.expected_hash)}</code>`;
}

async function checkIntegrity() {
  const flowId = $("integrity-flow").value;
  if (!flowId) { toast("Спочатку оберіть оброблений потік.", "error"); return; }
  try {
    const payload = JSON.parse($("integrity-json").value);
    const result = await api(`/integrity/${encodeURIComponent(flowId)}/check`, {
      method: "POST", body: JSON.stringify({ payload }),
    });
    const element = $("integrity-result");
    element.className = `integrity-result ${result.valid ? "valid" : "invalid"}`;
    element.innerHTML = `<strong>${result.valid ? "Цілісність підтверджено" : "Виявлено зміну даних"}</strong>Очікуваний хеш:<code>${escapeHtml(result.expected_hash)}</code>Обчислений хеш:<code>${escapeHtml(result.calculated_hash)}</code>`;
  } catch (error) {
    toast(error.message.includes("JSON") ? "Перевірте формат JSON у полі." : error.message, "error");
  }
}

async function registerDevice(event) {
  event.preventDefault();
  try {
    setNotice("device-tx-status", "Підтвердьте транзакцію у гаманці...", "warn");
    const result = await walletTransaction("register_device", { local_name: $("device-name").value });
    setNotice("device-tx-status", `Пристрій ${result.device_id} зареєстровано. Tx ${result.tx_hash}`, "success");
    toast("Пристрій зареєстровано в DeviceRegistry.", "success");
    await refreshAll();
  } catch (error) { setNotice("device-tx-status", error.message, "error"); }
}

async function grantAccess(event) {
  event.preventDefault();
  const validUntil = Math.floor(Date.now() / 1000) + Number($("expiry-hours").value) * 3600;
  try {
    setNotice("access-tx-status", "Підтвердьте транзакцію у гаманці...", "warn");
    const result = await walletTransaction("grant_access", {
      device_id: $("grant-device").value,
      actor: $("actor-address").value.trim(),
      valid_until: validUntil,
    });
    setNotice("access-tx-status", `Дозвіл видано до ${new Date(validUntil * 1000).toLocaleString("uk-UA")}. Tx ${result.tx_hash}`, "success");
    await refreshAudit();
  } catch (error) { setNotice("access-tx-status", error.message, "error"); }
}

async function checkGateway(event) {
  event.preventDefault();
  try {
    const result = await api("/gateway/check", {
      method: "POST",
      body: JSON.stringify({ device_id: $("gateway-device").value, actor: $("gateway-actor").value.trim() }),
    });
    setNotice("gateway-result", `${result.allowed ? "ДОЗВОЛЕНО" : "ВІДХИЛЕНО"}: ${result.reason} · стан ${result.device_status}`, result.allowed ? "success" : "error");
  } catch (error) { setNotice("gateway-result", error.message, "error"); }
}

function renderModelSummary(card, comparison) {
  const metrics = card.held_out_test_metrics || {};
  $("model-version").textContent = `v${card.model_version}`;
  $("model-hash-short").textContent = short(card.artifact_sha256, 12, 8);
  $("registered-model-pill").textContent = `MODEL ${card.model_version}`;
  $("decision-model-badge").textContent = card.model_name.toUpperCase();
  $("model-summary").innerHTML = `
    <div class="model-kpi"><span>F1 attack</span><strong>${Number(metrics.f1_attack).toFixed(4)}</strong></div>
    <div class="model-kpi"><span>Precision</span><strong>${Number(metrics.precision_attack).toFixed(4)}</strong></div>
    <div class="model-kpi"><span>Recall</span><strong>${Number(metrics.recall_attack).toFixed(4)}</strong></div>
    <div class="model-kpi"><span>FPR</span><strong>${Number(metrics.false_positive_rate).toFixed(4)}</strong></div>
    <div class="model-kpi"><span>PR-AUC</span><strong>${Number(metrics.pr_auc).toFixed(4)}</strong></div>
    <div class="model-kpi"><span>Group CV F1 ± SD</span><strong>${Number(card.group_cv_f1_mean).toFixed(3)} ± ${Number(card.group_cv_f1_sd).toFixed(3)}</strong></div>
    <div class="model-meta">Артефакт SHA-256: <span class="mono">${escapeHtml(card.artifact_sha256)}</span> · Random Forest налаштовано на validation groups, тест відділено за src_ip. Порівняння методів: ${comparison.map((item) => `${escapeHtml(item.model)} F1=${Number(item.f1_attack).toFixed(3)}`).join(" · ")}</div>`;
}

async function refreshMonitor() {
  try {
    const monitor = await api("/oracle/status");
    $("oracle-state").textContent = monitor.status === "error" ? "Помилка" : "Готовий";
    $("oracle-last-action").textContent = monitor.last_success ? `Остання транзакція ${new Date(monitor.last_success).toLocaleTimeString("uk-UA")}` : "Очікує потік";
    $("monitor-pill").textContent = monitor.status.toUpperCase();
    $("monitor-pill").className = `pill ${monitor.status === "error" ? "error" : "success"}`;
    $("monitor-details").innerHTML = `
      <div class="monitor-stat"><span>Стан сервісу</span><strong>${escapeHtml(monitor.status)}</strong></div>
      <div class="monitor-stat"><span>Оброблено прогнозів</span><strong>${Number(monitor.processed || 0)}</strong></div>
      <div class="monitor-stat"><span>Остання помилка</span><strong>${escapeHtml(monitor.last_error || "Немає")}</strong></div>`;
    $("oracle-health").textContent = monitor.status === "error" ? "Потрібна перевірка" : `Оброблено рішень: ${monitor.processed || 0}`;
  } catch (error) { $("oracle-health").textContent = "API недоступний"; }
}

async function refreshAll() {
  try {
    const health = await api("/health");
    $("api-status").textContent = health.status === "ok" ? "API та EVM доступні" : "API доступний, EVM недоступна";
    setNetworkPill(`CONNECTED · ${health.chain.chain_id}`, health.chain.chain_id === health.chain.expected_chain_id ? "success" : "error");
  } catch (error) {
    $("api-status").textContent = "API недоступний";
    setNetworkPill("API OFFLINE", "error");
  }
  await refreshDevices();
  await refreshAudit();
  await refreshMonitor();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function init() {
  bindNavigation();
  $("connect-wallet").addEventListener("click", connectWallet);
  $("register-device-form").addEventListener("submit", registerDevice);
  $("grant-access-form").addEventListener("submit", grantAccess);
  $("gateway-check-form").addEventListener("submit", checkGateway);
  $("inference-form").addEventListener("submit", runInference);
  $("refresh-devices").addEventListener("click", refreshDevices);
  $("refresh-audit").addEventListener("click", refreshAudit);
  $("refresh-all").addEventListener("click", refreshAll);
  $("load-integrity-payload").addEventListener("click", () => loadIntegrityPayload().catch((error) => toast(error.message, "error")));
  $("check-integrity").addEventListener("click", checkIntegrity);
  $("check-last-gateway").addEventListener("click", async () => {
    if (!state.lastPrediction) { toast("Спочатку виконайте класифікацію.", "warn"); return; }
    $("gateway-device").value = state.lastPrediction.device_id;
    $("gateway-actor").value = state.config.roles.actor;
    try {
      const result = await api("/gateway/check", {
        method: "POST", body: JSON.stringify({ device_id: state.lastPrediction.device_id, actor: state.config.roles.actor }),
      });
      setNotice("last-gateway-result", `${result.allowed ? "ДОЗВОЛЕНО" : "ВІДХИЛЕНО"}: ${result.reason} · стан ${result.device_status}`, result.allowed ? "success" : "error");
    } catch (error) { setNotice("last-gateway-result", error.message, "error"); }
  });
  $("demo-sample").addEventListener("change", renderFeaturePreview);

  try {
    state.config = await api("/config");
    const [models] = await Promise.all([api("/models"), loadSamples()]);
    renderModelSummary(models.primary, models.comparison);
    await refreshAll();
  } catch (error) {
    toast(`Початкова ініціалізація не вдалася: ${error.message}`, "error");
  }
  if (window.ethereum) {
    const accounts = await window.ethereum.request({ method: "eth_accounts" }).catch(() => []);
    if (accounts.length) {
      state.account = accounts[0];
      state.provider = window.ethereum;
      updateRoleUI();
    }
    window.ethereum.on?.("accountsChanged", async (accounts) => {
      state.account = accounts[0] || null;
      updateRoleUI();
      await refreshDevices();
    });
    window.ethereum.on?.("chainChanged", () => window.location.reload());
  }
  window.setInterval(refreshAll, 5000);
}

document.addEventListener("DOMContentLoaded", init);

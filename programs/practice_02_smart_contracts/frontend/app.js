const $ = (selector) => document.querySelector(selector);
const STATUS_NAMES = ["Активна", "Успішна", "Неуспішна"];
const ERRORS = {
  NotAuthor: "Створювати кампанії можуть лише зареєстровані автори.",
  ZeroGoal: "Мета кампанії має бути більшою за нуль.",
  DeadlineNotFuture: "Дедлайн має бути в майбутньому.",
  CampaignNotFound: "Кампанію не знайдено.",
  CampaignNotActive: "Кампанія вже не приймає внески.",
  CampaignEnded: "Дедлайн кампанії минув.",
  DeadlineNotReached: "Дедлайн ще не настав.",
  ContributionIsZero: "Внесок має бути більшим за нуль.",
  GoalNotReached: "Мета ще не досягнута або кошти вже недоступні.",
  GoalReached: "Повернення можливе лише після невдалої кампанії.",
  NotCreator: "Вивести кошти може лише автор кампанії.",
  AlreadyWithdrawn: "Кошти цієї кампанії вже виведені.",
  NothingToRefund: "Для цього гаманця немає внеску до повернення.",
  EnforcedPause: "Дії тимчасово зупинені адміністратором.",
  AccessControlUnauthorizedAccount: "Ваш гаманець не має потрібної ролі."
};

let provider, signer, hub, userAddress, refreshTimer;
const status = (message, kind = "") => { $("#status").textContent = message; $("#status").dataset.kind = kind; };
function friendlyError(error) {
  const data = error?.data || error?.info?.error?.data;
  if (data && hub) {
    try { const parsed = hub.interface.parseError(data); if (parsed && ERRORS[parsed.name]) return ERRORS[parsed.name]; } catch (_) {}
  }
  if (error?.code === 4001) return "Транзакцію відхилено у MetaMask.";
  if (error?.message?.includes("insufficient funds")) return "На рахунку недостатньо ETH для газу.";
  return "Транзакцію відхилено. Перевірте мережу, баланс і стан кампанії.";
}
async function transaction(promise, label) {
  try {
    status(`${label}: очікує підтвердження…`, "pending");
    const tx = await promise;
    status(`${label}: транзакція надіслана (${tx.hash.slice(0, 12)}…). Очікуємо блок…`, "pending");
    await tx.wait();
    status(`${label}: підтверджено.`, "success");
    await refreshCampaigns();
    return true;
  } catch (error) { status(friendlyError(error), "error"); return false; }
}
async function connect() {
  if (!window.ethereum) { status("MetaMask не знайдено. Встановіть розширення гаманця.", "error"); return; }
  try {
    await window.ethereum.request({ method: "eth_requestAccounts" });
    provider = new ethers.BrowserProvider(window.ethereum);
    signer = await provider.getSigner();
    userAddress = await signer.getAddress();
    const chain = await provider.getNetwork();
    const expected = BigInt(window.CROWD_CONFIG.chainId);
    if (chain.chainId !== expected) {
      $("#network").textContent = `Неправильна мережа: ${chain.name} (${chain.chainId}). Очікується chain ID ${expected}.`;
      status("Перемкніть MetaMask у мережу, для якої розгорнуто контракти.", "error");
      return;
    }
    const abi = await fetch("public/CrowdfundingHub.json").then((r) => r.json());
    hub = new ethers.Contract(window.CROWD_CONFIG.hub, abi, signer);
    $("#account").textContent = `${userAddress.slice(0, 8)}…${userAddress.slice(-6)}`;
    $("#network").textContent = `Підключено до ${window.CROWD_CONFIG.network}, chain ID ${chain.chainId}.`;
    $("#connect").textContent = "Гаманець підключено";
    $("#createPanel").classList.remove("hidden");
    subscribeEvents();
    await refreshCampaigns();
    await refreshHistory();
  } catch (error) { status(friendlyError(error), "error"); }
}
function renderCampaign(campaign, id) {
  const goal = BigInt(campaign.goal), raised = BigInt(campaign.totalRaised);
  const percent = goal === 0n ? 0 : Math.min(100, Number(raised * 100n / goal));
  const card = document.createElement("article"); card.className = "card";
  const title = document.createElement("h3"); title.textContent = `Кампанія №${id}`;
  const info = document.createElement("p"); info.className = "muted";
  info.textContent = `${STATUS_NAMES[Number(campaign.status)]} · автор ${campaign.creator.slice(0, 8)}…`;
  const goalLine = document.createElement("p"); goalLine.textContent = `${ethers.formatEther(raised)} / ${ethers.formatEther(goal)} ETH`;
  const meter = document.createElement("div"); meter.className = "meter";
  const fill = document.createElement("span"); fill.style.width = `${percent}%`; meter.append(fill);
  const end = document.createElement("p"); end.className = "muted"; end.textContent = `Дедлайн: ${new Date(Number(campaign.deadline) * 1000).toLocaleString("uk-UA")}`;
  card.append(title, info, goalLine, meter, end);
  if (Number(campaign.status) === 0) {
    if (Number(campaign.deadline) <= Math.floor(Date.now() / 1000)) {
      const finalize = document.createElement("button"); finalize.className = "secondary"; finalize.textContent = "Завершити кампанію";
      finalize.onclick = () => transaction(hub.finalize(id), "Фіналізація кампанії"); card.append(finalize);
    } else {
      const form = document.createElement("form");
      const amount = document.createElement("input"); amount.type = "number"; amount.min = "0.000000000000000001"; amount.step = "any"; amount.placeholder = "ETH"; amount.required = true;
      const submit = document.createElement("button"); submit.textContent = "Внести";
      form.append(amount, submit); form.addEventListener("submit", async (event) => { event.preventDefault(); await transaction(hub.contribute(id, { value: ethers.parseEther(amount.value) }), "Внесок"); }); card.append(form);
    }
  }
  if (Number(campaign.status) === 2) {
    const refund = document.createElement("button"); refund.className = "secondary"; refund.textContent = "Повернути внесок";
    refund.onclick = () => transaction(hub.refund(id), "Повернення"); card.append(refund);
  }
  if (Number(campaign.status) === 1 && campaign.creator.toLowerCase() === userAddress.toLowerCase() && !campaign.proceedsWithdrawn) {
    const withdraw = document.createElement("button"); withdraw.textContent = "Забрати кошти";
    withdraw.onclick = () => transaction(hub.withdrawProceeds(id), "Виплата автору"); card.append(withdraw);
  }
  return card;
}
async function refreshCampaigns() {
  if (!hub) return;
  try {
    const count = Number(await hub.campaignCount()); const target = $("#campaigns"); target.replaceChildren();
    const page = await hub.getCampaigns(0, Math.min(count || 1, 100));
    page.forEach((campaign, index) => target.append(renderCampaign(campaign, index + 1)));
    if (!page.length) target.textContent = "Кампаній поки немає.";
  } catch (error) { status(friendlyError(error), "error"); }
}
function subscribeEvents() {
  for (const name of ["CampaignCreated", "ContributionReceived", "CampaignSucceeded", "CampaignFailed", "ProceedsWithdrawn", "ContributionRefunded"]) {
    hub.on(name, () => { status(`Отримано подію ${name}; оновлюємо стан.`); refreshCampaigns(); refreshHistory(); });
  }
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshCampaigns, 15000);
}
async function refreshHistory() {
  const list = $("#history");
  try {
    const historyFile = window.CROWD_CONFIG.network === "localhost" ? "history.json" : `history-${window.CROWD_CONFIG.network}.json`;
    const entries = await fetch(`public/${historyFile}`, { cache: "no-store" }).then((r) => r.ok ? r.json() : []);
    list.replaceChildren();
    entries.slice(-30).reverse().forEach((entry) => {
      const item = document.createElement("li"); item.textContent = `Блок ${entry.blockNumber}: ${entry.event} · `;
      const link = document.createElement("a"); link.href = window.CROWD_CONFIG.network === "sepolia" ? `https://sepolia.etherscan.io/tx/${entry.transactionHash}` : "#"; link.textContent = entry.transactionHash.slice(0, 14) + "…"; link.rel = "noreferrer";
      item.append(link); list.append(item);
    });
    if (!entries.length) list.textContent = "Історію буде показано після запуску індексатора.";
  } catch (_) { list.textContent = "Історія подій поки не індексована."; }
}

$("#connect").addEventListener("click", connect);
$("#refresh").addEventListener("click", refreshCampaigns);
$("#historyRefresh").addEventListener("click", refreshHistory);
$("#createForm").addEventListener("submit", async (event) => {
  event.preventDefault(); if (!hub) return status("Спочатку підключіть MetaMask.", "error");
  const form = new FormData(event.currentTarget);
  const hours = Number(form.get("hours"));
  const deadline = Math.floor(Date.now() / 1000) + hours * 3600;
  await transaction(hub.createCampaign(ethers.parseEther(form.get("goal")), deadline, form.get("uri")), "Створення кампанії");
});
if (window.ethereum) window.ethereum.on("accountsChanged", () => window.location.reload());

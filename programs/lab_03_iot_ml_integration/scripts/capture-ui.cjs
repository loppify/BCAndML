const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const CODE_ROOT = path.resolve(__dirname, "..");
const IMAGE_DIR = path.resolve(CODE_ROOT, "..", "images");
const BASE_URL = process.env.DEMO_BASE_URL || "http://127.0.0.1:8080";
const RPC_URL = process.env.WEB3_PROVIDER_URL || "http://127.0.0.1:8545";

async function installLocalWallet(context, account, chainId) {
  await context.addInitScript(({ rpcUrl, account, chainId }) => {
    let requestId = 0;
    const listeners = new Map();
    window.ethereum = {
      isMetaMask: true,
      selectedAddress: account,
      request: async ({ method, params = [] }) => {
        if (method === "eth_accounts") return [];
        if (method === "eth_requestAccounts") return [account];
        if (method === "eth_chainId") return `0x${Number(chainId).toString(16)}`;
        if (method === "wallet_switchEthereumChain" || method === "wallet_addEthereumChain") return null;
        const response = await fetch(rpcUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: ++requestId, method, params }),
        });
        const result = await response.json();
        if (result.error) {
          const error = new Error(result.error.message || "Local wallet RPC error");
          error.code = result.error.code;
          throw error;
        }
        return result.result;
      },
      on: (name, handler) => {
        if (!listeners.has(name)) listeners.set(name, []);
        listeners.get(name).push(handler);
      },
      removeListener: (name, handler) => {
        listeners.set(name, (listeners.get(name) || []).filter((item) => item !== handler));
      },
    };
  }, { rpcUrl: RPC_URL, account, chainId });
}

async function main() {
  fs.mkdirSync(IMAGE_DIR, { recursive: true });
  const configResponse = await fetch(`${BASE_URL}/api/config`);
  if (!configResponse.ok) throw new Error(`API config returned HTTP ${configResponse.status}`);
  const config = await configResponse.json();
  const truths = JSON.parse(fs.readFileSync(path.join(CODE_ROOT, "artifacts", "demo_flow_truth.json"), "utf8"));
  const samples = await (await fetch(`${BASE_URL}/api/demo-flows`)).json();
  const normalSample = samples.find((sample) => truths[sample.sample_id] === 0);
  const attackSample = samples.find((sample) => truths[sample.sample_id] === 1);
  if (!normalSample || !attackSample) throw new Error("Correctly classified normal and attack examples are required for the browser scenario.");

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  await installLocalWallet(page.context(), config.roles.owner, config.expected_chain_id);

  try {
    await page.goto(BASE_URL, { waitUntil: "networkidle" });
    const connectButton = page.getByRole("button", { name: "Підключити гаманець" });
    if (await connectButton.isVisible().catch(() => false)) await connectButton.click();
    await page.getByText("ВЛАСНИК", { exact: true }).waitFor({ timeout: 15000 });
    await page.waitForSelector(".metric-grid .metric-card");
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_dashboard.png"), fullPage: true });

    await page.locator("[data-view='devices']").click();
    await page.waitForSelector("#device-table tr td");
    await page.locator("#device-name").fill("Віртуальний контрольний вузол");
    await page.locator("#register-device-form button[type='submit']").click();
    await page.locator("#device-tx-status.success").waitFor({ timeout: 30000 });
    const registrationNotice = await page.locator("#device-tx-status").innerText();
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_device_registration.png"), fullPage: true });

    const devicesAfterRegistration = await (await fetch(`${BASE_URL}/api/devices`)).json();
    const newDevice = devicesAfterRegistration.find((device) => device.local_name === "Віртуальний контрольний вузол");
    if (!newDevice) throw new Error("The new device was not returned by the on-chain registry.");
    await page.selectOption("#grant-device", newDevice.device_id);
    await page.locator("#actor-address").fill(config.roles.actor);
    await page.locator("#grant-access-form button[type='submit']").click();
    await page.locator("#access-tx-status.success").waitFor({ timeout: 30000 });
    const grantNotice = await page.locator("#access-tx-status").innerText();
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_access_grant.png"), fullPage: true });
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_owner_devices.png"), fullPage: true });

    await page.locator("[data-view='decision']").click();
    await page.waitForFunction(() => document.querySelectorAll("#inference-device option[value]").length > 0);
    const targetDevice = newDevice.device_id;
    if (!targetDevice) throw new Error("No active registered device is available for the UI scenario.");
    await page.selectOption("#inference-device", targetDevice);
    await page.selectOption("#demo-sample", normalSample.sample_id);
    await page.locator("#inference-form button[type='submit']").click();
    await page.locator("#decision-result .decision-banner.normal").waitFor({ timeout: 60000 });
    await page.locator("#inference-status.success").waitFor({ timeout: 60000 });
    const normalNotice = await page.locator("#inference-status").innerText();
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_model_decision_normal.png"), fullPage: true });

    await page.selectOption("#demo-sample", attackSample.sample_id);
    await page.locator("#inference-form button[type='submit']").click();
    await page.locator("#decision-result .decision-banner.attack").waitFor({ timeout: 60000 });
    await page.locator("#inference-status.success").waitFor({ timeout: 60000 });
    await page.locator("#inference-status").waitFor();
    const inferenceNotice = await page.locator("#inference-status").innerText();
    const decisionDetails = await page.locator("#decision-result").innerText();
    if (!decisionDetails.includes("Quarantined")) {
      const audit = await (await fetch(`${BASE_URL}/api/audit?limit=100`)).json();
      const deviceEvents = audit.events.filter((event) => event.device_id === targetDevice.toLowerCase());
      throw new Error(`Attack decision was recorded, but the device was not quarantined: ${decisionDetails}; events=${JSON.stringify(deviceEvents)}`);
    }
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_model_decision_attack.png"), fullPage: true });

    await page.locator("#check-last-gateway").click();
    await page.locator("#last-gateway-result").waitFor({ timeout: 15000 });
    const gatewayText = await page.locator("#last-gateway-result").innerText();
    if (!gatewayText.includes("ВІДХИЛЕНО")) throw new Error(`Expected gateway denial after quarantine, got: ${gatewayText}`);
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_gateway_denied.png"), fullPage: true });

    await page.locator("[data-view='audit']").click();
    await page.getByText("DecisionRecorded", { exact: true }).first().waitFor({ timeout: 15000 });
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_audit_log.png"), fullPage: true });

    await page.locator("[data-view='integrity']").click();
    await page.waitForFunction(() => document.querySelectorAll("#integrity-flow option[value]").length > 0);
    const option = await page.locator("#integrity-flow option").evaluateAll((items) => items.map((item) => item.value).filter(Boolean)[0]);
    await page.selectOption("#integrity-flow", option);
    await page.locator("#load-integrity-payload").click();
    await page.locator("#integrity-json").waitFor();
    await page.locator("#check-integrity").click();
    await page.locator("#integrity-result.valid").waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_integrity_valid.png"), fullPage: true });
    await page.locator("#integrity-json").evaluate((element) => {
      const payload = JSON.parse(element.value);
      payload.features.src_pkts = Number(payload.features.src_pkts || 0) + 1;
      element.value = JSON.stringify(payload, null, 2);
    });
    await page.locator("#check-integrity").click();
    await page.locator("#integrity-result.invalid").waitFor({ timeout: 10000 });
    await page.screenshot({ path: path.join(IMAGE_DIR, "ui_integrity_tampered.png"), fullPage: true });

    const auditorContext = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await installLocalWallet(auditorContext, config.roles.auditor, config.expected_chain_id);
    const auditorPage = await auditorContext.newPage();
    await auditorPage.goto(BASE_URL, { waitUntil: "networkidle" });
    await auditorPage.getByRole("button", { name: "Підключити гаманець" }).click();
    await auditorPage.getByText("АУДИТОР", { exact: true }).waitFor({ timeout: 15000 });
    if (await auditorPage.locator("[data-view='devices']").isVisible()) {
      throw new Error("The auditor account can see owner-only device management.");
    }
    await auditorPage.locator("[data-view='audit']").click();
    await auditorPage.getByText("DecisionRecorded", { exact: true }).first().waitFor({ timeout: 15000 });
    await auditorPage.screenshot({ path: path.join(IMAGE_DIR, "ui_auditor_audit.png"), fullPage: true });
    await auditorContext.close();

    process.stdout.write(JSON.stringify({
      owner_address: config.roles.owner,
      auditor_address: config.roles.auditor,
      sample_id: attackSample.sample_id,
      device_id: targetDevice,
      browser_transaction_hashes: {
        device_registration: registrationNotice.match(/0x[0-9a-fA-F]{64}/)?.[0] || null,
        access_grant: grantNotice.match(/0x[0-9a-fA-F]{64}/)?.[0] || null,
        normal_decision: normalNotice.match(/0x[0-9a-fA-F]{64}/)?.[0] || null,
        attack_decision: inferenceNotice.match(/0x[0-9a-fA-F]{64}/)?.[0] || null,
      },
      screenshots: ["ui_dashboard.png", "ui_device_registration.png", "ui_access_grant.png", "ui_owner_devices.png",
                    "ui_model_decision_normal.png", "ui_model_decision_attack.png", "ui_gateway_denied.png",
                    "ui_audit_log.png", "ui_auditor_audit.png",
                    "ui_integrity_valid.png", "ui_integrity_tampered.png"],
      browser_transactions_used_hardhat_rpc: true,
    }, null, 2) + "\n");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

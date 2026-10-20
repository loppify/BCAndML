const { expect } = require("chai");
const { ethers } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function revertedGas(contract, method) {
  const [signer] = await ethers.getSigners();
  const trace = await ethers.provider.send("debug_traceCall", [{
    from: signer.address,
    to: await contract.getAddress(),
    data: contract.interface.encodeFunctionData(method, [true]),
    gas: "0x186a0"
  }, "latest", { disableMemory: true, disableStack: true, disableStorage: true }]);
  return 21000 + trace.structLogs.reduce((total, op) => total + Number(op.gasCost), 0);
}

describe("Gas optimization measurements", function () {
  it("measures storage packing and custom-error gas before/after", async function () {
    const Wide = await ethers.getContractFactory("WideCampaignRecord");
    const wide = await Wide.deploy();
    const Packed = await ethers.getContractFactory("PackedCampaignRecord");
    const packed = await Packed.deploy();
    const wideCreate = Number((await (await wide.create(1000, 2000)).wait()).gasUsed);
    const packedCreate = Number((await (await packed.create(1000, 2000)).wait()).gasUsed);
    const wideContribution = Number((await (await wide.contribute(1, 1)).wait()).gasUsed);
    const packedContribution = Number((await (await packed.contribute(1, 1)).wait()).gasUsed);

    const ErrorBench = await ethers.getContractFactory("ErrorStyleBenchmark");
    const errorBench = await ErrorBench.deploy();
    const customErrorGas = await revertedGas(errorBench, "customError");
    const revertStringGas = await revertedGas(errorBench, "revertString");
    await errorBench.customError(false);
    await errorBench.revertString(false);
    const result = { storage: { wideCreate, packedCreate, wideContribution, packedContribution }, errors: { revertStringGas, customErrorGas } };
    const output = path.resolve(__dirname, "../artifacts/gas_results.json");
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.log("GAS_MEASUREMENTS", JSON.stringify(result));
    expect(packedCreate).to.be.lessThan(wideCreate);
    expect(customErrorGas).to.be.lessThan(revertStringGas);
  });
});

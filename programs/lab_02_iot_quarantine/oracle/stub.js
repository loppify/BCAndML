const fs = require("node:fs");
const path = require("node:path");

const model = JSON.parse(fs.readFileSync(path.join(__dirname, "stub-model.json"), "utf8"));

function classifyFlow(flow) {
  if (!Number.isInteger(flow.failedLogins) || flow.failedLogins < 0) {
    throw new TypeError("failedLogins must be a non-negative integer");
  }
  const attack = flow.failedLogins >= model.rule.attackMinimum;
  return {
    attack,
    confidence: attack ? model.rule.attackConfidenceBps : model.rule.normalConfidenceBps,
    modelVersion: model.version,
  };
}

module.exports = { classifyFlow, model };

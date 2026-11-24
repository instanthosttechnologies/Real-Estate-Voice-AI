import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

console.log("==================================================================");
console.log("   RUNNING ALL FRONTEND SUITES & ARCHITECTURAL VERIFICATIONS      ");
console.log("==================================================================");

const suites = [
  path.join(__dirname, "frontend_verification.mjs"),
  path.join(__dirname, "robot_voice_widget.test.mjs"),
  path.join(__dirname, "voice_fine_tuning_and_transcript.test.mjs"),
  path.join(__dirname, "universal_dataset_admin.test.mjs"),
];

let allPassed = true;

for (const suite of suites) {
  const result = spawnSync("node", [suite], { stdio: "inherit" });
  if (result.status !== 0) {
    allPassed = false;
  }
}

if (!allPassed) {
  console.error("\n[FAILED] One or more test suites failed.");
  process.exit(1);
} else {
  console.log("\n[SUCCESS] All frontend test suites passed cleanly with 0 errors!");
  process.exit(0);
}

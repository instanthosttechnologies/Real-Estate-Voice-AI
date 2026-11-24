import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("   PHASE 3: UNIVERSAL DATASET ADMIN DASHBOARD VERIFICATION        ");
console.log("==================================================================");

let passed = 0;
let total = 0;

function test(name, fn) {
  total++;
  try {
    fn();
    console.log(`[PASS] ${name}`);
    passed++;
  } catch (err) {
    console.error(`[FAIL] ${name}:`, err.message);
  }
}

// 1. Admin Page Navigation & Tabs
test("Admin Dashboard includes 3 tabs including AI Knowledge / Dataset Management", () => {
  const adminPagePath = path.join(projectRoot, "src", "app", "admin", "page.tsx");
  const content = fs.readFileSync(adminPagePath, "utf-8");

  assert(content.includes('"registered" | "ranking" | "datasets"'), "State must support 'datasets' tab");
  assert(content.includes("All Registered Customers"), "Must preserve All Registered Customers tab");
  assert(content.includes("Customer Priority Ranking"), "Must preserve Customer Priority Ranking tab");
  assert(content.includes("AI Knowledge / Dataset Management"), "Must include AI Knowledge / Dataset Management tab");
  assert(content.includes("<DatasetManagement />"), "Must render DatasetManagement component");
  assert(content.includes("handleToggleCustomer"), "Must preserve customer details inline expansion");
});

// 2. Dataset Management Component Architecture
test("DatasetManagement component implements Active Dataset Card, Version History, and Wizard", () => {
  const compPath = path.join(projectRoot, "src", "components", "DatasetManagement.tsx");
  assert(fs.existsSync(compPath), "DatasetManagement.tsx must exist");
  const content = fs.readFileSync(compPath, "utf-8");

  assert(content.includes("Active Dataset"), "Must display Active Dataset section");
  assert(content.includes("Dataset Version History"), "Must display Version History section");
  assert(content.includes("Universal Dynamic Dataset Ingestion Wizard"), "Must include Ingestion Wizard modal");
  assert(content.includes("handleStartInspection"), "Must handle inspection of uploaded files");
  assert(content.includes("handleConfirmAndUpload"), "Must support approval and activation flows");
  assert(content.includes("handleRollback"), "Must support version rollback");
});

// 3. Dynamic Column Discovery & Approval Requirements
test("DatasetManagement supports dynamic column inspection and Admin field whitelisting", () => {
  const compPath = path.join(projectRoot, "src", "components", "DatasetManagement.tsx");
  const content = fs.readFileSync(compPath, "utf-8");

  assert(content.includes("Discovered Columns"), "Must show discovered columns count");
  assert(content.includes("toggleFieldApproval"), "Must allow toggling field approvals via checkboxes");
  assert(content.includes("displayIdentifier"), "Must allow designating a primary display identifier");
  assert(content.includes("welcomeGreeting"), "Must allow setting custom AI opening greeting");
  assert(content.includes("domainName"), "Must allow setting business/domain name");
  assert(content.includes("fieldLabels"), "Must allow setting spoken display labels");
  assert(content.includes("Key Candidate"), "Must display candidate identifier badges");
});

// 4. Query Preview Panel (Zero Bedrock calls)
test("DatasetManagement includes Query Preview sandbox exercising offline query engine", () => {
  const compPath = path.join(projectRoot, "src", "components", "DatasetManagement.tsx");
  const content = fs.readFileSync(compPath, "utf-8");

  assert(content.includes("Query Preview & Grounding Sandbox"), "Must feature Query Preview Sandbox");
  assert(content.includes("handleRunPreviewQuery"), "Must handle executing preview queries");
  assert(content.includes("Zero Bedrock Calls"), "Must document offline zero-Bedrock execution");
  assert(content.includes("Unapproved fields strictly omitted"), "Must verify zero leakage of unapproved fields");
});

// 5. Frontend API Client Dataset Methods
test("api-client implements typed dataset inspection, approval, activation, and preview methods", () => {
  const apiPath = path.join(projectRoot, "src", "lib", "api.ts");
  const content = fs.readFileSync(apiPath, "utf-8");

  assert(content.includes("export interface DatasetInspectionResponse"), "Must export DatasetInspectionResponse");
  assert(content.includes("export interface DatasetDetailResponse"), "Must export DatasetDetailResponse");
  assert(content.includes("export interface DatasetPreviewQueryResponse"), "Must export DatasetPreviewQueryResponse");
  assert(content.includes("inspect(file: File)"), "api.datasets must implement inspect");
  assert(content.includes("upload("), "api.datasets must implement upload");
  assert(content.includes("approve("), "api.datasets must implement approve");
  assert(content.includes("activate("), "api.datasets must implement activate");
  assert(content.includes("rollback("), "api.datasets must implement rollback");
  assert(content.includes("previewQuery("), "api.datasets must implement previewQuery");
});

console.log("------------------------------------------------------------------");
console.log(`Total tests run: ${total}`);
console.log(`Passed: ${passed}`);
console.log(`Failed: ${total - passed}`);
console.log("==================================================================");

if (passed === total) {
  process.exit(0);
} else {
  process.exit(1);
}

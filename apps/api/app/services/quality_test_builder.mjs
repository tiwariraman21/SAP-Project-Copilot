import fs from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { SpreadsheetFile, Workbook } = require("@oai/artifact-tool");
const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("Usage: quality_test_builder.mjs <input.json> <output.xlsx>");

const PRIORITY_LABELS = [
  ["must", "Must Have"],
  ["should", "Good To Have"],
  ["could", "Nice To Have"],
  ["wont", "Won't Have"],
  ["won", "Won't Have"],
  ["good", "Good To Have"],
  ["nice", "Nice To Have"],
];

function priorityLabel(value) {
  const key = String(value || "").toLowerCase().replace(/[^a-z]/g, "");
  for (const [prefix, label] of PRIORITY_LABELS) {
    if (key.startsWith(prefix)) return label;
  }
  return "Good To Have";
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const cases = data.test_cases || [];
const workbook = Workbook.create();
const tests = workbook.worksheets.add("Test Cases");
const summary = workbook.worksheets.add("Quality Summary");
const guidance = workbook.worksheets.add("Execution Guide");
const green = "#0D6B50", dark = "#17211E", pale = "#E8F3ED", line = "#CBDAD2", orange = "#F47C42";

tests.showGridLines = false;
tests.mergeCells("A1:R1");
tests.getRange("A1").values = [[data.title || "Quality Test Pack"]];
tests.getRange("A1:R1").format = { fill: dark, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34, verticalAlignment: "center" };
tests.mergeCells("A2:R2");
tests.getRange("A2").values = [["Editable execution workbook generated from approved requirements. Record actual results, evidence, defects, dates, and remarks during testing."]];
tests.getRange("A2:R2").format = { fill: pale, font: { color: dark, italic: true }, wrapText: true, rowHeight: 30 };
const headers = ["Test Key", "Req Key", "Title", "Priority", "Test Type", "Preconditions", "Test Steps", "Expected Result", "Actual Result", "Status", "Assigned To", "Planned Date", "Execution Date", "Defect ID", "Evidence", "Remarks", "Source Evidence", "Pass Flag"];
tests.getRange("A4:R4").values = [headers];
tests.getRange("A4:R4").format = { fill: green, font: { bold: true, color: "#FFFFFF" }, wrapText: true, rowHeight: 32, verticalAlignment: "center" };
const rows = cases.map(item => [
  item.test_key, item.requirement_key, item.title,
  priorityLabel(item.priority), item.test_type || "Functional",
  (item.preconditions || []).map((x, i) => `${i + 1}. ${x}`).join("\n"),
  (item.steps || []).map((x, i) => `${i + 1}. ${x}`).join("\n"), item.expected_result,
  item.actual_result || "", item.status || "Not Run", item.assigned_to || "QA Engineer",
  item.planned_date ? new Date(`${item.planned_date}T00:00:00`) : null,
  item.execution_date ? new Date(`${item.execution_date}T00:00:00`) : null,
  item.defect_id || "", item.evidence || "", item.remarks || "", item.source_evidence || "Approved BRD source", null,
]);
if (rows.length) {
  const last = 4 + rows.length;
  tests.getRange(`A5:R${last}`).values = rows;
  tests.getRange("R5").formulas = [[`=IF(J5="Passed",1,0)`]];
  tests.getRange(`R5:R${last}`).fillDown();
  tests.getRange(`L5:M${last}`).format.numberFormat = "yyyy-mm-dd";
  tests.getRange(`R5:R${last}`).format.numberFormat = "0";
  tests.getRange(`A5:R${last}`).format = { verticalAlignment: "top", wrapText: true, borders: { insideHorizontal: { style: "thin", color: line } }, rowHeight: 64 };
  tests.getRange(`D5:D${last}`).dataValidation = { rule: { type: "list", values: ["Must Have", "Good To Have", "Nice To Have", "Won't Have"] } };
  tests.getRange(`E5:E${last}`).dataValidation = { rule: { type: "list", values: ["Functional", "Integration", "Regression", "Security", "Performance", "UAT"] } };
  tests.getRange(`J5:J${last}`).dataValidation = { rule: { type: "list", values: ["Not Run", "In Progress", "Passed", "Failed", "Blocked", "Not Applicable"] } };
  tests.getRange(`K5:K${last}`).dataValidation = { rule: { type: "list", values: ["QA Engineer", "SAP Functional Consultant", "Developer", "Business Tester", "Security Tester", "Unassigned"] } };
  tests.getRange(`J5:J${last}`).conditionalFormats.add("containsText", { text: "Passed", format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } } });
  tests.getRange(`J5:J${last}`).conditionalFormats.add("containsText", { text: "Failed", format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } } });
  tests.getRange(`J5:J${last}`).conditionalFormats.add("containsText", { text: "Blocked", format: { fill: "#FFF1E8", font: { color: "#9A3412", bold: true } } });
  tests.getRange(`D5:D${last}`).conditionalFormats.add("containsText", { text: "Must Have", format: { fill: "#FFF1E8", font: { color: "#9A3412", bold: true } } });
  tests.tables.add(`A4:R${last}`, true, "QualityTestCasesTable");
}
tests.freezePanes.freezeRows(4); tests.freezePanes.freezeColumns(2);
const widths = [13, 12, 26, 16, 14, 34, 42, 42, 34, 15, 24, 15, 15, 14, 28, 30, 42, 10];
headers.forEach((_, i) => { tests.getRangeByIndexes(0, i, Math.max(rows.length + 4, 5), 1).format.columnWidth = widths[i]; });

summary.showGridLines = false;
summary.mergeCells("A1:H1"); summary.getRange("A1").values = [["Quality Testing Summary"]];
summary.getRange("A1:H1").format = { fill: dark, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34 };
summary.getRange("A3:B9").values = [["KPI", "Value"], ["Total Tests", null], ["Passed", null], ["Failed", null], ["Blocked", null], ["Not Run", null], ["Pass Rate", null]];
summary.getRange("A3:B3").format = { fill: green, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("B4:B9").formulas = [[`=COUNTA('Test Cases'!$A$5:$A$504)`], [`=COUNTIF('Test Cases'!$J$5:$J$504,"Passed")`], [`=COUNTIF('Test Cases'!$J$5:$J$504,"Failed")`], [`=COUNTIF('Test Cases'!$J$5:$J$504,"Blocked")`], [`=COUNTIF('Test Cases'!$J$5:$J$504,"Not Run")`], [`=IF(B4=0,0,B5/B4)`]];
summary.getRange("B9").format.numberFormat = "0.0%";
summary.getRange("A4:B9").format = { borders: { insideHorizontal: { style: "thin", color: line } }, rowHeight: 27 };
summary.getRange("D3:H3").values = [["Priority", "Total", "Passed", "Failed", "Coverage %"]];
summary.getRange("D3:H3").format = { fill: orange, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("D4:D7").values = [["Must Have"], ["Good To Have"], ["Nice To Have"], ["Won't Have"]];
summary.getRange("E4").formulas = [[`=COUNTIF('Test Cases'!$D$5:$D$504,D4)`]]; summary.getRange("E4:E7").fillDown();
summary.getRange("F4").formulas = [[`=COUNTIFS('Test Cases'!$D$5:$D$504,D4,'Test Cases'!$J$5:$J$504,"Passed")`]]; summary.getRange("F4:F7").fillDown();
summary.getRange("G4").formulas = [[`=COUNTIFS('Test Cases'!$D$5:$D$504,D4,'Test Cases'!$J$5:$J$504,"Failed")`]]; summary.getRange("G4:G7").fillDown();
summary.getRange("H4").formulas = [[`=IF(E4=0,0,F4/E4)`]]; summary.getRange("H4:H7").fillDown(); summary.getRange("H4:H7").format.numberFormat = "0.0%";
summary.getRange("D4:H7").format = { borders: { insideHorizontal: { style: "thin", color: line } }, rowHeight: 27 };
summary.getRange("A:H").format.columnWidth = 17; summary.getRange("A:A").format.columnWidth = 22; summary.freezePanes.freezeRows(3);

guidance.showGridLines = false;
guidance.mergeCells("A1:D1"); guidance.getRange("A1").values = [["Test Execution Guide"]];
guidance.getRange("A1:D1").format = { fill: dark, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 34 };
guidance.getRange("A3:B9").values = [["Section", "Guidance"], ["Entry criteria", (data.entry_criteria || []).join("; ")], ["Exit criteria", (data.exit_criteria || []).join("; ")], ["Execution", "Update Actual Result, Status, Execution Date, Defect ID, Evidence, and Remarks for every executed test."], ["Evidence", "Reference a secure evidence location; do not embed passwords or sensitive data."], ["Defects", "Use the approved defect-management identifier and link failures to the matching test key."], ["Governance", "Business and QA owners must review all Must Have failures before release."]];
guidance.getRange("A3:B3").format = { fill: green, font: { bold: true, color: "#FFFFFF" } };
guidance.getRange("A4:B9").format = { wrapText: true, verticalAlignment: "top", borders: { insideHorizontal: { style: "thin", color: line } }, rowHeight: 42 };
guidance.getRange("A:A").format.columnWidth = 24; guidance.getRange("B:B").format.columnWidth = 86; guidance.freezePanes.freezeRows(3);

const output = await SpreadsheetFile.exportXlsx(workbook); await output.save(outputPath);
const inspection = await workbook.inspect({ kind: "workbook,sheet,table", maxChars: 8000, tableMaxRows: 8, tableMaxCols: 18 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
const previews = [];
if (process.env.SPREADSHEET_PREVIEW_DIR) {
  await fs.mkdir(process.env.SPREADSHEET_PREVIEW_DIR, { recursive: true });
  for (const sheetName of ["Test Cases", "Quality Summary", "Execution Guide"]) {
    const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
    const path = `${process.env.SPREADSHEET_PREVIEW_DIR}/${sheetName.toLowerCase().replaceAll(" ", "-")}.png`;
    await fs.writeFile(path, new Uint8Array(await preview.arrayBuffer())); previews.push(path);
  }
}
console.log(JSON.stringify({ outputPath, testCount: rows.length, inspection: inspection.ndjson, errors: errors.ndjson, previews }));

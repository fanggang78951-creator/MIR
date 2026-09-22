import { FileBlob, SpreadsheetFile } from "file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const inputPath = process.argv[2];
if (!inputPath) throw new Error("usage: verify_weapon_enchant_workbook.mjs <input.xlsx>");

const expected = ["基础设置", "结果候选", "普通洗练设置", "词条路由库", "填写说明"];
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const actual = workbook.worksheets.items.map((item) => item.name);
if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error(`sheet order mismatch: ${JSON.stringify(actual)}`);
}

for (const sheet of workbook.worksheets.items) {
  const check = await workbook.inspect({
    kind: "table,formula",
    sheetId: sheet.name,
    maxChars: 7000,
    tableMaxRows: 40,
    tableMaxCols: 12,
    tableMaxCellChars: 100,
  });
  console.log(check.ndjson);
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "weapon enchant v2 formula error scan",
});
if (errors.ndjson && !errors.ndjson.includes('"matches":[]')) {
  console.log(errors.ndjson);
}
console.log(JSON.stringify({ ok: true, input: inputPath, sheets: actual }));

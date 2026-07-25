import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const cwd = process.cwd();
const sourcePath = path.join(cwd, 'new data', 'bangalore_projects_classified.json');
const outputDir = path.join(cwd, 'outputs', 'bangalore_units_report');
const outputPath = path.join(outputDir, 'bangalore_units_report.xlsx');
const qwisePreviewPath = path.join(outputDir, 'preview_qwise.png');
const estimatePreviewPath = path.join(outputDir, 'preview_estimate.png');

const bengaluruCity2011 = 8443675;
const bengaluruUa2016 = 10456000;

const data = JSON.parse(await fs.readFile(sourcePath, 'utf8'));

function groupBy(field) {
  const map = new Map();
  for (const row of data) {
    const key = row[field] || 'NA';
    const units = Number(row.units || 0);
    const current = map.get(key) || { projects: 0, units: 0 };
    current.projects += 1;
    current.units += units;
    map.set(key, current);
  }
  return map;
}

function sumUnits(rows) {
  return rows.reduce((acc, row) => acc + Number(row.units || 0), 0);
}

const totalProjects = data.length;
const totalUnits = sumUnits(data);
const q1Map = groupBy('quartile analysis 1');
const q2Map = groupBy('quartile analysis 2');
const statusMap = groupBy('construction_status');

const q1Rows = ['Q1', 'Q2', 'Q3', 'Q4'].map((label) => ({
  label,
  ...q1Map.get(label),
}));

const q2Rows = [
  { label: 'NA', ...(q2Map.get('NA') || { projects: 0, units: 0 }) },
  { label: 'Q4-Sub-Q1', ...(q2Map.get('Q4-Sub-Q1') || { projects: 0, units: 0 }) },
  { label: 'Q4-Sub-Q2', ...(q2Map.get('Q4-Sub-Q2') || { projects: 0, units: 0 }) },
  { label: 'Q4-Sub-Q3', ...(q2Map.get('Q4-Sub-Q3') || { projects: 0, units: 0 }) },
  { label: 'Q4-Sub-Q4', ...(q2Map.get('Q4-Sub-Q4') || { projects: 0, units: 0 }) },
];

const statusRows = ['NA', 'Ready To Move', 'Under Construction'].map((label) => ({
  label,
  ...(statusMap.get(label) || { projects: 0, units: 0 }),
}));

const q4TotalUnits = q1Map.get('Q4')?.units || 0;
const q2ClassifiedUnits = q2Rows.slice(1).reduce((acc, row) => acc + row.units, 0);
const q2MissingUnits = q4TotalUnits - q2ClassifiedUnits;
const q2MissingProjects = (q1Map.get('Q4')?.projects || 0) - q2Rows.slice(1).reduce((acc, row) => acc + row.projects, 0);

const wb = Workbook.create();
const qSheet = wb.worksheets.add('Q-wise');
const eSheet = wb.worksheets.add('Estimate');

for (const sheet of [qSheet, eSheet]) {
  sheet.showGridLines = false;
  if (sheet.freezePanes?.freezeRows) {
    sheet.freezePanes.freezeRows(4);
  }
}

function mergeText(sheet, rangeAddress, text, style = {}) {
  const range = sheet.getRange(rangeAddress);
  range.merge();
  range.values = [[text]];
  if (Object.keys(style).length > 0) {
    range.format = style;
  }
  return range;
}

function styleTableRange(sheet, rangeAddress) {
  sheet.getRange(rangeAddress).format = {
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    verticalAlignment: 'center',
  };
}

function styleHeaderRange(sheet, rangeAddress, fill = 'accent1') {
  sheet.getRange(rangeAddress).format = {
    fill,
    font: { bold: true, color: 'lt1' },
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    horizontalAlignment: 'center',
    verticalAlignment: 'center',
    wrapText: true,
  };
}

function styleTotalRow(sheet, rangeAddress) {
  sheet.getRange(rangeAddress).format = {
    fill: 'lt2',
    font: { bold: true },
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    verticalAlignment: 'center',
  };
}

function styleNote(sheet, rangeAddress) {
  sheet.getRange(rangeAddress).format = {
    fill: 'lt2',
    font: { italic: true, color: '#4B5563' },
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    wrapText: true,
    verticalAlignment: 'top',
  };
}

// ------------------------
// Sheet 1: Q-wise summary
// ------------------------
mergeText(
  qSheet,
  'A1:F1',
  'Bangalore Projects: Q-wise Unit Breakdown',
  {
    fill: 'accent1',
    font: { bold: true, color: 'lt1', size: 14 },
    horizontalAlignment: 'center',
    verticalAlignment: 'center',
  },
);
qSheet.getRange('A2:F2').merge();
qSheet.getRange('A2').values = [[`Source: ${path.relative(cwd, sourcePath)} | ${totalProjects.toLocaleString('en-US')} projects | ${totalUnits.toLocaleString('en-US')} units`]];
qSheet.getRange('A2:F2').format = {
  fill: 'lt2',
  font: { italic: true, color: '#4B5563' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  wrapText: true,
  verticalAlignment: 'center',
};

qSheet.getRange('A4:F4').merge();
qSheet.getRange('A4').values = [['Quartile Analysis 1']];
qSheet.getRange('A4:F4').format = {
  fill: 'accent2',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(qSheet, 'A5:F5', 'accent1');
qSheet.getRange('A5:F5').values = [[
  'Quartile',
  'Projects',
  'Units',
  'Share of projects',
  'Share of units',
  'Avg units / project',
]];

qSheet.getRange('A6:C9').values = q1Rows.map((row) => [row.label, row.projects, row.units]);
for (let i = 0; i < 4; i += 1) {
  const row = 6 + i;
  qSheet.getRange(`D${row}`).formulas = [[`=B${row}/$B$10`]];
  qSheet.getRange(`E${row}`).formulas = [[`=C${row}/$C$10`]];
  qSheet.getRange(`F${row}`).formulas = [[`=C${row}/B${row}`]];
}
qSheet.getRange('B10').formulas = [['=SUM(B6:B9)']];
qSheet.getRange('C10').formulas = [['=SUM(C6:C9)']];
qSheet.getRange('D10').formulas = [['=SUM(D6:D9)']];
qSheet.getRange('E10').formulas = [['=SUM(E6:E9)']];
qSheet.getRange('F10').formulas = [['=C10/B10']];
qSheet.getRange('A10').values = [['Total']];
styleTableRange(qSheet, 'A5:F10');
styleTotalRow(qSheet, 'A10:F10');
qSheet.getRange('B6:C10').format.numberFormat = '#,##0';
qSheet.getRange('D6:E10').format.numberFormat = '0.0%';
qSheet.getRange('F6:F10').format.numberFormat = '#,##0.0';

qSheet.getRange('A12:F12').merge();
qSheet.getRange('A12').values = [['Quartile Analysis 2']];
qSheet.getRange('A12:F12').format = {
  fill: 'accent3',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(qSheet, 'A13:F13', 'accent1');
qSheet.getRange('A13:F13').values = [[
  'Segment',
  'Projects',
  'Units',
  'Share of all projects',
  'Share of all units',
  'Share within Q4 sub-group',
]];

const q2StartRow = 14;
for (let i = 0; i < q2Rows.length; i += 1) {
  const row = q2StartRow + i;
  const item = q2Rows[i];
  qSheet.getRange(`A${row}`).values = [[item.label]];
  qSheet.getRange(`B${row}`).values = [[item.projects]];
  qSheet.getRange(`C${row}`).values = [[item.units]];
  qSheet.getRange(`D${row}`).formulas = [[`=B${row}/$B$19`]];
  qSheet.getRange(`E${row}`).formulas = [[`=C${row}/$C$19`]];
  if (i === 0) {
    qSheet.getRange(`F${row}`).values = [['']];
  } else {
    qSheet.getRange(`F${row}`).formulas = [[`=C${row}/SUM($C$15:$C$18)`]];
  }
}
qSheet.getRange('A19').values = [['Total']];
qSheet.getRange('B19').formulas = [['=SUM(B14:B18)']];
qSheet.getRange('C19').formulas = [['=SUM(C14:C18)']];
qSheet.getRange('D19').formulas = [['=SUM(D14:D18)']];
qSheet.getRange('E19').formulas = [['=SUM(E14:E18)']];
qSheet.getRange('F19').formulas = [['=SUM(F15:F18)']];
styleTableRange(qSheet, 'A13:F19');
styleTotalRow(qSheet, 'A19:F19');
qSheet.getRange('B14:C19').format.numberFormat = '#,##0';
qSheet.getRange('D14:E19').format.numberFormat = '0.0%';
qSheet.getRange('F14:F19').format.numberFormat = '0.0%';

mergeText(
  qSheet,
  'A21:F22',
  `Q4 analysis 2 note: ${q2MissingProjects.toLocaleString('en-US')} Q4 projects (${q2MissingUnits.toLocaleString('en-US')} units) are missing a quartile analysis 2 label, so the NA bucket includes all non-Q4 rows plus those Q4 rows.`,
  {
    fill: 'lt2',
    font: { italic: true, color: '#4B5563' },
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    wrapText: true,
    verticalAlignment: 'top',
  },
);

qSheet.getRange('A24:F24').merge();
qSheet.getRange('A24').values = [[`Source file: ${path.relative(cwd, sourcePath)}`]];
qSheet.getRange('A24:F24').format = {
  fill: 'lt2',
  font: { italic: true, color: '#6B7280' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  wrapText: true,
  verticalAlignment: 'center',
};

qSheet.getRange('A:A').format.columnWidth = 20;
qSheet.getRange('B:B').format.columnWidth = 12;
qSheet.getRange('C:C').format.columnWidth = 14;
qSheet.getRange('D:D').format.columnWidth = 16;
qSheet.getRange('E:E').format.columnWidth = 16;
qSheet.getRange('F:F').format.columnWidth = 18;
qSheet.getRange('A1:F1').format.rowHeight = 24;
qSheet.getRange('A4:F4').format.rowHeight = 22;
qSheet.getRange('A12:F12').format.rowHeight = 22;
qSheet.getRange('A21:F22').format.rowHeight = 38;
qSheet.getRange('A24:F24').format.rowHeight = 20;

// ------------------------
// Sheet 2: Estimate model
// ------------------------
mergeText(
  eSheet,
  'A1:H1',
  'Occupancy and Population Estimate',
  {
    fill: 'accent1',
    font: { bold: true, color: 'lt1', size: 14 },
    horizontalAlignment: 'center',
    verticalAlignment: 'center',
  },
);
eSheet.getRange('A2:H2').merge();
eSheet.getRange('A2').values = [[
  'Occupancy model uses construction status, a small under-construction occupancy allowance, family share, and household size assumptions. Benchmarks are Bengaluru city 2011 census and a 2016 urban-agglomeration estimate.',
]];
eSheet.getRange('A2:H2').format = {
  fill: 'lt2',
  font: { italic: true, color: '#4B5563' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  wrapText: true,
  verticalAlignment: 'center',
};

eSheet.getRange('A4:D4').merge();
eSheet.getRange('A4').values = [['Construction Status Split']];
eSheet.getRange('A4:D4').format = {
  fill: 'accent2',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(eSheet, 'A5:D5', 'accent1');
eSheet.getRange('A5:D5').values = [[
  'Status',
  'Projects',
  'Units',
  'Share of units',
]];
for (let i = 0; i < statusRows.length; i += 1) {
  const row = 6 + i;
  const item = statusRows[i];
  eSheet.getRange(`A${row}`).values = [[item.label]];
  eSheet.getRange(`B${row}`).values = [[item.projects]];
  eSheet.getRange(`C${row}`).values = [[item.units]];
  eSheet.getRange(`D${row}`).formulas = [[`=C${row}/$C$9`]];
}
eSheet.getRange('A9').values = [['Total']];
eSheet.getRange('B9').formulas = [['=SUM(B6:B8)']];
eSheet.getRange('C9').formulas = [['=SUM(C6:C8)']];
eSheet.getRange('D9').formulas = [['=SUM(D6:D8)']];
styleTableRange(eSheet, 'A5:D9');
styleTotalRow(eSheet, 'A9:D9');
eSheet.getRange('B6:C9').format.numberFormat = '#,##0';
eSheet.getRange('D6:D9').format.numberFormat = '0.0%';

eSheet.getRange('A11:C11').merge();
eSheet.getRange('A11').values = [['Occupancy Assumptions']];
eSheet.getRange('A11:C11').format = {
  fill: 'accent3',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(eSheet, 'A12:C12', 'accent1');
eSheet.getRange('A12:C12').values = [[
  'Assumption',
  'Value',
  'Comment',
]];

const assumptions = [
  ['Occupancy rate of occupiable stock', 0.9, 'Share of occupiable stock assumed occupied'],
  ['Share of under-construction units treated as occupiable today', 0.1, 'Small allowance for near-complete stock'],
  ['Family share of occupied units', 0.75, 'Occupied units used by families / households'],
  ['Avg persons per family unit', 4.1, 'Used for family-occupied units'],
  ['Avg persons per non-family unit', 1.5, 'Used for singles / non-family occupancy'],
];
for (let i = 0; i < assumptions.length; i += 1) {
  const row = 13 + i;
  const [label, value, comment] = assumptions[i];
  eSheet.getRange(`A${row}`).values = [[label]];
  eSheet.getRange(`B${row}`).values = [[value]];
  eSheet.getRange(`C${row}`).values = [[comment]];
}
styleTableRange(eSheet, 'A12:C17');
eSheet.getRange('B13:B14').format.numberFormat = '0.0%';
eSheet.getRange('B15:B15').format.numberFormat = '0.0%';
eSheet.getRange('B16:B17').format.numberFormat = '#,##0.0';
eSheet.getRange('A13:C17').format.wrapText = true;

eSheet.getRange('F4:H4').merge();
eSheet.getRange('F4').values = [['Occupancy Model']];
eSheet.getRange('F4:H4').format = {
  fill: 'accent4',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(eSheet, 'F5:H5', 'accent1');
eSheet.getRange('F5:H5').values = [[
  'Metric',
  'Value',
  'Comment',
]];

const outputs = [
  ['Occupiable stock today', `=C7 + C8*$B$14`, 'Ready-to-move units plus 10% of under-construction units'],
  ['Estimated occupied units', `=G6*$B$13`, 'Occupiable stock multiplied by the occupancy rate'],
  ['Family-occupied units', `=G7*$B$15`, 'Occupied units multiplied by the family share'],
  ['Non-family occupied units', `=G7-G8`, 'Residual occupied units'],
  ['Estimated population', `=G8*$B$16 + G9*$B$17`, 'Families plus non-family households'],
  ['Population as % of Bengaluru city 2011', `=G10/${bengaluruCity2011}`, 'Base estimate compared with 2011 city census'],
  ['Population as % of Bengaluru UA 2016 est', `=G10/${bengaluruUa2016}`, 'Base estimate compared with 2016 UA estimate'],
  ['Full-stock theoretical max population', `='Q-wise'!$C$10*$B$16`, 'All units occupied at family-unit size'],
];

for (let i = 0; i < outputs.length; i += 1) {
  const row = 6 + i;
  const [label, formula, comment] = outputs[i];
  eSheet.getRange(`F${row}`).values = [[label]];
  eSheet.getRange(`G${row}`).formulas = [[formula]];
  eSheet.getRange(`H${row}`).values = [[comment]];
}
styleTableRange(eSheet, 'F5:H13');
eSheet.getRange('G6:G10').format.numberFormat = '#,##0';
eSheet.getRange('G11:G13').format.numberFormat = '0.0%';
eSheet.getRange('G13').format.numberFormat = '#,##0';
eSheet.getRange('G6:G13').format.horizontalAlignment = 'right';
eSheet.getRange('F6:H13').format.wrapText = true;

eSheet.getRange('F15:H15').merge();
eSheet.getRange('F15').values = [['Bengaluru Benchmark Check']];
eSheet.getRange('F15:H15').format = {
  fill: 'accent5',
  font: { bold: true, color: 'lt1' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  verticalAlignment: 'center',
};
styleHeaderRange(eSheet, 'F16:H16', 'accent1');
eSheet.getRange('F16:H16').values = [[
  'Benchmark',
  'Population',
  'Base estimate as % of benchmark',
]];

const benchmarkRows = [
  ['Bengaluru city (2011 census)', bengaluruCity2011, '=G10/G17'],
  ['Bengaluru urban agglomeration (2016 est.)', bengaluruUa2016, '=G10/G18'],
  ['Full-stock theoretical max (all units x 4.1)', `='Q-wise'!$C$10*$B$16`, '=G10/G19'],
  ['Base estimate', '=G10', '=1'],
];
for (let i = 0; i < benchmarkRows.length; i += 1) {
  const row = 17 + i;
  const [label, population, pctFormula] = benchmarkRows[i];
  eSheet.getRange(`F${row}`).values = [[label]];
  if (typeof population === 'number') {
    eSheet.getRange(`G${row}`).values = [[population]];
  } else {
    eSheet.getRange(`G${row}`).formulas = [[population]];
  }
  eSheet.getRange(`H${row}`).formulas = [[pctFormula]];
}
styleTableRange(eSheet, 'F16:H20');
eSheet.getRange('G17:G20').format.numberFormat = '#,##0';
eSheet.getRange('H17:H20').format.numberFormat = '0.0%';
styleTotalRow(eSheet, 'F20:H20');

mergeText(
  eSheet,
  'A22:H23',
  'Interpretation: even the full-stock theoretical max stays below the 2011 Bengaluru city census population, so this dataset is a strong housing-supply slice but not a whole-city population proxy.',
  {
    fill: 'lt2',
    font: { italic: true, color: '#4B5563' },
    borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
    wrapText: true,
    verticalAlignment: 'top',
  },
);

eSheet.getRange('A25:H25').merge();
eSheet.getRange('A25').values = [[
  `Benchmarks: https://en.wikipedia.org/wiki/Bengaluru | https://en.wikipedia.org/wiki/Bengaluru_Urban_district`,
]];
eSheet.getRange('A25:H25').format = {
  fill: 'lt2',
  font: { italic: true, color: '#6B7280' },
  borders: { preset: 'all', style: 'thin', color: '#D1D5DB' },
  wrapText: true,
  verticalAlignment: 'center',
};

eSheet.getRange('A:A').format.columnWidth = 30;
eSheet.getRange('B:B').format.columnWidth = 14;
eSheet.getRange('C:C').format.columnWidth = 26;
eSheet.getRange('D:D').format.columnWidth = 16;
eSheet.getRange('E:E').format.columnWidth = 4;
eSheet.getRange('F:F').format.columnWidth = 32;
eSheet.getRange('G:G').format.columnWidth = 18;
eSheet.getRange('H:H').format.columnWidth = 28;
eSheet.getRange('A1:H1').format.rowHeight = 24;
eSheet.getRange('A4:D4').format.rowHeight = 22;
eSheet.getRange('A11:C11').format.rowHeight = 22;
eSheet.getRange('F4:H4').format.rowHeight = 22;
eSheet.getRange('F15:H15').format.rowHeight = 22;
eSheet.getRange('A22:H23').format.rowHeight = 40;
eSheet.getRange('A25:H25').format.rowHeight = 20;

await fs.mkdir(outputDir, { recursive: true });

const qPreview = await wb.render({ sheetName: 'Q-wise', range: 'A1:F24', scale: 1.5 });
await fs.writeFile(qwisePreviewPath, Buffer.from(await qPreview.arrayBuffer()));

const ePreview = await wb.render({ sheetName: 'Estimate', range: 'A1:H25', scale: 1.5 });
await fs.writeFile(estimatePreviewPath, Buffer.from(await ePreview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);

console.log(JSON.stringify({
  outputPath,
  qwisePreviewPath,
  estimatePreviewPath,
  totalProjects,
  totalUnits,
  q2MissingProjects,
  q2MissingUnits,
}, null, 2));

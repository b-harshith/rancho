import fs from "node:fs/promises";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const outDir = "/Users/malleswararao/Desktop/school extraction/outputs/q4_fee_scenarios";
const outFile = `${outDir}/fee_threshold_scenario_matrix.xlsx`;
const previewFile = `${outDir}/fee_threshold_scenario_matrix_preview.png`;

const cities = [
  ["Delhi NCR", [[598,154050,2592.5,[8,16,39,78,116,155]],[240,79655,1786.9,[4,8,20,40,60,80]],[115,45370,1230.3,[3,5,12,23,35,46]]]],
  ["Bangalore", [[274,141971,2287.9,[8,15,36,71,107,142]],[110,44780,1081.4,[3,5,12,23,34,45]],[38,10659,493.0,[1,2,3,6,8,11]]]],
  ["Hyderabad", [[294,80136,1494.8,[5,9,21,41,61,81]],[127,42898,1021.2,[3,5,11,22,33,43]],[39,17630,589.7,[1,2,5,9,14,18]]]],
  ["Mumbai", [[203,76338,1372.3,[4,8,20,39,58,77]],[75,30309,818.8,[2,4,8,16,23,31]],[44,16241,582.7,[1,2,5,9,13,17]]]],
  ["Chennai", [[82,20115,458.9,[2,3,6,11,16,21]],[28,7698,309.3,[1,1,2,4,6,8]],[13,5110,264.9,[1,1,2,3,4,6]]]],
  ["Kolkata", [[66,16991,232.4,[1,2,5,9,13,17]],[16,5619,96.5,[1,1,2,3,5,6]],[5,3681,68.3,[1,1,1,2,3,4]]]],
  ["Pune", [[42,17964,359.8,[1,2,5,9,14,18]],[14,4578,186.5,[1,1,2,3,4,5]],[6,2977,159.5,[1,1,1,2,3,3]]]],
];
const slash = (vals, decimals=false) => vals.map(v => decimals ? Number(v).toLocaleString("en-IN", {minimumFractionDigits:1, maximumFractionDigits:1}) : Number(v).toLocaleString("en-IN")).join(" / ");
const matrix = cities.map(([city, s]) => [
  city,
  slash(s.map(x=>x[0])),
  slash(s.map(x=>x[1])),
  slash(s.map(x=>x[2]), true),
  ...[0,1,2,3,4,5].map(i => slash(s.map(x=>x[3][i]))),
]);
const totals = [0,1,2].map(k => ({
  schools: cities.reduce((a,[,s])=>a+s[k][0],0),
  students: cities.reduce((a,[,s])=>a+s[k][1],0),
  market: cities.reduce((a,[,s])=>a+s[k][2],0),
  camps: [0,1,2,3,4,5].map(i=>cities.reduce((a,[,s])=>a+s[k][3][i],0)),
}));
matrix.push([
  "TOTAL",
  slash(totals.map(x=>x.schools)),
  slash(totals.map(x=>x.students)),
  slash(totals.map(x=>x.market), true),
  ...[0,1,2,3,4,5].map(i=>slash(totals.map(x=>x.camps[i]))),
]);

const wb = Workbook.create();
const ws = wb.worksheets.add("Scenario Matrix");
ws.showGridLines = false;
ws.mergeCells("A1:J1");
ws.getRange("A1").values = [["Fee-Threshold Market & Campus Expansion Matrix"]];
ws.mergeCells("A2:J2");
ws.getRange("A2").values = [["Scenario order in every slash-separated cell: Fee ≥ ₹1.0L  /  Fee ≥ ₹1.6L  /  Fee ≥ ₹2.0L"]];
ws.mergeCells("A3:J3");
ws.getRange("A3").values = [["Campus capacity: 200 students  |  Occupancy: 100%  |  Effective capacity: 200 students  |  Maximum penetration: 20%"]];
ws.mergeCells("A4:J4");
ws.getRange("A4").values = [["Students are Grades 2–9. Tuition market is INR crore and uses annual fee midpoint × enrollment. Campus requirements are rounded up city-wise."]];

const headers = [["City","Schools\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Students\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Annual tuition market (₹ Cr)\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 1%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 2%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 5%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 10%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 15%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L","Campuses @ 20%\n≥₹1.0L / ≥₹1.6L / ≥₹2.0L"]];
ws.getRange("A6:J6").values = headers;
ws.getRange(`A7:J${6+matrix.length}`).values = matrix;
ws.freezePanes.freezeRows(6);
ws.freezePanes.freezeColumns(1);

ws.getRange("A1:J1").format = {fill:"#102A43",font:{bold:true,color:"#FFFFFF",size:20},verticalAlignment:"center"};
ws.getRange("A2:J2").format = {fill:"#DCEEF2",font:{bold:true,color:"#102A43",size:11},verticalAlignment:"center"};
ws.getRange("A3:J3").format = {fill:"#EDF5F7",font:{bold:true,color:"#176B87",size:11},verticalAlignment:"center"};
ws.getRange("A4:J4").format = {fill:"#F7FAFC",font:{italic:true,color:"#52606D",size:10},verticalAlignment:"center"};
ws.getRange("A6:J6").format = {fill:"#176B87",font:{bold:true,color:"#FFFFFF",size:10},wrapText:true,horizontalAlignment:"center",verticalAlignment:"center",borders:{preset:"all",style:"thin",color:"#B7C9D3"}};
ws.getRange(`A7:J${5+matrix.length}`).format = {font:{color:"#102A43",size:10},horizontalAlignment:"center",verticalAlignment:"center",borders:{preset:"inside",style:"thin",color:"#D6E1E8"}};
ws.getRange(`A7:A${6+matrix.length}`).format = {font:{bold:true,color:"#102A43"},horizontalAlignment:"left"};
ws.getRange(`A${6+matrix.length}:J${6+matrix.length}`).format = {fill:"#FBF4E4",font:{bold:true,color:"#102A43"},borders:{preset:"doubleBottom",style:"medium",color:"#D9A441"}};

for (let r=7; r<6+matrix.length; r++) if (r%2===0) ws.getRange(`A${r}:J${r}`).format.fill="#F7FAFC";
ws.getRange("A1:J1").format.rowHeight = 38;
ws.getRange("A2:J4").format.rowHeight = 26;
ws.getRange("A6:J6").format.rowHeight = 58;
ws.getRange(`A7:J${6+matrix.length}`).format.rowHeight = 28;
ws.getRange(`A${6+matrix.length}:J${6+matrix.length}`).format.rowHeight = 34;
const widths=[18,29,31,35,24,24,24,24,24,24];
for(let i=0;i<10;i++) ws.getRangeByIndexes(0,i,6+matrix.length,1).format.columnWidth=widths[i];

await fs.mkdir(outDir,{recursive:true});
const preview=await wb.render({sheetName:"Scenario Matrix",range:`A1:J${6+matrix.length}`,scale:1.5,format:"png"});
await fs.writeFile(previewFile,new Uint8Array(await preview.arrayBuffer()));
const exported=await SpreadsheetFile.exportXlsx(wb);await exported.save(outFile);
const inspection=await wb.inspect({kind:"table",range:`Scenario Matrix!A1:J${6+matrix.length}`,include:"values,formulas",tableMaxRows:15,tableMaxCols:10,maxChars:6000});
console.log(inspection.ndjson);
const errors=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",options:{useRegex:true,maxResults:50},summary:"formula errors"});
console.log(errors.ndjson);
console.log(outFile);

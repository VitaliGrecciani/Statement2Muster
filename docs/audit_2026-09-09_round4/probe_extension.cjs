// Synthetic source-function tests; no browser profile or network changes.
const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'extension/app.js'),'utf8');
const lib=require(path.join(root,'extension/lib/pdf.min.js'));
const ctx={console,Blob,Uint8Array,pdfjsLib:lib,chrome:{runtime:{getURL:p=>path.join(root,'extension',p)}}};
vm.createContext(ctx);
vm.runInContext(source.substring(source.indexOf('function normalizeDate('),source.indexOf('async function readFileAsText(')),ctx);
(async()=>{
const out={pdfjs_version:lib.version};
out.year_boundary=ctx.parsePdfTextClientSide('American Express\nDatum 07.01.2026\n31.12 02.01 SYNTHETIC SHOP 10,00','synthetic.pdf');
out.invalid_date=ctx.normalizeDate('31.02.2026');
out.csv_quoted_semicolon=ctx.parseCsvClientSide('Date;Description;Amount;Currency\n02.06.2026;"SHOP;Branch";-12.34;USD','synthetic.csv');
let handler,opened=0;
vm.runInNewContext(fs.readFileSync(path.join(root,'extension_firefox_build/background.js'),'utf8'),{browser:{action:{onClicked:{addListener:f=>handler=f}},sidebarAction:{open:()=>{opened++;return Promise.resolve();}}},console});
handler();out.firefox_mock_action_open_calls=opened;
const pdfPath=String.raw`C:\Users\zorik\.codex\visualizations\2026\09\08\01a082d5-c032-7da0-a03d-7528ec41ddff\statement2muster-audit\synthetic-amex.pdf`;
if(fs.existsSync(pdfPath)){
 fs.copyFileSync(pdfPath,path.join(__dirname,'synthetic-amex.pdf'));
 const flat=await ctx.extractTextFromPdf(new Uint8Array(fs.readFileSync(pdfPath)));
 out.pdf_extraction={text:flat,result:ctx.parsePdfTextClientSide(flat,'synthetic.pdf')};
}
fs.writeFileSync(path.join(__dirname,'extension-results.json'),JSON.stringify(out,null,2));
console.log(JSON.stringify(out,null,2));
})().catch(e=>{console.error(e);process.exitCode=1});

// Execute actual source functions with minimal DOM/storage doubles, no browser profile.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'../..'),src=fs.readFileSync(path.join(root,'extension/app.js'),'utf8');
const out={},noop=()=>{},view={classList:{add:noop,remove:noop}};
const ctx={console,parsedTransactions:[],renderTableRows:noop,previewCount:{},previewTotal:{},searchInput:null,uploadView:view,previewView:view,historyView:view,showStatus:noop};
vm.createContext(ctx);
vm.runInContext(src.substring(src.indexOf('function displayPreview('),src.indexOf('function applyFilters(')),ctx);
const backendResults=JSON.parse(fs.readFileSync(path.join(__dirname,'results.json'),'utf8'));
out.datev_preview=ctx.displayPreview(backendResults.mixed_years.export_excerpt);
out.datev_first_parsed_row=ctx.parsedTransactions[0];
let callback;
const state={statementHistory:['Synthetic'],lastConvertedCsv:'Synthetic',lastConvertedFilename:'Synthetic.csv',lastAccountsFound:['Synthetic'],lastDuplicatesCount:0};
const clearCtx={btnClearHistory:{addEventListener:(_,fn)=>callback=fn},chrome:{storage:{local:{set:(values,cb)=>{Object.assign(state,values);cb();},remove:(keys,cb)=>{keys.forEach(k=>delete state[k]);cb();}}}},currentCsvText:'Synthetic',currentCsvBlob:{},currentCsvFilename:'Synthetic.csv',parsedTransactions:[{text:'Synthetic retained transaction'}],renderHistoryView:noop,showStatus:noop,setTimeout:noop,hideStatus:noop};
vm.createContext(clearCtx);
vm.runInContext(src.substring(src.indexOf("btnClearHistory.addEventListener("),src.indexOf('// Pro Upgrade Promo action')),clearCtx);
try{callback();out.clear_error=null;}catch(e){out.clear_error=e.toString();}
out.storage_after_clear=state;out.transactions_retained=clearCtx.parsedTransactions.length;
fs.writeFileSync(path.join(__dirname,'ui-results.json'),JSON.stringify(out,null,2));console.log(JSON.stringify(out,null,2));

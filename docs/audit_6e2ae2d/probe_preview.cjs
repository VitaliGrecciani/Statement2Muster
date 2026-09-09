const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'../..');
const src=fs.readFileSync(path.join(root,'extension/app.js'),'utf8');
const noop=()=>{},view={classList:{add:noop,remove:noop}};
const ctx={console,parsedTransactions:[],renderTableRows:noop,previewCount:{},previewTotal:{},searchInput:null,uploadView:view,previewView:view,historyView:view,showStatus:noop};
vm.createContext(ctx);
vm.runInContext(src.substring(src.indexOf('function displayPreview('),src.indexOf('function applyFilters(')),ctx);
const out={};
for(const fmt of ['datev','bmd','muster_csv']){
 const csv=new TextDecoder('windows-1252').decode(fs.readFileSync(path.join(__dirname,`fixture-${fmt}.csv`)));
 out[fmt]={summary:ctx.displayPreview(csv),transactions:ctx.parsedTransactions};
}
fs.writeFileSync(path.join(__dirname,'preview-results.json'),JSON.stringify(out,null,2));console.log(JSON.stringify(out,null,2));

const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'../..');
(async()=>{
const result={};
for(const build of ['extension','extension_firefox_build']){
 const src=fs.readFileSync(path.join(root,build,'app.js'),'utf8');
 let headers;
 const ctx={FormData,apiBaseUrl:'http://synthetic.invalid',document:{querySelector:()=>({value:'json'})},chrome:{storage:{local:{get:async()=>({authToken:'synthetic-token'})},session:{get:async()=>({})}}},fetch:async(url,options)=>{headers=options.headers;return {ok:false,status:401,json:async()=>({detail:'synthetic stop'})}}};
 vm.createContext(ctx);
 vm.runInContext(src.substring(src.indexOf('async function processBackendConversion('),src.indexOf('async function processClientSideFiles(')),ctx);
 try{await ctx.processBackendConversion([])}catch(e){}
 result[build]={local_token_present:true,conversion_authorization_header:headers?.Authorization||null};
}
fs.writeFileSync(path.join(__dirname,'auth-ui-results.json'),JSON.stringify(result,null,2));console.log(result);
})();

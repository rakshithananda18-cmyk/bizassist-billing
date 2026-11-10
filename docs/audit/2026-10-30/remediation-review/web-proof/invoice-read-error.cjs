const fs=require('fs'),vm=require('vm')
const file='frontend-billing/src/components/payments/InvoicesListView.jsx'
const source=fs.readFileSync(file,'utf8')
const body=source.match(/\.catch\(\(err\) => \{([\s\S]*?)\}\)/)[1]
let rows=['prior'],loadError=false,error=null
try{vm.runInNewContext(`(function(err){${body}})(new Error('synthetic HTTP503'))`,{setRows:value=>{rows=value},setLoadError:value=>{loadError=value}})}catch(err){error=err.message}
const result={file,error,loadError,rows,expectedErrorStateReached:loadError===true}
fs.writeFileSync('scratch/remediation-web-read-errors-result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))

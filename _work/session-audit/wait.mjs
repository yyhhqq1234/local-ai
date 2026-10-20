const t0=Date.now();
for(;;){
  try{ const r=await fetch('http://127.0.0.1:1234/v1/models'); if(r.ok){console.log('ready in',((Date.now()-t0)/1000).toFixed(1)+'s'); break;} }catch{}
  if(Date.now()-t0>180000){console.log('timeout');process.exit(1);}
  await new Promise(r=>setTimeout(r,2000));
}

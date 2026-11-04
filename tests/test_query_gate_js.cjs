const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('src/query_gate.js','utf8');
function setup(overrides={},responses=[{code:200,data:{hasAccount:true}}],registration='single'){
 let clock=0,serial=0;const timers=new Map(),calls=[];
 const root={appendChild(e){e.isConnected=true;}};
 const context={document:{documentElement:root,addEventListener(){},createElement(){return {style:{},isConnected:false};}},
  performance:{timeOrigin:1,now:()=>clock},Date:{now:()=>clock},
  setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,at:clock+Math.max(0,delay)});return id;},
  clearTimeout(id){timers.delete(id)},setInterval(){return 0},clearInterval(){},
  addEventListener(){},api:{async queryBuy(params){calls.push({at:clock,code:params.fndInn});
   const value=responses[Math.min(calls.length-1,responses.length-1)];
   return typeof value==='function'?value():value;}}};
 context.window=context;
 vm.createContext(context);
 const config={token:'test',code:'TEST01',mode:'first_launch',startAt:1000,endAt:5000,
  maxAttempts:6,retryMinMs:50,retryMaxMs:250,leaseMs:15000,requestTimeoutMs:1000,...overrides};
 vm.runInContext(source.replace('__CONFIG__',JSON.stringify(config)),context);
 const register=registration==='multiple'?"Object.defineProperties({},{$apis:{get(){return api;},configurable:true}});":registration==='reflect'?"Reflect.defineProperty({},'$apis',{get(){return api;},configurable:true});":"Object.defineProperty({},'$apis',{get(){return api;},configurable:true});";
 vm.runInContext(register+"globalThis.result=undefined;globalThis.error=undefined;api.queryBuy({fndInn:'TEST01'}).then(r=>result=r,e=>error=String(e));",context);
 async function flush(){for(let i=0;i<20;i++)await Promise.resolve();}
 async function to(target){
  await flush();let safety=0;
  while(true){
   const due=[...timers.entries()].filter(([id,t])=>t.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];
   if(!due)break;if(++safety>2000)throw Error('timer loop');
   clock=due[1].at;timers.delete(due[0]);due[1].fn();await flush();
  }
  clock=target;await flush();
 }
 return {context,calls,to,state:()=>context.__cmbQueryGate};
}
const sold={code:200,data:{hasAccount:true,ppsTag:'E'}};
const good={code:200,data:{hasAccount:true,posQty:'3000'}};
test('holds first query, then consumes five sold-out results and releases genuine sixth unchanged',async()=>{
 const h=setup({},[sold,sold,sold,sold,sold,good]);
 await h.to(999);assert.equal(h.calls.length,0);assert.equal(h.state().installed,true);
 await h.to(1000);assert.equal(h.calls.length,6);assert.equal(h.context.result,good);
 assert.equal(h.state().attempts,6);assert.equal(h.state().quota,'3000');
 // Duplicate initialization must share the completed promise without sending.
 vm.runInContext("api.queryBuy({fndInn:'TEST01'})",h.context);await h.to(1001);assert.equal(h.calls.length,6);
});
test('five retries means six total requests and exhausted state',async()=>{
 const h=setup({},[sold]);await h.to(1000);assert.equal(h.calls.length,6);
 assert.equal(h.state().reason,'attempts_exhausted');assert.equal(h.context.error,undefined);
});
test('random delays are bounded and queries stop at irregular window',async()=>{
 const h=setup({mode:'redemption',endAt:2000},[sold]);await h.to(2001);
 assert.equal(h.state().reason,'window_expired');assert.ok(h.calls.length>1);
 for(let i=1;i<h.calls.length;i++){const gap=h.calls[i].at-h.calls[i-1].at;assert.ok(gap>=50&&gap<=250);}
 assert.ok(h.calls.every(c=>c.at<2000));
});
test('bank rejection is not retried as no quota',async()=>{
 const h=setup({},[{code:500,data:{hasAccount:true,ppsTag:'E'}}]);await h.to(1000);
 assert.equal(h.calls.length,1);assert.equal(h.state().reason,'query_rejected');
});
test('normal response may omit ppsTag, just as observed on 133045A',async()=>{
 const h=setup({},[good]);await h.to(1000);assert.equal(h.context.result,good);
});
test('wrong product never sends query',async()=>{
 const h=setup({code:'OTHER1'});await h.to(1000);assert.equal(h.calls.length,0);assert.equal(h.state().reason,'product_mismatch');
});
test('lease expiry before start never sends a request',async()=>{
 const h=setup({startAt:20000});await h.to(16000);assert.equal(h.calls.length,0);assert.equal(h.state().reason,'watcher_lost');
});
test('cancelled page never releases initial query',async()=>{
 const h=setup();h.state().cancel('test');await h.to(1000);assert.equal(h.calls.length,0);
});
test('timeout never overlaps a second query or releases a late response',async()=>{
 let resolve;const h=setup({},[()=>new Promise(r=>resolve=r)]);
 await h.to(2001);assert.equal(h.calls.length,1);assert.equal(h.state().reason,'query_failed');
 resolve(good);await h.to(2002);assert.equal(h.context.result,undefined);assert.equal(h.calls.length,1);
});
test('window expires while waiting for server: no late result reaches original page',async()=>{
 let resolve;const h=setup({mode:'redemption',endAt:1500},[()=>new Promise(r=>resolve=r)]);
 await h.to(1400);await h.to(1500);resolve(good);await h.to(1501);
 assert.equal(h.context.result,undefined);assert.equal(h.context.error,undefined);assert.equal(h.state().reason,'window_expired');assert.equal(h.calls.length,1);
});

test('Vue defineProperties and Reflect registration are intercepted before initial request',async()=>{
 for(const registration of ['multiple','reflect']){
  const h=setup({},[good],registration);await h.to(999);
  assert.equal(h.state().installed,true);assert.equal(h.calls.length,0);
  await h.to(1000);assert.equal(h.calls.length,1);assert.equal(h.context.result,good);
 }
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/risk_confirm.js','utf8');
async function run(options={}){
 const calls=[];let time=0;
 const success={code:200,data:{}};
 const api={async queryPreEntrust(){calls.push('precheck');return options.failed?{code:500}:success;},
  async getSellFeeInfo(){calls.push('risk_data');return success;},
  async querysuitableextern(){calls.push('suitability');return success;}};
 const view={fndInn:'TEST01',amount:'0.01',viewType:'A',isZzyAccount:!!options.funding,
  isNewProtocolCard:!!options.protocol,copyInputShow:false,$apis:api,
  $options:{name:'App'},$children:[],ordInfo:{},
  async $nextTick(){},
  async querySuitableExtern(){await api.querysuitableextern();},
  async preAmountExam(){calls.push('next');view.querySuitableExtern();
   const result=await api.queryPreEntrust();if(result.code!==200)return;
   view.copyInputShow=true;popup.getSellFeeInfo();},
  callPwd(){calls.push('password');},
  doBuy(){calls.push('submit');}};
 const input={$options:{name:'owl-transcription-popup'},$children:[],userInputText:'',sampleInputText:'original bank text',
  onTranscriptionPopupQuickInput(){calls.push('quick');this.userInputText=options.mismatch?'wrong':this.sampleInputText;},
  onTranscriptionPopupConfirm(){calls.push('validate');
   if(this.userInputText.trim()===this.sampleInputText){calls.push('trace_confirm');view.callPwd();}}};
 const popup={$options:{name:'CopyInputPopup'},$children:[input],
  async getSellFeeInfo(){await api.getSellFeeInfo();calls.push('risk_updated');}};
 view.$children=[popup];
 const context={window:null,document:{querySelector(){return {__vue__:view}},hidden:false},
  performance:{now:()=>time},setTimeout(fn,ms){return setTimeout(()=>{time+=ms;fn()},0);}};
 context.window=context;vm.createContext(context);
 const config={code:options.wrong?'OTHER':'TEST01',amount:'0.01',token:'test',timeoutMs:1000};
 const started=vm.runInContext(source.replace('__CONFIG__',JSON.stringify(config)),context);
 for(let i=0;i<100;i++){
  await new Promise(r=>setTimeout(r,1));
  const s=context.__cmbRiskConfirm;
  if(!started.started||s?.status==='password_requested'||s?.status==='stopped')break;
 }
 return {calls,context,started,view,api,input};
}
test('uses bank prechecks and original text validation exactly once, without submitting',async()=>{
 const h=await run();const s=h.context.__cmbRiskConfirm;
 assert.equal(s.status,'password_requested');assert.equal(s.passwordCalls,1);assert.equal(s.textMatches,true);
 assert.deepEqual(h.calls,['next','suitability','precheck','risk_data','risk_updated','quick','validate','trace_confirm','password']);
 assert.ok(!h.calls.includes('submit'));s.cleanup('test');
 assert.equal(h.view.callPwd.name,'callPwd');
});
test('failed bank precheck never confirms risk or opens password',async()=>{
 const h=await run({failed:true});assert.equal(h.context.__cmbRiskConfirm.status,'stopped');
 assert.ok(!h.calls.includes('quick'));assert.ok(!h.calls.includes('password'));
});
test('text mismatch never fabricates a successful confirmation',async()=>{
 const h=await run({mismatch:true});assert.equal(h.context.__cmbRiskConfirm.reason,'risk_text_mismatch');
 assert.ok(!h.calls.includes('validate'));assert.ok(!h.calls.includes('password'));
});
test('unsupported protocol or funding path stops before next',async()=>{
 for(const mode of ['protocol','funding']){const h=await run({[mode]:true});assert.equal(h.started.started,false);assert.equal(h.calls.length,0);}
});
test('wrong product stops without starting any bank precheck',async()=>{
 const h=await run({wrong:true});assert.equal(h.started.started,false);assert.equal(h.calls.length,0);
});

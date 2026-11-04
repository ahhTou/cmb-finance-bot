/* Preserve the bank prechecks, component validation, and confirmation trace. */
(config=>{
 const root=document.querySelector('#app')?.__vue__;
 let view,popup;
 (function walk(v,d){if(!v||d>20)return;
  if(v.ordInfo&&typeof v.preAmountExam==='function')view=v;
  if(v.$options.name==='CopyInputPopup')popup=v;
  (v.$children||[]).forEach(c=>walk(c,d+1));})(root,0);
 if(!view||!popup||view.fndInn!==config.code||Number(String(view.amount).replace(/,/g,''))!==Number(config.amount))
  return {started:false,reason:'product_or_amount_mismatch'};
 if(view.isZzyAccount||view.isNewProtocolCard)return {started:false,reason:'additional_confirmation_required'};
 if(view.viewType!=='A'||view.buyButtonDisabled||view.buyFeeLoading||view.copyInputShow)
  return {started:false,reason:'form_not_ready'};
 const state=window.__cmbRiskConfirm={token:config.token,status:'starting',events:[],passwordCalls:0};
 const began=performance.now(),saved=[];
 let lease=began+3000;
 state.keepAlive=token=>{if(token!==config.token)return false;lease=performance.now()+3000;return true;};
 function check(){if(cancelled)throw Error('cancelled');if(performance.now()>lease)throw Error('watcher_lost');if(performance.now()-began>config.timeoutMs)throw Error('deadline');if(document.hidden)throw Error('document_hidden');}
 function note(name){state.events.push({name,ms:Math.round(performance.now()-began)});}
 function replace(obj,key,fn){const original=obj[key];saved.push(()=>{if(obj[key]===fn)obj[key]=original;});obj[key]=fn;return original;}
 const api=view.$apis;
 let originalPwd=view.callPwd;
 replace(view,'callPwd',function(...args){
  check();
  if(++state.passwordCalls!==1)throw Error('duplicate_password_panel');
  note('password_handler');state.status='password_handler_called';
  return originalPwd.apply(this,args);
 });
 function observeAPI(key,field){
  if(typeof api[key]!=='function')return;
  const original=api[key];replace(api,key,async function(...args){
   const response=await original.apply(this,args);
   state[field]=response&&response.code===200;
   note(field+(state[field]?'_ok':'_failed'));
   return response;
  });
 }
 observeAPI('queryPreEntrust','precheck');
 observeAPI('getSellFeeInfo','riskData');
 observeAPI('querysuitableextern','suitabilityData');
 const originalSuitable=view.querySuitableExtern;
 replace(view,'querySuitableExtern',async function(...args){
  state.suitabilityStarted=true;
  const response=await originalSuitable.apply(this,args);
  state.suitabilityDone=true;note('suitability_done');return response;
 });
 const originalFee=popup.getSellFeeInfo;
 replace(popup,'getSellFeeInfo',async function(...args){
  const response=await originalFee.apply(this,args);
  state.riskRendered=true;note('risk_component_updated');return response;
 });
 let cancelled=false;
 state.cleanup=token=>{if(token!==config.token)return false;cancelled=true;for(const restore of saved.splice(0).reverse())restore();return true;};
 async function wait(check,label,timeout=config.timeoutMs){
  const end=performance.now()+timeout;
  while(performance.now()<end){
   check();
   if(state.precheck===false||state.riskData===false||state.suitabilityData===false)throw Error('bank_precheck_failed');
   if(check())return;
   if(view.protocolCardShow)throw Error('additional_protocol_confirmation');
   await new Promise(resolve=>setTimeout(resolve,20));
  }
  throw Error('timeout_'+label);
 }
 (async()=>{
  try{
   note('next_handler');view.preAmountExam();
   await wait(()=>view.copyInputShow&&state.precheck&&state.riskData&&state.riskRendered
     &&(!state.suitabilityStarted||state.suitabilityDone),'risk_ready');
   await view.$nextTick();
   let input;
   (function walk(v,d){if(!v||d>6)return;
    if(typeof v.onTranscriptionPopupQuickInput==='function'&&typeof v.onTranscriptionPopupConfirm==='function')input=v;
    (v.$children||[]).forEach(c=>walk(c,d+1));})(popup,0);
   if(!input)throw Error('risk_controls_missing');
   state.status='risk_confirming';note('risk_ready');
   check();input.onTranscriptionPopupQuickInput();note('quick_input');
   await view.$nextTick();
   state.textMatches=typeof input.sampleInputText==='string'&&input.sampleInputText.length>0
     &&String(input.userInputText||'').trim()===input.sampleInputText;
   if(!state.textMatches)throw Error('risk_text_mismatch');
   check();input.onTranscriptionPopupConfirm();note('risk_confirm');
   await wait(()=>state.passwordCalls===1||view.fastSellConfirmShow,'password_handler');
   if(view.fastSellConfirmShow)throw Error('additional_funding_confirmation');
   state.status='password_requested';
  }catch(error){state.status='stopped';state.reason=String(error.message);note('stopped');}
 })();
 return {started:true,token:config.token};
})(__CONFIG__)

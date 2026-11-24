import {Viewer, Display, Timer} from '/assets/js/three-cad-viewer.esm.js';
import {createPage} from '/assets/js/ocp-viewer-core/page.js';

const $ = id => document.getElementById(id);
const labels = {pending:'未確認',accepted:'採用',rejected:'除外'};
let state, scene, page, viewer, row=0, current, dirty=false, loading=false, sequence=0, ready=false;
let phase='contacts', simplifyRow=0, simplifyCurrent;
let activeSetId=null, facePicking=false, gesture=null, press=null;
function syncFacePicking(){if(page)page.handleMessage({type:'ui',config:{analysisTool:phase==='simplification'&&facePicking?'select':phase==='contacts'&&$('pick').value!=='off'?'select':'off',shapeFilter:'face'}});}
function editPickedFace(ref,remove){
  if((state.simplification?.protected_faces||[]).some(r=>refKey(r)===refKey(ref))){message('接合面は残す面に固定されています。',true);return;}
  if(ref[0]!==$('set-part').value){message('対象部品の面を選んでください。',true);return;}
  const option=Array.from($('set-members').options).find(o=>o.value===refKey(ref));
  if(option&&option.selected!==!remove){option.selected=!remove;markDirty();draw();}
}
const names={}, leaves={};
function message(text,error=false){$('message').textContent=text;$('message').dataset.error=error;}
async function api(path,data){
  const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-B2-Token':state.token},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw Error(result.error || response.statusText);return result;
}
function refKey(ref){return JSON.stringify(ref);}
function markDirty(){dirty=true;message('未保存の変更があります。保存してから候補を切り替えてください。');controls();}
function controls(){
  const accept=$('decision').value==='accepted';$('mode').disabled=!accept;$('target').disabled=!accept||$('mode').value!=='keep_gap';$('tolerance').disabled=!accept;$('save').disabled=loading||!ready||!current;
  $('simplify-stage').disabled=!state?.contacts_complete||loading||!ready;
  $('contacts-stage').disabled=loading||!ready;
  $('candidate').disabled=loading;$('simplify-candidate').disabled=loading;
  $('simplify-decision').disabled=loading||!$('set-members').selectedOptions.length;
  $('simplify-notes').disabled=loading;
  $('simplify-save').disabled=loading||!state?.simplification||!$('set-members').selectedOptions.length;
  for(const id of ['set-picker','set-part','set-name','set-members','set-policy','set-policy-notes','select-faces','clear-faces'])$(id).disabled=loading;
  $('set-name').disabled=loading||['keep','omit'].includes($('simplify-decision').value);
  $('set-delete').disabled=loading||!activeSetId;
  $('approximation-panel').hidden=$('simplify-decision').value!=='simplify';
  const members=Array.from($('set-members').selectedOptions,o=>JSON.parse(o.value));
  $('set-summary').textContent=`選択中 ${members.length} 面${members.length?'：'+members.map(ref=>`${names[ref[0]]} 面${ref[1]}`).join('、'):''}`;
  const record=state?.simplification;
  $('simplify-finish').disabled=loading||!record||record.proposals.some(r=>r.decision==='pending')||dirty;
  $('simplify-start').disabled=loading||!state?.contacts_complete;
}
function stageStatus(){
  const text=!state.contacts_complete?'接合面レビューを全件保存すると簡略化レビューへ進めます。':state.simplification_status==='stale'?'接合面が変更されました。簡略化の削除提案を作り直してください。':state.simplification_status==='confirmed'?'接合面・簡略化レビューとも完了しています。':state.simplification?'接合面を保護して、削除提案をレビューしてください。':'接合面レビュー完了。次に簡略化の削除提案を作成してください。';
  $('stage-status').textContent=text;controls();
}
function viewRefs(){return phase==='contacts'?(current?.faces||[]):Array.from($('set-members').selectedOptions,o=>JSON.parse(o.value));}
function fillList(){
  $('candidate').replaceChildren(...state.draft.reviews.map((r,i)=>{
    const refs=r.faces.map(f=>names[f[0]] || f[0]);const option=new Option(`${i+1} · ${labels[r.decision]} · ${refs.join(' / ')}`,i);return option;
  }));$('candidate').value=row;
  $('progress').textContent=`${state.draft.reviews.filter(r=>r.decision==='pending').length} / ${state.draft.reviews.length} 件が未確認`;
}
function textRefs(){ $('refs').textContent=current.faces.map((f,i)=>`${i+1}面目: ${names[f[0]]} · 配置 ${f[0]} · BREP面 ${f[1]}`).join('\n');$('refs').style.whiteSpace='pre-wrap'; }
function metrics(m){
  $('metrics').textContent=m?`${m.contact_type==='cylindrical'?'円筒接合':'平面接合'} · OCCT再計測\n隙間 ${m.gap_mm.toPrecision(7)} mm\n重なり ${m.overlap_mm2.toFixed(4)} mm²${m.contact_type==='cylindrical'?'\n面積は小さい半径側を基準':''}`:'重なりなし、または対応外の面ペアです。採用できません。';
}
async function measure(){const request=++sequence;$('metrics').textContent='OCCTで面ペアを計測中…';try{const result=await api('/api/measure',{faces:current.faces});if(request===sequence)metrics(result.measurement);}catch(e){if(request===sequence)message(e.message,true);}}
function draw(){
  if(!ready)return;
  const refs=viewRefs();
  const highlighted=new Set(refs.map(refKey));
  const protectedFaces=new Set((state.simplification?.protected_faces||[]).map(refKey));
  const proposals=new Map((state.simplification?.proposals||[]).map(r=>[refKey(r.face),r.decision]));
  const setColors=new Map();
  const palette=['#8961c6','#b87925','#488943','#a45591','#397b92'];
  let approximationIndex=0;
  for(const group of state.simplification?.sets||[])if(group.decision==='simplify'){
    const color=palette[approximationIndex++%palette.length];
    for(const ref of group.faces)setColors.set(refKey(ref),color);
  }
  for(const group of state.simplification?.sets||[])for(const ref of group.faces)proposals.set(refKey(ref),group.decision);
  let changed=false;
  for(const [path,ref] of Object.entries(scene.face_map)){
    const key=refKey(ref);
    let color='#9eacbf';
    if(phase==='simplification'){
      if(protectedFaces.has(key))color='#16857b';
      else if(proposals.has(key))color={pending:'#e16a86',keep:'#4a85c4',simplify:'#8961c6',omit:'#d54848'}[proposals.get(key)];
      if(setColors.has(key)&&!protectedFaces.has(key))color=setColors.get(key);
    }
    if(highlighted.has(key)&&!protectedFaces.has(key))color='#ff8c00';
    if(leaves[path].color!==color){leaves[path].color=color;changed=true;}
  }
  if(changed){
    const camera=viewer.getCameraLocationSettings();
    scene.model.config.reset_camera='keep';
    page.handleMessage(scene.model);
    viewer.setCameraLocationSettings(camera.position,camera.quaternion,camera.target,camera.zoom,false);
  }
  syncFacePicking();
  const mode=$('isolate').value;
  const ids= mode==='all'?null:phase==='simplification'?[$('set-part').value]:!refs.length?null: mode==='pair'||phase==='simplification'?refs.map(f=>f[0]):[refs[mode==='first'?0:1][0]];
  viewer.setStates(Object.fromEntries(Object.entries(scene.face_map).map(([path,ref])=>[path,!ids||ids.includes(ref[0])?[1,1]:[0,0]])));
  clip();
}
function clip(){
  if(!ready)return;
  const bb=scene.model.data.shapes.bb;
  const sizes=['x','y','z'].map(a=>bb[a+'max']-bb[a+'min']);
  for(let i=0;i<3;i++){const normal=[0,0,0];normal[i]=-1;viewer.setClipNormal(i,normal,null,false);}
  if($('clipaxis').value!=='off'){
    const i=Number($('clipaxis').value);
    viewer.setClipSlider(i,sizes[i]*(Number($('clip').value)/100-.5),true);
  }
  viewer.setLocalClipping($('clipaxis').value!=='off');
}
function fitVisible(){
  if(!ready)return;
  const refs=viewRefs();
  const mode=$('isolate').value;
  const ids=mode==='all'?Object.keys(scene.part_bounds):phase==='simplification'?[$('set-part').value]:!refs.length?Object.keys(scene.part_bounds):mode==='pair'||phase==='simplification'?refs.map(f=>f[0]):[refs[mode==='first'?0:1][0]];
  const boxes=ids.map(id=>scene.part_bounds[id]);
  const low=[0,1,2].map(i=>Math.min(...boxes.map(b=>b[i]))),high=[0,1,2].map(i=>Math.max(...boxes.map(b=>b[i+3])));
  const target=low.map((v,i)=>(v+high[i])/2),camera=viewer.getCameraLocationSettings();
  const position=camera.position.map((v,i)=>v+target[i]-camera.target[i]);
  const bb=scene.model.data.shapes.bb;
  const globalSize=Math.hypot(...['x','y','z'].map(a=>bb[a+'max']-bb[a+'min']));
  viewer.setCameraLocationSettings(position,camera.quaternion,target,.8*globalSize/Math.hypot(...low.map((v,i)=>high[i]-v)),false);
}
function loadRow(){
  if(!state.draft.reviews[row])return;
  current=structuredClone(state.draft.reviews[row]);
  $('decision').value=current.decision;$('mode').value=current.condition?.mode || 'close';
  $('target').value=current.condition?.target_gap_mm || 0;$('tolerance').value=current.condition?.tolerance_mm || 0;
  $('notes').value=state.draft.simplification_notes;$('pick').value='off';dirty=false;
  textRefs();draw();measure();controls();message('保存済みの面と判断を表示しています。');
  if(current.faces.some(ref=>scene.unrendered_faces.some(missing=>refKey(ref)===refKey(missing))))message('この候補には描画できない面があります。採用は保存できません。',true);
  if(page)page.handleMessage({type:'ui',config:{analysisTool:'off'}});
}
function selected(status){
  if(!ready||!status.selected)return;
  if(phase==='simplification'&&(!facePicking||!gesture||gesture.consumed))return;
  if(phase==='contacts'&&(!current||$('pick').value==='off'))return;
  const refs=[];
  for(const [key,ids] of Object.entries(status.selected)){
    // Each rendered leaf is one BREP face. Accept only a Face selection on a
    // known leaf; never reinterpret the viewer's element number as a BREP ID.
    const path=key.replace(/\/faces?$/i,'');
    if(!/\/faces?$/i.test(key)||!ids.length||!scene.face_map[path])continue;
    refs.push(scene.face_map[path]);
  }
  if(refs.length!==1)return;
  if(phase==='simplification'){const remove=gesture.remove;gesture.consumed=true;queueMicrotask(()=>{viewer.clearSelection();editPickedFace(refs[0],remove);});return;}
  const side=Number($('pick').value),ref=refs[0];
  if(ref[0]===current.faces[1-side][0]){message('異なる部品の面を選んでください。',true);return;}
  current.faces[side]=ref;current.decision='pending';current.condition=null;$('decision').value='pending';
  $('pick').value='off';page.handleMessage({type:'ui',config:{analysisTool:'off'}});
  textRefs();draw();measure();markDirty();
}
$('candidate').onchange=()=>{if(dirty){$('candidate').value=row;message('現在の変更を保存するか、戻してから切り替えてください。',true);return;}row=Number($('candidate').value);loadRow();};
for(const id of ['decision','mode','target','tolerance','notes'])$(id).addEventListener('input',markDirty);
$('revert').onclick=()=>loadRow();$('isolate').onchange=draw;$('clipaxis').onchange=clip;$('clip').oninput=clip;
$('pick').onchange=()=>page.handleMessage({type:'ui',config:{analysisTool:$('pick').value==='off'?'off':'select',shapeFilter:'face'}});
$('fit').onclick=fitVisible;
$('save').onclick=async()=>{
  try{loading=true;controls();const decision=$('decision').value;
    const mode=$('mode').value;
    const item={candidate_id:current.candidate_id,faces:current.faces,decision,condition:decision==='accepted'?{mode,target_gap_mm:mode==='close'?0:Number($('target').value),tolerance_mm:Number($('tolerance').value)}:null};
    state=await api('/api/save',{revision:state.revision,item,simplification_notes:$('notes').value});fillList();loadRow();stageStatus();message('接合面レビューをファイルに保存しました。');
  }catch(e){message(e.message,true);}finally{loading=false;controls();}
};
function loadSetForm(group=null){
  activeSetId=group?.id||null;
  const record=state.simplification, groups=record?.sets||[];
  $('set-picker').replaceChildren(new Option('新しいセット',''),...groups.map(g=>new Option(`${names[g.faces[0][0]]} · ${g.name}`,g.id)));
  $('set-picker').value=activeSetId||'';
  $('set-part').replaceChildren(...Object.keys(scene.part_bounds).map(id=>new Option(`${names[id]} · ${id}`,id)));
  const part=group?.faces[0][0]||simplifyCurrent?.face[0]||Object.keys(scene.part_bounds)[0];
  $('set-part').value=part;
  $('set-name').value=group?.name||`${names[part]}_セット`;
  fillSetMembers(group?.faces||(simplifyCurrent?[simplifyCurrent.face]:[]));
  $('simplify-decision').value=group?.decision||simplifyCurrent?.decision||'pending';
  $('set-policy').value=group?.approximation?.policy||'unspecified';
  $('set-policy-notes').value=group?.approximation?.notes||'';
  controls();
}
function fillSetMembers(selected=[]){
  const record=state.simplification,part=$('set-part').value;
  const protectedFaces=new Set((record?.protected_faces||[]).map(refKey));
  const otherOwners=new Set((record?.sets||[]).filter(g=>g.id!==activeSetId).flatMap(g=>g.faces.map(refKey)));
  const refs=Array.from(new Map(Object.values(scene.face_map).map(ref=>[refKey(ref),ref])).values()).filter(ref=>ref[0]===part&&!protectedFaces.has(refKey(ref))).sort((a,b)=>a[1]-b[1]);
  const selectedKeys=new Set(selected.map(refKey));
  $('set-members').replaceChildren(...refs.map(ref=>{const o=new Option(`面 ${ref[1]}${otherOwners.has(refKey(ref))?'（保存時に移動）':''}`,refKey(ref));o.selected=selectedKeys.has(o.value);return o;}));
}
function loadSimplification(selectedSetId=null){
  const record=state.simplification;
  $('simplify-start-panel').hidden=!!record;$('simplify-review-panel').hidden=!record;
  if(!record){simplifyCurrent=undefined;activeSetId=null;$('set-members').replaceChildren();draw();controls();return;}
  simplifyRow=Math.min(simplifyRow,Math.max(0,record.proposals.length-1));
  const labels={pending:'未確認',keep:'残す',simplify:'簡略化して残す',omit:'省略する'};
  const chosen=(record.sets||[]).find(g=>g.id===selectedSetId);
  if(chosen){const first=record.proposals.findIndex(r=>chosen.faces.some(ref=>refKey(ref)===refKey(r.face)));if(first>=0)simplifyRow=first;}
  $('simplify-candidate').replaceChildren(...record.proposals.map((r,i)=>new Option(`${r.id} · ${labels[r.decision]} · ${names[r.face[0]]} 面${r.face[1]}`,i)));
  $('simplify-candidate').value=simplifyRow;
  const pending=record.proposals.filter(r=>r.decision==='pending').length;
  $('simplify-progress').textContent=`自動提案 ${record.proposals.length} 面 / 未確認 ${pending} 面 / セット ${(record.sets||[]).length} 組 / 保護する接合面 ${record.protected_faces.length} 面${record.confirmed?' · 確定済み':''}`;
  simplifyCurrent=record.proposals[simplifyRow]?structuredClone(record.proposals[simplifyRow]):undefined;
  $('simplify-notes').value=record.notes;
  $('simplify-decision').disabled=!simplifyCurrent;
  if(simplifyCurrent){
    const m=simplifyCurrent.measurement;
    const size=m.surface_type==='planar'?`面内幅 ${m.planar_spans_mm.map(v=>v.toFixed(4)).join(' × ')} mm`:`円筒径 ${m.diameter_mm.toFixed(4)} mm / 軸方向幅 ${m.axial_span_mm.toFixed(4)} mm`;
    $('simplify-metrics').textContent=`${simplifyCurrent.reasons.join('\n')}\n${size}\n面積 ${m.area_mm2.toFixed(4)} mm²\n必要な開口・内壁は残してください。`;
    $('simplify-refs').textContent=`${names[simplifyCurrent.face[0]]} · 配置 ${simplifyCurrent.face[0]} · BREP面 ${simplifyCurrent.face[1]}`;
    $('simplify-decision').value=simplifyCurrent.decision;
  }else{
    $('simplify-metrics').textContent='削除提案はありません。すべての面を残す方針を確認して確定してください。';$('simplify-refs').textContent='';
  }
  const group=chosen||(record.sets||[]).find(g=>simplifyCurrent&&g.faces.some(ref=>refKey(ref)===refKey(simplifyCurrent.face)));
  loadSetForm(group);dirty=false;draw();controls();
  if(simplifyCurrent&&scene.unrendered_faces.some(ref=>refKey(ref)===refKey(simplifyCurrent.face)))message('描画できない面です。この画面で省略の判断は保存できません。',true);
}
function switchPhase(next){
  if(dirty){message('未保存の変更を保存するか、戻してから工程を切り替えてください。',true);return;}
  if(next==='simplification'&&!state.contacts_complete){message('接合面レビューを先に完了してください。',true);return;}
  phase=next;$('contact-panel').hidden=phase!=='contacts';$('simplify-panel').hidden=phase!=='simplification';
  $('contacts-stage').setAttribute('aria-pressed',String(phase==='contacts'));$('simplify-stage').setAttribute('aria-pressed',String(phase==='simplification'));
  $('pick').value='off';$('pick').disabled=phase!=='contacts';$('isolate').value='pair';
  for(const option of $('isolate').options)if(['first','second'].includes(option.value))option.disabled=phase!=='contacts';
  page.handleMessage({type:'ui',config:{analysisTool:'off'}});message('');
  if(phase==='contacts')loadRow();else loadSimplification();stageStatus();fitVisible();
}
const simplifyRequest=()=>({revision:state.revision,simplification_revision:state.simplification_revision});
$('contacts-stage').onclick=()=>switchPhase('contacts');$('simplify-stage').onclick=()=>switchPhase('simplification');
$('simplify-start').onclick=async()=>{
  try{loading=true;controls();state=await api('/api/simplification/start',{...simplifyRequest(),threshold_mm:Number($('threshold').value)});loadSimplification();stageStatus();message('接合面を保護して削除提案を作成しました。');}
  catch(e){message(e.message,true);}finally{loading=false;controls();}
};
$('simplify-candidate').onchange=()=>{if(dirty){$('simplify-candidate').value=simplifyRow;message('現在の簡略化判断を保存するか、戻してください。',true);return;}simplifyRow=Number($('simplify-candidate').value);loadSimplification();};
for(const id of ['simplify-decision','simplify-notes','set-name','set-policy','set-policy-notes'])$(id).addEventListener('input',markDirty);
$('set-members').onchange=()=>{markDirty();draw();};
$('select-faces').onclick=()=>{facePicking=!facePicking;$('select-faces').setAttribute('aria-pressed',String(facePicking));syncFacePicking();};
$('clear-faces').onclick=()=>{for(const option of $('set-members').options)option.selected=false;markDirty();draw();};
$('set-picker').onchange=()=>{
  if(dirty){$('set-picker').value=activeSetId||'';message('セットの変更を保存するか、戻してください。',true);return;}
  const group=(state.simplification.sets||[]).find(g=>g.id===$('set-picker').value);
  loadSetForm(group);draw();
};
$('set-part').onchange=()=>{
  const part=$('set-part').value;activeSetId=null;$('set-picker').value='';$('set-name').value=`${names[part]}_セット`;fillSetMembers();markDirty();draw();
};
$('simplify-revert').onclick=()=>{loadSimplification();message('保存済みの簡略化判断に戻しました。');};
$('simplify-save').onclick=async()=>{
  const faces=viewRefs();if(!faces.length)return;
  try{loading=true;controls();const decision=$('simplify-decision').value;
    const approximation=decision==='simplify'?{policy:$('set-policy').value,notes:$('set-policy-notes').value,detail_policy:'omit_chamfers_and_fillets'}:null;
    const group={id:activeSetId,name:$('set-name').value,faces,decision,approximation};
    state=await api('/api/simplification/set/save',{...simplifyRequest(),set:group,notes:$('simplify-notes').value});
    const saved=state.saved_set_id;loadSimplification(saved);stageStatus();message('簡略化セットを保存しました。');}
  catch(e){message(e.message,true);}finally{loading=false;controls();}
};
$('set-delete').onclick=async()=>{
  if(dirty){message('未保存の変更を戻してからセットを解除してください。',true);return;}
  try{loading=true;controls();state=await api('/api/simplification/set/delete',{...simplifyRequest(),id:activeSetId});loadSimplification();stageStatus();message('セットを解除しました。対象の自動提案を再確認してください。');}
  catch(e){message(e.message,true);}finally{loading=false;controls();}
};
$('simplify-finish').onclick=async()=>{
  try{loading=true;controls();state=await api('/api/simplification/finish',{...simplifyRequest(),notes:$('simplify-notes').value});loadSimplification();stageStatus();message('簡略化レビューを確定しました。B3への出力は専用CLIで行います。');}
  catch(e){message(e.message,true);}finally{loading=false;controls();}
};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
try{
  [state,scene]=await Promise.all([api('/api/state'),api('/api/scene')]);
  for(const node of state.nodes)names[node.id]=node.definition_name || node.name;
  function walk(node){if(node.parts)node.parts.forEach(walk);else{leaves[node.id]=node;}}
  walk(scene.model.data.shapes);
  const container=$('viewport');
  container.addEventListener('mousedown',event=>{press=event.button===0&&event.target.tagName==='CANVAS'?{x:event.clientX,y:event.clientY}:null;},true);
  container.addEventListener('mouseup',event=>{
    gesture=press&&event.button===0&&Math.hypot(event.clientX-press.x,event.clientY-press.y)<=4?{remove:event.shiftKey,consumed:false}:null;
    press=null;const currentGesture=gesture;setTimeout(()=>{if(gesture===currentGesture)gesture=null;},0);
  },true);
  class ReviewViewer extends Viewer{constructor(...args){super(...args);viewer=this;}}
  page=createPage({Viewer:ReviewViewer,Display,Timer,container,listen:false,theme:'light',getSize:()=>({width:container.clientWidth,height:container.clientHeight}),overrides:{display:{theme:'light',glass:true,tools:true,treeWidth:200,externalMeasurementBackend:false},viewer:{control:'trackball',up:'Z',tools:true,glass:true}},send:(type,status)=>{if(type==='status')selected(status);}});
  page.handleMessage(scene.model);ready=true;fillList();stageStatus();
  if(scene.unrendered_faces.length)$('renderwarning').textContent=`描画対象外の面 ${scene.unrendered_faces.length} 件: ${scene.unrendered_faces.map(f=>`${names[f[0]]} 面${f[1]}`).join('、')}。該当面を含む候補はこの画面では採用できません。`;
  if(state.draft.reviews.length){loadRow();fitVisible();}else{message('接合候補はありません。');$('save').disabled=true;}
  window.addEventListener('resize',()=>page.resize());
}catch(e){message(e.message,true);console.error(e);}

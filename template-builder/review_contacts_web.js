import {Viewer, Display, Timer} from '/assets/js/three-cad-viewer.esm.js';
import {createPage} from '/assets/js/ocp-viewer-core/page.js';

const $ = id => document.getElementById(id);
const labels = {pending:'未確認',accepted:'採用',rejected:'除外'};
let state, scene, page, viewer, row=0, current, dirty=false, loading=false, sequence=0, ready=false;
const names={}, leaves={};
function message(text,error=false){$('message').textContent=text;$('message').dataset.error=error;}
async function api(path,data){
  const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-B2-Token':state.token},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw Error(result.error || response.statusText);return result;
}
function refKey(ref){return JSON.stringify(ref);}
function markDirty(){dirty=true;message('未保存の変更があります。保存してから候補を切り替えてください。');controls();}
function controls(){const accept=$('decision').value==='accepted';$('mode').disabled=!accept;$('target').disabled=!accept||$('mode').value!=='keep_gap';$('tolerance').disabled=!accept;$('save').disabled=loading||!ready||!current;}
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
  if(!ready||!current)return;
  const highlighted=new Set(current.faces.map(refKey));
  let changed=false;
  for(const [path,ref] of Object.entries(scene.face_map)){
    const color=highlighted.has(refKey(ref))?'#ff8c00':'#9eacbf';
    if(leaves[path].color!==color){leaves[path].color=color;changed=true;}
  }
  if(changed){
    const camera=viewer.getCameraLocationSettings();
    scene.model.config.reset_camera='keep';
    page.handleMessage(scene.model);
    viewer.setCameraLocationSettings(camera.position,camera.quaternion,camera.target,camera.zoom,false);
  }
  const mode=$('isolate').value;
  const ids= mode==='all'?null: mode==='pair'?current.faces.map(f=>f[0]):[current.faces[mode==='first'?0:1][0]];
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
  if(!ready||!current)return;
  const mode=$('isolate').value;
  const ids=mode==='all'?Object.keys(scene.part_bounds):mode==='pair'?current.faces.map(f=>f[0]):[current.faces[mode==='first'?0:1][0]];
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
  if(!ready||!current||$('pick').value==='off'||!status.selected)return;
  const refs=[];
  for(const [key,ids] of Object.entries(status.selected)){
    // Each rendered leaf is one BREP face. Accept only a Face selection on a
    // known leaf; never reinterpret the viewer's element number as a BREP ID.
    const path=key.replace(/\/faces?$/i,'');
    if(!/\/faces?$/i.test(key)||!ids.length||!scene.face_map[path])continue;
    refs.push(scene.face_map[path]);
  }
  if(refs.length!==1)return;
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
    state=await api('/api/save',{revision:state.revision,item,simplification_notes:$('notes').value});fillList();loadRow();message('レビューをファイルに保存しました。');
  }catch(e){message(e.message,true);}finally{loading=false;controls();}
};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
try{
  [state,scene]=await Promise.all([api('/api/state'),api('/api/scene')]);
  for(const node of state.nodes)names[node.id]=node.definition_name || node.name;
  function walk(node){if(node.parts)node.parts.forEach(walk);else{leaves[node.id]=node;}}
  walk(scene.model.data.shapes);
  const container=$('viewport');
  class ReviewViewer extends Viewer{constructor(...args){super(...args);viewer=this;}}
  page=createPage({Viewer:ReviewViewer,Display,Timer,container,listen:false,theme:'light',getSize:()=>({width:container.clientWidth,height:container.clientHeight}),overrides:{display:{theme:'light',glass:true,tools:true,treeWidth:200,externalMeasurementBackend:false},viewer:{control:'trackball',up:'Z',tools:true,glass:true}},send:(type,status)=>{if(type==='status')selected(status);}});
  page.handleMessage(scene.model);ready=true;fillList();
  if(scene.unrendered_faces.length)$('renderwarning').textContent=`描画対象外の面 ${scene.unrendered_faces.length} 件: ${scene.unrendered_faces.map(f=>`${names[f[0]]} 面${f[1]}`).join('、')}。該当面を含む候補はこの画面では採用できません。`;
  if(state.draft.reviews.length){loadRow();fitVisible();}else{message('接合候補はありません。');$('save').disabled=true;}
  window.addEventListener('resize',()=>page.resize());
}catch(e){message(e.message,true);console.error(e);}

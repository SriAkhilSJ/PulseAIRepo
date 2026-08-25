// GARGANTUA — app shell: renderer, RT ping-pong post, camera paths, HUD,
// persistence, hotkeys, screenshot mode. ES modules, no build step.
import * as THREE from '../vendor/three/three.module.min.js';
import { OrbitControls } from '../vendor/three/controls/OrbitControls.js';
import { QUALITY, PARAM_DEFS, defaultParams, PRESETS, CAMERA_PATHS } from './config.js';
import { VERT, FRAG_SCENE, FRAG_BRIGHT, FRAG_BLUR, FRAG_COMPOSITE, patchScene } from './shaders.js';

const $ = (s) => document.querySelector(s);
const clamp = (x,a,b)=>Math.min(b,Math.max(a,x));
const lerp = (a,b,t)=>a+(b-a)*t;
const canvas = $('#gl');

const params = defaultParams();
let presetId = 'interstellar', pathIdx = 0, qIdx = 2, dbgView = 0;
let paused = false, simT = 0, uiHidden = false;

/* ---------------------------------------------------------------- storage */
const LS_KEY = 'gargantua.v1';
function persist(){
  try{ localStorage.setItem(LS_KEY, JSON.stringify({ params, presetId, pathIdx, qIdx, dbgView })); }
  catch(e){ /* private mode */ }
}
function restore(){
  try{
    const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
    if(!s) return false;
    Object.assign(params, s.params||{});
    presetId = PRESETS[s.presetId] ? s.presetId : presetId;
    pathIdx = clamp(s.pathIdx|0, 0, CAMERA_PATHS.length-1);
    qIdx = ['low','med','high'].indexOf(s.qKey)>=0 ? ['low','med','high'].indexOf(s.qKey) : qIdx;
    if(typeof s.dbgView === 'number') dbgView = clamp(s.dbgView|0, 0, 9);
    return true;
  }catch(e){ return false; }
}
const qKeys = ['low','med','high'];

/* -------------------------------------------------------------- renderer */
let renderer, sceneQ, camQ, quadQ, rtScene, rtA, rtB, sceneMat, brightMat, blurMat, compMat;
let W = 1, H = 1, dpr = 1, resScale = 1;

function makeRT(w,h){
  const opts = { minFilter:THREE.LinearFilter, magFilter:THREE.LinearFilter,
    wrapS:THREE.ClampToEdgeWrapping, wrapT:THREE.ClampToEdgeWrapping,
    format:THREE.RGBAFormat, type:THREE.HalfFloatType, depthBuffer:false, stencilBuffer:false };
  const rt = new THREE.WebGLRenderTarget(Math.max(2,w|0), Math.max(2,h|0), opts);
  return rt;
}

function initGL(){
  renderer = new THREE.WebGLRenderer({ canvas, antialias:false, depth:false, stencil:false,
    powerPreference:'high-performance', preserveDrawingBuffer:true });
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // manual gamma in composite
  sceneQ = new THREE.Scene();
  camQ = new THREE.OrthographicCamera(-1,1,1,-1,0,1);

  const geo = new THREE.PlaneGeometry(2,2);
  const mk = (frag, uniforms) => new THREE.RawShaderMaterial
    ? new THREE.ShaderMaterial({ vertexShader:VERT, fragmentShader:frag, uniforms, depthTest:false, depthWrite:false })
    : null;

  sceneMat = mk(FRAG_SCENE, {});
  brightMat = mk(FRAG_BRIGHT, { tSrc:{value:null}, uTexel:{value:new THREE.Vector2()}, uThreshold:{value:1.0} });
  blurMat   = mk(FRAG_BLUR,   { tSrc:{value:null}, uTexel:{value:new THREE.Vector2()},
                                uDir:{value:new THREE.Vector2()}, uRadius:{value:1} });
  compMat   = mk(FRAG_COMPOSITE, {
    tScene:{value:null}, tBloom:{value:null}, uRes:{value:new THREE.Vector2(1,1)},
    uTime:{value:0}, uBloomStr:{value:1}, uExposureEV:{value:0}, uGrain:{value:0},
    uAberr:{value:0}, uVignette:{value:0}, uBlackFloor:{value:0}, uSeed:{value:0} });

  quadQ = new THREE.Mesh(geo, sceneMat);
  quadQ.frustumCulled = false;
  sceneQ.add(quadQ);
  resize();
}

function resize(){
  W = Math.max(2, window.innerWidth); H = Math.max(2, window.innerHeight);
  dpr = clamp(window.devicePixelRatio || 1, 1, 2);
  resScale = QUALITY[qKeys[qIdx]].resScale;
  const w = Math.max(2, Math.round(W*dpr*resScale)), h = Math.max(2, Math.round(H*dpr*resScale));
  renderer.setPixelRatio(1); renderer.setSize(W, H, false);
  if(rtScene) rtScene.dispose();
  [rtA, rtB].forEach(rt => rt && rt.dispose());
  rtScene = makeRT(w,h); rtA = makeRT(w>>1,h>>1); rtB = makeRT(w>>1,h>>1);
  compMat.uniforms.uRes.value.set(W*dpr, H*dpr);
  brightMat.uniforms.uTexel.value.set(1/w, 1/h);
  blurMat.uniforms.uTexel.value.set(1/(w>>1), 1/(h>>1));
  applySceneUniforms();
  $('#tRes').textContent = `${w}×${h}`;
}

/* ------------------------------------------------------- camera & motion */
const orbitCam = new THREE.PerspectiveCamera(52, innerWidth/Math.max(innerHeight,1), .05, 400);
const controls = new OrbitControls(orbitCam, canvas);
controls.enableDamping = true; controls.dampingFactor = .06;
controls.minDistance = 3.4; controls.maxDistance = 90;
controls.target.set(0,0,0);
controls.addEventListener('start', ()=>{ if(pathIdx!==0){ pathIdx=0; syncPathLabel(); persist(); }});

const sph = { r:26, th:1.42, ph:0.6 };       // spherical around origin
function orbitToXYZ(r, th, ph){
  return new THREE.Vector3(
    r*Math.sin(th)*Math.sin(ph), r*Math.cos(th), r*Math.sin(th)*Math.cos(ph));
}

function cinematicPos(t){
  // returns {pos, look} — deterministic functions of t
  switch(CAMERA_PATHS[pathIdx].id){
    case 'slowspin': {
      const r = 24 + 2*Math.sin(t*.11), th = 1.45 + .05*Math.sin(t*.07), ph = t*.05;
      return { pos:orbitToXYZ(r,th,ph), look:new THREE.Vector3(0,.4,0) };
    }
    case 'grazing': {
      const u = t*.10, r = lerp(34, 8.5, .5-.5*Math.cos(u)), ph = u*.9+.4;
      const th = 1.5708 - .18*(.5-.5*Math.cos(u*1.3));
      return { pos:orbitToXYZ(r,clamp(th,.35,2.6),ph), look:new THREE.Vector3(0,0,0) };
    }
    case 'plunge': {
      const cyc = 46.0, u = (t%cyc)/cyc, e = u*u*(3-2*u);
      const r = lerp(30, 7.2, e)*(u<.5?1:.55+.45*Math.abs(1-2*u));
      const th = 1.52 - .25*e, ph = t*.08;
      return { pos:orbitToXYZ(r,clamp(th,.4,2.5),ph), look:new THREE.Vector3(0,0,0) };
    }
    case 'rise': {
      const u = .5-.5*Math.cos(t*.045), r = lerp(15,40,u), th = lerp(.30,1.62,u*u), ph = t*.04+.8;
      return { pos:orbitToXYZ(r,th,ph), look:new THREE.Vector3(0,0,0) };
    }
    default: return { pos:orbitToXYZ(sph.r,sph.th,sph.ph), look:new THREE.Vector3(0,0,0) };
  }
}
function currentCam(){
  if(pathIdx===0){
    sph.r = clamp(orbitCam.position.length(), controls.minDistance, controls.maxDistance);
    const p = orbitCam.position.clone().normalize();
    sph.th = Math.acos(clamp(p.y,-1,1)); sph.ph = Math.atan2(p.x, p.z);
    return { pos:orbitCam.position.clone(), look:controls.target };
  }
  const { pos, look } = cinematicPos(simT);
  orbitCam.position.copy(pos); orbitCam.lookAt(look); controls.target.copy(look);
  return { pos:orbitCam.position.clone(), look };
}

/* -------------------------------------------------------- scene uniforms */
const U = {};
function buildSceneUniforms(){
  for(const [k] of PARAM_DEFS) U['u'+k[0].toUpperCase()+k.slice(1)] = { value: params[k] };
  Object.assign(sceneMat.uniforms, U, {
    uRes:{ value:new THREE.Vector2() }, uTime:{ value:0 }, uTanFov:{ value:.5 },
    uSteps:{ value:QUALITY.high.steps }, uDbg:{ value:0 }, uSeed:{ value:Math.random()*100 },
    uAspect:{ value:1 }, uCamPos:{ value:new THREE.Vector3() }, uCamRight:{ value:new THREE.Vector3() },
    uCamUp:{ value:new THREE.Vector3() }, uCamFwd:{ value:new THREE.Vector3() }
  });
}
function refreshParamUniforms(){ for(const [k] of PARAM_DEFS) sceneMat.uniforms['u'+k[0].toUpperCase()+k.slice(1)].value = params[k]; }

function applySceneUniforms(){
  const su = sceneMat.uniforms;
  su.uRes.value.set(rtScene.width, rtScene.height);
  su.uAspect.value = rtScene.width/rtScene.height;
  su.uSteps.value = QUALITY[qKeys[qIdx]].steps;
  su.uDbg.value = dbgView;
}

function renderFrame(dt){
  const { pos } = currentCam();
  orbitCam.fov = params.camFov; orbitCam.updateProjectionMatrix();
  const fwd = new THREE.Vector3(); orbitCam.getWorldDirection(fwd);
  const up = new THREE.Vector3(0,1,0);
  const right = new THREE.Vector3().crossVectors(fwd, up).normalize();
  const upv = new THREE.Vector3().crossVectors(right, fwd).normalize();
  const tanF = Math.tan(params.camFov*Math.PI/360);

  const su = sceneMat.uniforms;
  su.uTime.value = simT;
  su.uTanFov.value = tanF;
  su.uCamPos.value.copy(pos);
  su.uCamFwd.value.copy(fwd); su.uCamRight.value.copy(right); su.uCamUp.value.copy(upv);
  refreshParamUniforms();

  quadQ.material = sceneMat; quadQ.visible = true;
  renderer.setRenderTarget(rtScene); renderer.render(sceneQ, camQ);

  // brightness prefilter -> half-res blur chain x2
  brightMat.uniforms.tSrc.value = rtScene.texture;
  brightMat.uniforms.uThreshold.value = 1.0;
  quadQ.material = brightMat;
  renderer.setRenderTarget(rtA); renderer.render(sceneQ, camQ);

  const rad = params.bloomRadius;
  for(let i=0;i<2;i++){
    blurMat.uniforms.tSrc.value = rtA.texture;
    blurMat.uniforms.uDir.value.set(1,0); blurMat.uniforms.uRadius.value = rad;
    quadQ.material = blurMat; renderer.setRenderTarget(rtB); renderer.render(sceneQ, camQ);

    blurMat.uniforms.tSrc.value = rtB.texture;
    blurMat.uniforms.uDir.value.set(0,1);
    quadQ.material = blurMat; renderer.setRenderTarget(rtA); renderer.render(sceneQ, camQ);
  }

  const cu = compMat.uniforms;
  cu.tScene.value = rtScene.texture; cu.tBloom.value = rtA.texture;
  cu.uTime.value = simT; cu.uBloomStr.value = params.bloomStrength;
  cu.uExposureEV.value = params.exposure; cu.uGrain.value = params.grainAmt;
  cu.uAberr.value = params.aberration; cu.uVignette.value = params.vignette;
  cu.uBlackFloor.value = params.blackFloor; cu.uSeed.value = 3.17;
  quadQ.material = compMat;
  renderer.setRenderTarget(null); renderer.render(sceneQ, camQ);
}

/* ------------------------------------------------------------ audio drone */
let AC = null, masterGain = null, audioOn = false, oscs = [];
function toggleAudio(){
  if(!audioOn){
    AC = AC || new (window.AudioContext||window.webkitAudioContext)();
    AC.resume && AC.resume();
    masterGain = AC.createGain(); masterGain.gain.value = 0.0001;
    masterGain.connect(AC.destination);
    const filt = AC.createBiquadFilter(); filt.type='lowpass'; filt.frequency.value = 320;
    filt.connect(masterGain);
    [[38,.50],[57,.28],[76.2,.16],[114,.09]].forEach(([f,g],i)=>{
      const o = AC.createOscillator(), og = AC.createGain();
      o.type = i%2 ? 'triangle':'sine'; o.frequency.value = f; og.gain.value = g;
      o.connect(og); og.connect(filt); o.start();
      oscs.push({o, og});
    });
    masterGain.gain.linearRampToValueAtTime(.14, AC.currentTime+2.5);
    audioOn = true;
  } else {
    masterGain.gain.linearRampToValueAtTime(.0001, AC.currentTime+.6);
    setTimeout(()=>{ oscs.forEach(({o})=>{try{o.stop()}catch(e){}}); oscs = []; }, 800);
    audioOn = false;
  }
  $('#btnAudio').textContent = 'AUDIO: '+(audioOn?'ON':'OFF');
}

/* ------------------------------------------------------------- UI wiring */
function buildSliders(){
  const host = $('#sliders'); host.innerHTML = '';
  for(const [k,label,min,max,step,def] of PARAM_DEFS){
    const wrap = document.createElement('div'); wrap.className='ctl';
    wrap.innerHTML = `<label><span>${label}</span><output>${fmt(params[k],step)}</output></label>
      <input type="range" min="${min}" max="${max}" step="${step}" value="${params[k]}">`;
    const inp = wrap.querySelector('input'), out = wrap.querySelector('output');
    inp.addEventListener('input', ()=>{
      params[k] = parseFloat(inp.value);
      out.textContent = fmt(params[k], step);
      persist();
    });
    wrap.dataset.key = k; wrap.dataset.def = def;
    host.appendChild(wrap);
  }
  $('#pCount').textContent = `· ${PARAM_DEFS.length}`;
}
const fmt = (v,step)=> step>=1 ? String(Math.round(v)) : v.toFixed(step>=0.1?1:(step>=0.01?2:(step>=0.001?3:4)));

function setParams(obj){
  Object.assign(params, obj);
  document.querySelectorAll('#sliders .ctl').forEach(w=>{
    const k = w.dataset.key, inp = w.querySelector('input'), out = w.querySelector('output');
    inp.value = params[k]; out.textContent = fmt(params[k], parseFloat(inp.step)||.01);
  });
  persist();
}
function loadPreset(id, silent){
  presetId = id; setParams(PRESETS[id].p);
  $('#presetLabel').textContent = 'PRESET · '+PRESETS[id].name;
  if(!silent) persist();
}
function cyclePreset(dir){
  const ids = Object.keys(PRESETS); let i = ids.indexOf(presetId);
  loadPreset(ids[(i+dir+ids.length)%ids.length]);
}
function cyclePath(){
  pathIdx = (pathIdx+1)%CAMERA_PATHS.length;
  if(pathIdx!==0){ orbitCam.position.copy(cinematicPos(simT).pos); }
  syncPathLabel(); persist();
}
const syncPathLabel = ()=> $('#pathLabel').textContent = 'PATH · '+CAMERA_PATHS[pathIdx].name;

const DBG_NAMES = ['BEAUTY','HDR LUMA','STEP HEAT','DOPPLER g','DISK EMISSION','DEFLECTION','RAY DIRECTIONS','CRITICAL CURVE','HORIZON MASK','SKY ONLY'];
function setDbg(v){ dbgView = ((v%10)+10)%10; applySceneUniforms();
  $('#dbgLabel').textContent = `VIEW ${dbgView} · ${DBG_NAMES[dbgView]}`; persist(); }

function cycleQuality(){ qIdx=(qIdx+1)%3; resize(); $('#qLabel').textContent='Q · '+QUALITY[qKeys[qIdx]].label; persist(); }

/* --------------------------------------------------------------- boot/HUD */
let bootP = 0;
function bootMsg(m,p){ const f=$('#bootFill'), b=$('#bootMsg'); b.textContent=m;
  bootP=Math.max(bootP,p); f.style.width=(bootP*100)+'%'; }

/* ------------------------------------------------------ screenshot mode */
const QS = new URLSearchParams(location.search);
async function shotMode(){
  const w = parseInt(QS.get('w')||'1280',10), h = parseInt(QS.get('h')||'720',10);
  const t = parseFloat(QS.get('t')||'37.4');
  if(QS.has('preset')) loadPreset(QS.get('preset'), true);
  if(QS.get('path')) { const i=CAMERA_PATHS.findIndex(c=>c.id===QS.get('path')); if(i>=0) pathIdx=i; }
  if(QS.get('q')){ qIdx = Math.max(0,qKeys.indexOf(QS.get('q'))); }
  if(QS.get('view')) dbgView = clamp(parseInt(QS.get('view'),10)||0,0,9);
  simT = t;
  window.__shotDone = false;
  await new Promise(r=>setTimeout(r,450));           // settle compile + first frames
  renderFrame(0);
  canvas.toBlob(b=>{
    if(!b) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = `gargantua_${presetId}_${w}x${h}_t${t}.png`;
    a.click(); URL.revokeObjectURL(a.href);
    window.__shotDone = true;
    console.info('[GARGANTUA] screenshot saved.');
  }, 'image/png');
}

/* ----------------------------------------------------------- main loop */
let lastT = performance.now(), fpsAcc = 0, fpsN = 0, msAcc = 0, hudTick = 0;
function frame(now){
  requestAnimationFrame(frame);
  const dt = Math.min((now-lastT)/1000, 0.1); lastT = now;
  if(!paused) simT += dt*params.timeWarp;
  try{
    controls.update();
    renderFrame(dt);
    msAcc += dt*1000; fpsAcc += dt; fpsN++;
    if(now-hudTick > 250){
      hudTick = now;
      $('#tFps').textContent = Math.round(fpsN/fpsAcc);
      $('#tMs').textContent = (msAcc/Math.max(fpsN,1)).toFixed(1);
      fpsAcc = 0; fpsN = 0; msAcc = 0;
      updateTelemetry();
    }
  }catch(err){
    console.error('[GARGANTUA] frame error:', err);
    contextLostHandler();
  }
}
function updateTelemetry(){
  const { pos } = orbitCam;
  const r = pos.length();
  $('#vRad').textContent = r.toFixed(2);
  const inc = Math.acos(clamp(pos.y/r,-1,1))*180/Math.PI;
  $('#vInc').textContent = inc.toFixed(1);
  const fovr = params.camFov*Math.PI/180;
  $('#vImpact').textContent = (Math.tan(fovr/2)*r*1.6).toFixed(1);
  $('#vG').textContent = (0.65 + 0.35*Math.sin(simT*.13)).toFixed(3);
  $('#vState').textContent = paused ? 'paused' : 'integrating';
  $('#tSteps').textContent = QUALITY[qKeys[qIdx]].steps;
}

function contextLostHandler(){
  if(renderer && !renderer.getContext().isContextLost()) return;
  console.warn('[GARGANTUA] WebGL context lost — attempting recovery.');
  bootMsg('recovering WebGL context…', .5);
  try{ renderer.forceContextRestore(); }catch(e){}
  setTimeout(()=>location.reload(), 1200);
}
canvas.addEventListener('webglcontextlost', e=>{ e.preventDefault(); contextLostHandler(); });
window.addEventListener('resize', resize);

/* ------------------------------------------------------------- hotkeys */
window.addEventListener('keydown', e=>{
  if(e.target.tagName === 'INPUT') return;
  switch(e.code){
    case 'KeyH': uiHidden=!uiHidden; document.body.classList.toggle('ui-hidden',uiHidden); break;
    case 'Space': paused=!paused; e.preventDefault(); break;
    case 'Digit0': setDbg(0); break; case 'Digit1': setDbg(1); break;
    case 'Digit2': setDbg(2); break; case 'Digit3': setDbg(3); break;
    case 'Digit4': setDbg(4); break; case 'Digit5': setDbg(5); break;
    case 'Digit6': setDbg(6); break; case 'Digit7': setDbg(7); break;
    case 'Digit8': setDbg(8); break; case 'Digit9': setDbg(9); break;
    case 'KeyP': cyclePreset(e.shiftKey?-1:1); break;
    case 'KeyC': cyclePath(); break;
    case 'KeyQ': cycleQuality(); break;
    case 'BracketLeft': setParams({exposure:clamp(params.exposure-.25,-2.5,2.5)}); break;
    case 'BracketRight': setParams({exposure:clamp(params.exposure+.25,-2.5,2.5)}); break;
    case 'KeyM': toggleAudio(); break;
    case 'KeyR': loadPreset(presetId); break;
    case 'KeyS': saveShot(); break;
    case 'Slash': if(e.shiftKey) $('#helpOverlay').hidden = !$('#helpOverlay').hidden; break;
  }
});
$('#btnCloseHelp').addEventListener('click', ()=>$('#helpOverlay').hidden = true);
$('#btnReset').addEventListener('click', ()=>loadPreset(presetId));
$('#btnAudio').addEventListener('click', toggleAudio);
$('#btnShot').addEventListener('click', saveShot);
function saveShot(){
  renderFrame(0);
  canvas.toBlob(b=>{
    const a=document.createElement('a'); a.href=URL.createObjectURL(b);
    a.download=`gargantua_${Date.now()}.png`; a.click(); URL.revokeObjectURL(a.href);
  },'image/png');
}

/* --------------------------------------------------------------- startup */
(async function main(){
  restore();
  buildSliders();
  bootMsg('linking shaders…', .35);

  initGL();
  buildSceneUniforms();
  applySceneUniforms();
  $('#qLabel').textContent = 'Q · '+QUALITY[qKeys[qIdx]].label;
  $('#presetLabel').textContent = 'PRESET · '+PRESETS[presetId].name;
  setDbg(dbgView); syncPathLabel();

  bootMsg('compiling spacetime…', .75);
  await new Promise(r=>setTimeout(r,60));

  requestAnimationFrame(frame);
  bootMsg('ready', 1);
  setTimeout(()=>$('#boot').classList.add('gone'), 500);

  if(QS.has('shot')) shotMode();
})();

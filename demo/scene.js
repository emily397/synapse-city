/* Synapse City, cute suburb demo. Vanilla three.js (inlined above, so THREE's
   classes are in module scope). A cozy sunny town: pastel cottages, gardens,
   trees, drifting clouds, and little hoppy robot residents. Drives a mock
   "living town" so it looks alive with no backend. */

const DISTRICTS = [
  { id:"lab",      name:"The Lab",      x:-24, z:-22, color:0x5db4ff, roof:0x7fbfff },
  { id:"workshop", name:"The Workshop", x: 22, z:-24, color:0xffa24d, roof:0xffb877 },
  { id:"school",   name:"The School",   x:-26, z: 20, color:0x5fd98a, roof:0x8fe6a8 },
  { id:"arena",    name:"The Green",     x:  0, z:  0, color:0xff7fa8, roof:0xffa8c4 },
  { id:"studio",   name:"The Studio",   x: 26, z: 22, color:0xc08bff, roof:0xd3aeff },
  { id:"plaza",    name:"The Plaza",    x:  0, z:-32, color:0xffd24d, roof:0xffe08a },
  { id:"homes",    name:"The Homes",    x:  0, z: 32, color:0x8fd0ff, roof:0xa8d8ff },
];
const ROADS = [["plaza","arena"],["arena","lab"],["arena","workshop"],["arena","school"],
  ["arena","studio"],["arena","homes"],["lab","school"],["workshop","studio"]];
const CAST = [
  { id:"ada",  name:"Ada",  role:"Scientist", color:0x5db4ff, elo:1000 },
  { id:"milo", name:"Milo", role:"Engineer",  color:0xffa24d, elo:1000 },
  { id:"sofia",name:"Sofia",role:"Teacher",   color:0x5fd98a, elo:1000 },
  { id:"rex",  name:"Rex",  role:"Skeptic",   color:0xff7fa8, elo:1000 },
  { id:"nova", name:"Nova", role:"Creative",  color:0xc08bff, elo:1000 },
  { id:"juno", name:"Juno", role:"Judge",     color:0xffd24d, elo:1000 },
];
const LINES = {
  Scientist:["What's the actual mechanism here?","If that holds, we'd see a measurable effect!","Let's strip it to first principles."],
  Engineer:["Ship it, then measure!","The bottleneck is state, not compute.","Give me an interface and I'll run it."],
  Teacher:["Think of it like a little garden.","One line: a feedback loop with memory.","The part people miss is the edge case."],
  Skeptic:["Where's the evidence for that?","Steelman it first, then here's the crack.","It breaks the moment inputs get tricky."],
  Creative:["What if it ran backwards?","Let's mash it with jazz improv!","Reimagine it from the dream, not the spec."],
  Judge:["Specificity wins, marking that down.","The concrete point beat the clever one.","Lovely, but a touch hand-wavy."],
};
const byId = Object.fromEntries(DISTRICTS.map(d => [d.id, d]));
const rand = (a,b) => a + Math.random()*(b-a);

// ---------- renderer / scene ----------
const canvas = document.getElementById("c");
const renderer = new WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = PCFSoftShadowMap;

const scene = new Scene();
scene.background = new Color(0xbfe6ff);
scene.fog = new Fog(0xcdeeff, 90, 240);

const camera = new PerspectiveCamera(42, innerWidth/innerHeight, 0.1, 1000);
camera.position.set(0, 40, 60);
function resize(){ camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); }
addEventListener("resize", resize); resize();

scene.add(new HemisphereLight(0xfff6e0, 0x88bb77, 1.0));
const sun = new DirectionalLight(0xfff2d0, 1.35);
sun.position.set(34, 60, 26); sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left:-90, right:90, top:90, bottom:-90 });
scene.add(sun);

// grassy ground + soft ponds of colour under each district
const grass = new Mesh(new CircleGeometry(150, 64),
  new MeshStandardMaterial({ color: 0x8fd772, roughness: 1 }));
grass.rotation.x = -Math.PI/2; grass.receiveShadow = true; scene.add(grass);

// ---------- sprite text helpers ----------
function mkSprite(draw, wPx, hPx, worldW){
  const cv = document.createElement("canvas"); cv.width = wPx; cv.height = hPx;
  draw(cv.getContext("2d"), wPx, hPx);
  const tex = new CanvasTexture(cv); tex.anisotropy = 4;
  const sp = new Sprite(new SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  sp.scale.set(worldW, worldW*hPx/wPx, 1); return sp;
}
const hex = n => "#" + n.toString(16).padStart(6,"0");
function roundRect(g,x,y,w,h,r){ g.beginPath(); g.moveTo(x+r,y); g.arcTo(x+w,y,x+w,y+h,r);
  g.arcTo(x+w,y+h,x,y+h,r); g.arcTo(x,y+h,x,y,r); g.arcTo(x,y,x+w,y,r); g.closePath(); }
function labelSprite(text, color, worldW){
  return mkSprite((g,w,h)=>{
    g.font = "bold 42px ui-rounded,'Segoe UI',system-ui,sans-serif";
    g.fillStyle = "rgba(255,255,255,0.92)"; roundRect(g,6,6,w-12,h-12,26); g.fill();
    g.strokeStyle = color; g.lineWidth = 5; g.stroke();
    g.fillStyle = color; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(text, w/2, h/2+2);
  }, 512, 128, worldW);
}
function bubbleSprite(text, color){
  const words = text.split(" "); const lines = []; let ln = "";
  for (const w of words){ if ((ln+w).length > 22){ lines.push(ln.trim()); ln = ""; } ln += w+" "; }
  lines.push(ln.trim());
  const H = 64 + lines.length*46;
  return mkSprite((g,w,h)=>{
    g.font = "32px ui-rounded,'Segoe UI',system-ui,sans-serif";
    g.fillStyle = "rgba(255,255,255,0.97)"; roundRect(g,10,10,w-20,h-34,26); g.fill();
    g.strokeStyle = color; g.lineWidth = 5; g.stroke();
    g.beginPath(); g.moveTo(w/2-16,h-26); g.lineTo(w/2+16,h-26); g.lineTo(w/2,h-4); g.closePath();
    g.fillStyle = "rgba(255,255,255,0.97)"; g.fill();
    g.fillStyle = "#3a4a63"; g.textAlign = "center"; g.textBaseline = "middle";
    lines.forEach((l,i)=>g.fillText(l, w/2, 42 + i*46));
  }, 512, H, 12);
}

// ---------- cute props ----------
const swayers = [];
function house(wall, roof){
  const g = new Group();
  const body = new Mesh(new BoxGeometry(2.4,2.2,2.4),
    new MeshStandardMaterial({ color: wall, roughness: 0.85 }));
  body.position.y = 1.1; body.castShadow = body.receiveShadow = true; g.add(body);
  const r = new Mesh(new ConeGeometry(2.15,1.6,4),
    new MeshStandardMaterial({ color: roof, roughness: 0.7 }));
  r.position.y = 3.0; r.rotation.y = Math.PI/4; r.castShadow = true; g.add(r);
  const door = new Mesh(new BoxGeometry(0.7,1.05,0.12),
    new MeshStandardMaterial({ color: 0x7a5233 }));
  door.position.set(0,0.55,1.22); g.add(door);
  const wins = [];
  for (const x of [-0.72,0.72]){
    const w = new Mesh(new BoxGeometry(0.55,0.55,0.12),
      new MeshStandardMaterial({ color: 0xfff3c6, emissive: 0xffcf6b, emissiveIntensity: 0.7 }));
    w.position.set(x,1.35,1.22); g.add(w); wins.push(w);
  }
  const chim = new Mesh(new BoxGeometry(0.34,0.9,0.34),
    new MeshStandardMaterial({ color: roof }));
  chim.position.set(0.72,3.1,0.4); g.add(chim);
  g.userData.wins = wins;
  return g;
}
function tree(){
  const g = new Group();
  const trunk = new Mesh(new CylinderGeometry(0.16,0.24,1.0,7),
    new MeshStandardMaterial({ color: 0x8a5a3b }));
  trunk.position.y = 0.5; g.add(trunk);
  const top = new Mesh(new SphereGeometry(0.95,12,12),
    new MeshStandardMaterial({ color: 0x57c268, roughness: 0.95 }));
  top.position.y = 1.7; top.castShadow = true;
  top.userData.sway = rand(0,6.28); g.add(top); swayers.push(top);
  return g;
}
function pine(){
  const g = new Group();
  const trunk = new Mesh(new CylinderGeometry(0.16,0.2,0.7,6),
    new MeshStandardMaterial({ color: 0x8a5a3b }));
  trunk.position.y = 0.35; g.add(trunk);
  const c = new Mesh(new ConeGeometry(0.9,2.0,8),
    new MeshStandardMaterial({ color: 0x3fae5c, roughness: 0.95 }));
  c.position.y = 1.5; c.castShadow = true; c.userData.sway = rand(0,6.28);
  g.add(c); swayers.push(c);
  return g;
}
function bush(){
  const b = new Mesh(new SphereGeometry(0.55,10,10),
    new MeshStandardMaterial({ color: 0x62c46e, roughness: 1 }));
  b.position.y = 0.4; b.castShadow = true; return b;
}
function flower(color){
  const g = new Group();
  const stem = new Mesh(new CylinderGeometry(0.03,0.03,0.4,5),
    new MeshStandardMaterial({ color: 0x4a9d54 }));
  stem.position.y = 0.2; g.add(stem);
  const head = new Mesh(new SphereGeometry(0.13,8,8),
    new MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25 }));
  head.position.y = 0.42; g.add(head);
  return g;
}
const FLOWER_COLORS = [0xff7f9e,0xffd24d,0xff9a5a,0xb98bff,0xff6f91,0xfff2a8];

// ---------- build neighbourhoods ----------
for (const d of DISTRICTS){
  // soft lawn plot
  const plot = new Mesh(new CircleGeometry(9.5,48),
    new MeshStandardMaterial({ color: d.color, roughness: 1, transparent: true, opacity: 0.18 }));
  plot.rotation.x = -Math.PI/2; plot.position.set(d.x,0.02,d.z); plot.receiveShadow = true;
  scene.add(plot); d.plot = plot;

  let seed = d.id.split("").reduce((a,c)=>a+c.charCodeAt(0),0);
  const rnd = () => (seed = (seed*9301+49297)%233280)/233280;
  const houses = 3 + Math.floor(rnd()*2);
  for (let i=0;i<houses;i++){
    const a = (i/houses)*Math.PI*2 + rnd()*0.5, rad = 4.5 + rnd()*2.5;
    const h = house(0xfff4e2 - (rnd()*0x080808|0), d.roof);
    h.position.set(d.x+Math.cos(a)*rad, 0, d.z+Math.sin(a)*rad);
    h.rotation.y = -a + Math.PI/2 + rand(-0.3,0.3);
    h.scale.setScalar(0.9 + rnd()*0.35);
    scene.add(h);
  }
  for (let i=0;i<5;i++){
    const t = (rnd()<0.5?tree():pine());
    t.position.set(d.x+rand(-8,8), 0, d.z+rand(-8,8)); scene.add(t);
  }
  for (let i=0;i<4;i++){ const b = bush(); b.position.set(d.x+rand(-8,8),0,d.z+rand(-8,8)); scene.add(b); }
  for (let i=0;i<10;i++){ const f = flower(FLOWER_COLORS[(rnd()*FLOWER_COLORS.length)|0]);
    f.position.set(d.x+rand(-9,9),0,d.z+rand(-9,9)); scene.add(f); }

  const lab = labelSprite(d.name, hex(d.color), 12);
  lab.position.set(d.x, 8.5, d.z); scene.add(lab);
}
// scatter some trees between neighbourhoods
for (let i=0;i<40;i++){
  const t = (Math.random()<0.5?tree():pine());
  const x = rand(-70,70), z = rand(-70,70);
  if (Math.hypot(x,z) > 44 && Math.hypot(x,z) < 90){ t.position.set(x,0,z); scene.add(t); }
}
// cobble paths
for (const [a,b] of ROADS){
  const A = byId[a], B = byId[b];
  const dx = B.x-A.x, dz = B.z-A.z, len = Math.hypot(dx,dz);
  const path = new Mesh(new PlaneGeometry(len, 2.6),
    new MeshStandardMaterial({ color: 0xe6d6ad, roughness: 1 }));
  path.rotation.x = -Math.PI/2; path.rotation.z = -Math.atan2(dz,dx);
  path.position.set((A.x+B.x)/2, 0.03, (A.z+B.z)/2); path.receiveShadow = true; scene.add(path);
}

// ---------- clouds ----------
const clouds = [];
for (let i=0;i<9;i++){
  const g = new Group();
  const puffs = 3 + (Math.random()*3|0);
  for (let j=0;j<puffs;j++){
    const s = new Mesh(new SphereGeometry(rand(2,3.4),10,10),
      new MeshStandardMaterial({ color: 0xffffff, roughness: 1, emissive: 0xffffff, emissiveIntensity: 0.12 }));
    s.position.set(rand(-4,4), rand(-0.6,0.6), rand(-2,2)); g.add(s);
  }
  g.position.set(rand(-80,80), rand(26,40), rand(-70,70));
  g.userData.sp = rand(0.6,1.6); scene.add(g); clouds.push(g);
}

// ---------- cute residents ----------
const avatars = CAST.map((c,i)=>{
  const g = new Group();
  const home = DISTRICTS[i % DISTRICTS.length];
  g.position.set(home.x, 0, home.z);
  const glow = new Mesh(new CircleGeometry(1.0,24),
    new MeshBasicMaterial({ color: c.color, transparent: true, opacity: 0.35 }));
  glow.rotation.x = -Math.PI/2; glow.position.y = 0.03; g.add(glow);
  const body = new Mesh(new SphereGeometry(0.72,20,20),
    new MeshStandardMaterial({ color: c.color, emissive: c.color, emissiveIntensity: 0.28,
      roughness: 0.45, metalness: 0.05 }));
  body.position.y = 0.8; body.castShadow = true; g.add(body);
  const head = new Mesh(new SphereGeometry(0.56,20,20),
    new MeshStandardMaterial({ color: 0xfffaf2, emissive: c.color, emissiveIntensity: 0.12 }));
  head.position.y = 1.7; head.castShadow = true; g.add(head);
  for (const ex of [-0.2,0.2]){
    const eye = new Mesh(new SphereGeometry(0.075,8,8), new MeshStandardMaterial({ color: 0x2b3448 }));
    eye.position.set(ex,1.74,0.5); g.add(eye);
  }
  for (const cx of [-0.34,0.34]){
    const cheek = new Mesh(new SphereGeometry(0.09,8,8),
      new MeshStandardMaterial({ color: 0xff9db0, transparent: true, opacity: 0.75 }));
    cheek.position.set(cx,1.62,0.44); g.add(cheek);
  }
  const tag = labelSprite(c.name, hex(c.color), 5.5);
  tag.position.set(0, 2.7, 0); g.add(tag);
  scene.add(g);
  return { ...c, g, home: home.id, district: home.id,
    target: new Vector3(home.x,0,home.z), bubble: null, bubbleUntil: 0, phase: i*1.7, moving: 0 };
});

// ---------- HUD state (same wiring as before) ----------
const H = { conv:0, judge:0, rows:0, mem:0, gen:0, ts:0.30, tsHist:[] };
const feedEl = document.getElementById("feed");
function feed(color, name, text){
  const div = document.createElement("div"); div.className = "fi";
  div.innerHTML = `<span class="dot" style="background:${color}"></span><span class="t"><b>${name}</b> ${text}</span>`;
  feedEl.prepend(div); while (feedEl.children.length > 22) feedEl.removeChild(feedEl.lastChild);
}
const set = (id,v) => document.getElementById(id).textContent = v;
function renderElo(){
  const rows = [...CAST].sort((a,b)=>b.elo-a.elo);
  const mx = Math.max(...rows.map(r=>r.elo)), mn = Math.min(...rows.map(r=>r.elo));
  document.getElementById("elo").innerHTML = rows.map(r=>{
    const w = 6 + (mx===mn?50:(r.elo-mn)/(mx-mn)*94);
    return `<div class="elorow"><span class="who">${r.name}</span><div class="bar"><div style="width:${w}%"></div></div><span class="r">${Math.round(r.elo)}</span></div>`;
  }).join("");
}
function renderSpark(){
  const d = H.tsHist; if (d.length < 2) return;
  const pts = d.map((v,i)=>`${i/(d.length-1)*150},${30-v*30}`).join(" ");
  document.getElementById("spark").innerHTML = `<polyline points="${pts}" fill="none" stroke="#2fae5c" stroke-width="2.5"/>`;
}
renderElo();

let minutes = 8*60;
function tickClock(){
  minutes += 12; const h = Math.floor(minutes/60)%24, m = minutes%60;
  set("clk", `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`);
  set("day", `Day ${Math.floor(minutes/1440)+1} ☀`);
}

// ---------- mock driver ----------
const focus = new Vector3(0,2,0), focusTarget = new Vector3(0,2,0);
function speak(av){
  const line = LINES[av.role][Math.floor(Math.random()*LINES[av.role].length)];
  if (av.bubble){ av.g.remove(av.bubble); av.bubble.material.map.dispose(); av.bubble.material.dispose(); }
  av.bubble = bubbleSprite(line, hex(av.color)); av.bubble.position.set(0,3.6,0);
  av.g.add(av.bubble); av.bubbleUntil = performance.now()+5200;
  feed(hex(av.color), av.name, line);
  const d = byId[av.district]; focusTarget.set(d.x,2,d.z);
}
function step(){
  const av = avatars[Math.floor(Math.random()*avatars.length)];
  const d = DISTRICTS[Math.floor(Math.random()*DISTRICTS.length)];
  av.district = d.id; av.target.set(d.x+rand(-5,5),0,d.z+rand(-5,5)); av.moving = 1;
  if (Math.random()<0.72) speak(av);
  H.conv += 1; H.mem += 3 + (Math.random()*4|0);
  if (d.id==="arena" && Math.random()<0.7){
    H.judge += 1; H.rows += 6;
    const a = av, b = avatars[Math.floor(Math.random()*avatars.length)];
    if (b!==a && a.id!=="juno" && b.id!=="juno"){
      const ea = 1/(1+10**((b.elo-a.elo)/400)); const sa = Math.random()<0.5?1:0;
      a.elo += 24*(sa-ea); b.elo += 24*((1-sa)-(1-ea));
      feed("#f2b705","Juno",`${a.name} vs ${b.name}, ${sa?a.name:b.name} wins!`); renderElo();
    }
  } else H.rows += 2;
  set("mConv",H.conv); set("mJudge",H.judge); set("mRows",H.rows); set("mMem",H.mem);
}
function generation(){
  H.gen += 1; H.ts = Math.min(0.92, H.ts + 0.06 + Math.random()*0.05 - 0.02);
  H.tsHist.push(H.ts); if (H.tsHist.length>30) H.tsHist.shift();
  set("genN",H.gen); set("tsPct",Math.round(H.ts*100)+"%"); renderSpark();
  feed("#2fae5c",`Generation ${H.gen}`,`${20+H.gen*4} SFT + ${8+H.gen*2} DPO, task ${Math.round(H.ts*100)}%`);
}
setInterval(step, 1500); setInterval(tickClock, 900); setInterval(generation, 7000);
feed("#5db4ff","Synapse City","the town woke up. neighbours are saying hello!");

// ---------- animate ----------
let last = performance.now(), frames = 0, fpsT = 0;
function animate(now){
  requestAnimationFrame(animate);
  const dt = Math.min(0.05,(now-last)/1000); last = now;
  const t = now/1000;

  for (const av of avatars){
    const dx = av.target.x-av.g.position.x, dz = av.target.z-av.g.position.z;
    const dist = Math.hypot(dx,dz);
    av.g.position.x += dx*Math.min(1,dt*1.8);
    av.g.position.z += dz*Math.min(1,dt*1.8);
    av.moving = dist > 0.4 ? 1 : 0;
    const hop = av.moving ? Math.abs(Math.sin(now/120 + av.phase))*0.35 : 0;
    av.g.position.y = 0.1 + hop + Math.sin(now/380 + av.phase)*0.06;
    if (dist > 0.05) av.g.rotation.y += (Math.atan2(dx,dz) - av.g.rotation.y)*Math.min(1,dt*4);
    if (av.bubble && now > av.bubbleUntil){ av.g.remove(av.bubble); av.bubble = null; }
  }
  for (const s of swayers) s.rotation.z = Math.sin(t*1.4 + s.userData.sway)*0.05;
  for (const c of clouds){ c.position.x += c.userData.sp*dt*1.2;
    if (c.position.x > 90) c.position.x = -90; }
  // gentle window twinkle
  const tw = 0.6 + Math.sin(t*2)*0.2;

  focus.lerp(focusTarget, Math.min(1,dt*1.3));
  const a = now*0.00010;
  camera.position.x += (focus.x+Math.cos(a)*34 - camera.position.x)*Math.min(1,dt*0.8);
  camera.position.z += (focus.z+Math.sin(a)*34 - camera.position.z)*Math.min(1,dt*0.8);
  camera.position.y += (23 - camera.position.y)*Math.min(1,dt*0.8);
  camera.lookAt(focus.x, 2, focus.z);
  renderer.render(scene, camera);

  frames++; fpsT += dt;
  if (fpsT >= 1){ document.getElementById("fps").textContent = Math.round(frames/fpsT)+" fps"; frames = 0; fpsT = 0; }
}
requestAnimationFrame(animate);

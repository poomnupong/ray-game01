import {View} from './renderer.js';
import {Controls} from './controls.js';

const $ = selector => document.querySelector(selector);
let view;
try {
  view = new View($('#world'));
} catch (error) {
  $('#lobby-status').textContent = `3D could not start: ${error.message}. Use a browser with WebGL enabled.`;
  $('#play').disabled = true;
  console.error(error);
}
let socket=null, state=null, welcome=null, selfId=null, selected=0;
let room='FERN', playing=false, connected=false, retries=0, retryTimer=null, toastTimer=null;
let intentional=false, panelMode='help', invSignature='', lastDeath=0, lastWin=false;
let lastStateAt=0, nearbySignature='';
const controls=new Controls($('#world'),$('#joystick'),$('#stick'),$('#jump'),action);
let token;
try {
  token=localStorage.getItem('wildwood-scout');
  if(!/^[a-f0-9]{32}$/.test(token||'')) {
    const bytes=new Uint8Array(16);
    crypto.getRandomValues(bytes);
    token=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    localStorage.setItem('wildwood-scout',token);
  }
} catch(error) {
  const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
  token=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  $('#lobby-status').textContent='Storage is unavailable. This scout will not survive a page reload.';
}
function notice(text,error=false) {
  clearTimeout(toastTimer);
  $('#toast').textContent=text;
  $('#toast').className=`visible${error?' error':''}`;
  toastTimer=setTimeout(()=>$('#toast').className='',3800);
  if(!playing) $('#lobby-status').textContent=text;
}
function send(msg) {
  if(socket?.readyState===WebSocket.OPEN && connected) socket.send(JSON.stringify(msg));
}
function action(name,extra={}) {
  if(!connected) {notice('Not connected. Waiting to rejoin your camp.',true);return;}
  send({type:'input',...controls.input()});
  send({type:'action',action:name,slot:selected,...extra});
}
function setConnected(value) {
  connected=value;
  controls.enabled=value && !$('#panel').open;
  if(!value) controls.reset();
  document.body.classList.toggle('connection-lost',playing&&!value);
  for(const button of document.querySelectorAll('.actions button, .utility button')) button.disabled=!value;
}
function connect() {
  clearTimeout(retryTimer);
  intentional=false;
  $('#play').disabled=true;
  $('#lobby-status').textContent='Growing your shared world…';
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  socket=ws;
  ws.onopen=()=>ws.send(JSON.stringify({type:'join',room,token,reconnect:playing}));
  ws.onmessage=event=>{
    if(socket!==ws) return;
    const msg=JSON.parse(event.data);
    if(msg.type==='welcome') {
      welcome=msg;selfId=msg.id;retries=0;playing=true;lastWin=false;
      controls.yaw=msg.state.players.find(p=>p.id===selfId)?.yaw||0;
      controls.pitch=msg.state.players.find(p=>p.id===selfId)?.pitch||-.12;
      view.load(msg.blocks,msg.size,msg.height);
      $('#lobby').hidden=true;$('#shade').hidden=true;$('#hud').hidden=false;
      $('#room-label').textContent=room;
      setConnected(true);
      invSignature='';
      applyState(msg.state);
      if(!sessionStorage.getItem('wildwood-tutorial')) {
        openPanel('help');sessionStorage.setItem('wildwood-tutorial','seen');
      } else notice('Camp joined. Your pack and world are shared with this server.');
    } else if(msg.type==='state') applyState(msg);
    else if(msg.type==='notice' || msg.type==='error') {
      notice(msg.text,msg.type==='error');
      if(!connected && msg.type==='error') {
        intentional=true;ws.close();$('#play').disabled=false;
      }
    }
  };
  ws.onerror=()=>notice('Cannot reach the camp server. Check Wi-Fi and the host address.',true);
  ws.onclose=()=>{
    if(socket!==ws) return;
    setConnected(false);$('#play').disabled=false;
    if(intentional) return;
    if(!playing) {$('#lobby-status').textContent='Server unavailable. Check the host, then tap Enter to retry.';return;}
    retries++;
    const delay=Math.min(10,1+retries*2);
    $('#connection').textContent=`Offline · retry in ${delay}s`;
    notice(`Connection lost. Rejoining ${room} in ${delay}s…`,true);
    retryTimer=setTimeout(connect,delay*1000);
  };
}
function applyState(next) {
  lastStateAt=performance.now();
  state=next;
  view.edits(next.changes||[]);
  view.updateEntities(next,selfId);
  const p=next.you;
  $('#health').value=p.hp;$('#health-text').textContent=Math.ceil(p.hp);
  $('#food').value=p.hunger;$('#food-text').textContent=Math.ceil(p.hunger);
  $('#air').value=p.oxygen;$('#oxygen').hidden=p.oxygen>=99;
  $('#connection').textContent=`Online · ${next.players.length} / 8 scouts`;
  $('#day-label').textContent=`${next.night?'Night':'Day'} ${Math.floor(next.clock/welcome.dayLength)+1}`;
  const phase=next.clock%welcome.dayLength;
  const left=next.night?welcome.dayLength-phase:welcome.dayLength*welcome.dayFraction-phase;
  $('#time-left').textContent=`${Math.ceil(left)}s to ${next.night?'dawn':'nightfall'}`;
  $('#location').textContent=`Forest island · ${Math.floor(p.pos[0])}, ${Math.floor(p.pos[2])}`;
  const relics=p.inv.reduce((n,s)=>n+(s?.item==='relic'?s.count:0),0);
  $('#relic-count').textContent=relics;
  $('#objective').firstChild.textContent=next.won?'Keep restored · ': 'Restore the keep · ';
  const signature=JSON.stringify(p.inv);
  if(signature!==invSignature) {
    invSignature=signature;renderHotbar();
    if($('#panel').open && panelMode!=='help') renderPanel();
  }
  if($('#panel').open && panelMode==='pack') {
    const nearby=next.players.filter(other=>other.id!==selfId&&dist(other.pos,p.pos)<=6).map(other=>other.id).join(',');
    if(nearby!==nearbySignature) {nearbySignature=nearby;renderPanel();}
  }
  if(p.deaths>lastDeath) notice('You returned to camp. Your pack is safe.');
  lastDeath=p.deaths;
  if(next.won&&!lastWin) notice('The keep beacon is lit! Wildwood is restored. Keep building together.');
  lastWin=next.won;
  for(const event of next.events||[]) {
    if(!event.player||event.player===selfId) notice(event.text);
  }
}
function itemMarkup(stack) {
  if(!stack) return '<span>Empty</span>';
  return `<i class="item-glyph" data-item="${stack.item}" aria-hidden="true"></i><span>${welcome.items[stack.item].name}</span><b>${stack.count}</b>`;
}
function renderHotbar() {
  if(!state) return;
  $('#hotbar').innerHTML=state.you.inv.slice(0,5).map((s,i)=>`<button class="${i===selected?'selected':''}" data-slot="${i}" aria-label="Select ${s?welcome.items[s.item].name:'empty slot'}">${itemMarkup(s)}</button>`).join('');
  if(selected>=5) {
    $('#hotbar').insertAdjacentHTML('beforeend',`<button class="selected" data-slot="${selected}" aria-label="Selected pack slot">${itemMarkup(state.you.inv[selected])}</button>`);
  }
  for(const button of $('#hotbar').children) button.onclick=()=>{
    selected=Number(button.dataset.slot);renderHotbar();
  };
}
function openPanel(mode) {
  panelMode=mode;
  controls.reset();controls.enabled=false;
  renderPanel();
  if(!$('#panel').open) $('#panel').showModal();
}
function renderPanel() {
  $('#panel-title').textContent={help:'Field guide',pack:'Your pack',craft:'Crafting bench'}[panelMode];
  const body=$('#panel-body');
  if(panelMode==='help') {
    body.innerHTML=`<div class="guide">
      <p class="lead">Welcome to Wildwood. Build a home with friends, then bring light back to the keep.</p>
      <h3>Two thumbs, no keyboard</h3>
      <p><strong>Left thumb:</strong> move with the round joystick. <strong>Right thumb:</strong> drag any empty part of the world to look around. You can do both at once.</p>
      <p><strong>Strike:</strong> aim the centre cross at a block or animal; hold to mine or attack. <strong>Build:</strong> select a block in your pack, aim at a surface, then tap or hold. A placed block uses one item.</p>
      <p><strong>Rise:</strong> hold to jump or swim upward. Water slows you down; watch your air. <strong>Open:</strong> aim at a golden treasure block. <strong>Forage:</strong> stand on grass to gather berries.</p>
      <h3>Your first day</h3>
      <p>Start with timber, earth, stone and berries. Open the treasure at <strong>16, 11</strong> beside camp. Craft a stone pick first, then mine the copper outcrop at <strong>20, 13</strong>. Cut planks, craft a sword, and build a shelter before night.</p>
      <p>Days are peaceful. Pigs, cows, chickens, horses, deer, foxes and rabbits wander the forest. Zombies chase at night; skeletons fire arrows. Solid walls stop their attacks. Your handheld light helps after dark.</p>
      <h3>Three wild wardens</h3>
      <p>Bosses sleep until you strike them. Each drops a wild relic, copper and meals. <strong>Thorn Colossus (28, 48):</strong> leave its red quake ring. <strong>Tide Warden (55, 29):</strong> dodge its arrow volley. <strong>Ember Ram (48, 52):</strong> move sideways before its charge. A warning appears before every special attack.</p>
      <p>Use three relics, 8 copper and 12 planks to craft a <strong>Keep beacon</strong>. Place it anywhere to restore the island for everyone in your room. A copper-and-stone charm reduces damage while carried.</p>
      <h3>Pack &amp; survival</h3>
      <p>12 slots, 32 items per stack. Tools take a whole slot and work automatically while carried. Crafting and treasure never partially consume items. Select food in Pack and tap Eat. Use <strong>Give to scout</strong> in Pack to share a stack with a friend within 6 blocks; pool your relics to craft the beacon. Discarding a stack deletes it; there are no ground pickups yet.</p>
      <p>You keep your pack when you fall; you return to forest camp. Bosses do not respawn in this first version. Chests are shared and can only be looted once. The map is a bounded 64 × 64 island.</p>
      <h3>Play together on Wi-Fi</h3>
      <p>Everyone opens this server's address in their browser and chooses the same <strong>FERN, TIDE or EMBER</strong> camp. All three are independent copies of the island. Up to 8 scouts per camp; no keyboard or account needed.</p>
      <p>Host address: <strong>${location.host}</strong>. On a tablet, replace localhost with the host computer's Wi-Fi IP. The host must keep the server running and allow local network access. Do not expose this prototype to the public internet.</p>
      <p>Worlds and packs save on the host every 10 seconds and when leaving. Your browser remembers your scout. Clearing browser storage creates a new scout. Close this guide to continue; the shared world does not pause.</p>
      <h3>Optional desktop controls</h3>
      <p>W/A/S/D to walk, Space to jump, mouse-drag the world to look. All actions remain visible buttons.</p>
    </div>`;
    return;
  }
  if(!state) {body.innerHTML='<p>Join a camp to open your pack and crafting bench.</p>';return;}
  if(panelMode==='pack') {
    const occupied=state.you.inv.filter(Boolean).length;
    body.innerHTML=`<p>${occupied} / 12 slots used · Stack limit 32. Select any slot to equip it.</p>
      <div class="pack-grid">${state.you.inv.map((s,i)=>`<button class="pack-slot ${i===selected?'selected':''}" data-slot="${i}" aria-label="Slot ${i+1}: ${s?welcome.items[s.item].name+' '+s.count:'empty'}">${itemMarkup(s)}</button>`).join('')}</div>
      <div class="pack-footer"><p id="selected-item">${state.you.inv[selected]?welcome.items[state.you.inv[selected].item].name:'Empty slot'} selected</p>
      <button id="eat" ${welcome.items[state.you.inv[selected]?.item]?.food?'':'disabled'}>Eat one</button>
      <button id="drop" ${state.you.inv[selected]?'':'disabled'}>Discard stack</button></div>
      <div class="pack-footer">${state.players.filter(p=>p.id!==selfId&&dist(p.pos,state.you.pos)<=6).map(p=>
        `<button data-give="${p.id}" ${state.you.inv[selected]?'':'disabled'}>Give to ${p.name}</button>`).join('') || '<p>Stand near a friend to share the selected stack.</p>'}</div>`;
    for(const button of body.querySelectorAll('[data-slot]')) button.onclick=()=>{
      selected=Number(button.dataset.slot);renderPanel();renderHotbar();
    };
    $('#eat').onclick=()=>action('eat');
    for(const button of body.querySelectorAll('[data-give]')) button.onclick=()=>action('give',{target:button.dataset.give});
    $('#drop').onclick=()=> {
      const s=state.you.inv[selected];
      if(!s) return;
      $('#drop').textContent=`Discard ${s.count}?`;
      $('#drop').onclick=()=>action('drop');
    };
  } else {
    const inv=state.you.inv;
    const count=item=>inv.reduce((n,s)=>n+(s?.item===item?s.count:0),0);
    body.innerHTML='<p>Recipes use supplies from your pack. Tools work automatically while carried.</p>'+
      Object.entries(welcome.recipes).map(([id,r])=>{
        const ready=Object.entries(r.cost).every(([item,n])=>count(item)>=n);
        return `<div class="recipe"><div><h3>${r.name}</h3><p>${Object.entries(r.cost).map(([item,n])=>`<span class="${count(item)<n?'missing':''}">${welcome.items[item].name} ${count(item)} / ${n}</span>`).join(' · ')}</p><p>Makes ${Object.entries(r.out).map(([item,n])=>`${n} ${welcome.items[item].name}`).join(', ')}</p></div><button data-recipe="${id}" ${ready?'':'disabled'}>Craft</button></div>`;
      }).join('');
    for(const button of body.querySelectorAll('[data-recipe]')) button.onclick=()=>action('craft',{recipe:button.dataset.recipe});
  }
}
$('#close-panel').onclick=()=>$('#panel').close();
$('#panel').addEventListener('close',()=>{controls.enabled=connected;controls.reset();});
$('#help').onclick=()=>openPanel('help');
$('#lobby-help').onclick=()=>openPanel('help');
$('#pack').onclick=()=>openPanel('pack');
$('#craft').onclick=()=>openPanel('craft');
$('#forage').onclick=()=>action('gather');
$('#open').onclick=()=>action('open');
$('#play').onclick=()=>{if(view)connect();};
for(const button of document.querySelectorAll('[data-room]')) button.onclick=()=>{
  room=button.dataset.room;
  for(const b of document.querySelectorAll('[data-room]')) {
    b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));
  }
};
$('#leave').onclick=()=>{
  intentional=true;clearTimeout(retryTimer);socket?.close();
  playing=false;setConnected(false);state=null;
  $('#hud').hidden=true;$('#lobby').hidden=false;$('#shade').hidden=false;
  $('#play').disabled=false;$('#lobby-status').textContent='Camp left. Your world and pack are saved on the host.';
  view.clearTerrain();for(const id of [...view.entities.keys()])view.removeEntity(id);
  view.makePreview();
};
setInterval(()=>{
  if(connected && !document.hidden) send({type:'input',...controls.input()});
},50);
setInterval(()=>{
  if(connected && !document.hidden && performance.now()-lastStateAt>5000) {
    setConnected(false);
    notice('The server stopped responding. Reconnecting…',true);
    socket?.close(4000,'State timeout');
  }
},1000);
let last=performance.now(),frame=0;
function animate(now) {
  requestAnimationFrame(animate);
  if(!view||document.hidden)return;
  const dt=Math.min(.1,(now-last)/1000);last=now;
  let hit=null;
  if(state) {
    const p=state.you.pos;
    hit=view.ray(controls.yaw,controls.pitch,[p[0],p[1]+1.5,p[2]]);
    if(frame++%6===0) {
      let label=hit?welcome.catalog[hit.block].name:'';
      if(hit?.block===10) label+=state.chests[hit.pos.join(',')]?' · Empty':' · Tap Open';
      const origin=[p[0],p[1]+1.5,p[2]];
      const vec=[-Math.sin(controls.yaw)*Math.cos(controls.pitch),Math.sin(controls.pitch),-Math.cos(controls.yaw)*Math.cos(controls.pitch)];
      for(const mob of state.mobs) {
        if(mob.hp<=0) continue;
        const delta=[mob.pos[0]-origin[0],mob.pos[1]+(mob.boss?1.4:.65)-origin[1],mob.pos[2]-origin[2]];
        const along=delta.reduce((n,v,i)=>n+v*vec[i],0);
        const off=Math.sqrt(Math.max(0,delta.reduce((n,v)=>n+v*v,0)-along*along));
        if(along>0&&along<4.8&&off<(mob.boss?1.4:.8)&&(!hit||dist(hit.pos,origin)>along)) {
          label=`${mob.name} · ${Math.ceil(mob.hp)} health`;
          break;
        }
      }
      $('#target').textContent=label;
      const boss=state.mobs.filter(m=>m.boss&&m.hp>0).sort((a,b)=>dist(a.pos,p)-dist(b.pos,p))[0];
      const near=boss&&dist(boss.pos,p)<20;
      $('#boss-hud').hidden=!near;
      if(near) {
        $('#boss-name').textContent=boss.name;$('#boss-health').max=boss.maxhp;$('#boss-health').value=boss.hp;
        $('#boss-attack').textContent=boss.windup>0?`${boss.attack} incoming — move!`:boss.awake?`${Math.ceil(boss.hp)} health · ${boss.attack}`:'Sleeping · strike only when ready';
      }
    }
  }
  view.render(dt,state?.night,state?.you.pos,controls.yaw,controls.pitch,hit,connected);
}
const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
requestAnimationFrame(animate);

// A read-only diagnostic surface for smoke tests and local troubleshooting.
window.wildwood={
  get state(){return state;},get connected(){return connected;},
  get controls(){return controls;},get view(){return view;},
  get selected(){return selected;},get room(){return room;},
};

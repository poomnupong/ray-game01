import * as THREE from './vendor/three.module.js';

const style = getComputedStyle(document.documentElement);
const color = token => new THREE.Color(style.getPropertyValue(`--cp-${token}`).trim());
const tint = (token, other, mix) => color(token).lerp(color(other), mix);
const palette = [
  color('surface'), tint('success', 'bg', .18), tint('warning', 'text', .62),
  color('border-strong'), tint('warning', 'text', .70), tint('success', 'text', .35),
  color('link'), tint('warning', 'surface', .65), tint('warning', 'accent', .35),
  tint('warning', 'surface', .35), color('warning'), color('warning'),
  color('accent'), color('text-muted'),
];
const faces = [
  {n:[1,0,0], v:[[1,0,1],[1,0,0],[1,1,0],[1,1,1]], shade:.78},
  {n:[-1,0,0], v:[[0,0,0],[0,0,1],[0,1,1],[0,1,0]], shade:.68},
  {n:[0,1,0], v:[[0,1,1],[1,1,1],[1,1,0],[0,1,0]], shade:1},
  {n:[0,-1,0], v:[[0,0,0],[1,0,0],[1,0,1],[0,0,1]], shade:.50},
  {n:[0,0,1], v:[[0,0,1],[1,0,1],[1,1,1],[0,1,1]], shade:.88},
  {n:[0,0,-1], v:[[1,0,0],[0,0,0],[0,1,0],[1,1,0]], shade:.75},
];
const box = new THREE.BoxGeometry(1, 1, 1);
const mats = new Map();
function material(token) {
  if (!mats.has(token)) mats.set(token, new THREE.MeshLambertMaterial({color: color(token)}));
  return mats.get(token);
}

export class View {
  constructor(canvas) {
    this.renderer = new THREE.WebGLRenderer({canvas, antialias: false, powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.sky = tint('link', 'surface', .60);
    this.scene.background = this.sky.clone();
    this.scene.fog = new THREE.Fog(this.sky, 25, 70);
    this.camera = new THREE.PerspectiveCamera(70, 1, .06, 90);
    this.camera.rotation.order = 'YXZ';
    this.sun = new THREE.DirectionalLight(color('surface'), 2.2);
    this.sun.position.set(20, 40, 15);
    this.scene.add(this.sun);
    this.ambient = new THREE.HemisphereLight(color('surface'), color('text-muted'), 2.0);
    this.scene.add(this.ambient);
    this.torch = new THREE.PointLight(color('warning'), 0, 11, 1.6);
    this.scene.add(this.torch);
    this.terrain = new THREE.Group();
    this.scene.add(this.terrain);
    this.entities = new Map();
    this.chunks = new Map();
    this.blocks = null;
    this.size = 64;
    this.height = 28;
    this.solidMat = new THREE.MeshLambertMaterial({vertexColors:true});
    this.waterMat = new THREE.MeshLambertMaterial({vertexColors:true, transparent:true, opacity:.57, side:THREE.DoubleSide});
    this.selection = new THREE.LineSegments(new THREE.EdgesGeometry(box),
      new THREE.LineBasicMaterial({color:color('accent-fg'), depthTest:false}));
    this.selection.scale.setScalar(1.006);
    this.selection.visible = false;
    this.scene.add(this.selection);
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.makePreview();
  }

  resize() {
    this.renderer.setSize(innerWidth, innerHeight, false);
    this.camera.aspect = innerWidth / innerHeight;
    this.camera.updateProjectionMatrix();
  }

  get(x, y, z) {
    if (x < 0 || z < 0 || y < 0 || x >= this.size || z >= this.size || y >= this.height) return 0;
    return this.blocks[(y * this.size + z) * this.size + x];
  }

  load(runs, size, height) {
    this.size = size;
    this.height = height;
    this.blocks = new Uint8Array(size * size * height);
    let offset = 0;
    for (let i = 0; i < runs.length; i += 2) {
      this.blocks.fill(runs[i], offset, offset + runs[i+1]);
      offset += runs[i+1];
    }
    this.clearTerrain();
    for (let x = 0; x < size; x += 8) {
      for (let z = 0; z < size; z += 8) this.buildChunk(x / 8, z / 8);
    }
    this.preview = false;
    for (const id of [...this.entities.keys()]) this.removeEntity(id);
  }

  clearTerrain() {
    for (const group of this.chunks.values()) {
      for (const mesh of group.children) mesh.geometry.dispose();
      this.terrain.remove(group);
    }
    this.chunks.clear();
  }

  buildChunk(cx, cz) {
    if (cx < 0 || cz < 0 || cx >= this.size / 8 || cz >= this.size / 8) return;
    const key = `${cx},${cz}`;
    const old = this.chunks.get(key);
    if (old) {
      for (const mesh of old.children) mesh.geometry.dispose();
      this.terrain.remove(old);
    }
    const solid = {p:[], n:[], c:[]}, water = {p:[], n:[], c:[]};
    for (let x = cx * 8; x < cx * 8 + 8; x++) {
      for (let z = cz * 8; z < cz * 8 + 8; z++) {
        for (let y = 0; y < this.height; y++) {
          const b = this.get(x,y,z);
          if (!b) continue;
          const buffers = b === 6 ? water : solid;
          for (const face of faces) {
            const neighbor = this.get(x+face.n[0],y+face.n[1],z+face.n[2]);
            if (b === 6 ? (neighbor !== 0 || face.n[1] !== 1) : (neighbor !== 0 && neighbor !== 6)) continue;
            let base = palette[b];
            if (b === 1 && face.n[1] !== 1) base = palette[2];
            const shade = face.shade * (.92 + ((x*17+y*23+z*31) % 13) / 100);
            const c = base.clone().multiplyScalar(shade);
            for (const i of [0,1,2,0,2,3]) {
              const v = face.v[i];
              buffers.p.push(x+v[0], y+v[1] - (b === 6 ? .08 : 0), z+v[2]);
              buffers.n.push(...face.n);
              buffers.c.push(c.r,c.g,c.b);
            }
          }
        }
      }
    }
    const group = new THREE.Group();
    for (const [data, mat] of [[solid, this.solidMat], [water, this.waterMat]]) {
      if (!data.p.length) continue;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position',new THREE.Float32BufferAttribute(data.p,3));
      geometry.setAttribute('normal',new THREE.Float32BufferAttribute(data.n,3));
      geometry.setAttribute('color',new THREE.Float32BufferAttribute(data.c,3));
      geometry.computeBoundingSphere();
      group.add(new THREE.Mesh(geometry,mat));
    }
    this.chunks.set(key,group);
    this.terrain.add(group);
  }

  edits(changes) {
    const dirty = new Set();
    for (const [x,y,z,b] of changes) {
      this.blocks[(y*this.size+z)*this.size+x] = b;
      dirty.add(`${Math.floor(x/8)},${Math.floor(z/8)}`);
      if (x%8 === 0) dirty.add(`${Math.floor(x/8)-1},${Math.floor(z/8)}`);
      if (x%8 === 7) dirty.add(`${Math.floor(x/8)+1},${Math.floor(z/8)}`);
      if (z%8 === 0) dirty.add(`${Math.floor(x/8)},${Math.floor(z/8)-1}`);
      if (z%8 === 7) dirty.add(`${Math.floor(x/8)},${Math.floor(z/8)+1}`);
    }
    for (const key of dirty) this.buildChunk(...key.split(',').map(Number));
  }

  ray(yaw,pitch,pos) {
    const vec = [-Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),-Math.cos(yaw)*Math.cos(pitch)];
    let prev = pos.map(Math.floor);
    for (let t = .05; t < 5.5; t += .05) {
      const p = pos.map((v,i) => Math.floor(v+vec[i]*t));
      const b = this.get(...p);
      if (b && b !== 6) return {pos:p, prev, block:b};
      prev = p;
    }
    return null;
  }

  cube(group, token, x,y,z, sx,sy,sz) {
    const mesh = new THREE.Mesh(box,material(token));
    mesh.position.set(x,y,z);
    mesh.scale.set(sx,sy,sz);
    group.add(mesh);
    return mesh;
  }

  model(kind,name) {
    const g = new THREE.Group();
    const cube = (token,x,y,z,sx,sy,sz) => this.cube(g,token,x,y,z,sx,sy,sz);
    if (kind==='chest') {
      cube('text-muted',0,.72,0,1.015,.10,1.015);
      cube('warning',0,.64,-.515,.18,.24,.06);
      cube('text-muted',0,1.025,0,1.015,.05,1.015);
      return g;
    }
    const humanoid = ['scout','zombie','skeleton','thorn','tide'].includes(kind);
    if (humanoid) {
      const token = {scout:'accent', zombie:'success', skeleton:'bg', thorn:'success', tide:'link'}[kind];
      cube(token,0,1,0,.6,.72,.38);
      cube(kind==='scout'?'warning':token,0,1.58,0,.48,.48,.48);
      for (const side of [-1,1]) {
        cube(token,side*.42,1,-.05,.22,.8,.24);
        cube('text-muted',side*.18,.34,0,.22,.68,.24);
        cube('text',side*.13,1.62,-.245,.07,.07,.035);
      }
      if (kind==='scout') {
        cube('text-muted',0,1,.28,.46,.52,.26);
        cube('accent',0,1.84,0,.6,.10,.6);
      }
      if (kind==='skeleton') {
        for (let y=.78;y<1.25;y+=.15) cube('text-muted',0,y,-.21,.48,.04,.03);
        cube('warning',.56,1,-.20,.08,.75,.08);
      }
      if (kind==='thorn') {
        cube('warning',0,1.5,-.27,.3,.3,.1);
        for (const side of [-1,1]) cube('warning',side*.35,2.03,0,.15,.5,.16);
        g.scale.setScalar(2);
      }
      if (kind==='tide') {
        for (const side of [-1,1]) cube('link',side*.52,1.45,0,.35,.7,.12);
        cube('warning',0,1.68,-.28,.18,.18,.10);
        g.scale.setScalar(1.8);
      }
    } else {
      const token = {pig:'accent',cow:'bg',chicken:'surface',horse:'text-muted',
        deer:'warning',fox:'warning',rabbit:'border',ember:'accent'}[kind] || 'accent';
      const small = ['chicken','rabbit','fox'].includes(kind);
      const scale = small ? .58 : kind==='horse' ? 1.15 : 1;
      cube(token,0,.72,0,.75,.65,1.1);
      cube(token,0,1.05,-.62,.48,.55,.5);
      for (const side of [-1,1]) {
        cube('text',side*.17,1.14,-.88,.055,.07,.025);
        cube(token,side*.17,1.42,-.62,.12,.22,.14);
        for (const end of [-1,1]) cube('text-muted',side*.25,.22,end*.37,.18,.46,.18);
      }
      if (kind==='pig') cube('accent-fg',0,.95,-.9,.28,.18,.07);
      if (kind==='cow') {
        cube('text',.39,.8,.16,.035,.3,.4);
        cube('text',-.39,.72,-.2,.035,.35,.35);
        for (const side of [-1,1]) cube('warning',side*.29,1.38,-.7,.14,.3,.15);
      }
      if (kind==='chicken') {
        cube('warning',0,1,-.94,.19,.15,.22);
        cube('accent',0,1.4,-.7,.12,.18,.22);
        for (const side of [-1,1]) cube('bg',side*.42,.8,0,.2,.38,.65);
      }
      if (kind==='horse') {
        cube(token,0,1.20,-.4,.38,.65,.38);
        cube('text',0,1.3,-.14,.13,.72,.16);
      }
      if (kind==='deer') for (const side of [-1,1]) {
        cube('text-muted',side*.28,1.65,-.6,.10,.55,.10);
        cube('text-muted',side*.38,1.8,-.6,.3,.1,.1);
      }
      if (kind==='fox') cube('surface',0,.88,.82,.27,.28,.6);
      if (kind==='rabbit') for (const side of [-1,1]) cube('border',side*.15,1.8,-.58,.12,.75,.14);
      if (kind==='ember') {
        for (const side of [-1,1]) {
          cube('warning',side*.4,1.5,-.5,.32,.35,.4);
          cube('text',side*.5,1.3,-.7,.16,.4,.22);
        }
        cube('warning',0,.8,0,.8,.2,1.15);
        g.scale.setScalar(2.4);
      } else g.scale.setScalar(scale);
    }
    if (name) {
      const canvas = document.createElement('canvas');
      canvas.width = 256; canvas.height = 48;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = style.getPropertyValue('--cp-panel-strong').trim();
      ctx.fillRect(0,0,256,48);
      ctx.fillStyle = style.getPropertyValue('--cp-text').trim();
      ctx.font = 'bold 24px "Segoe UI", sans-serif';
      ctx.textAlign='center'; ctx.fillText(name,128,32);
      const texture = new THREE.CanvasTexture(canvas);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map:texture,depthTest:false}));
      sprite.position.y = 2.25;
      sprite.scale.set(2,.375,1);
      g.add(sprite);
    }
    return g;
  }

  removeEntity(id) {
    const entity = this.entities.get(id);
    if (!entity) return;
    this.scene.remove(entity.group);
    entity.group.traverse(obj => {
      if (obj.isSprite) { obj.material.map.dispose(); obj.material.dispose(); }
    });
    if (entity.ring) {
      this.scene.remove(entity.ring);
      entity.ring.geometry.dispose();
      entity.ring.material.dispose();
    }
    this.entities.delete(id);
  }

  updateEntities(state,selfId) {
    const list = [
      ...state.mobs.filter(m => m.hp>0),
      ...state.players.filter(p => p.id!==selfId).map(p => ({...p,kind:'scout'})),
      ...state.projectiles.map(p => ({...p,kind:'arrow'})),
      ...Object.keys(state.chests).map(key=>{
        const p=key.split(',').map(Number);
        return {id:`chest:${key}`,kind:'chest',pos:[p[0]+.5,p[1],p[2]+.5]};
      }),
    ];
    const present = new Set();
    for (const data of list) {
      present.add(data.id);
      let e = this.entities.get(data.id);
      if (!e) {
        const group = data.kind==='arrow' ? new THREE.Group() : this.model(data.kind,data.kind==='scout'?data.name:null);
        if (data.kind==='arrow') this.cube(group,'warning',0,0,0,.10,.10,.5);
        group.position.fromArray(data.pos);
        this.scene.add(group);
        e = {group, target:new THREE.Vector3(...data.pos), yaw:data.yaw||0};
        if (data.boss) {
          e.ring = new THREE.Mesh(new THREE.RingGeometry(5.7,6,40),
            new THREE.MeshBasicMaterial({color:color('danger'),transparent:true,opacity:.55,side:THREE.DoubleSide}));
          e.ring.rotation.x = -Math.PI/2;
          this.scene.add(e.ring);
        }
        this.entities.set(data.id,e);
      }
      e.target.fromArray(data.pos);
      e.yaw = data.yaw || 0;
      if (e.ring) {
        e.ring.visible = data.windup > 0;
        e.ring.position.set(data.pos[0],data.pos[1]+.04,data.pos[2]);
      }
    }
    for (const id of this.entities.keys()) if (!present.has(id)) this.removeEntity(id);
  }

  makePreview() {
    this.blocks = new Uint8Array(this.size*this.size*this.height);
    const put = (x,y,z,b) => this.blocks[(y*this.size+z)*this.size+x] = b;
    for(let x=0;x<this.size;x++) for(let z=0;z<this.size;z++) {
      const h = Math.round(7+Math.sin(x/8)+Math.cos(z/9));
      for(let y=0;y<=h;y++) put(x,y,z,y===h?1:2);
      if (x%7===3 && z%8===4) {
        for(let y=h+1;y<h+5;y++) put(x,y,z,4);
        for(let dx=-2;dx<=2;dx++) for(let dz=-2;dz<=2;dz++) {
          if(x+dx<0 || z+dz<0 || x+dx>=64 || z+dz>=64) continue;
          for(let dy=4;dy<=6;dy++) if(Math.abs(dx)+Math.abs(dz)<4) put(x+dx,h+dy,z+dz,5);
        }
      }
    }
    for(let x=0;x<8;x++) for(let z=0;z<8;z++) this.buildChunk(x,z);
    this.camera.position.set(26,15,27);
    this.camera.lookAt(35,8,12);
    this.preview = true;
  }

  render(dt, night, pos, yaw, pitch, hit, connected) {
    if (!this.preview && pos) {
      const target = new THREE.Vector3(pos[0],pos[1]+1.5,pos[2]);
      if (this.camera.position.distanceTo(target)>5) this.camera.position.copy(target);
      else this.camera.position.lerp(target,1-Math.exp(-dt*20));
      this.camera.rotation.set(pitch,yaw,0,'YXZ');
      this.selection.visible = !!hit && connected;
      if(hit) this.selection.position.set(hit.pos[0]+.5,hit.pos[1]+.5,hit.pos[2]+.5);
    }
    this.sun.intensity = night ? .15 : 2.2;
    this.ambient.intensity = night ? .85 : 2.0;
    this.torch.intensity = night ? 9 : 0;
    this.torch.position.copy(this.camera.position);
    const bg = night ? tint('link','text',.83) : this.sky;
    const underwater = pos && this.get(Math.floor(pos[0]),Math.floor(pos[1]+1.5),Math.floor(pos[2]))===6;
    this.scene.background.copy(underwater?palette[6]:bg);
    this.scene.fog.color.copy(this.scene.background);
    this.scene.fog.near = underwater ? 1 : 25;
    this.scene.fog.far = underwater ? 12 : 70;
    for (const e of this.entities.values()) {
      e.group.position.lerp(e.target,1-Math.exp(-dt*12));
      const delta = Math.atan2(Math.sin(e.yaw-e.group.rotation.y),Math.cos(e.yaw-e.group.rotation.y));
      e.group.rotation.y += delta * Math.min(1,dt*12);
    }
    this.renderer.render(this.scene,this.camera);
  }
}

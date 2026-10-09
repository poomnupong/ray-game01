export class Controls {
  constructor(canvas, joystick, stick, jump, onAction) {
    this.move = {x:0,z:0};
    this.yaw = 0;
    this.pitch = -.12;
    this.jump = false;
    this.enabled = false;
    this.keys = new Set();
    this.look = null;
    this.joy = null;
    this.jumpPointers = new Set();
    this.actionPointers = new Map();
    this.stick = stick;
    this.joystick = joystick;
    const capture = (element,event) => {
      event.preventDefault();
      element.setPointerCapture(event.pointerId);
    };
    joystick.addEventListener('pointerdown',e => {
      if (!this.enabled || this.joy!==null) return;
      capture(joystick,e);
      this.joy=e.pointerId;
      this.moveStick(e);
    });
    joystick.addEventListener('pointermove',e => { if(e.pointerId===this.joy) this.moveStick(e); });
    const endJoy = e => {
      if(e.pointerId!==this.joy) return;
      this.joy=null; this.move={x:0,z:0}; stick.style.transform='';
    };
    for(const kind of ['pointerup','pointercancel','lostpointercapture']) joystick.addEventListener(kind,endJoy);
    canvas.addEventListener('pointerdown',e => {
      if(!this.enabled || this.look!==null) return;
      capture(canvas,e);
      this.look={id:e.pointerId,x:e.clientX,y:e.clientY};
    });
    canvas.addEventListener('pointermove',e => {
      if(!this.look || this.look.id!==e.pointerId) return;
      this.yaw -= (e.clientX-this.look.x)*.006;
      this.pitch = Math.max(-1.5,Math.min(1.5,this.pitch-(e.clientY-this.look.y)*.006));
      this.look.x=e.clientX; this.look.y=e.clientY;
      document.querySelector('#look-hint').style.opacity='0';
    });
    const endLook = e => { if(this.look?.id===e.pointerId) this.look=null; };
    for(const kind of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(kind,endLook);
    jump.addEventListener('pointerdown',e => {
      if(!this.enabled) return;
      capture(jump,e); this.jumpPointers.add(e.pointerId); this.jump=true;
    });
    const endJump = e => {this.jumpPointers.delete(e.pointerId); this.jump=this.jumpPointers.size>0;};
    for(const kind of ['pointerup','pointercancel','lostpointercapture']) jump.addEventListener(kind,endJump);
    for(const [id,action] of [['mine','mine'],['place','place']]) {
      const element=document.getElementById(id);
      element.addEventListener('pointerdown',e => {
        if(!this.enabled) return;
        capture(element,e);
        onAction(action);
        const timer=setInterval(() => {if(this.enabled) onAction(action);},action==='mine'?600:350);
        this.actionPointers.set(e.pointerId,timer);
      });
      const end=e => {clearInterval(this.actionPointers.get(e.pointerId));this.actionPointers.delete(e.pointerId);};
      for(const kind of ['pointerup','pointercancel','lostpointercapture']) element.addEventListener(kind,end);
      // Keyboard and assistive click activation, without duplicating pointer taps.
      element.addEventListener('click',e => {if(e.detail===0 && this.enabled) onAction(action);});
    }
    window.addEventListener('keydown',e => {
      if(!this.enabled || document.querySelector('dialog[open]')) return;
      if(['KeyW','KeyA','KeyS','KeyD','Space','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)) {
        e.preventDefault(); this.keys.add(e.code);
      }
    });
    window.addEventListener('keyup',e => this.keys.delete(e.code));
    window.addEventListener('blur',()=>this.reset());
    document.addEventListener('visibilitychange',()=>{if(document.hidden)this.reset();});
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    document.addEventListener('gesturestart',e=>e.preventDefault());
  }
  moveStick(e) {
    const rect=this.joystick.getBoundingClientRect();
    const limit=rect.width*.32;
    const dx=e.clientX-rect.left-rect.width/2, dy=e.clientY-rect.top-rect.height/2;
    const length=Math.max(limit,Math.hypot(dx,dy));
    this.move={x:dx/length,z:-dy/length};
    this.stick.style.transform=`translate(${dx/length*limit}px,${dy/length*limit}px)`;
  }
  input() {
    if(!this.enabled) return {x:0,z:0,jump:false,yaw:this.yaw,pitch:this.pitch};
    const k=this.keys;
    return {x:Math.max(-1,Math.min(1,this.move.x+(k.has('KeyD')?1:0)-(k.has('KeyA')?1:0))),
      z:Math.max(-1,Math.min(1,this.move.z+(k.has('KeyW')?1:0)-(k.has('KeyS')?1:0))),
      jump:this.jump||k.has('Space'),yaw:this.yaw,pitch:this.pitch};
  }
  reset() {
    this.move={x:0,z:0};this.jump=false;this.joy=null;this.look=null;
    this.keys.clear();this.jumpPointers.clear();this.stick.style.transform='';
    for(const timer of this.actionPointers.values()) clearInterval(timer);
    this.actionPointers.clear();
  }
}

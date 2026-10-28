import {ConsoleNavigation} from './navigation.js';

/** Local window lifecycle only. Closing a view never sends an experiment command. */
export class ConsoleWindows {
  static describe(route) {
    const page=ConsoleNavigation.resolve(route);
    if(page.page==='desktop')return {key:'desktop',title:'Desktop'};
    if(page.runId)return {key:'run:'+page.runId,title:'Experiment · '+page.runId.slice(0,8)};
    if(page.page==='configuration')return {key:'settings',title:'System Settings'};
    if(page.page==='system')return {key:'system',title:'System Info'};
    if(page.page==='programs')return {key:'files',title:'Files'};
    return {key:'workstation',title:'Workstation'};
  }

  constructor(app) {
    this.app=app;this.windows=new Map();this.active=null;this.order=0;this.pendingRoute=null;
  }

  start() {
    this.layer=document.querySelector('#window-layer');this.tasks=document.querySelector('#window-tasks');
    this.surface=document.querySelector('#view-surface');this.template=this.surface.cloneNode(true);this.surface.remove();
    const launchers=document.querySelector('#console-navigation');
    for(const [title,route,icon] of [['Files','#programs','▤'],['Workstation','#station','▦'],['System Settings','#configuration','⚙'],['System Info','#system','ⓘ']]) {
      const link=this.app.element('a');link.href=route;link.setAttribute('aria-label',title);link.title=title;
      const glyph=this.app.element('span',icon,'taskbar-icon');glyph.setAttribute('aria-hidden','true');
      link.append(glyph,this.app.element('span',title,'taskbar-label'));
      link.dataset.action='window.open';link.dataset.entityId=ConsoleWindows.describe(route).key;
      link.addEventListener('click',event=>{if(location.hash===route){event.preventDefault();this.navigate(route);}});
      launchers.append(link);
    }
    document.querySelector('.taskbar-brand').addEventListener('click',event=>{event.preventDefault();this.showDesktop();});
    window.addEventListener('resize',()=>{for(const record of this.windows.values())this.clamp(record);});
    this.navigate(location.hash || '#programs');
  }

  isCurrentRoute() {
    return Boolean(this.active && this.active.route===(location.hash || '#programs'));
  }

  operationPending() {
    const a=this.app;
    return Boolean(a.busy || a.configSaving || a.programs.working || a.programs.launching || a.setup.working || a.workstation.layout.editor.saving || a.configuration.carriers.busy);
  }

  notice(message='') {
    const node=document.querySelector('#shell-notice');node.textContent=message;node.hidden=!message;
  }

  async navigate(route) {
    this.pendingRoute=route || '#programs';
    clearTimeout(this.routeTimer);
    // Let the owning controller settle before retargeting its DOM references.
    if(this.operationPending()) {this.routeTimer=setTimeout(()=>this.navigate(this.pendingRoute),60);return;}
    const target=this.pendingRoute;this.pendingRoute=null;
    if(this.app.workstation.layout.editor.open && this.active?.route!==target) {
      this.notice('Close the rack position editor before switching windows.');
      location.replace(this.active.route);return;
    }
    const descriptor=ConsoleWindows.describe(target);
    if(descriptor.key==='desktop') {this.showDesktop();return;}
    let record=this.windows.get(descriptor.key);
    if(!record) {
      if(this.windows.size>=16) {this.notice('Close an unused window before opening another.');location.replace(this.active?.route || '#desktop');return;}
      record=this.create(descriptor,target);
    }
    const routeChanged=record.route!==target;record.route=target;
    this.activate(record);
    if(routeChanged)this.app.renderKey=null;
    if(location.hash!==target) {location.replace(target);return;}
    this.app.navigation.select();await this.app.refresh();
  }

  create(descriptor,route) {
    const a=this.app,frame=a.element('section','','console-window');
    frame.setAttribute('role','region');frame.setAttribute('aria-label',descriptor.title+' window');
    frame.dataset.windowId=descriptor.key;
    const bar=a.element('header','','window-titlebar');
    const title=a.element('button',descriptor.title,'window-title');title.dataset.action='window.focus';
    title.addEventListener('click',()=>this.open(record));
    const controls=a.element('div','','window-controls');
    const record={...descriptor,route,frame,bar,titleNode:title,minimized:false,maximized:false,renderKey:null,
      surface:this.windows.size===0 && this.surface ? this.surface:this.template.cloneNode(true)};
    this.surface=null;
    for(const [label,symbol,action] of [['Minimize','−','minimize'],['Maximize','□','maximize'],['Close','×','close']]) {
      const button=a.element('button',symbol);button.setAttribute('aria-label',label+' '+record.title);
      button.dataset.action='window.'+action;button.dataset.entityId=record.key;
      button.title=label;button.addEventListener('click',()=>this[action](record));controls.append(button);
      if(action==='maximize')record.maximizeButton=button;
    }
    bar.append(title,controls);frame.append(bar,record.surface);
    record.surface.querySelector('#refresh').addEventListener('click',()=>a.refresh());
    const cover=a.element('button','','window-activate-cover');cover.setAttribute('aria-label','Activate '+record.title);
    cover.dataset.action='window.focus';cover.addEventListener('click',()=>this.open(record));frame.append(cover);record.cover=cover;
    const index=this.windows.size;frame.style.left=(20+(index%5)*22)+'px';frame.style.top=(18+(index%5)*22)+'px';
    bar.addEventListener('pointerdown',event=>this.beginMove(record,event));
    bar.addEventListener('dblclick',event=>{if(!event.target.closest('.window-controls'))this.maximize(record);});
    this.windows.set(record.key,record);this.layer.append(frame);this.clamp(record);return record;
  }

  bind(record,enabled) {
    // IDs address the active renderer only. Inactive windows retain their real DOM.
    for(const node of [record.surface,...record.surface.querySelectorAll('[id],[data-window-dom-id]')]) {
      if(!enabled && node.id) {node.dataset.windowDomId=node.id;node.removeAttribute('id');}
      else if(enabled && node.dataset.windowDomId) {node.id=node.dataset.windowDomId;delete node.dataset.windowDomId;}
    }
    record.surface.inert=!enabled;record.surface.setAttribute('aria-hidden',String(!enabled));record.cover.hidden=enabled;
    record.frame.dataset.active=String(enabled);
    if(!enabled)return;
    const a=this.app;a.content=record.surface.querySelector('#content');a.alert=record.surface.querySelector('#alert');
    a.button=record.surface.querySelector('#refresh');a.interaction.content=a.content;
    a.interaction.status=record.surface.querySelector('#operation-status');a.interaction.lastResult=null;
    a.renderKey=record.renderKey;
  }

  activate(record) {
    if(this.active!==record) {
      if(this.active){this.active.renderKey=this.app.renderKey;this.active.selectedEntity=this.app.shell.selectedEntity;this.bind(this.active,false);}
      this.active=record;this.bind(record,true);this.app.shell.selectedEntity=record.selectedEntity || null;
    }
    record.minimized=false;record.frame.hidden=false;record.frame.style.zIndex=String(++this.order);
    document.querySelector('#desktop-home').hidden=true;this.notice();this.renderTasks();
  }

  open(record) {
    if(location.hash===record.route)this.navigate(record.route);else location.hash=record.route;
  }

  guarded(record) {
    if(this.operationPending()) {this.notice('A console operation is finishing. Try again when it settles.');return true;}
    if(this.app.workstation.layout.editor.open || record.key==='settings' && this.app.configWorking && this.app.configDirty()) {
      this.notice('Save or discard the open edit before closing or minimizing this window.');return true;
    }
    return false;
  }

  minimize(record) {
    if(this.guarded(record))return;
    record.minimized=true;record.frame.hidden=true;this.selectRemaining(record);
  }

  close(record) {
    if(this.guarded(record))return;
    record.frame.remove();this.windows.delete(record.key);this.selectRemaining(record);
  }

  selectRemaining(record) {
    if(this.active===record) {
      record.renderKey=this.app.renderKey;this.bind(record,false);this.active=null;
      const next=[...this.windows.values()].filter(item=>!item.minimized).sort((a,b)=>Number(b.frame.style.zIndex)-Number(a.frame.style.zIndex))[0];
      if(next)this.open(next);else this.showDesktop();
    }
    this.renderTasks();
  }

  showDesktop() {
    if(this.operationPending()) {this.pendingRoute='#desktop';this.routeTimer=setTimeout(()=>this.navigate('#desktop'),60);return;}
    if(this.app.workstation.layout.editor.open) {this.notice('Close the rack position editor before showing the desktop.');return;}
    if(this.active) {this.active.renderKey=this.app.renderKey;this.bind(this.active,false);this.active=null;}
    clearTimeout(this.app.timer);
    for(const record of this.windows.values()){record.minimized=true;record.frame.hidden=true;}
    document.querySelector('#desktop-home').hidden=false;this.notice();this.renderTasks();
    if(location.hash!=='#desktop')location.hash='#desktop';
  }

  maximize(record) {
    record.maximized=!record.maximized;record.frame.classList.toggle('maximized',record.maximized);
    record.maximizeButton.setAttribute('aria-label',(record.maximized ? 'Restore ':'Maximize ')+record.title);
    record.maximizeButton.title=record.maximized ? 'Restore':'Maximize';
  }

  clamp(record) {
    const area=this.layer.getBoundingClientRect();
    record.frame.style.left=Math.max(0,Math.min(parseFloat(record.frame.style.left)||0,area.width-Math.min(record.frame.getBoundingClientRect().width,area.width)))+'px';
    record.frame.style.top=Math.max(0,Math.min(parseFloat(record.frame.style.top)||0,area.height-Math.min(record.frame.getBoundingClientRect().height,area.height)))+'px';
  }

  beginMove(record,event) {
    if(event.button!==0 || record.maximized || event.target.closest('.window-controls') || matchMedia('(max-width:720px)').matches)return;
    if(this.active!==record){this.open(record);return;}
    const x=event.clientX,y=event.clientY,left=parseFloat(record.frame.style.left)||0,top=parseFloat(record.frame.style.top)||0;
    const move=next=>{record.frame.style.left=left+next.clientX-x+'px';record.frame.style.top=top+next.clientY-y+'px';this.clamp(record);};
    const end=()=>{record.bar.removeEventListener('pointermove',move);record.bar.removeEventListener('pointerup',end);record.bar.removeEventListener('lostpointercapture',end);};
    record.bar.setPointerCapture(event.pointerId);record.bar.addEventListener('pointermove',move);
    record.bar.addEventListener('pointerup',end);record.bar.addEventListener('lostpointercapture',end);
  }

  renderTasks() {
    const nodes=[];
    for(const record of this.windows.values()) {
      if(!record.key.startsWith('run:'))continue;
      const task=this.app.element('button',record.title,'window-task');task.dataset.action='window.focus';task.dataset.entityId=record.key;
      task.setAttribute('aria-label','Show '+record.title);task.setAttribute('aria-pressed',String(this.active===record));
      task.dataset.minimized=String(record.minimized);task.title=record.title;task.addEventListener('click',()=>this.open(record));nodes.push(task);
    }
    this.tasks.replaceChildren(...nodes);this.tasks.hidden=nodes.length===0;
    document.querySelector('.taskbar-divider').hidden=nodes.length===0;
    for(const link of document.querySelectorAll('#console-navigation a')) {
      const record=this.windows.get(link.dataset.entityId);
      link.dataset.open=String(Boolean(record));link.dataset.minimized=String(Boolean(record?.minimized));
      link.title=link.getAttribute('aria-label')+(record ? record.minimized ? ' · minimized':' · open':'');
      if(this.active?.key===link.dataset.entityId)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    }
  }
}

import {ConsoleNavigation} from './navigation.js';
import {ConsoleWindows} from './console-windows.js';

/** Typed view control shared by ordinary navigation and external presentation requests. */
export class ConsoleShell {
  constructor(app) {
    this.app=app;this.workspace=new ConsoleWindows(app);this.session=null;this.rendererToken=null;this.timer=null;
    this.stopped=false;this.heartbeatTimer=null;this.completed=new Map();this.selectedEntity=null;
  }

  start() {
    window.addEventListener('pagehide',()=>this.stop());
    document.addEventListener('focusin',event=>{
      const node=event.target.closest?.('[data-entity-id]');
      if(node && /^(workstation|setup)\./.test(node.dataset.action || '')) this.selectedEntity=node.dataset.entityId;
    });
    this.tick();this.heartbeat();
  }

  state() {
    const a=this.app,route=ConsoleNavigation.resolve(this.workspace.active?.route || '#desktop');
    const view=route.page==='desktop' ? 'desktop':route.page==='run' ? 'experiment':route.page==='configuration' ? 'settings':
      route.page==='system' ? 'system_info':route.page==='programs' ? 'files':'workstation';
    return {view,entity_id:route.runId || null,selected_entity_id:this.workspace.active ? this.selectedEntity:null,
      dirty:Boolean(a.configWorking && a.configDirty() || a.workstation.layout.editor.open),
      busy:Boolean(a.busy || a.configSaving || a.programs.working || a.setup.working || this.workspace.pendingRoute)};
  }

  async bootstrap() {
    const result=await this.app.configurationFetch('/api/v1/session');
    if(!this.app.configToken)this.app.configToken=result.access_token;
    this.rendererToken=result.renderer_access_token || null;
    return Boolean(this.rendererToken);
  }

  async rendererRequest(payload) {
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000);
    try {
      const response=await fetch('/api/v1/console/renderer',{method:'POST',cache:'no-store',signal:controller.signal,
        headers:{'Content-Type':'application/json','Authorization':`Bearer ${this.rendererToken}`},body:JSON.stringify(payload)});
      const result=await response.json();
      if(!response.ok || result.schema!=='culsma_view_interaction_v1') {
        const error=new Error(result.error?.code || 'CONSOLE_RENDERER_UNAVAILABLE');error.httpStatus=response.status;throw error;
      }
      return result.data;
    } finally {clearTimeout(timeout);}
  }

  identity(action) {
    return {action,session_id:this.session.session_id,epoch:this.session.epoch,revision:this.session.revision};
  }

  async heartbeat() {
    if(this.stopped)return;
    try {
      if(this.session && this.rendererToken) {
        const result=await this.rendererRequest(this.identity('heartbeat'));
        if(this.session?.epoch===result.session.epoch && result.session.revision>this.session.revision)this.session=result.session;
      }
    } catch { /* The main poll reconciles expired or unavailable sessions. */ }
    finally {if(!this.stopped)this.heartbeatTimer=setTimeout(()=>this.heartbeat(),4000);}
  }

  async tick() {
    if(this.stopped)return;
    try {
      if(!this.rendererToken && !await this.bootstrap()) {this.stopped=true;return;}
      if(!this.session) {
        const result=await this.rendererRequest({action:'register',state:this.state()});this.session=result.session;
      }
      const result=await this.rendererRequest({...this.identity('poll'),state:this.state()});
      this.session=result.session;
      for(const receipt of result.requests) {
        if(this.stopped)break;
        let completed=this.completed.get(receipt.request_id);
        if(!completed) {
          let outcome='deferred';
          if(receipt.request.expected_revision===this.session.revision && !this.state().dirty && !this.state().busy && !document.hidden) {
            try {await this.applyViewRequest(receipt.request);outcome='displayed';}
            catch {outcome=this.state().dirty || document.hidden ? 'deferred':'rejected';}
          }
          completed={outcome,state:this.state()};this.completed.set(receipt.request_id,completed);
          if(this.completed.size>64)this.completed.delete(this.completed.keys().next().value);
        }
        const ack=await this.rendererRequest({...this.identity('acknowledge'),request_id:receipt.request_id,...completed});
        this.session=ack.session;
      }
    } catch(error) {
      // Reconcile only this renderer session; never repeat an experiment command.
      if(error.httpStatus===409 && this.session && error.message!=='CONSOLE_RENDERER_EXPIRED') {
        try {this.session=(await this.rendererRequest(this.identity('inspect'))).session;} catch {this.session=null;this.rendererToken=null;}
      } else if(error.httpStatus===401 || error.message==='CONSOLE_RENDERER_EXPIRED') {
        this.session=null;this.rendererToken=null;this.completed.clear();
      }
    } finally {
      if(!this.stopped)this.timer=setTimeout(()=>this.tick(),1000);
    }
  }

  route(view,entityId=null) {
    const routes={desktop:'#desktop',workstation:'#station',files:'#programs',settings:'#configuration',system_info:'#system'};
    if(view==='experiment' && entityId)return '#run/'+encodeURIComponent(entityId);
    if(!Object.hasOwn(routes,view))throw new Error('CONSOLE_VIEW_UNSUPPORTED');
    return routes[view];
  }

  async openView(view,entityId=null) {
    if(this.state().dirty || document.hidden)throw new Error('CONSOLE_VIEW_DEFERRED');
    const route=this.route(view,entityId);this.selectedEntity=null;
    if(location.hash!==route)location.hash=route;else await this.app.refresh();
    await this.waitForView(view,entityId);
  }

  async waitForView(view,entityId) {
    const deadline=Date.now()+10000;
    while(Date.now()<deadline) {
      if(document.hidden || this.state().dirty)throw new Error('CONSOLE_VIEW_DEFERRED');
      if(this.viewReady(view,entityId)) {
        await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
        if(this.viewReady(view,entityId))return;
      }
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    throw new Error('CONSOLE_VIEW_NOT_RENDERED');
  }

  viewReady(view,entityId) {
    if(view==='desktop')return location.hash==='#desktop' && !this.workspace.active;
    if(!this.workspace.isCurrentRoute() || !this.workspace.active || this.workspace.active.minimized)return false;
    const content=this.app.content,data=content.dataset;
    const page=view==='experiment' ? 'run':view==='settings' ? 'configuration':view==='system_info' ? 'system':view==='files' ? 'programs':'station';
    return location.hash===this.route(view,entityId) && data.page===page && data.loadState==='ready' && !this.app.busy &&
      (view!=='experiment' || data.runId===entityId && Boolean(content.querySelector('[data-region="run-outcome"]')));
  }

  revealEntity(entityId) {
    const node=[...this.app.content.querySelectorAll('[data-entity-id]')].find(item=>
      item.dataset.entityId===entityId && item.dataset.action==='workstation.inspect-layout-item');
    if(!node || !node.getClientRects().length)throw new Error('CONSOLE_VIEW_TARGET_NOT_RENDERED');
    for(const previous of this.app.content.querySelectorAll('.console-revealed'))previous.classList.remove('console-revealed');
    node.classList.add('console-revealed');node.scrollIntoView({block:'center',inline:'center'});node.focus({preventScroll:true});
    this.selectedEntity=entityId;
  }

  async applyViewRequest(request) {
    await this.openView(request.view,request.view==='experiment' ? request.entity_id:null);
    if(request.entity_id && request.view==='workstation')this.revealEntity(request.entity_id);
  }

  stop() {
    this.stopped=true;clearTimeout(this.timer);clearTimeout(this.heartbeatTimer);
    if(this.session && this.rendererToken) {
      fetch('/api/v1/console/renderer',{method:'POST',keepalive:true,
        headers:{'Content-Type':'application/json','Authorization':`Bearer ${this.rendererToken}`},
        body:JSON.stringify(this.identity('close'))}).catch(()=>{});
    }
  }
}

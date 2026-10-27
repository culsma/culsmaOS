import {WorkstationLayoutView} from './workstation-layout.js';

/** Compose existing console views; business commands remain in their owning controllers. */
export class ConsoleWorkstation {
  constructor(app) {this.app=app;this.layout=new WorkstationLayoutView(app);}

  resourceTable(title, rows, columns) {
    const a=this.app,card=a.card(title);
    card.append(a.table(columns.map(item=>item[0]),(rows || []).map(row=>columns.map(item=>row[item[1]])),'No records in this snapshot.'));
    return card;
  }

  device(device) {
    const a=this.app,card=a.card(device.device_id);
    card.append(a.details([['Mode',device.mode],['Evidence accounting',a.badge(device.evidence_accounting)],
      ['Position basis',a.badge(device.positions?.status)]]));
    card.append(a.element('h3','Consumables'),a.table(['Resource','Known used','Available from records'],
      Object.entries(device.consumables || {}).map(([name,item])=>[name,item.known_consumed,item.available_from_records ?? 'Unknown'])));
    card.append(a.element('h3','Recorded plate locations'),a.table(['Labware','Recorded position'],Object.entries(device.positions?.current || {}),
      device.positions?.status==='unknown' ? 'Positions are unknown. Isolation is retained.':'No positions declared.'));
    card.append(a.element('h3','Unresolved operations'),a.table(['Run','Step','Operation','Status'],(device.unresolved_operations || []).map(row=>[
      a.runLink(row.run_id),row.step_id,row.operation_kind,row.status]),'No unresolved operations recorded.'));
    const reasons=device.positions?.unresolved_motion || [];
    if(reasons.length) card.append(a.element('p','Position uncertainty: '+reasons.join(', '),'notice'));
    return card;
  }

  /** Stable sections keep editing and horizontal deck scroll independent of polling. */
  mount() {
    const a=this.app;
    if(a.content.querySelector('[data-region=workstation-workspace]')) return false;
    const root=a.element('div');root.dataset.region='workstation-workspace';
    const actions=a.element('div','','config-actions');
    const fresh=a.element('a','New experiment','action-link');fresh.href='#programs';actions.append(fresh);
    root.append(actions);
    for(const name of ['program','layout','run']) {
      const region=a.element('div');region.dataset.region='workstation-'+name+'-host';root.append(region);
      if(name==='program') region.dataset.region='workstation-program';
    }
    for(const [name,label] of [['runs','Runs and history'],['state','Station state and resources']]) {
      const details=a.element('details','','workstation-disclosure');details.dataset.region='workstation-'+name;
      details.append(a.element('summary',label));
      const body=a.element('div');body.dataset.region='workstation-'+name+'-host';details.append(body);root.append(details);
    }
    a.content.replaceChildren(root);return true;
  }

  region(name, key, build, force=false) {
    const target=this.app.content.querySelector(`[data-region=workstation-${name}-host]`);
    if(!target || (!force && target.renderKey===key)) return;
    const scrolls=[...target.querySelectorAll('.setup-deck-scroll,.loading-well-scroll,.table-wrap')].map(node=>[node.scrollLeft,node.scrollTop]);
    const disclosures=new Map([...target.querySelectorAll('details')].map(node=>[node.querySelector('summary')?.textContent,node.open]));
    const active=target.contains(document.activeElement) ? document.activeElement:null;
    const field=active?.dataset.field,action=active?.dataset.action,entity=active?.dataset.entityId;
    build(target);target.renderKey=key;
    for(const node of target.querySelectorAll('details')) {
      const key=node.querySelector('summary')?.textContent;
      if(disclosures.has(key)) node.open=disclosures.get(key);
    }
    [...target.querySelectorAll('.setup-deck-scroll,.loading-well-scroll,.table-wrap')].forEach((node,index)=>{
      if(scrolls[index]) [node.scrollLeft,node.scrollTop]=scrolls[index];
    });
    const next=[...target.querySelectorAll('[data-field],[data-action]')].find(node=>field ? node.dataset.field===field:action && node.dataset.action===action && node.dataset.entityId===entity);
    next?.focus({preventScroll:true});
  }

  renderState(data, target) {
    const a=this.app,inspection=data.devices || {},resources=inspection.resources || {};
    const basis=a.card('Observation source');
    basis.append(a.element('p','Recorded OS state. Hardware presence and physical contents have not been detected.','note'),
      a.details([['Device records',inspection.registration],['Local resource accounting',resources.local_accounting],['Station resource accounting',resources.station_accounting]]));
    target.replaceChildren(basis,...(inspection.devices || []).map(device=>this.device(device)),
      this.resourceTable('Station reservations',resources.station_reservations,[['Run','run_id'],['Owner','owner_id'],['State','status']]),
      this.resourceTable('Station locks',resources.station_locks,[['Resource','resource_id'],['Run','run_id']]),
      this.resourceTable('Local locks',resources.locks,[['Resource','resource_id'],['Attempt','attempt_id']]),
      this.resourceTable('Active permits',resources.permits,[['Attempt','attempt_id'],['Effect','effect_id'],['Status','status']]));
    const modules=a.card('Module state details');modules.append(a.badge('planned'),a.element('p','A shared module observation interface is not available yet. Device command parameters and receipts remain under each run.','note'));target.append(modules);
  }

  render(data, run, navigation, force=false) {
    const a=this.app,mounted=this.mount();
    if(a.activation.view?.host && a.activation.view.host.status!==data.host.status) {
      a.activation.view.host.status=data.host.status;force=true;
    }
    const activeFingerprint=data.layout?.configuration_fingerprint;
    if(a.activation.view?.active && activeFingerprint && activeFingerprint!==a.activation.view.active.fingerprint) {
      a.activation.view.active.fingerprint=activeFingerprint;force=true;
    }
    const program=a.content.querySelector('[data-region=workstation-program]');
    const switched=program.hidden!==Boolean(run);program.hidden=Boolean(run);
    if(!run && (mounted || switched || force || !program.childNodes.length)) {
      if(this.libraryError) program.replaceChildren(a.element('p',`Program selection unavailable: ${this.libraryError}`,'notice'));
      else a.programs.render();
    }
    const layoutHost=a.content.querySelector('[data-region=workstation-layout-host]');
    // A run's loading plan already includes the experiment-specific deck and contents.
    layoutHost.hidden=Boolean(run?.status==='awaiting_setup' && run?.result?.os?.setup || !run && a.programs.inspection?.preparation?.plan);
    const editableLayout={...data.layout,editing_ready:data.host.status==='ready' && !a.activation.pending() && !(data.runs || []).some(run=>!['completed','failed','rejected','cancelled'].includes(run.status))};
    this.region('layout',JSON.stringify(editableLayout),target=>target.replaceChildren(this.layout.render(editableLayout)));
    this.region('run',JSON.stringify([run,run ? null:data.host.status,a.setup.plans.get(run?.run_id),a.programs.controlMessages.get(run?.run_id)]),target=>{
      if(run) a.renderRun(run,target);
      else {const card=a.card('Station readiness');card.append(a.badge(data.host.status),a.element('p','Choose a protocol above. Its loading plan and execution results will appear here.','note'));target.replaceChildren(card);}
    },force);
    this.region('runs',JSON.stringify(data.runs),target=>{
      target.replaceChildren(a.element('h2','Active runs and queue'),a.runTable(a.navigation.constructor.runs(data.runs || [])),
        a.element('h2','Run history'),a.runTable(a.navigation.constructor.runs(data.runs || [],true)));
    });
    this.region('state',JSON.stringify(data.devices),target=>this.renderState(data,target));
    if(mounted || force) {
      if(['active','history'].includes(navigation.section)) a.content.querySelector('[data-region=workstation-runs]').open=true;
      if(navigation.section==='state') a.content.querySelector('[data-region=workstation-state]').open=true;
    }
    a.interaction.view(run ? 'run':'station',{loadState:'ready',runId:run?.run_id,runState:run?.status,hostState:data.host.status,section:'workstation'});
    if(data.host.blocked_run) a.showAlert(`Run ${data.host.blocked_run} retains the queue: ${a.display(data.host.blocked_reason)}. Inspect its evidence before further action.`);
    else if(data.host.worker_error) a.showAlert(data.host.worker_error);
  }

  async read(path, signal) {
    const response=await fetch('/api/v1'+path,{cache:'no-store',signal});
    const snapshot=await response.json();
    if(!response.ok || snapshot.schema!=='culsma_console_v1') {
      const error=new Error(snapshot.error?.code || 'CONSOLE_RESPONSE_INVALID');error.httpStatus=response.status;throw error;
    }
    return snapshot;
  }

  async refresh() {
    const a=this.app,route=location.hash || '#station',navigation=a.navigation.constructor.resolve(route);
    a.busy=true;a.syncBusy();a.button.disabled=true;
    const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),12000);
    try {
      const [station,selected]=await Promise.all([this.read('/station',controller.signal),
        navigation.runId ? this.read('/runs/'+encodeURIComponent(navigation.runId),controller.signal):null]);
      if(!a.programs.library || a.renderKey===null) {
        try {await a.programs.load();this.libraryError=null;} catch(error) {this.libraryError=error.message;}
      }
      if(selected) {await a.programs.observeControl(selected.data.run_id);await a.setup.observe(selected.data);}
      if(route!==(location.hash || '#station')) {a.pending=true;return;}
      a.lastObserved=station.observed_at;
      document.querySelector('#title').textContent='Workstation';a.navigation.select();
      document.querySelector('#connection').replaceChildren(a.badge('Connected'));
      document.querySelector('#observed').textContent=`${a.display(station.data.host.status)} · Read ${new Date(station.observed_at).toLocaleTimeString()} · OS records`;
      const changedRun=this.runId!==selected?.data.run_id;
      if(changedRun) {const target=a.content.querySelector('[data-region=workstation-run-host]');if(target) target.replaceChildren();}
      this.runId=selected?.data.run_id;
      if(a.renderKey!==route) a.showAlert(null);
      this.render(station.data,selected?.data,navigation,a.renderKey===null || changedRun);
      a.renderKey=route;
    } catch(error) {
      if(route!==(location.hash || '#station')) {a.pending=true;return;}
      a.renderKey=null;a.interaction.view('station',{loadState:'unavailable'});
      document.querySelector('#connection').replaceChildren(a.badge('Disconnected'));
      a.showAlert(`Read unavailable: ${error.message}`);
      a.content.replaceChildren(a.element('p','No current snapshot. Existing station records are unchanged.','empty'));
    } finally {
      clearTimeout(deadline);a.busy=false;a.syncBusy();a.button.disabled=false;
      if(a.pending) {a.pending=false;a.refresh();}
      else if(!document.hidden && a.navigation.constructor.resolve(location.hash).group==='Workstation') a.timer=setTimeout(()=>a.refresh(),2500);
    }
  }
}

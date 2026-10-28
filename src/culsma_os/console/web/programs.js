export class ConsolePrograms {
  constructor(app) {
    this.app = app;
    this.inspection = null;
    this.selection = null;
    this.bindingReview = null;
    this.bindingDraft = null;
    this.drafts = [];
    this.working = false;
    this.controlMessages = new Map();
  }

  pending(key) {
    try { return JSON.parse(sessionStorage.getItem(`culsma-console:${key}`) || 'null'); }
    catch { return null; }
  }

  remember(key, value) {
    // Store request identities, never credentials; storage failure prevents submission.
    if (value === null) sessionStorage.removeItem(`culsma-console:${key}`);
    else sessionStorage.setItem(`culsma-console:${key}`,JSON.stringify(value));
  }

  async request(payload = null) {
    if (!this.app.configToken) {
      const session = await this.app.configurationFetch('/api/v1/session');
      this.app.configToken = session.access_token;
    }
    return this.app.configurationFetch('/api/v1/programs',payload);
  }

  async load() {
    this.library = await this.request();
    try { await this.app.activation.refresh(); } catch { this.app.activation.view = null; }
    const drafts = await this.app.configurationFetch('/api/v1/configuration/drafts');
    this.drafts = drafts.drafts || [];
    if (this.bindingReview && !this.drafts.some(draft => draft.draft_id === this.bindingReview.draft_id && draft.revision === this.bindingReview.revision)) this.bindingReview = null;
  }

  render() {
    const a=this.app,target=a.content.querySelector('[data-region=workstation-program]');
    if(!target || target.hidden) return;
    const card=a.card('Run an experiment');card.dataset.region='experiment-picker';
    card.append(a.element('p','Select a file to view it. Double-click or choose Run protocol to start. Preparation checks run automatically.','note'));
    const selected=this.selection || '';
    if(!this.library?.enabled) card.append(a.element('p','No experiment library is available for this station.','notice'));
    if(!selected) card.append(a.element('p','Choose a protocol from Files to begin.','empty'));
    a.interaction.view('programs',{loadState:this.working ? 'loading':'ready',programId:selected,
      snapshotId:this.inspection?.snapshot_id,validationState:this.inspection ? (this.inspection.valid ? 'valid':'invalid'):'not_checked'});
    if(this.working) card.append(a.element('p',this.opened ? 'Preparing experiment requirements…':'Reading protocol…','notice'));
    if(this.previewError) card.append(a.element('p',this.previewError,'notice'));
    if(selected && !this.working) card.append(a.configButton('Run protocol',()=>this.launch(selected),'',
      {action:'program.check',entity:selected}));
    const children=[card],inspection=this.inspection,preparation=inspection?.preparation;
    const current=this.app.activation.view?.active?.fingerprint;
    const stale=!!inspection && this.reviewedConfiguration?.fingerprint!==current;
    if(inspection) {
      const view=a.card(this.opened ? 'Experiment requirements':'Protocol preview');view.dataset.region='experiment-requirements';
      view.append(a.element('h3',inspection.program_id));
      if(this.opened && stale) view.append(a.element('p','The station layout changed. Refresh requirements before preparing this experiment.','notice'));
      if(!inspection.valid) view.append(a.element('p','This protocol needs correction before it can run.','notice'),
        a.table(['Problem','Severity'],(inspection.diagnostics || []).map(d=>[d.code,d.severity])));
      else if(preparation?.status==='available') {
        const plan=preparation.plan;
        const relocated=plan.items.filter(item=>item.preferred_satisfied===false);
        if(relocated.length) view.append(a.element('p',`Some preferred positions are unavailable: ${relocated.map(item=>item.name || item.allocation_id).join(', ')}. Review the proposed replacements below.`,'notice'));
        view.append(a.element('p',`${plan.loadout.length} labware items · ${plan.items.length} containers or wells · ${(plan.supplies || []).length} supply location${(plan.supplies || []).length===1 ? '':'s'}`,'experiment-summary'),
          a.element('p','Proposed loading on the current station. Select a checklist item or its position on the deck to inspect the same item.','note'),
          a.setup.layout.render(plan,{run_id:'preview:'+inspection.snapshot_id}),
          a.element('p','Volumes are initial quantities requested by the protocol. Tip availability is declared; the driver checks the exact requirement before execution. Nothing has been reserved or physically detected.','note'));
      } else if(preparation?.status==='blocked') {
        view.append(a.element('p','The current layout cannot accommodate this protocol. Update the labware or its configured capacity, then refresh requirements.','notice'),
          a.table(['Required container','Kind','Capacity (µL)','Initial volume (µL)'],(preparation.requirements || []).map(r=>[r.name,r.kind,r.capacity_uL,r.initial_volume_uL])),
          a.element('p',preparation.diagnostic,'mono'));
      } else if(inspection.valid && this.opened) view.append(a.element('p','This driver does not provide a loading preview. Running still uses the station configuration and execution checks.','notice'));
      if(preparation && preparation.status!=='unsupported') view.append(a.configButton('Change station labware',()=>{
        this.inspection=null;this.selection=null;this.render();
        a.content.querySelector('[data-region=workstation-layout-host]')?.scrollIntoView({block:'start'});
      },'',{action:'program.edit-labware'}));
      if(!this.opened && inspection.valid) view.append(a.element('p',`${inspection.allocations.length} containers or wells · Culsma protocol`,'experiment-summary'),a.element('p','Run this protocol to check preparation and start on the current workstation.','note'));
      const technical=a.element('details');technical.append(a.element('summary','Protocol source and validation details'),
        a.element('p',inspection.scope,'note'),a.element('p',`Operations: ${(inspection.operations || []).join(', ')}`),
        a.element('pre',inspection.source || 'Source unavailable','record-json'));
      if(inspection.valid) technical.append(this.renderBindings());view.append(technical);children.push(view);
    }
    const pending=this.pending('submission');
    if(pending) {
      const action=a.card('Run request');
      action.append(a.element('p',`Waiting for the request for ${pending.program_id}. Check its outcome before starting another experiment.`,'notice'));
      const button=a.configButton('Check run request',()=>this.submit(),'',{action:'program.submit',entity:pending.program_id});
      button.disabled=this.working;action.append(button);children.push(action);
    }
    this.mountFiles();
    target.replaceChildren(...children);
    for(const field of target.querySelectorAll('input,select')) field.disabled=this.working || !!pending;
    const layout=a.content.querySelector('[data-region=workstation-layout-host]');
    if(layout) layout.hidden=!!preparation?.plan;
  }

  bindingIsActive(report) {
    const origin = this.app.activation.view?.active?.origin;
    return !!origin && origin.draft_id === report.draft_id && origin.revision === report.revision
      && origin.configuration_fingerprint === report.fingerprint;
  }

  renderBindings() {
    const a = this.app;
    const card = a.card('Check program bindings');
    card.dataset.region = 'program-bindings';
    card.append(a.element('p','Compare this reviewed source snapshot with a saved configuration. This does not change the running service configuration or select a configuration for submission.','note'));
    const selected = this.drafts.find(draft => draft.draft_id === this.bindingDraft) || this.drafts[0];
    this.bindingDraft = selected?.draft_id || null;
    if (!selected) {
      card.append(a.element('p','Save a configuration draft first.','empty'));
      return card;
    }
    const label = draft => `${draft.title} · r${draft.revision} · ${draft.draft_id}`;
    card.append(a.configField('Saved configuration',label(selected),value => {
      this.bindingDraft = this.drafts.find(draft => label(draft) === value)?.draft_id || null;
      this.bindingReview = null;
      const draft = this.drafts.find(item => item.draft_id === this.bindingDraft);
      this.app.interaction.result('program.check-bindings','not_checked','Configuration selection changed. Check the selected saved bindings.',{entity:draft?.draft_id,revision:draft?.revision});
      this.render();
    },this.drafts.map(label),{field:'/binding-draft'}));
    const button = a.configButton('Check saved bindings',() => this.checkBindings(selected),'',
      {action:'program.check-bindings',entity:selected.draft_id,revision:selected.revision});
    button.disabled = this.working;card.append(button);
    if (this.bindingReview) {
      const report = this.bindingReview;
      card.dataset.validationState = report.valid ? 'valid':'invalid';
      card.dataset.draftId = report.draft_id;card.dataset.revision = report.revision;
      card.dataset.snapshotId = report.snapshot_id;
      card.append(a.badge(report.valid ? 'valid':'invalid'),a.details([
        ['Configuration',`${report.draft_id} · r${report.revision}`],['Program snapshot',report.snapshot_id],
        ['Activation',this.bindingIsActive(report) ? 'This saved revision is active':'Review only · this is not the active saved revision']
      ]),a.element('p',report.scope,'note'));
      card.append(a.table(['Allocation','Name','Physical address','Status'],report.bindings.map(item => [
        item.allocation_id,item.name || '—',item.address ? `${item.address.labware} / ${item.address.well}`:'—',item.status
      ]),'No binding comparison available.'));
      card.append(a.table(['Owner','Code','Message'],report.diagnostics.map(item => [item.owner,item.code,item.message || '']),
        'Bindings match this snapshot. Worker preflight is still required.'));
    } else card.dataset.validationState = 'not_checked';
    return card;
  }

  async checkBindings(draft) {
    if (this.working || !this.inspection?.valid) return;
    this.working = true;this.bindingReview = null;this.app.syncBusy();this.render();
    this.app.interaction.result('program.check-bindings','pending','Checking saved configuration bindings.',{entity:draft.draft_id,revision:draft.revision});
    try {
      this.bindingReview = await this.app.configurationFetch('/api/v1/configuration/program-bindings',{
        draft_id:draft.draft_id,revision:draft.revision,program_id:this.inspection.program_id,snapshot_id:this.inspection.snapshot_id
      });
      this.app.interaction.result('program.check-bindings',this.bindingReview.valid ? 'succeeded':'invalid',
        this.bindingReview.valid ? 'Bindings match the reviewed program. This check did not change the active configuration.':'Binding checks found problems; inspect the report.',
        {entity:draft.draft_id,revision:draft.revision});
      this.app.showAlert(null);
    } catch (error) {
      this.app.interaction.result('program.check-bindings',this.app.interaction.responseOutcome(error,true),error.message,
        {entity:draft.draft_id,revision:draft.revision});
      this.app.showAlert(error.message);
    } finally {
      this.working = false;this.app.syncBusy();this.render();
      if (this.app.content.querySelector('[data-region=workstation-program]:not([hidden])')) this.app.interaction.focus('program.check-bindings');
    }
  }

  mountFiles() {
    const host=this.app.content.querySelector('[data-region=workstation-files]'),files=this.renderFiles();
    if(host && host.firstElementChild!==files) host.replaceChildren(files);
  }

  renderFiles() {
    const a=this.app;
    // Keep file buttons mounted during reads so a second click reaches dblclick.
    if(!this.files || this.filesLibrary!==this.library) {
      this.filesLibrary=this.library;
      this.files=a.element('aside','','program-files card');this.files.setAttribute('aria-label','Program files');
      this.files.append(a.element('h2','Files'));
      this.files.append(a.element('p',this.library?.source_root || 'No program directory configured.','program-location'));
      const actions=a.element('div','','program-file-actions');
      const refresh=a.configButton('Refresh files',()=>this.refreshFiles(),'',{action:'program.refresh-files'});
      actions.append(refresh);this.files.append(actions);
      const list=a.element('ul','','program-file-list');list.setAttribute('aria-label','Protocols');
      const folders=new Map([['',list]]);
      for(const item of this.library?.programs || []) {
        const parts=item.program_id.split('/');let parent=list,path='';
        for(const part of parts.slice(0,-1)) {
          path=path ? path+'/'+part:part;
          if(!folders.has(path)) {
            const row=a.element('li'),folder=a.element('details');folder.open=true;folder.dataset.folder=path;
            folder.append(a.element('summary',part));const nested=a.element('ul');folder.append(nested);row.append(folder);parent.append(row);folders.set(path,nested);
          }
          parent=folders.get(path);
        }
        const row=a.element('li'),button=a.configButton(parts.at(-1),()=>this.openFile(item.program_id,false),'',
          {action:'program.select',entity:item.program_id});
        button.classList.add('program-file');button.title=item.program_id;button.setAttribute('aria-label',item.program_id);
        button.addEventListener('dblclick',()=>this.openFile(item.program_id,true));
        row.append(button);parent.append(row);
      }
      if(!this.library?.programs?.length) this.files.append(a.element('p','Add .culs files or project folders to this directory, then refresh.','empty'));
      this.files.append(list,a.element('p','Single-click: view · Double-click: run. Preparation checks run automatically.','note'));
    }
    this.files.querySelector('[data-action="program.refresh-files"]').disabled=this.working || this.refreshing || !this.library?.enabled;
    for(const button of this.files.querySelectorAll('[data-action="program.select"]')) {
      button.setAttribute('aria-pressed',String(button.dataset.entityId===this.selection));
      button.disabled=!!this.pending('submission') || !!this.launching;
    }
    return this.files;
  }

  openFile(programId, prepare) {
    if(this.pending('submission') || this.launching) return;
    if(location.hash!=='#station' && location.hash!=='#programs') location.hash='#station';
    return prepare ? this.launch(programId):this.inspect(programId,false);
  }

  async launch(programId) {
    if(this.launching || this.pending('submission')) return;
    this.launching=true;
    try {
      await this.inspect(programId,true);
      if(this.selection===programId && this.inspection?.valid && this.inspection.preparation?.status!=='blocked')
        await this.submit();
    } finally {this.launching=false;this.render();this.mountFiles();}
  }

  async refreshFiles() {
    if(this.working || this.refreshing) return;
    this.refreshing=true;this.mountFiles();
    try {this.library=await this.request();this.previewError=null;}
    catch(error) {this.previewError='Unable to read files: '+error.message;}
    finally {this.refreshing=false;this.mountFiles();this.render();}
  }

  async inspect(programId, prepare=true) {
    if(this.pending('submission')) return;
    const version=this.readVersion=(this.readVersion || 0)+1;
    this.selection=programId;this.opened=prepare;this.inspection=null;this.bindingReview=null;this.previewError=null;
    this.reviewedConfiguration=null;
    this.working=true;this.app.syncBusy();this.render();
    // Source selection stays local to the detail pane so a status banner cannot
    // move the file under the pointer between the two clicks of a double-click.
    if(prepare) this.app.interaction.result('program.check','pending','Matching protocol requirements to this station.',{entity:programId});
    try {
      let configuration=null;
      if(prepare) {
        await this.app.activation.refresh();
        if(version!==this.readVersion) return;
        configuration=structuredClone(this.app.activation.view.active);
      }
      const inspection=await this.request({action:prepare ? 'preview':'inspect',program_id:programId});
      if(version!==this.readVersion) return;
      this.inspection=inspection;this.reviewedConfiguration=configuration;
      if(configuration) {
        this.bindingDraft=configuration.origin?.draft_id || this.bindingDraft;
        if(inspection.preparation) configuration.fingerprint=inspection.preparation.configuration_fingerprint;
      }
      if(prepare) {
        const blocked=inspection.preparation?.status==='blocked';
        this.app.interaction.result('program.check',inspection.valid && !blocked ? 'succeeded':'invalid',
          blocked ? 'Preparation failed: '+inspection.preparation.diagnostic:inspection.valid ? 'Preparation checks passed. Starting the experiment.':'Source checks rejected this program.',{entity:programId});
        this.app.showAlert(blocked ? inspection.preparation.diagnostic:null);
      }
    } catch(error) {
      if(version!==this.readVersion) return;
      this.previewError='Unable to prepare requirements: '+error.message;
      if(prepare) {
        this.app.interaction.result('program.check',this.app.interaction.responseOutcome(error,true),error.message,{entity:programId});
        this.app.showAlert(error.message);
      }
    } finally {
      if(version===this.readVersion) {this.working=false;this.app.syncBusy();this.render();}
    }
  }

  async submit() {
    if (this.working) return;
    if(!this.pending('submission') && (!this.inspection?.valid || this.inspection.preparation?.status==='blocked'
      || this.reviewedConfiguration?.fingerprint!==this.app.activation.view?.active?.fingerprint)) return;
    this.working = true;this.app.syncBusy();this.render();
    let payload;
    const retained=this.pending('submission');
    try {
      payload = retained || {action:'start',program_id:this.inspection.program_id,
        snapshot_id:this.inspection.snapshot_id,request_id:crypto.randomUUID(),configuration_fingerprint:this.reviewedConfiguration.fingerprint};
      this.remember('submission',payload);
      this.app.interaction.result('program.submit','pending','Submission pending. Request identity retained.',{entity:payload.program_id,requestId:payload.request_id});
      const result = await this.request(payload);
      this.remember('submission',null);
      this.app.showAlert(null);
      this.app.interaction.result('program.submit','acknowledged','Run requested. Preparation checks run automatically; follow the progress and result below.',{entity:result.run.run_id,requestId:payload.request_id});
      location.hash = `#run/${encodeURIComponent(result.run.run_id)}`;
    } catch (error) {
      const rejected=!retained && Number.isInteger(error.httpStatus) && error.httpStatus<500;
      if(rejected) this.remember('submission',null);
      const message=rejected ? `Unable to start: ${error.message}`:`${error.message}. Request identity retained; no automatic retry.`;
      this.app.interaction.result('program.submit',this.app.interaction.responseOutcome(error),message,{entity:payload?.program_id,requestId:payload?.request_id});
      this.app.showAlert(message);
    }
    finally { this.working = false;this.app.syncBusy();this.render(); }
  }

  renderControls(run) {
    const a = this.app;
    const card = a.card('Run controls');
    card.dataset.region = 'run-controls';card.dataset.entityId = run.run_id;
    card.append(a.element('p','Requests enter the existing worker control queue. Pause applies at an execution boundary; cancel does not undo completed actions. An acknowledgement is not proof that a control has been applied.','note'));
    const key = `control:${run.run_id}`;
    const pending = this.pending(key);
    const actions = pending ? (pending.acknowledged ? []:[pending.action]) : run.status === 'awaiting_setup' ? ['cancel'] : run.status === 'paused' ? ['resume','cancel'] : ['ready','running','waiting','finalizing'].includes(run.status) ? ['pause','cancel'] : [];
    for (const action of actions) {
      const button = a.configButton(pending ? `Retry same ${action} request` : `${action[0].toUpperCase()+action.slice(1)} run`,() => this.control(run.run_id,action),'',{action:`run.${action}`,entity:run.run_id});
      button.disabled = this.working;card.append(button);
    }
    if (run.status === 'needs_reconciliation') card.append(a.element('p','Execution outcome needs reconciliation. Isolation is retained; this console cannot reconcile or restart this run.','notice'));
    if (pending?.acknowledged) card.append(a.element('p','Control request acknowledged; waiting for the worker result.','note'));
    if (!actions.length && !pending && run.status !== 'needs_reconciliation') card.append(a.element('p','No control is available for this state.','empty'));
    if (this.controlMessages.has(run.run_id)) card.append(a.element('p',this.controlMessages.get(run.run_id),'notice'));
    if ((run.pending_controls || []).length) card.append(a.table(['Request','Action','State'],run.pending_controls.map(item => [item.request_id,item.action,item.status || 'pending'])));
    return card;
  }

  async observeControl(runId) {
    const key = `control:${runId}`;
    const pending = this.pending(key);
    if (!pending) return;
    try {
      const result = await this.request({action:'control-status',run_id:runId,request_id:pending.request_id});
      const status = result.acknowledgement;
      const message = `${pending.action}: ${status.status}${status.error ? ` · ${status.error}`:''}`;
      this.controlMessages.set(runId,message);
      if (this.app.interaction.status.hidden || this.app.interaction.status.dataset.requestId === pending.request_id)
        this.app.interaction.result(`run.${pending.action}`,status.status,message,{entity:runId,requestId:pending.request_id});
      if (['applied','rejected'].includes(status.status)) this.remember(key,null);
      else this.remember(key,{...pending,acknowledged:true});
    } catch { /* Keep the identity; an unavailable receipt never means not accepted. */ }
  }

  async control(runId,action) {
    if (this.working) return;
    this.working = true;this.app.syncBusy();
    for (const button of this.app.content.querySelectorAll('button[data-action^="run."]')) button.disabled = true;
    let payload;
    try {
      const key = `control:${runId}`;
      const saved = this.pending(key);
      payload = saved ? {action:saved.action,run_id:saved.run_id,request_id:saved.request_id}
        : {action,run_id:runId,request_id:crypto.randomUUID()};
      this.remember(key,payload);
      this.app.interaction.result(`run.${payload.action}`,'pending','Run control request pending.',{entity:runId,requestId:payload.request_id});
      await this.request(payload);
      this.remember(key,{...payload,acknowledged:true});
      this.controlMessages.set(runId,`${payload.action} request acknowledged. Inspect the run state and pending controls for the applied result.`);
      this.app.interaction.result(`run.${payload.action}`,'acknowledged',`${payload.action} request acknowledged; waiting for the worker result.`,{entity:runId,requestId:payload.request_id});
      this.app.showAlert(null);
    } catch (error) {
      const message = `${error.message}. The same request ID is retained for retry.`;
      this.controlMessages.set(runId,message);
      this.app.interaction.result(`run.${action}`,this.app.interaction.responseOutcome(error),message,{entity:runId,requestId:payload?.request_id});
    }
    finally { this.working = false;this.app.syncBusy();this.app.renderKey = null;this.app.refresh(); }
  }
}

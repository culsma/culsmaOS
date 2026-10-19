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

  async refresh() {
    this.app.interaction.view('programs',{loadState:'loading'});
    this.app.busy = true;this.app.syncBusy();
    this.app.button.disabled = true;
    try {
      this.library = await this.request();
      const drafts = await this.app.configurationFetch('/api/v1/configuration/drafts');
      this.drafts = drafts.drafts || [];
      if (this.bindingReview && !this.drafts.some(draft => draft.draft_id === this.bindingReview.draft_id && draft.revision === this.bindingReview.revision)) this.bindingReview = null;
      if (location.hash !== '#programs') return;
      this.app.showAlert(null);
      this.render();
    } catch (error) {
      if (location.hash === '#programs') this.app.interaction.view('programs',{loadState:'unavailable'});
      this.app.showAlert(error.message);
    } finally {
      this.app.busy = false;this.app.syncBusy();
      this.app.button.disabled = false;
      if (this.app.pending) { this.app.pending = false; this.app.refresh(); }
    }
  }

  render() {
    if (location.hash !== '#programs') return;
    const a = this.app;
    document.querySelector('#title').textContent = 'Submit a program';
    for (const id of ['station','runs','configuration','programs']) document.querySelector(`#${id}-tab`).setAttribute('aria-current',id === 'programs' ? 'page':'false');
    document.querySelector('#connection').replaceChildren(a.element('span','Local library','badge neutral'));
    document.querySelector('#observed').textContent = 'Program library · explicit submission to the selected resident service';
    const card = a.card('Choose and check');
    card.append(a.element('p','Programs use the running service configuration. Configuration drafts are not activated here. A successful source check does not prove that the station has the required layout or consumables.','note'));
    if (!this.library?.enabled) card.append(a.element('p','Program selection is disabled. Start this console with --program-root pointing to a trusted source directory.','notice'));
    const selected = this.selection || this.library?.programs?.[0]?.program_id;
    this.selection = selected;
    a.interaction.view('programs',{loadState:'ready',programId:selected,snapshotId:this.inspection?.snapshot_id,
      validationState:this.inspection ? (this.inspection.valid ? 'valid':'invalid'):'not_checked'});
    card.append(a.configField('Program',selected,value => {
      this.selection = value;this.inspection = null;this.bindingReview = null;
      this.app.interaction.result('program.check','not_checked','Program selection changed. Check the source before continuing.',{entity:value});this.render();
    },(this.library?.programs || []).map(item => item.program_id),{field:'/program-id'}));
    const check = a.configButton('Check program',() => this.inspect(selected),'',{action:'program.check',entity:selected});
    check.disabled = this.working || !selected;card.append(check);
    const children = [card];
    if (this.inspection) {
      const view = a.card('Reviewed source snapshot');
      view.append(a.badge(this.inspection.valid ? 'valid':'invalid'),a.details([
        ['Program',this.inspection.program_id],['Snapshot',a.element('span',this.inspection.snapshot_id,'mono')],
        ['Configuration','Running service · worker preflight still required']
      ]),a.element('p',this.inspection.scope,'note'));
      view.append(a.table(['Diagnostic','Severity'],(this.inspection.diagnostics || []).map(item => [item.code,item.severity]),'No source diagnostics.'));
      view.append(a.table(['Allocation','Name'],(this.inspection.allocations || []).map(item => [item.allocation_id,item.name]),'No container allocations.'));
      view.append(a.element('p',`Operations: ${(this.inspection.operations || []).join(', ')}`,'note'));
      const source = a.element('details');source.append(a.element('summary','Program source'),a.element('pre',this.inspection.source || 'Source unavailable','record-json'));view.append(source);
      children.push(view);
      if (this.inspection.valid) children.push(this.renderBindings());
    }
    const pending = this.pending('submission');
    if (pending || this.inspection?.valid) {
      const submit = a.card('Submit to the resident queue');
      if (pending) submit.append(a.element('p',`A submission receipt is still pending for ${pending.program_id}. Retry uses the same saved request ID; it does not create a new submission identity.`,'notice'));
      else submit.append(a.element('p','Submit the reviewed snapshot. The existing worker performs device preflight and records execution evidence. Admission is not completed execution.','note'));
      const button = a.configButton(pending ? 'Retry same submission':'Submit reviewed snapshot',() => this.submit(),'',
        {action:'program.submit',entity:pending?.program_id || this.inspection.program_id});
      button.disabled = this.working;submit.append(button);children.push(submit);
    }
    a.content.replaceChildren(...children);
    for (const field of a.content.querySelectorAll('input,select')) field.disabled = this.working;
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
        ['Activation','Not applied · submissions still use the running service']
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
        this.bindingReview.valid ? 'Bindings match the reviewed program. Configuration has not been applied.':'Binding checks found problems; inspect the report.',
        {entity:draft.draft_id,revision:draft.revision});
      this.app.showAlert(null);
    } catch (error) {
      this.app.interaction.result('program.check-bindings',this.app.interaction.responseOutcome(error,true),error.message,
        {entity:draft.draft_id,revision:draft.revision});
      this.app.showAlert(error.message);
    } finally {
      this.working = false;this.app.syncBusy();this.render();
      if (location.hash === '#programs') this.app.interaction.focus('program.check-bindings');
    }
  }

  async inspect(programId) {
    if (this.working) return;
    this.selection = programId;this.inspection = null;this.bindingReview = null;
    this.working = true;this.app.syncBusy();this.render();
    this.app.interaction.result('program.check','pending','Checking program source.',{entity:programId});
    try {
      this.inspection = await this.request({action:'inspect',program_id:programId});
      this.app.interaction.result('program.check',this.inspection.valid ? 'succeeded':'invalid',
        this.inspection.valid ? 'Source snapshot checked. Device and resource preflight still runs in the worker.':'Source checks rejected this program.',{entity:programId});
      this.app.showAlert(null);
    } catch (error) {
      this.app.interaction.result('program.check',this.app.interaction.responseOutcome(error,true),error.message,{entity:programId});
      this.app.showAlert(error.message);
    }
    finally {
      this.working = false;this.app.syncBusy();this.render();
      if (location.hash === '#programs') this.app.interaction.focus(this.inspection?.valid ? 'program.submit':'program.check');
    }
  }

  async submit() {
    if (this.working) return;
    this.working = true;this.app.syncBusy();this.render();
    let payload;
    try {
      payload = this.pending('submission') || {action:'submit',program_id:this.inspection.program_id,
        snapshot_id:this.inspection.snapshot_id,request_id:crypto.randomUUID()};
      this.remember('submission',payload);
      this.app.interaction.result('program.submit','pending','Submission pending. Request identity retained.',{entity:payload.program_id,requestId:payload.request_id});
      const result = await this.request(payload);
      this.remember('submission',null);
      this.app.showAlert(null);
      this.app.interaction.result('program.submit','acknowledged','Program admitted to the queue. Follow the run state for execution outcome.',{entity:result.run.run_id,requestId:payload.request_id});
      location.hash = `#run/${encodeURIComponent(result.run.run_id)}`;
    } catch (error) {
      const message = `${error.message}. Request identity retained; no automatic retry.`;
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
    const actions = pending ? (pending.acknowledged ? []:[pending.action]) : run.status === 'paused' ? ['resume','cancel'] : ['ready','running','waiting','finalizing'].includes(run.status) ? ['pause','cancel'] : [];
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

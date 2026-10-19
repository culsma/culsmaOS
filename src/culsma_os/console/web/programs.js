export class ConsolePrograms {
  constructor(app) {
    this.app = app;
    this.inspection = null;
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
    this.app.busy = true;
    this.app.button.disabled = true;
    try {
      this.library = await this.request();
      if (location.hash !== '#programs') return;
      this.app.showAlert(null);
      this.render();
    } catch (error) {
      this.app.showAlert(error.message);
    } finally {
      this.app.busy = false;
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
    let selected = this.inspection?.program_id || this.library?.programs?.[0]?.program_id;
    card.append(a.configField('Program',selected,value => { selected = value; },(this.library?.programs || []).map(item => item.program_id)));
    const check = a.configButton('Check program',() => this.inspect(selected));
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
    }
    const pending = this.pending('submission');
    if (pending || this.inspection?.valid) {
      const submit = a.card('Submit to the resident queue');
      if (pending) submit.append(a.element('p',`A submission receipt is still pending for ${pending.program_id}. Retry uses the same saved request ID; it does not create a new submission identity.`,'notice'));
      else submit.append(a.element('p','Submit the reviewed snapshot. The existing worker performs device preflight and records execution evidence. Admission is not completed execution.','note'));
      const button = a.configButton(pending ? 'Retry same submission':'Submit reviewed snapshot',() => this.submit());
      button.disabled = this.working;submit.append(button);children.push(submit);
    }
    a.content.replaceChildren(...children);
  }

  async inspect(programId) {
    if (this.working) return;
    this.inspection = null;
    this.working = true;this.render();
    try {
      this.inspection = await this.request({action:'inspect',program_id:programId});
      this.app.showAlert(null);
    } catch (error) { this.app.showAlert(error.message); }
    finally { this.working = false;this.render(); }
  }

  async submit() {
    if (this.working) return;
    this.working = true;this.render();
    try {
      const payload = this.pending('submission') || {action:'submit',program_id:this.inspection.program_id,
        snapshot_id:this.inspection.snapshot_id,request_id:crypto.randomUUID()};
      this.remember('submission',payload);
      const result = await this.request(payload);
      this.remember('submission',null);
      this.app.showAlert(null);
      location.hash = `#run/${encodeURIComponent(result.run.run_id)}`;
    } catch (error) { this.app.showAlert(`${error.message}. No new submission ID was generated. You can retry the same request.`); }
    finally { this.working = false;this.render(); }
  }

  renderControls(run) {
    const a = this.app;
    const card = a.card('Run controls');
    card.append(a.element('p','Requests enter the existing worker control queue. Pause applies at an execution boundary; cancel does not undo completed actions. An acknowledgement is not proof that a control has been applied.','note'));
    const key = `control:${run.run_id}`;
    const pending = this.pending(key);
    const actions = pending ? (pending.acknowledged ? []:[pending.action]) : run.status === 'paused' ? ['resume','cancel'] : ['ready','running','waiting','finalizing'].includes(run.status) ? ['pause','cancel'] : [];
    for (const action of actions) {
      const button = a.configButton(pending ? `Retry same ${action} request` : `${action[0].toUpperCase()+action.slice(1)} run`,() => this.control(run.run_id,action));
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
      this.controlMessages.set(runId,`${pending.action}: ${status.status}${status.error ? ` · ${status.error}`:''}`);
      if (['applied','rejected'].includes(status.status)) this.remember(key,null);
      else this.remember(key,{...pending,acknowledged:true});
    } catch { /* Keep the identity; an unavailable receipt never means not accepted. */ }
  }

  async control(runId,action) {
    if (this.working) return;
    this.working = true;
    try {
      const key = `control:${runId}`;
      const payload = this.pending(key) || {action,run_id:runId,request_id:crypto.randomUUID()};
      this.remember(key,payload);
      await this.request(payload);
      this.remember(key,{...payload,acknowledged:true});
      this.controlMessages.set(runId,`${payload.action} request acknowledged. Inspect the run state and pending controls for the applied result.`);
      this.app.showAlert(null);
    } catch (error) { this.controlMessages.set(runId,`${error.message}. The same request ID is retained for retry.`); }
    finally { this.working = false;this.app.renderKey = null;this.app.refresh(); }
  }
}

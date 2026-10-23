export class ConsoleRunSetup {
  constructor(app) {
    this.app = app;
    this.plans = new Map();
    this.edits = new Map();
    this.confirmations = new Map();
    this.expanded = new Set();
    this.working = false;
  }

  async request(payload, confirmation = false) {
    if (!this.app.configToken) {
      const session = await this.app.configurationFetch('/api/v1/session');
      this.app.configToken = session.access_token;
    }
    return this.app.configurationFetch(confirmation ? '/api/v1/setup/confirmation':'/api/v1/setup', payload);
  }

  async observe(run) {
    if (!run.result?.os?.setup) return;
    const plan = await this.request({action:'show',run_id:run.run_id});
    const previous = this.plans.get(run.run_id);
    if (previous?.fingerprint !== plan.fingerprint) {
      this.confirmations.delete(run.run_id);
      // Preserve unsaved edits with their old fingerprint: the OS will reject an overwrite.
      if (!this.edits.get(run.run_id)?.dirty) this.edits.delete(run.run_id);
    }
    this.plans.set(run.run_id,plan);
    const pending = this.pending(run.run_id);
    if (pending) {
      const receipt = await this.request({action:'status',run_id:run.run_id,request_id:pending.request_id});
      if (['completed','failed'].includes(receipt.status)) {
        this.remember(run.run_id,null);
        if (receipt.status === 'completed') this.edits.delete(run.run_id);
        this.app.interaction.result(`setup.${pending.action}`,receipt.status,receipt.error || `${pending.action} applied.`,
          {entity:run.run_id,requestId:pending.request_id});
      }
    }
  }

  pending(runId) {
    try {return JSON.parse(sessionStorage.getItem(`culsma-setup:${runId}`) || 'null');}
    catch {return null;}
  }

  remember(runId, value) {
    const key = `culsma-setup:${runId}`;
    if (value) sessionStorage.setItem(key,JSON.stringify(value));
    else sessionStorage.removeItem(key);
  }

  render(run) {
    const a = this.app;
    const plan = this.plans.get(run.run_id) || run.result?.os?.setup;
    if (!plan) return a.element('span');
    const card = a.card('Prepare and load');
    card.dataset.region = 'run-setup';card.dataset.setupFingerprint = plan.fingerprint || '';
    card.append(a.badge(plan.phase || 'unavailable'),a.element('p',
      'One shared plan for console and MCP. Place the listed labware and contents, then confirm this exact plan. No physical detection is implied.','note'));
    if (!plan.fingerprint) {card.append(a.element('p',plan.error || 'Waiting for a valid loading plan.','notice'));return card;}
    const editable = run.status === 'awaiting_setup';
    for (const item of plan.loadout || []) {
      const section = a.element('section','','setup-labware');
      section.dataset.labwareId = item.labware;
      const place = item.placement || {};
      section.append(a.element('h3',`${item.model || item.labware} · ${item.labware}`),
        a.element('p',`Carrier ${place.carrier || '—'} · track ${place.track || '—'} · site ${place.site || '—'}`),
        a.element('p',place.orientation || 'Use the declared labware orientation.','note'));
      section.append(a.table(['Container','Position','Initial volume (µL)','Contents'],(item.containers || []).map(c => [
        c.name,c.well,c.volume_uL,this.contents(c.contents)
      ])));
      card.append(section);
    }
    if ((plan.supplies || []).length) card.append(a.table(['Supply','Model','Placement','Available positions','Declared available','Requirement check'],plan.supplies.map(s => [
      s.id,s.model,`Carrier ${s.carrier || '—'} · track ${s.track || '—'} · site ${s.site || '—'}`,
      (s.positions || []).join(', '),s.available,s.requirement_status === 'checked_during_driver_preparation' ? 'Checked before execution':s.requirement_status
    ])));
    if (editable) this.renderPlacement(card,run,plan);
    const pending = this.pending(run.run_id);
    if (pending) {
      const retry = a.configButton(`Retry same ${pending.action} request`,() => this.command(run,plan,pending.action), '',
        {action:`setup.${pending.action}`,entity:run.run_id});
      retry.disabled = this.working;card.append(retry,a.element('p','Request identity retained until its outcome is known.','note'));
    } else if (editable && plan.phase === 'planned') {
      const begin = a.configButton('Begin loading · reserve station',() => this.command(run,plan,'begin'),'',
        {action:'setup.begin',entity:run.run_id});
      begin.disabled = this.working;card.append(begin);
    } else if (editable && plan.phase === 'loading') {
      card.append(a.element('p','Station reserved. Load every item above before confirming.','notice'));
      const label = a.element('label');const check = a.element('input');check.type = 'checkbox';
      check.checked = this.confirmations.get(run.run_id) === plan.fingerprint;
      check.setAttribute('aria-label','I loaded every item according to this plan');
      a.interaction.identify(check,{field:'/setup/loaded',entity:run.run_id});
      check.addEventListener('change',() => {
        if (check.checked) this.confirmations.set(run.run_id,plan.fingerprint);else this.confirmations.delete(run.run_id);
        confirm.disabled = !check.checked || this.working;
      });
      label.append(check,a.element('span','I loaded every item according to this plan'));card.append(label);
      const confirm = a.configButton('Confirm loaded · allow execution',() => this.command(run,plan,'confirm'),'',
        {action:'setup.confirm',entity:run.run_id});
      confirm.disabled = !check.checked || this.working;card.append(confirm);
    }
    if (plan.confirmation) card.append(a.element('p',`Confirmation: ${plan.confirmation.source} · physical detection: no`,'note'));
    const activity=a.table(['Action','Origin','Status','Request'],(plan.activity || []).map(e => [e.action,e.origin,e.status,e.request_id]),'No preparation commands recorded.');
    activity.dataset.region='setup-activity';card.append(activity);
    return card;
  }

  contents(values) {
    const entries = Object.entries(values || {});
    if (!entries.length) return 'Empty';
    return entries.map(([name,quantity]) => typeof quantity === 'object' && quantity !== null
      ? `${name}: ${quantity.value ?? '—'} ${quantity.unit || ''}`.trim()
      : `${name}: ${quantity}`).join(' · ');
  }

  renderPlacement(card,run,plan) {
    const a = this.app;
    let edit = this.edits.get(run.run_id);
    if (!edit) {edit = {fingerprint:plan.fingerprint,values:structuredClone(plan.preferences || {}),dirty:false};this.edits.set(run.run_id,edit);}
    const section = a.element('details');section.append(a.element('summary','Placement preferences'));
    section.open = this.expanded.has(run.run_id) || edit.fingerprint !== plan.fingerprint;
    section.addEventListener('toggle',() => {
      if (!section.isConnected) return;
      if (section.open) this.expanded.add(run.run_id);else this.expanded.delete(run.run_id);
    });
    if (edit.fingerprint !== plan.fingerprint) {
      section.append(a.element('p','The shared plan changed. Reload current preferences before editing.','notice'));
      section.append(a.configButton('Reload current preferences',() => {
        this.edits.delete(run.run_id);a.renderKey=null;a.refresh();
      },'',{action:'setup.reload',entity:run.run_id}));
    } else {
      for (const item of plan.items || []) {
        const id = item.allocation_id;
        const values = edit.values;
        const mode = values.fixed?.[id] ? 'fixed':values.preferred?.[id] ? 'preferred':'automatic';
        const address = values[mode]?.[id] || item.address;
        const row = a.element('div','','setup-placement');row.append(a.element('h4',item.name || id));
        const update = (newMode,labware,well) => {
          edit.dirty=true;
          for (const key of ['fixed','preferred']) if (values[key]) delete values[key][id];
          if (newMode !== 'automatic') (values[newMode] ||= {})[id] = {labware,well};
        };
        let chosenMode = mode, chosenLabware = address.labware, chosenWell = address.well;
        row.append(a.configField('Placement mode',mode,value => {chosenMode=value;update(value,chosenLabware,chosenWell);},
          ['automatic','fixed','preferred'],{field:`/setup/${id}/mode`}));
        const candidates=(plan.candidates || []).filter(p => p.kinds.includes(item.kind) && p.capacity_uL >= item.capacity_uL
          && (!item.carrier || p.well === item.well));
        const positionField=a.configField('Position',address.well,value => {chosenWell=value;update(chosenMode,chosenLabware,value);},
          candidates.filter(p => p.labware === chosenLabware).map(p => p.well),{field:`/setup/${id}/well`});
        row.append(a.configField('Labware',address.labware,value => {
          chosenLabware=value;
          const choices=candidates.filter(p => p.labware === value).map(p => p.well);
          if (!choices.includes(chosenWell)) chosenWell=choices[0] || '';
          const select=positionField.querySelector('select');select.replaceChildren();
          for (const choice of choices) {const option=a.element('option',choice);option.value=choice;select.append(option);}
          select.value=chosenWell;update(chosenMode,value,chosenWell);
        },[...new Set(candidates.map(p => p.labware))],{field:`/setup/${id}/labware`}));
        row.append(positionField);
        section.append(row);
      }
      const save = a.configButton('Apply placement requirements',() => this.command(run,plan,'revise'),'',
        {action:'setup.revise',entity:run.run_id});save.disabled=this.working;section.append(save);
    }
    card.append(section);
  }

  async command(run,plan,action) {
    if (this.working) return;
    if (action === 'confirm' && this.confirmations.get(run.run_id) !== plan.fingerprint) return;
    this.working = true;this.app.syncBusy();
    let payload = this.pending(run.run_id);
    if (!payload) {
      payload={action,run_id:run.run_id,request_id:crypto.randomUUID(),fingerprint:plan.fingerprint};
      if (action === 'revise') {
        const edit=this.edits.get(run.run_id);payload.fingerprint=edit.fingerprint;payload.preferences=structuredClone(edit.values);
      }
      if (action === 'confirm') payload.acknowledged=true;
      this.remember(run.run_id,payload);
    }
    try {
      await this.request(payload,payload.action === 'confirm');
      this.app.interaction.result(`setup.${payload.action}`,'acknowledged','Request queued. Waiting for OS application.',
        {entity:run.run_id,requestId:payload.request_id});
    } catch (error) {
      this.app.showAlert(`${error.message}. The request ID is retained; no automatic retry.`);
    } finally {
      this.working=false;this.app.syncBusy();this.app.renderKey=null;this.app.refresh();
    }
  }
}

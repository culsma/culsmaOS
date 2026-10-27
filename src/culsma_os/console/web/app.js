import {ConsoleNavigation} from './navigation.js';
import {ConsoleWorkstation} from './workstation.js';
import {ConsoleRunSetup} from './setup.js';
import {ConsolePrograms} from './programs.js';
import {ConsoleInteraction} from './interaction.js';
import {ConsoleActivation} from './activation.js';
import {ConsoleConfiguration,ConsoleSystemInformation} from './configuration.js';

class StationConsoleApp {
  constructor() {
    this.content = document.querySelector('#content');
    this.alert = document.querySelector('#alert');
    this.interaction = new ConsoleInteraction(this.content,document.querySelector('#operation-status'));
    this.button = document.querySelector('#refresh');
    this.busy = false;
    this.pending = false;
    this.timer = null;
    this.lastObserved = null;
    this.openRecords = new Set();
    this.renderKey = null;
    this.configToken = null;
    this.configDraft = null;
    this.configWorking = null;
    this.configProfiles = [];
    this.configDrafts = [];
    this.configValidation = null;
    this.programs = new ConsolePrograms(this);
    this.setup = new ConsoleRunSetup(this);
    this.activation = new ConsoleActivation(this);
    this.configuration = new ConsoleConfiguration(this);
    this.systemInformation = new ConsoleSystemInformation(this);
    this.navigation = new ConsoleNavigation(this);
    this.workstation = new ConsoleWorkstation(this);
  }

  start() {
    this.button.addEventListener('click', () => this.refresh());
    window.addEventListener('hashchange', () => { this.renderKey=null; window.scrollTo({top: 0}); this.navigation.select(); this.refresh(); });
    document.addEventListener('visibilitychange', () => {
      clearTimeout(this.timer);
      if (!document.hidden) this.refresh();
    });
    this.refresh();
  }

  element(tag, text = '', className = '') {
    const node = document.createElement(tag);
    if (text !== '') node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  syncBusy() { this.interaction.busy(this.busy || this.configSaving || this.programs.working || this.setup.working); }

  display(value, fallback = 'Not recorded') {
    return value === null || value === undefined || value === '' ? fallback : String(value);
  }

  badge(status) {
    const good = ['valid', 'ready', 'completed', 'registered', 'recorded', 'Connected'];
    const bad = ['invalid', 'failed', 'Disconnected'];
    const tone = good.includes(status) ? 'good' : bad.includes(status) ? 'bad' : 'warn';
    return this.element('span', this.display(status), `badge ${tone}`);
  }

  card(title) {
    const node = this.element('section', '', 'card section');
    node.append(this.element('h2', title));
    return node;
  }

  details(values) {
    const list = this.element('dl', '', 'details');
    for (const [label, value] of values) {
      list.append(this.element('dt', label));
      const entry = this.element('dd');
      entry.append(value instanceof Node ? value : this.display(value));
      list.append(entry);
    }
    return list;
  }

  table(headers, rows, empty = 'No records yet.') {
    if (!rows.length) return this.element('p', empty, 'empty');
    const wrapper = this.element('div', '', 'table-wrap');
    const table = this.element('table');
    const heading = this.element('tr');
    for (const label of headers) heading.append(this.element('th', label));
    const head = this.element('thead');
    head.append(heading);
    const body = this.element('tbody');
    for (const row of rows) {
      const line = this.element('tr');
      for (const value of row) {
        const cell = this.element('td');
        cell.append(value instanceof Node ? value : this.display(value));
        line.append(cell);
      }
      body.append(line);
    }
    table.append(head, body);
    wrapper.append(table);
    return wrapper;
  }

  runLink(runId) {
    const link = this.element('a', runId, 'mono');
    link.href = `#run/${encodeURIComponent(runId)}`;
    this.interaction.identify(link,{action:'run.inspect',entity:runId});
    return link;
  }

  runTable(runs) {
    return this.table(['Run', 'State', 'Revision', 'Outcome / reason'], runs.map(run => [
      this.runLink(run.run_id), this.badge(run.status), run.revision,
      run.error || run.body_error || run.body_outcome || '—'
    ]));
  }

  showAlert(message) {
    this.alert.textContent = message || '';
    this.alert.hidden = !message;
  }

  recordDetails(label, value) {
    const disclosure = this.element('details', '', 'record-details');
    const key = [label, value?.run_id, value?.effect_id, value?.step_id].join(':');
    disclosure.open = this.openRecords.has(key);
    disclosure.addEventListener('toggle', () => {
      if (disclosure.open) this.openRecords.add(key);
      else this.openRecords.delete(key);
    });
    disclosure.append(this.element('summary', label));
    disclosure.append(this.element('pre', JSON.stringify(value, null, 2), 'record-json'));
    return disclosure;
  }

  renderEvidence(evidence) {
    const card = this.card('Execution evidence');
    if (!evidence) {
      card.append(this.element('p', 'This service does not provide a run evidence view.', 'empty'));
      return card;
    }
    card.append(this.element('p', 'OS journal records, not physical measurements. Device attempts and logical completions are listed separately in journal insertion order; no hardware timing is inferred. The run summary is read independently.', 'note'));
    if (evidence.accounting !== 'recorded') {
      card.append(this.element('p', 'Execution journal is unavailable. An empty view does not prove that no action occurred.', 'notice'));
    }
    card.append(this.element('h3', 'Device execution attempts'));
    const attempts = evidence.attempts || [];
    if (attempts.some(item => item.evidence?.payload?.backend?.source === 'local_model')) {
      const origin = this.element('p', 'Local model simulation · not an official vendor simulator or a physical measurement.', 'notice');
      origin.dataset.region = 'evidence-source';
      origin.dataset.source = 'local_model';
      card.append(origin);
    }
    if (!attempts.length) card.append(this.element('p', 'No device attempts are recorded in this snapshot.', 'empty'));
    for (const item of attempts) {
      const row = this.element('article', '', 'evidence-attempt');
      const identity = this.element('div');
      identity.append(this.element('h4', this.display(item.step_id), 'mono'),
        this.element('div', `${this.display(item.device_id)} · ${item.mode}`, 'label'));
      const proof = item.evidence;
      const status = proof ? proof.outcome : item.evidence_status;
      const outcome = this.element('div', '', 'evidence-outcomes');
      for (const [label, value] of [['Evidence', status], ['Material', item.registration?.status || 'not_recorded']]) {
        const field = this.element('div');
        field.append(this.element('div', label, 'label'), this.badge(value));
        outcome.append(field);
      }
      const scope = proof?.payload?.evidence_scope || (proof?.payload?.aggregate ? 'aggregate coverage' : null);
      if (scope) outcome.append(this.element('div', scope, 'label'));
      const detail = this.element('div');
      detail.append(this.recordDetails('Intent and references', {
        attempt_id: item.attempt_id, effect_id: item.effect_id, context: item.context
      }));
      if (proof) detail.append(this.recordDetails('Execution receipt', proof));
      if (item.registration?.receipt) detail.append(this.recordDetails('Registration receipt', item.registration.receipt));
      row.append(identity, outcome, detail);
      card.append(row);
    }
    card.append(this.element('p', 'Missing evidence means no matching receipt is recorded; it does not mean the action failed or never happened. A derived or aggregate receipt keeps its original coverage in the expanded record.', 'note'));
    card.append(this.element('h3', 'Logical completions · no device action'));
    card.append(this.table(['Effect', 'Mode', 'Material registration', 'Records'], (evidence.logical_completions || []).map(item => [
      this.element('span', item.effect_id, 'mono'), item.mode, this.badge(item.registration?.status || 'not_recorded'),
      this.recordDetails('Logical completion and registration', item)
    ]), 'No logical completions are recorded in this snapshot.'));
    return card;
  }

  renderRun(data, target = this.content) {
    this.interaction.view('run',{loadState:'ready',runId:data.run_id,runState:data.status});
    const result = data.result || {};
    const os = result.os || {};
    const record = os.registered_material;
    const state = this.card('Run state');
    state.append(this.details([
      ['Run', this.element('span', data.run_id, 'mono')], ['State', this.badge(data.status)],
      ['Revision', data.revision], ['Body outcome', data.body_outcome],
      ['Mode', os.mode], ['Pending controls', (data.pending_controls || []).length]
    ]));
    const semantic = this.card('Program report');
    semantic.append(this.details([
      ['Semantic steps completed', result.execution?.completed_steps],
      ['Semantic steps total', result.execution?.total_steps],
      ['Report', result.headline], ['Unresolved material effects', (os.unresolved_material_effects || []).length]
    ]));
    semantic.append(this.element('p', 'Program summaries are distinct from registered material and physical measurements.', 'note'));
    const material = this.card('OS-registered material');
    if (record) {
      material.append(this.element('p', `Registration version ${record.version} · ${record.mode}`, 'label'));
      const containers = Object.entries(record.state?.containers || {});
      material.append(this.table(['Container', 'Kind', 'Volume (µL)', 'Capacity (µL)'], containers.map(([id, item]) => [
        item.metadata?.allocation_name || id, item.metadata?.kind, item.volume_uL, item.metadata?.capacity_uL
      ])));
      material.append(this.element('p', 'Registered quantities are model state backed by execution evidence, not measured biological results.', 'note'));
    } else {
      material.append(this.element('p', 'No registered material snapshot is available for this run.', 'empty'));
    }
    const diagnostics = (result.alerts || []).map(item => typeof item === 'string' ? item : item.code || 'Diagnostic');
    const phase=ConsoleNavigation.phase(data,ConsoleNavigation.resolve(location.hash).section);
    const panels={};
    for(const name of ['preparation','execution','results']) {
      const panel=this.element('section','','run-stage');panel.id='run-panel-'+name;
      panel.setAttribute('aria-label',name[0].toUpperCase()+name.slice(1));
      panel.dataset.stage=name;panels[name]=panel;
    }
    const preparation = this.setup.render(data);
    if (data.status === 'awaiting_setup') panels.preparation.append(preparation);
    else {
      const saved = this.element('details');saved.append(this.element('summary','Loading plan'),preparation);
      panels.preparation.append(saved);
    }
    if(!panels.preparation.querySelector('[data-region="run-setup"]')) panels.preparation.append(this.card('Preparation'),this.element('p','No loading plan is recorded for this run.','note'));
    const feedback=this.card('Execution feedback');
    feedback.append(this.badge(data.status),this.element('p','Progress follows the feedback supplied by the driver. A batch receipt covers the completed batch; individual hardware progress is not inferred.','note'));
    const logs=this.element('details');logs.append(this.element('summary','Agent task and logs · planned'),this.element('p','A console log interface is not available yet. Recorded execution receipts are available in Results.','note'));feedback.append(logs);
    panels.execution.append(this.programs.renderControls(data),feedback);
    const proof=this.element('details','','evidence-disclosure');proof.append(this.element('summary','Execution evidence and receipts'),this.renderEvidence(data.execution_evidence));
    panels.results.append(semantic,material,proof);
    this.content.dataset.stage=phase;
    target.replaceChildren(state,...Object.values(panels));
    this.showAlert(data.error || data.body_error || (diagnostics.length ? diagnostics.join(' · ') : null));
  }

  async configurationFetch(path, payload = null) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const headers = {'X-Culsma-Console':'1'};
      if (this.configToken) headers.Authorization = `Bearer ${this.configToken}`;
      if (payload) headers['Content-Type'] = 'application/json';
      const response = await fetch(path, {method:payload ? 'POST' : 'GET', headers,
        body:payload ? JSON.stringify(payload) : undefined, cache:'no-store', signal:controller.signal});
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401) this.configToken = null;
        const error = new Error([result.error?.code || 'CONSOLE_REQUEST_FAILED',...(result.error?.diagnostics || []).map(item => item.code)].join(' · '));
        error.httpStatus = response.status;error.code = result.error?.code;
        throw error;
      }
      return result.data || result;
    } finally { clearTimeout(timeout); }
  }

  selectPage(page) { this.navigation.select(); }

  async refreshConfiguration() {
    const route = location.hash;const page = ConsoleNavigation.resolve(route).page;
    this.interaction.view(page,{loadState:'loading'});
    this.busy = true;this.syncBusy();
    this.button.disabled = true;
    try {
      if (!this.configToken) {
        const session = await this.configurationFetch('/api/v1/session');
        this.configToken = session.access_token;
      }
      const [profiles,drafts] = await Promise.all([
        this.configurationFetch('/api/v1/configuration/profiles'),
        this.configurationFetch('/api/v1/configuration/drafts')]);
      try { await this.activation.refresh(); } catch { this.activation.view = null; }
      this.configProfiles = profiles.profiles || [];
      this.configDrafts = drafts.drafts || [];
      let configurationError = null;
      try { await this.configuration.readCurrent(page === 'configuration'); } catch (error) { configurationError = error.message; }
      if (location.hash !== route) { this.pending = true; return; }
      document.querySelector('#title').textContent = page === 'system' ? 'System Info':'System Settings';
      this.selectPage(page);
      document.querySelector('#connection').replaceChildren(this.badge('Connected'));
      document.querySelector('#observed').textContent = page === 'system' ? 'Saved configuration and installed plugin definitions · no hardware discovery':'Layout settings · explicit changes to the current configuration';
      this.showAlert(configurationError || (profiles.unavailable?.length ? `Profiles unavailable: ${profiles.unavailable.join(', ')}` : null));
      if (page === 'system') this.renderSystemInformation();else this.renderConfiguration();
    } catch (error) {
      if (location.hash === route) this.interaction.view(page,{loadState:'unavailable'});
      this.showAlert(error.message);
    }
    finally {
      this.busy = false; this.syncBusy();this.button.disabled = false;
      if (this.pending) { this.pending = false; this.refresh(); }
    }
  }

  configField(label, value, changed, options = null, identity = {}) {
    const wrapper = this.element('label', '', 'config-field');
    wrapper.append(this.element('span', label));
    const input = this.element(options ? 'select' : 'input');
    input.setAttribute('aria-label',label);
    this.interaction.identify(input,identity);
    if (options) {
      for (const choice of [...new Set([value || '',...options])]) {
        const option = this.element('option',choice || 'Select…'); option.value = choice;
        input.append(option);
      }
    } else input.type = 'text';
    input.value = value || '';
    input.addEventListener(options ? 'change' : 'input',() => {changed(input.value,input); if (location.hash === '#configuration') { this.configValidation = null; this.updateConfigActions(); }});
    wrapper.append(input);
    return wrapper;
  }

  configPath(value, path) { return path.reduce((item,key) => item?.[key],value); }

  setConfigPath(path, value) {
    let target = this.configWorking;
    for (const key of path.slice(0,-1)) {
      if (!target[key] || typeof target[key] !== 'object') target[key] = {};
      target = target[key];
    }
    target[path[path.length-1]] = value;
  }

  configDirty() {
    return this.configuration.jsonEdited || this.configuration.invalidFields.size > 0 || !this.configDraft || JSON.stringify(this.configWorking) !== JSON.stringify(this.configDraft.configuration)
      || this.configTitle !== this.configDraft.title || this.configDriver !== this.configDraft.driver;
  }

  updateConfigActions() {
    if (location.hash !== '#configuration') return;
    const dirty = this.configWorking ? this.configDirty():false;
    for (const input of this.content.querySelectorAll('input,select,textarea,button')) input.disabled = !!this.configSaving;
    const validation = document.querySelector('#draft-validation');
    if (validation) validation.hidden = dirty || !this.configValidation;
    const discard = document.querySelector('#discard-configuration');
    if (discard) discard.disabled = !!this.configSaving || !dirty;
    const save = document.querySelector('#save-configuration');
    if (save) save.disabled = !!this.configSaving || !dirty || this.configuration.jsonEdited || this.configuration.invalidFields.size > 0;
    const validate = document.querySelector('#validate-draft');
    const exportButton = document.querySelector('#export-draft');
    if (validate) validate.disabled = dirty || this.configSaving;
    if (exportButton) exportButton.disabled = dirty || this.configSaving || !this.configValidation?.valid;
    const state = document.querySelector('#draft-state');
    this.interaction.view('configuration',{loadState:'ready',draftId:this.configDraft?.draft_id,revision:this.configDraft?.revision,dirty,
      validationState:dirty ? 'not_checked' : this.configValidation ? (this.configValidation.valid ? 'valid':'invalid'):'not_checked'});
    this.interaction.diagnostics(!dirty && this.configValidation ? this.configValidation.diagnostics || []:[]);
    for (const input of this.content.querySelectorAll('[data-field]')) {
      if (this.configuration.invalidFields.has(input.dataset.field)) input.setAttribute('aria-invalid','true');
    }
    this.configuration.updateChangeSummary();
    this.activation.updateActions();
    this.configuration.layoutImport.updateActions();
    if (state) state.textContent = this.configuration.jsonEdited ? 'Unapplied JSON edits · update the proposal in Advanced, or discard edits'
      : this.configuration.invalidFields.size ? 'Correct invalid numeric fields before saving' : dirty ? `Unsaved changes · based on ${this.configDraft ? `revision ${this.configDraft.revision}`:'a new draft'} · save before validation` : `Saved revision ${this.configDraft.revision} · ${this.configDraft.fingerprint.slice(0,12)}`;
  }

  startConfigDraft(driver, configuration, title = 'New station configuration', record = null) {
    this.activation.confirmed = false;
    this.configuration.invalidFields.clear();
    this.configuration.invalidValues.clear();
    this.configuration.jsonEdited = false;this.configuration.jsonText = null;
    this.configDraft = record;
    this.configDriver = driver;
    this.configTitle = title;
    this.configWorking = structuredClone(configuration);
    this.configValidation = null;
    this.renderConfiguration();
  }

  configButton(label, action, id = '', identity = {}) {
    const button = this.element('button', label);
    button.type = 'button'; if (id) button.id = id;
    this.interaction.identify(button,identity);
    button.addEventListener('click',action);
    return button;
  }

  async configAction(action, extra = {}) {
    if (this.configSaving) return;
    if (this.configuration.jsonEdited && action !== 'get') {this.showAlert('Update proposed settings from JSON before saving.');return;}
    if (this.configuration.invalidFields.size && action !== 'get') {this.showAlert('Correct the highlighted numeric fields before saving.');return;}
    this.activation.confirmed = false;
    this.configSaving = true; this.syncBusy();this.updateConfigActions();
    const operation = `configuration.${action === 'create' ? 'save':action}`;
    this.interaction.result(operation,'pending','Configuration request pending.');
    try {
      const payload = {action,...extra};
      if (action !== 'create' && action !== 'get') Object.assign(payload,{draft_id:this.configDraft.draft_id,revision:this.configDraft.revision});
      if (['create','save'].includes(action)) Object.assign(payload,{title:this.configTitle,driver:this.configDriver,configuration:this.configWorking});
      const data = await this.configurationFetch('/api/v1/configuration/drafts',payload);
      if (data.draft) {
        this.startConfigDraft(data.draft.driver,data.draft.configuration,data.draft.title,data.draft);
        this.configDrafts = [data.draft,...this.configDrafts.filter(item => item.draft_id !== data.draft.draft_id)];
      } else if (data.validation) this.configValidation = data.validation;
      if (action === 'export') {
        const blob = new Blob([JSON.stringify(data.configuration,null,2)+'\n'],{type:'application/json'});
        const url = URL.createObjectURL(blob);
        const link = this.element('a'); link.href = url;
        link.download = `station-${data.draft_id}-r${data.revision}.json`;
        link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
      }
      const revision = data.draft?.revision || data.revision;
      const message = ['create','save'].includes(action) ? `Changes saved · revision ${revision}. Apply them explicitly to change the station.`
        : action === 'get' ? `Configuration loaded for review · revision ${revision}.`
        : action === 'validate' ? `Saved revision ${revision}: ${data.validation.valid ? 'valid':'invalid'}. Static checks only.`
        : `Validated revision ${revision} exported. Running station unchanged.`;
      this.interaction.result(operation,action === 'validate' && !data.validation.valid ? 'invalid':'succeeded',message,
        {entity:data.draft?.draft_id || data.draft_id,revision});
      this.showAlert(null);
      if (location.hash === '#configuration') this.renderConfiguration();
    } catch (error) {
      const conflict = error.code === 'CONFIGURATION_REVISION_CONFLICT';
      const message = conflict ? 'The saved draft changed. Your local edits are retained; inspect the latest saved revision before replacing them.'
        : this.interaction.responseOutcome(error) === 'rejected' ? error.message : 'Configuration response unavailable. Check saved drafts before repeating a save.';
      this.interaction.result(operation,this.interaction.responseOutcome(error),message,{entity:this.configDraft?.draft_id,revision:this.configDraft?.revision});
      this.showAlert(error.message);
    }
    finally {
      this.configSaving = false;this.syncBusy();this.updateConfigActions();
      if (location.hash === '#configuration') this.interaction.focus(operation);
    }
  }

  renderSystemInformation() {
    if (ConsoleNavigation.resolve(location.hash).page !== 'system') return;
    this.systemInformation.render();
  }

  renderConfiguration() {
    if (location.hash !== '#configuration') return;
    this.configuration.render();
  }

  async refresh() {
    clearTimeout(this.timer);
    if (document.hidden) return;
    if (this.busy) { this.pending = true; return; }
    if (['configuration','system'].includes(ConsoleNavigation.resolve(location.hash).page)) {
      await this.refreshConfiguration();return;
    }
    await this.workstation.refresh();
  }
}

new StationConsoleApp().start();

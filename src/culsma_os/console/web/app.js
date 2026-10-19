class StationConsoleApp {
  constructor() {
    this.content = document.querySelector('#content');
    this.alert = document.querySelector('#alert');
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
  }

  start() {
    this.button.addEventListener('click', () => this.refresh());
    window.addEventListener('hashchange', () => { window.scrollTo({top: 0}); this.refresh(); });
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

  renderStation(data) {
    const host = data.host;
    const inspection = data.devices;
    const devices = inspection.devices || [];
    const runs = data.runs || [];
    const resources = inspection.resources || {};
    const summary = this.element('div', '', 'grid');
    const service = this.card('Resident service');
    service.append(this.badge(host.blocked_run ? 'blocked' : host.status));
    service.append(this.element('p', host.blocked_run ? 'Queue retained' : 'Explicit host connection', 'note'));
    const count = this.card('Programs');
    count.append(this.element('div', runs.length, 'metric'), this.element('div', 'Recorded runs in this resident queue', 'label'));
    const owned = this.card('Resource ownership');
    owned.append(this.element('div', Array.isArray(resources.station_reservations) ? resources.station_reservations.length : '—', 'metric'));
    owned.append(this.element('div', 'Recorded station reservations', 'label'));
    summary.append(service, count, owned);
    const deviceCards = this.element('div', '', 'device-grid');
    for (const device of devices) {
      const card = this.card(device.device_id);
      card.append(this.details([
        ['Mode', device.mode], ['Evidence accounting', this.badge(device.evidence_accounting)],
        ['Position basis', this.badge(device.positions?.status)],
        ['Unresolved operations', Array.isArray(device.unresolved_operations) ? device.unresolved_operations.length : '—']
      ]));
      const consumables = Object.entries(device.consumables || {});
      if (consumables.length) {
        card.append(this.element('h3', 'Consumables · recorded bounds'));
        card.append(this.table(['Resource', 'Known used', 'Available from records'], consumables.map(([name, item]) => [
          name, item.known_consumed, item.available_from_records === null ? 'Unknown' : item.available_from_records
        ])));
      }
      card.append(this.element('h3', 'Plate positions'));
      card.append(this.table(['Labware', 'Recorded position'], Object.entries(device.positions?.current || {}),
        device.positions?.status === 'unknown' ? 'Current positions are unknown. Isolation is retained.' : 'No positions declared.'));
      card.append(this.element('p', 'Device state comes from OS records; this is not a hardware connection test.', 'note'));
      deviceCards.append(card);
    }
    const programCard = this.card('Resident programs');
    programCard.append(this.runTable(runs));
    this.content.replaceChildren(summary, deviceCards, programCard);
    if (!devices.length) {
      const note = this.element('p', 'No device records yet. An idle, newly started service may not have registered its first device.', 'empty');
      deviceCards.append(note);
    }
    this.showAlert(host.blocked_run ? `Run ${host.blocked_run} retains the queue: ${this.display(host.blocked_reason)}. Inspect its evidence before taking any further action.` : host.worker_error);
  }

  renderRuns(data) {
    const card = this.card('Programs in the resident queue');
    card.append(this.runTable(data.runs || []));
    this.content.replaceChildren(card);
    this.showAlert(null);
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

  renderRun(data) {
    const back = this.element('a', '← All runs', 'back');
    back.href = '#runs';
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
    this.content.replaceChildren(back, state, semantic, this.renderEvidence(data.execution_evidence), material);
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
        throw new Error(result.error?.code || 'CONFIGURATION_REQUEST_FAILED');
      }
      return result.data || result;
    } finally { clearTimeout(timeout); }
  }

  async refreshConfiguration() {
    this.busy = true;
    this.button.disabled = true;
    try {
      if (!this.configToken) {
        const session = await this.configurationFetch('/api/v1/session');
        this.configToken = session.access_token;
      }
      const [profiles,drafts] = await Promise.all([
        this.configurationFetch('/api/v1/configuration/profiles'),
        this.configurationFetch('/api/v1/configuration/drafts')]);
      this.configProfiles = profiles.profiles || [];
      this.configDrafts = drafts.drafts || [];
      if (location.hash !== '#configuration') { this.pending = true; return; }
      document.querySelector('#title').textContent = 'Configuration drafts';
      for (const name of ['station','runs','configuration']) document.querySelector(`#${name}-tab`).setAttribute('aria-current',name === 'configuration' ? 'page':'false');
      document.querySelector('#connection').replaceChildren(this.badge('Connected'));
      document.querySelector('#observed').textContent = 'Local draft store · running station unchanged';
      this.showAlert(profiles.unavailable?.length ? `Profiles unavailable: ${profiles.unavailable.join(', ')}` : null);
      this.renderConfiguration();
    } catch (error) { this.showAlert(error.message); }
    finally {
      this.busy = false; this.button.disabled = false;
      if (this.pending) { this.pending = false; this.refresh(); }
    }
  }

  configField(label, value, changed, options = null) {
    const wrapper = this.element('label', '', 'config-field');
    wrapper.append(this.element('span', label));
    const input = this.element(options ? 'select' : 'input');
    input.setAttribute('aria-label',label);
    if (options) {
      for (const choice of [...new Set([value || '',...options])]) {
        const option = this.element('option',choice || 'Select…'); option.value = choice;
        input.append(option);
      }
    } else input.type = 'text';
    input.value = value || '';
    input.addEventListener(options ? 'change' : 'input',() => {changed(input.value); this.configValidation = null; this.updateConfigActions();});
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
    return !this.configDraft || JSON.stringify(this.configWorking) !== JSON.stringify(this.configDraft.configuration)
      || this.configTitle !== this.configDraft.title || this.configDriver !== this.configDraft.driver;
  }

  updateConfigActions() {
    const dirty = this.configDirty();
    for (const input of this.content.querySelectorAll('input,select,textarea,button')) input.disabled = !!this.configSaving;
    const validation = document.querySelector('#draft-validation');
    if (validation) validation.hidden = dirty || !this.configValidation;
    const validate = document.querySelector('#validate-draft');
    const exportButton = document.querySelector('#export-draft');
    if (validate) validate.disabled = dirty || this.configSaving;
    if (exportButton) exportButton.disabled = dirty || this.configSaving || !this.configValidation?.valid;
    const state = document.querySelector('#draft-state');
    if (state) state.textContent = dirty ? 'Unsaved changes · save before validation' : `Saved revision ${this.configDraft.revision} · ${this.configDraft.fingerprint.slice(0,12)}`;
  }

  startConfigDraft(driver, configuration, title = 'New station configuration', record = null) {
    this.configDraft = record;
    this.configDriver = driver;
    this.configTitle = title;
    this.configWorking = structuredClone(configuration);
    this.configValidation = null;
    this.renderConfiguration();
  }

  configButton(label, action, id = '') {
    const button = this.element('button', label);
    button.type = 'button'; if (id) button.id = id;
    button.addEventListener('click',action);
    return button;
  }

  async configAction(action, extra = {}) {
    if (this.configSaving) return;
    this.configSaving = true; this.updateConfigActions();
    try {
      const payload = {action,...extra};
      if (action !== 'create' && action !== 'get') Object.assign(payload,{draft_id:this.configDraft.draft_id,revision:this.configDraft.revision});
      if (['create','save'].includes(action)) Object.assign(payload,{title:this.configTitle,driver:this.configDriver,configuration:this.configWorking});
      const data = await this.configurationFetch('/api/v1/configuration/drafts',payload);
      if (data.draft) {
        this.startConfigDraft(data.draft.driver,data.draft.configuration,data.draft.title,data.draft);
        this.configDrafts = (await this.configurationFetch('/api/v1/configuration/drafts')).drafts;
      } else if (data.validation) this.configValidation = data.validation;
      if (action === 'export') {
        const blob = new Blob([JSON.stringify(data.configuration,null,2)+'\n'],{type:'application/json'});
        const url = URL.createObjectURL(blob);
        const link = this.element('a'); link.href = url;
        link.download = `station-${data.draft_id}-r${data.revision}.json`;
        link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
      }
      this.showAlert(null);
      this.renderConfiguration();
    } catch (error) { this.showAlert(error.message); }
    finally { this.configSaving = false; this.updateConfigActions(); }
  }

  renderConfiguration() {
    const setup = this.card('Prepare a configuration');
    setup.append(this.element('p','Save and validate a draft, then export it for an explicit station-service restart. Draft editing does not move equipment or reset station records.','note'));
    const profile = this.configProfiles.find(item => item.driver === this.configDriver) || this.configProfiles[0];
    let selected = profile?.driver;
    setup.append(this.configField('Installed profile',selected,value => {selected = value;},this.configProfiles.map(item => item.driver)));
    const actions = this.element('div','','config-actions');
    actions.append(this.configButton('New from profile',() => {
      const item = this.configProfiles.find(value => value.driver === selected);
      if (item) this.startConfigDraft(item.driver,item.template || {});
    }));
    const upload = this.element('input'); upload.type = 'file'; upload.accept = '.json,application/json';
    upload.setAttribute('aria-label','Import configuration JSON');
    upload.addEventListener('change',async () => {
      try {
        const file = upload.files[0]; if (!file) return;
        if (file.size > 200000) throw new Error('CONFIGURATION_TOO_LARGE');
        const value = JSON.parse(await file.text());
        if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('CONFIGURATION_JSON_INVALID');
        this.startConfigDraft(selected || '',value,file.name);
      } catch (error) { this.showAlert(error.message); }
    });
    actions.append(upload); setup.append(actions);
    if (!this.configProfiles.length) setup.append(this.element('p','No offline configuration profile is installed. Install a compatible external driver profile to validate and export drafts.','notice'));
    const saved = this.card('Saved drafts');
    for (const draft of this.configDrafts) saved.append(this.configButton(`Load ${draft.title} · r${draft.revision}`,() => this.configAction('get',{draft_id:draft.draft_id})));
    if (!this.configDrafts.length) saved.append(this.element('p','No saved drafts yet.','empty'));
    const children = [setup,saved];
    if (this.configWorking) {
      const editor = this.card('Edit draft');
      const fields = this.element('div','','config-grid');
      fields.append(this.configField('Draft title',this.configTitle,value => {this.configTitle = value;}));
      fields.append(this.configField('Driver',this.configDriver,value => {this.configDriver = value; this.renderConfiguration();},this.configProfiles.map(item => item.driver)));
      const definition = this.configProfiles.find(item => item.driver === this.configDriver);
      for (const field of definition?.fields || []) fields.append(this.configField(field.label,this.configPath(this.configWorking,field.path),value => this.setConfigPath(field.path,value),field.options));
      editor.append(fields);
      for (const map of definition?.maps || []) {
        editor.append(this.element('h3',map.label));
        const rawValues = this.configPath(this.configWorking,map.path);
        const values = rawValues && typeof rawValues === 'object' && !Array.isArray(rawValues) ? rawValues : {};
        for (const [name,value] of Object.entries(values)) {
          const row = this.element('div','','config-map-row');
          row.append(this.element('strong',name));
          for (const column of map.columns) row.append(this.configField(`${map.label} ${name} ${column}`,value?.[column],text => {
            if (!values[name] || typeof values[name] !== 'object' || Array.isArray(values[name])) values[name] = {};
            if (text === '') delete values[name][column]; else values[name][column] = text;
          }));
          row.append(this.configButton(`Remove ${name}`,() => {delete values[name];this.configValidation = null;this.renderConfiguration();}));
          editor.append(row);
        }
        let key = '';
        const add = this.element('div','','config-actions');
        add.append(this.configField(`New ${map.label} identifier`,'',value => {key = value;}),this.configButton(`Add ${map.label}`,() => {
          if (!key || Object.hasOwn(values,key) || ['__proto__','constructor','prototype'].includes(key)) {this.showAlert('CONFIGURATION_IDENTIFIER_INVALID');return;}
          values[key] = {};this.setConfigPath(map.path,values);this.configValidation = null;this.renderConfiguration();
        })); editor.append(add);
      }
      const advanced = this.element('details','','config-advanced');
      advanced.append(this.element('summary','Advanced configuration JSON · modules, routes and policy'));
      const json = this.element('textarea');json.value = JSON.stringify(this.configWorking,null,2);json.setAttribute('aria-label','Advanced configuration JSON');
      advanced.append(json,this.configButton('Apply JSON to editor',() => {
        try {const value = JSON.parse(json.value);if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('CONFIGURATION_JSON_INVALID');this.configWorking = value;this.configValidation = null;this.renderConfiguration();}
        catch (error) {this.showAlert(error.message);}
      })); editor.append(advanced);
      const controls = this.element('div','','config-actions');
      controls.append(this.configButton('Save draft',() => this.configAction(this.configDraft ? 'save':'create')),
        this.configButton('Validate saved draft',() => this.configAction('validate'),'validate-draft'),
        this.configButton('Export validated configuration',() => this.configAction('export'),'export-draft'));
      editor.append(controls);
      const state = this.element('p','','label');state.id = 'draft-state';editor.append(state);
      if (this.configValidation) {
        const validation = this.element('div'); validation.id = 'draft-validation';
        validation.append(this.badge(this.configValidation.valid ? 'valid':'invalid'));
        validation.append(this.element('p',this.configValidation.scope,'note'));
        validation.append(this.table(['Field','Code','Message'],(this.configValidation.diagnostics || []).map(item => [item.path,item.code,item.message]),'Static configuration checks passed. Program preflight still happens before execution.'));
        editor.append(validation);
      }
      children.push(editor);
    }
    this.content.replaceChildren(...children);
    this.updateConfigActions();
  }

  async refresh() {
    clearTimeout(this.timer);
    if (document.hidden) return;
    if (this.busy) { this.pending = true; return; }
    if (location.hash === '#configuration') { await this.refreshConfiguration(); return; }
    this.busy = true;
    this.button.disabled = true;
    document.querySelector('#configuration-tab').setAttribute('aria-current','false');
    const route = location.hash || '#station';
    const isRun = route.startsWith('#run/');
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 12000);
    try {
      const resource = isRun ? `/runs/${encodeURIComponent(decodeURIComponent(route.slice(5)))}` : route === '#runs' ? '/runs' : '/station';
      const response = await fetch(`/api/v1${resource}`, { cache: 'no-store', signal: controller.signal });
      const snapshot = await response.json();
      if (route !== (location.hash || '#station')) { this.pending = true; return; }
      if (!response.ok || snapshot.schema !== 'culsma_console_v1') {
        const failure = new Error(snapshot.error?.code || 'CONSOLE_RESPONSE_INVALID');
        failure.httpStatus = response.status;
        throw failure;
      }
      this.lastObserved = snapshot.observed_at;
      document.querySelector('#title').textContent = isRun ? 'Run detail' : route === '#runs' ? 'Programs' : 'Station overview';
      document.querySelector('#station-tab').setAttribute('aria-current', route === '#station' ? 'page' : 'false');
      document.querySelector('#runs-tab').setAttribute('aria-current', route !== '#station' ? 'page' : 'false');
      document.querySelector('#connection').className = '';
      document.querySelector('#connection').replaceChildren(this.badge('Connected'));
      document.querySelector('#observed').textContent = `Read ${new Date(snapshot.observed_at).toLocaleTimeString()} · OS records · separate snapshots`;
      const key = route + JSON.stringify(snapshot.data);
      if (key !== this.renderKey) {
        if (isRun) this.renderRun(snapshot.data);
        else if (route === '#runs') this.renderRuns(snapshot.data);
        else this.renderStation(snapshot.data);
        this.renderKey = key;
      }
    } catch (error) {
      this.renderKey = null;
      document.querySelector('#connection').className = '';
      const disconnected = error.httpStatus === 503 || error instanceof TypeError || error.name === 'AbortError';
      document.querySelector('#connection').replaceChildren(this.badge(disconnected ? 'Disconnected' : 'Read unavailable'));
      document.querySelector('#observed').textContent = this.lastObserved ? `Last successful read: ${new Date(this.lastObserved).toLocaleTimeString()}` : 'No snapshot received';
      this.showAlert(error.message === 'CONSOLE_HOST_UNAVAILABLE' ? 'The selected resident service is unavailable. Start it explicitly with culsma-os serve. The console does not start or resume device execution.' : `Read unavailable: ${error.message}`);
      this.content.replaceChildren(this.element('p', 'No current snapshot. Existing station records are unchanged.', 'empty'));
    } finally {
      clearTimeout(deadline);
      this.busy = false;
      this.button.disabled = false;
      if (this.pending) { this.pending = false; this.refresh(); }
      else if (!document.hidden && location.hash !== '#configuration') this.timer = setTimeout(() => this.refresh(), 2500);
    }
  }
}

new StationConsoleApp().start();

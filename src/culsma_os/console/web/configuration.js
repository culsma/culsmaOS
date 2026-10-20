/** Current-station presentation. Choices and fields come from installed profiles. */
export class ConsoleConfiguration {
  constructor(app) {
    this.app = app;
    this.activeRecord = null;
    this.invalidFields = new Set();
    this.invalidValues = new Map();
    this.jsonEdited = false;
    this.jsonText = null;
  }

  definition() { return this.app.configProfiles.find(item => item.driver === this.app.configDriver); }

  section(profile, id) {
    return {
      fields:(profile?.fields || []).filter(item => item.section === id),
      maps:(profile?.maps || []).filter(item => item.section === id),
      summaries:(profile?.summaries || []).filter(item => item.section === id)
    };
  }

  matchesOrigin(record, active) {
    const origin = active?.origin;
    return !!(origin && record && record.draft_id === origin.draft_id && record.revision === origin.revision
      && record.fingerprint === origin.configuration_fingerprint && (active.driver === undefined || record.driver === active.driver));
  }

  async readCurrent(initializeProposal = true) {
    const a = this.app;const active = a.activation.view?.active;
    this.activeRecord = null;
    if (!active?.origin) return;
    const result = await a.configurationFetch('/api/v1/configuration/drafts',
      {action:'get',draft_id:active.origin.draft_id,revision:active.origin.revision});
    if (a.activation.view?.active?.fingerprint !== active.fingerprint) return;
    if (!this.matchesOrigin(result.draft,active)) throw new Error('CURRENT_CONFIGURATION_IDENTITY_MISMATCH');
    this.activeRecord = result.draft;
    if (initializeProposal && !a.configWorking) a.startConfigDraft(result.draft.driver,result.draft.configuration,result.draft.title,result.draft);
  }

  changes(before, after, path = []) {
    if (JSON.stringify(before) === JSON.stringify(after)) return [];
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    if (object(before) && object(after)) {
      return [...new Set([...Object.keys(before),...Object.keys(after)])].sort()
        .flatMap(key => this.changes(before[key],after[key],[...path,key]));
    }
    return [{path,before,after}];
  }

  editValue(field, text, badInput = false) {
    const a = this.app;const pointer = a.interaction.pointer(['configuration',...field.path]);
    const value = field.type === 'number' && text !== '' ? Number(text) : text;
    if (badInput || (field.type === 'number' && text !== '' && !Number.isFinite(value))) {
      this.invalidFields.add(pointer);this.invalidValues.set(pointer,text);return false;
    }
    this.invalidFields.delete(pointer);this.invalidValues.delete(pointer);
    if (text === '' && field.optional) {
      const parent = a.configPath(a.configWorking,field.path.slice(0,-1));
      if (parent && typeof parent === 'object') delete parent[field.path.at(-1)];
    } else a.setConfigPath(field.path,value);
    return true;
  }

  editJSON(text) { this.jsonText = text;this.jsonEdited = true; }

  proposeJSON(text) {
    const value = JSON.parse(text);
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('CONFIGURATION_JSON_INVALID');
    this.app.configWorking = value;this.app.configValidation = null;
    this.invalidFields.clear();this.invalidValues.clear();this.jsonEdited = false;this.jsonText = null;
  }

  fields(definitions) {
    const a = this.app;const grid = a.element('div','','config-grid');
    for (const field of definitions) {
      const pointer = a.interaction.pointer(['configuration',...field.path]);
      const wrapper = a.configField(field.label,this.invalidValues.has(pointer) ? this.invalidValues.get(pointer) : (a.configPath(a.configWorking,field.path) ?? field.default ?? ''),
        (value,input) => {this.editValue(field,value,input.validity?.badInput);a.updateConfigActions();},field.options,{field:pointer});
      const input = wrapper.querySelector('input,select');
      if (field.type === 'number') {input.type = 'number';input.step = 'any';input.placeholder = 'Device default';}
      grid.append(wrapper);
    }
    return grid;
  }

  map(definition) {
    const a = this.app;const section = a.element('div');section.append(a.element('h3',definition.label));
    const raw = a.configPath(a.configWorking,definition.path);
    const values = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw:{};
    for (const [name,value] of Object.entries(values)) {
      const row = a.element('div','','config-map-row');
      a.interaction.identify(row,{collection:a.interaction.pointer(definition.path),entity:name});
      row.append(a.element('strong',name));
      for (const column of definition.columns) row.append(a.configField(`${definition.label} ${name} ${column}`,value?.[column],text => {
        if (!values[name] || typeof values[name] !== 'object' || Array.isArray(values[name])) values[name] = {};
        if (text === '') delete values[name][column];else values[name][column] = text;
      },null,{field:a.interaction.pointer(['configuration',...definition.path,name,column]),entity:name}));
      row.append(a.configButton(`Remove ${definition.label} ${name}`,() => {
        delete values[name];a.configValidation = null;a.renderConfiguration();
      },'',{action:'configuration.remove-entry',collection:a.interaction.pointer(definition.path),entity:name}));section.append(row);
    }
    let key = '';const add = a.element('div','','config-actions');
    add.append(a.configField(`New ${definition.label} identifier`,'',value => {key = value;},null,
      {field:a.interaction.pointer(['new-entry',...definition.path])}),a.configButton(`Add ${definition.label}`,() => {
      if (!key || Object.hasOwn(values,key) || ['__proto__','constructor','prototype'].includes(key)) {a.showAlert('CONFIGURATION_IDENTIFIER_INVALID');return;}
      values[key] = {};a.setConfigPath(definition.path,values);a.configValidation = null;a.renderConfiguration();
    },'',{action:'configuration.add-entry',collection:a.interaction.pointer(definition.path)}));section.append(add);return section;
  }

  renderEditor() {
    const a = this.app;const editor = a.card('Layout');editor.dataset.region = 'station-settings';
    editor.append(a.element('p',`Proposal: ${a.configTitle}${a.configDraft ? ` · r${a.configDraft.revision}`:''}`,'label'));
    const section = this.section(this.definition(),'layout');
    if (section.fields.length) editor.append(this.fields(section.fields));
    for (const map of section.maps) editor.append(this.map(map));
    if (!section.fields.length && !section.maps.length) editor.append(a.element('p','This profile exposes no structured layout fields. Its configuration remains available in Advanced JSON.','notice'));
    return editor;
  }

  updateChangeSummary(target = document.getElementById('configuration-change-summary')) {
    if (!target) return;
    const a = this.app;const base = this.activeRecord?.configuration;
    if (base) {
      const value = item => item === undefined ? '(not set)':JSON.stringify(item);
      const changes = this.changes(base,a.configWorking);
      const details = target.closest('details');
      if (details) {details.hidden = changes.length === 0;details.querySelector('summary').textContent = `Review ${changes.length} configuration change${changes.length === 1 ? '':'s'}`;}
      target.replaceChildren(a.table(['Setting','Current','Proposed'],changes
        .map(item => [a.interaction.pointer(item.path),value(item.before),value(item.after)]),'No setting changes from the current configuration.'));
    } else target.replaceChildren(a.element('p','Current configuration contents are unavailable. This proposal has not been compared with the running station.','notice'));
  }

  discardEdits() {
    const a = this.app;const record = a.configDraft || this.activeRecord;
    if (record) a.startConfigDraft(record.driver,record.configuration,record.title,record);
    else {
      a.configWorking = null;a.configDraft = null;a.configValidation = null;a.activation.confirmed = false;
      this.invalidFields.clear();this.invalidValues.clear();this.jsonEdited = false;this.jsonText = null;
      a.renderConfiguration();
    }
  }

  renderChanges() {
    const a = this.app;const card = a.card('Configuration changes');card.dataset.region = 'configuration-changes';
    const details = a.element('details','','config-advanced');details.open = !!this.changesExpanded;
    details.append(a.element('summary','Review configuration changes'));
    details.addEventListener('toggle',() => {this.changesExpanded = details.open;});
    const summary = a.element('div');summary.id = 'configuration-change-summary';details.append(summary);card.append(details);
    this.updateChangeSummary(summary);
    const controls = a.element('div','','config-actions');
    controls.append(a.configButton('Discard unsaved edits',() => this.discardEdits(),'discard-configuration',{action:'configuration.discard'}),a.configButton('Save changes',() => a.configAction(a.configDraft ? 'save':'create'),'save-configuration',{action:'configuration.save'}),
      a.configButton('Check saved changes',() => a.configAction('validate'),'validate-draft',{action:'configuration.validate'}));card.append(controls);
    if (a.configDraft) card.append(a.activation.controls());
    const state = a.element('p','','label');state.id = 'draft-state';card.append(state);
    if (a.configValidation) {
      const validation = a.element('div');validation.id = 'draft-validation';
      validation.append(a.badge(a.configValidation.valid ? 'valid':'invalid'),a.element('p',a.configValidation.scope,'note'),
        a.table(['Field','Code','Message'],(a.configValidation.diagnostics || []).map(item => [item.path,item.code,item.message]),'Static checks passed. Program preflight still happens before execution.'));card.append(validation);
    }
    return card;
  }

  renderAdvanced() {
    const a = this.app;const node = a.element('details','','card section config-advanced');
    node.append(a.element('summary','Advanced · configuration presets and JSON'));
    const profile = a.configProfiles.find(item => item.driver === a.configDriver) || a.configProfiles[0];let selected = profile?.driver;
    node.append(a.configField('Installed profile',selected,value => {selected = value;},a.configProfiles.map(item => item.driver),{field:'/profile'}));
    node.append(a.configButton('New from profile',() => {
      if (a.configWorking && a.configDirty()) {a.showAlert('Save current edits before loading another configuration.');return;}
      const item = a.configProfiles.find(value => value.driver === selected);
      if (item) a.startConfigDraft(item.driver,item.template || {});
    },'',{action:'configuration.new'}));
    for (const draft of a.configDrafts) node.append(a.configButton(`Load ${draft.title} · r${draft.revision}`,() => {
      if (a.configWorking && a.configDirty()) {a.showAlert('Save current edits before loading another configuration.');return;}
      return a.configAction('get',{draft_id:draft.draft_id});
    },'',{action:'configuration.get',entity:draft.draft_id,revision:draft.revision}));
    const upload = a.element('input');upload.type = 'file';upload.accept = '.json,application/json';upload.setAttribute('aria-label','Import configuration JSON');
    a.interaction.identify(upload,{action:'configuration.import',field:'/import'});
    upload.addEventListener('change',async () => {
      try {
        if (a.configWorking && a.configDirty()) throw new Error('Save current edits before importing another configuration.');
        const file = upload.files[0];if (!file) return;if (file.size > 200000) throw new Error('CONFIGURATION_TOO_LARGE');
        const value = JSON.parse(await file.text());if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('CONFIGURATION_JSON_INVALID');
        a.startConfigDraft(selected || '',value,file.name);
      } catch (error) {a.showAlert(error.message);}
    });node.append(upload);
    if (!a.configWorking) return node;
    node.append(a.configField('Configuration name',a.configTitle,value => {a.configTitle = value;},null,{field:'/title'}));
    const legacy = a.element('details','','config-advanced');legacy.append(a.element('summary','Legacy program bindings'));
    legacy.append(a.element('p','These bindings remain in the saved device configuration for compatibility. Review them against a program in Submit program.','note'));
    for (const map of this.definition()?.maps || []) if (map.section === 'program-bindings') legacy.append(this.map(map));
    node.append(legacy);
    const transfer = a.element('details','','config-advanced');transfer.append(a.element('summary','Transfer defaults'));
    transfer.append(a.element('p','Optional session defaults. Per-step flow-rate control is not configured here.','note'),this.fields(this.section(this.definition(),'transfer').fields));node.append(transfer);
    const advanced = a.element('details','','config-advanced');advanced.append(a.element('summary','Advanced configuration JSON'));
    const json = a.element('textarea');json.value = this.jsonEdited ? this.jsonText : JSON.stringify(a.configWorking,null,2);json.setAttribute('aria-label','Advanced configuration JSON');a.interaction.identify(json,{field:'/advanced-configuration'});
    json.addEventListener('input',() => {this.editJSON(json.value);a.configValidation = null;a.activation.confirmed = false;a.updateConfigActions();});
    advanced.append(a.element('p','Update proposed settings from JSON before saving. This replaces the proposal shown above.','note'),json,a.configButton('Update proposed settings from JSON',() => {
      try {
        this.proposeJSON(json.value);a.renderConfiguration();
      } catch (error) {a.showAlert(error.message);}
    },'',{action:'configuration.apply-json'}));node.append(advanced,
      a.configButton('Export validated configuration',() => a.configAction('export'),'export-draft',{action:'configuration.export'}));return node;
  }

  render() {
    const a = this.app;const context = a.element('div','','configuration-context');
    const origin = a.activation.view?.active?.origin;
    context.append(a.element('span',origin ? `Current configuration: ${origin.title} · r${origin.revision}`:'Current configuration: service startup settings'));
    const link = a.element('a','System Information');link.href = '#system';context.append(link);
    const nodes = [context];
    if (a.configWorking) nodes.push(this.renderEditor(),this.renderChanges());
    else nodes.push(a.element('p','No saved origin is available for this station. Import its configuration or start from an installed profile in Advanced.','notice'));
    nodes.push(this.renderAdvanced());a.content.replaceChildren(...nodes);a.updateConfigActions();
  }
}

/** Read-only projection of active saved configuration and installed definitions. */
export class ConsoleSystemInformation {
  constructor(app) { this.app = app; }

  model() {
    const a = this.app;const active = a.activation.view?.active;
    const candidate = a.configuration.activeRecord;
    const record = a.configuration.matchesOrigin(candidate,active) ? candidate:null;
    const profile = record ? a.configProfiles.find(item => item.driver === record.driver):null;
    const fields = (profile?.fields || []).filter(field => ['platform','instruments'].includes(field.section));
    const configured = fields.map(field => [field.label,a.display(a.configPath(record.configuration,field.path))]);
    const modules = (profile?.summaries || []).map(definition => ({label:definition.label,columns:definition.columns,
      rows:Object.entries(a.configPath(record.configuration,definition.path) || {}).map(([name,value]) => [name,...definition.columns.map(key => a.display(value?.[key]))])}));
    return {record,configured,modules,definitions:a.configProfiles.map(item => ({driver:item.driver,label:item.label,
      rows:(item.fields || []).filter(field => field.options && ['platform','instruments'].includes(field.section))
        .map(field => [field.label,field.options.join(', ')])}))};
  }

  render() {
    const a = this.app;const model = this.model();
    a.interaction.view('system',{loadState:'ready'});
    const equipment = a.card('Configured equipment');
    equipment.append(a.element('p','Source: the saved active configuration. These are declared settings, not detected hardware.','note'));
    equipment.append(a.table(['Parameter','Configured value'],model.configured,'No matching saved configuration is available.'));
    for (const module of model.modules) equipment.append(a.element('h3',module.label),a.table(['Name',...module.columns],module.rows,'None configured.'));
    const definitions = a.card('Driver definitions');
    definitions.append(a.element('p','Source: installed plugin metadata. Supported choices do not establish which hardware is connected.','note'));
    for (const profile of model.definitions) definitions.append(a.element('h3',profile.label || profile.driver),
      a.details([['Installed driver',profile.driver]]),a.table(['Parameter','Supported choices'],profile.rows));
    const connection = a.card('Connection information');
    connection.append(a.element('p','Serial ports, device network addresses, hardware identifiers and firmware versions are not collected by the current integration.','empty'));
    connection.append(a.element('p','Hardware discovery and online service settings remain future extensions.','note'));
    a.content.replaceChildren(a.activation.render(),equipment,definitions,connection);
  }
}

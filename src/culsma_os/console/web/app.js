class StationConsoleApp {
  constructor() {
    this.content = document.querySelector('#content');
    this.alert = document.querySelector('#alert');
    this.button = document.querySelector('#refresh');
    this.busy = false;
    this.pending = false;
    this.timer = null;
    this.lastObserved = null;
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
    const good = ['ready', 'completed', 'registered', 'recorded', 'Connected'];
    const bad = ['failed', 'Disconnected'];
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
    this.content.replaceChildren(back, state, semantic, material);
    this.showAlert(data.error || data.body_error || (diagnostics.length ? diagnostics.join(' · ') : null));
  }

  async refresh() {
    clearTimeout(this.timer);
    if (document.hidden) return;
    if (this.busy) { this.pending = true; return; }
    this.busy = true;
    this.button.disabled = true;
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
      if (isRun) this.renderRun(snapshot.data);
      else if (route === '#runs') this.renderRuns(snapshot.data);
      else this.renderStation(snapshot.data);
    } catch (error) {
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
      else if (!document.hidden) this.timer = setTimeout(() => this.refresh(), 2500);
    }
  }
}

new StationConsoleApp().start();

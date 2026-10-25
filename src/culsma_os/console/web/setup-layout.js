/** Read-only projection of the exact run loading plan; no live configuration queries. */
export class RunSetupLayout {
  constructor(app) {
    this.app = app;
    this.selected = new Map();
  }

  static items(plan) {
    const items = (plan.loadout || []).map(item => ({...item, kind:'labware', id:item.labware}));
    for (const supply of plan.supplies || []) items.push({...supply, id:supply.id, kind:'supply',
      placement:{carrier:supply.carrier,track:supply.track,site:supply.site,slot:supply.slot,module:supply.module},
      containers:[]});
    return items;
  }

  static groups(items) {
    const groups = new Map();
    for (const item of items) {
      const place = item.placement || {};
      const key = JSON.stringify([place.carrier || item.id,place.track || '',place.slot || '',place.module || '']);
      if (!groups.has(key)) groups.set(key,{placement:place,items:[]});
      groups.get(key).items.push(item);
    }
    const ordered = (left,right) => String(left ?? '').localeCompare(String(right ?? ''),'en',{numeric:true});
    const values = [...groups.values()].sort((a,b) => ordered(a.placement.track || a.placement.slot,b.placement.track || b.placement.slot));
    for (const group of values) group.items.sort((a,b) => ordered(a.placement?.site,b.placement?.site));
    return values;
  }

  static geometry(plan,item) {
    const rows = [...(plan.items || []).filter(row => row.address?.labware === item.id),
      ...(plan.candidates || []).filter(row => row.labware === item.id)];
    const shapes = [...new Set(rows.filter(row => Array.isArray(row.geometry)).map(row => JSON.stringify(row.geometry)))];
    if (shapes.length !== 1) return null;
    const shape = JSON.parse(shapes[0]);
    if (shape.length !== 2 || !shape.every(value => Number.isInteger(value) && value > 0 && value <= 48)) return null;
    return shape;
  }

  static rowName(index) {
    let value = index+1, name = '';
    while (value > 0) {value--;name = String.fromCharCode(65+value%26)+name;value = Math.floor(value/26);}
    return name;
  }

  static wells(plan,item) {
    const shape = this.geometry(plan,item);
    const used = new Set((item.containers || []).map(row => row.well));
    if (!shape || !used.size) return null;
    const positions = Array.from({length:shape[0]},(_,r) =>
      Array.from({length:shape[1]},(_,c) => this.rowName(r)+(c+1)));
    // Numeric/native aspiration positions are not silently relabelled as plate wells.
    if ([...used].some(well => !positions.some(row => row.includes(well)))) return null;
    return positions;
  }

  static location(item) {
    const place = item.placement || {};
    const parts = [];
    if (place.carrier) parts.push('Carrier '+place.carrier);
    if (place.track) parts.push('track '+place.track);
    if (place.slot) parts.push('slot '+place.slot);
    if (place.site) parts.push('site '+place.site);
    if (place.module) parts.push('module '+place.module);
    return parts.length ? parts.join(' · ') : 'Placement not specified in this plan';
  }

  static label(plan,item) {
    if (item.kind === 'supply') return item.id;
    const names = (item.containers || []).map(row => row.name).filter(Boolean);
    const isPlate = (plan.items || []).some(row => row.address?.labware === item.id && row.kind === 'well');
    return names.length === 1 && !isPlate ? names[0] : item.id;
  }

  render(plan,run) {
    const a = this.app, region = a.element('section','','loading-layout');
    region.dataset.region = 'loading-layout';region.dataset.setupFingerprint = plan.fingerprint;
    region.setAttribute('aria-label','Loading layout for this run');
    const items = RunSetupLayout.items(plan);
    if (!items.length) {
      region.append(a.element('p','No labware or supply placement is recorded in this loading plan.','empty'));
      return region;
    }
    const render = () => {
      let selected = items.find(item => item.id === this.selected.get(run.run_id));
      if (!selected) selected = items.find(item => RunSetupLayout.wells(plan,item)) || items[0];
      this.selected.set(run.run_id,selected.id);
      region.replaceChildren();
      const heading = a.element('div','','loading-layout-heading');
      heading.append(a.element('h3','Loading layout'),a.element('span','Required initial placement','label'));
      region.append(heading,a.element('p',
        'Select an item to inspect its location, contents and wells. Groups show declared carriers or slots; spacing is schematic, not a live image or a scale drawing.','note'));
      const board = a.element('div','','loading-board');
      for (const group of RunSetupLayout.groups(items)) {
        const carrier = a.element('section','','loading-carrier');
        const place = group.placement;
        const start = place.track ? 'Track '+place.track : place.slot ? 'Slot '+place.slot : 'Declared location';
        carrier.append(a.element('h4',start),a.element('p',place.carrier || place.module || 'Labware','label'));
        for (const item of group.items) {
          const control = a.element('button','','loading-item');control.type = 'button';
          control.dataset.labwareId = item.id;
          control.setAttribute('aria-label','Inspect '+item.id+' · '+RunSetupLayout.location(item));
          control.setAttribute('aria-pressed',String(item.id === selected.id));
          a.interaction.identify(control,{action:'setup.inspect-item',entity:item.id});
          const position = item.placement?.site ? 'Site '+item.placement.site : 'Placement';
          control.append(a.element('span',position,'loading-site'),a.element('strong',RunSetupLayout.label(plan,item)),
            a.element('span',item.model || 'Model not recorded','label'));
          const used = item.containers || [];
          const summary = item.kind === 'supply' ? `${item.available ?? 'Unknown'} declared positions` :
            RunSetupLayout.wells(plan,item) ? 'Wells '+used.map(row => row.well).join(', ') :
              used.map(row => `${row.volume_uL ?? 'Unknown'} µL`).join(' · ');
          control.append(a.element('span',summary,'loading-item-summary'));
          control.addEventListener('click',() => {
            this.selected.set(run.run_id,item.id);render();
            // Restore focus by literal identity, including names containing selector punctuation.
            [...region.querySelectorAll('[data-labware-id]')].find(node => node.dataset.labwareId === item.id)?.focus({preventScroll:true});
          });
          carrier.append(control);
        }
        board.append(carrier);
      }
      region.append(board,this.inspector(plan,selected));
    };
    render();
    return region;
  }

  inspector(plan,item) {
    const a = this.app, panel = a.element('section','','loading-inspector');
    panel.dataset.region = 'loading-inspector';panel.dataset.labwareId = item.id;
    panel.setAttribute('aria-label','Loading instructions for '+item.id);
    panel.append(a.element('h4',RunSetupLayout.label(plan,item)),a.element('p',RunSetupLayout.location(item),'loading-location'),
      a.element('p',item.model || 'Model not recorded','label'));
    if (item.placement?.orientation) panel.append(a.element('p',item.placement.orientation,'note'));
    const wells = RunSetupLayout.wells(plan,item);
    const used = new Map((item.containers || []).map(row => [row.well,row]));
    if (wells) {
      const wrapper = a.element('div','','loading-well-scroll'), grid = a.element('div','','loading-wells');
      grid.style.gridTemplateColumns = `24px repeat(${wells[0].length},minmax(26px,1fr))`;
      grid.setAttribute('role','img');grid.setAttribute('aria-label',`${wells.length} by ${wells[0].length} plate; required wells ${[...used.keys()].join(', ')}`);
      grid.append(a.element('span'));
      for (let c = 1; c <= wells[0].length; c++) grid.append(a.element('span',c,'loading-axis'));
      wells.forEach((row,r) => {
        grid.append(a.element('span',RunSetupLayout.rowName(r),'loading-axis'));
        for (const well of row) {
          const cell = a.element('span',used.has(well) ? well : '·','loading-well');
          cell.dataset.well = well;cell.dataset.required = String(used.has(well));
          cell.title = used.has(well) ? `${well}: ${used.get(well).volume_uL ?? 'Unknown'} µL initially required` : `${well}: not used by this plan`;
          grid.append(cell);
        }
      });
      wrapper.append(grid);panel.append(wrapper,a.element('p','Blue wells are used by this program. Other wells are outside this loading checklist.','note'));
    }
    if (item.kind === 'supply') {
      panel.append(a.element('p','Confirm this supply is in the declared position.','note'),
        a.table(['Declared positions','Declared available'],[[(item.positions || []).join(', ') || 'Not recorded',item.available]]));
    } else {
      const contents = value => Object.entries(value || {}).map(([name,quantity]) =>
        typeof quantity === 'object' && quantity !== null ? `${name}: ${quantity.value ?? 'Unknown'} ${quantity.unit || ''}` : `${name}: ${quantity}`).join(' · ') || 'Empty';
      panel.append(a.table(['Container / well','Initial volume (µL)','Contents'],(item.containers || []).map(row => [
        wells ? row.well : row.name || row.well,row.volume_uL,contents(row.contents)])));
    }
    return panel;
  }
}

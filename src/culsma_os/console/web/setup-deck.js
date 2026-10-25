/** Deck overview from the same driver layout descriptor used by the editor. */
export class RunSetupDeck {
  static at(value,path) {return (path || []).reduce((part,key) => part?.[key],value);}

  static scene(plan) {
    const {definition,configuration} = plan.layout || {};
    if (definition?.schema !== 'culsma_layout_v1' || !configuration) return null;
    const variant = definition.variants?.[this.at(configuration,definition.selector_path)];
    if (variant?.presentation !== 'tracks' || !Number.isInteger(variant.width) || variant.width < 1 || variant.width > 128) return null;
    const positions = variant.positions;
    if (!Array.isArray(positions) || positions.length !== variant.width ||
        positions.some((p,i) => p.x !== i || p.width !== 1 || typeof p.id !== 'string')) return null;
    const parent = definition.collections?.find(row => row.category === 'carrier');
    const children = definition.collections?.find(row => row.parent_field && row.category === 'labware');
    if (!parent?.keyed || !children?.keyed) return null;
    const carriers = this.at(configuration,parent.path),labware = this.at(configuration,children.path);
    if (!carriers || !labware || !Array.isArray(definition.catalogue)) return null;
    const occupied = new Set(), models = new Map(definition.catalogue.map(row => [row.id,row]));
    const rows = [];
    for (const [id,item] of Object.entries(carriers)) {
      const model = models.get(item[parent.model_field]), start = item[parent.position_field];
      const covered = model?.footprints?.[start],sites = model?.sites;
      if (!Array.isArray(covered) || !covered.length || !Array.isArray(sites) || !sites.length || sites.length > 16) return null;
      const indexes = covered.map(value => positions.findIndex(p => p.id === value));
      if (indexes.some((value,i) => value < 0 || (i && value !== indexes[i-1]+1) || occupied.has(value))) return null;
      indexes.forEach(value => occupied.add(value));
      const placements = Object.entries(labware).filter(([,child]) => child[children.parent_field] === id)
        .map(([name,child]) => ({id:name,site:child[children.position_field],model:child[children.model_field]}));
      if (placements.some(p => !sites.includes(p.site)) || new Set(placements.map(p => p.site)).size !== placements.length) return null;
      rows.push({id,model:item[parent.model_field],start:indexes[0],span:indexes.length,sites,placements,
        first:covered[0],last:covered.at(-1)});
    }
    return {label:variant.label,positions,carriers:rows.sort((a,b) => a.start-b.start)};
  }

  static render(app,scene,items,selected,onInspect) {
    const section = app.element('section','','setup-deck');section.dataset.region = 'loading-deck';
    section.setAttribute('aria-label',scene.label+' loading overview');
    section.append(app.element('h4',scene.label),app.element('p',
      'Track numbers run left to right. Carrier widths follow the declared layout; vertical site spacing is schematic. Blue items belong to this loading checklist.','note'));
    const viewport = app.element('div','','setup-deck-scroll');viewport.tabIndex = 0;
    viewport.setAttribute('aria-label','Scroll the complete deck horizontally');
    const board = app.element('div','','setup-deck-board');
    board.style.setProperty('--deck-tracks',scene.positions.length);board.style.minWidth = `${scene.positions.length*18}px`;
    const rails = app.element('div','','setup-deck-rails');rails.setAttribute('aria-hidden','true');
    scene.positions.forEach(position => rails.append(app.element('span',position.label || position.id,'setup-deck-track')));
    board.append(rails);
    const legend = app.element('ul','','setup-deck-legend');
    scene.carriers.forEach((carrier,index) => {
      const tag = 'C'+(index+1),range = carrier.first === carrier.last ? carrier.first : `${carrier.first}–${carrier.last}`;
      const frame = app.element('section','','setup-deck-carrier');
      frame.dataset.carrierId = carrier.id;frame.dataset.trackStart = carrier.first;frame.dataset.trackSpan = carrier.span;
      frame.style.left = `calc(${carrier.start/scene.positions.length*100}% + 2px)`;
      frame.style.width = `calc(${carrier.span/scene.positions.length*100}% - 4px)`;
      frame.setAttribute('aria-label',`${carrier.id}, tracks ${range}, ${carrier.model}`);
      const header = app.element('div',tag,'setup-deck-carrier-tag');header.title = `${carrier.id} · ${carrier.model} · tracks ${range}`;frame.append(header);
      const sites = app.element('div','','setup-deck-sites');
      carrier.sites.forEach(site => {
        const placed = carrier.placements.find(p => p.site === site),item = items.find(row => row.id === placed?.id);
        const label = placed ? placed.id : 'No labware declared';
        const cell = app.element(item ? 'button':'div',carrier.span < 3 ? site : `${site} · ${label}`,'setup-deck-site');
        cell.dataset.site = site;cell.title = `Site ${site} · ${label}`;
        if (item) {
          cell.type = 'button';cell.dataset.labwareId = item.id;cell.dataset.required = 'true';
          cell.setAttribute('aria-label',`Inspect deck item ${item.id} · carrier ${carrier.id} · site ${site}`);
          cell.setAttribute('aria-pressed',String(item.id === selected));
          app.interaction.identify(cell,{action:'setup.inspect-deck-item',entity:item.id});
          cell.addEventListener('click',() => onInspect(item.id));
        } else {cell.dataset.required = 'false';cell.setAttribute('aria-label',`Site ${site} · ${label}; outside this loading checklist`);}
        sites.append(cell);
      });
      frame.append(sites);board.append(frame);
      legend.append(app.element('li',`${tag} · ${carrier.id} · tracks ${range} · ${carrier.model}`));
    });
    viewport.append(board);section.append(viewport,legend,app.element('p',
      'Unhighlighted sites show declared layout only; their current physical contents have not been detected. Use the commissioned labware orientation.','note'));
    return section;
  }
}

/** Deck overview from the same driver layout descriptor used by the editor. */
export class RunSetupDeck {
  static at(value,path) {return (path || []).reduce((part,key) => part?.[key],value);}

  static scene(plan) {
    const {definition,configuration} = plan.layout || {};
    if (definition?.schema === 'culsma_layout_instances_v1') {
      const scene=definition.diagram?.scene;
      if (!scene || !Array.isArray(scene.positions) || !scene.positions.length || scene.positions.length>128 ||
          !Array.isArray(scene.carriers) || scene.carriers.length>128 || scene.carriers.some(row=>
            !Number.isInteger(row.start) || !Number.isInteger(row.span) || row.start<0 || row.span<1 ||
            row.start+row.span>scene.positions.length || !Array.isArray(row.sites) || !Array.isArray(row.placements))) return null;
      return {...scene,stacked:true};
    }
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

  static presentation(scene, stacked) {
    // Keep track addresses and ordering while giving narrow carriers usable controls.
    const widths=scene.positions.map(()=>24);
    for(const carrier of scene.carriers) {
      const minimum=carrier.span<3 ? 76:168;
      const perTrack=Math.max(24,Math.ceil(minimum/carrier.span));
      for(let n=carrier.start;n<carrier.start+carrier.span;n++)widths[n]=Math.max(widths[n],perTrack);
    }
    const offsets=[0];for(const width of widths)offsets.push(offsets.at(-1)+width);
    const maxSites=Math.max(1,...scene.carriers.map(c=>c.sites.length));
    const maxStack=stacked ? Math.max(1,...scene.carriers.flatMap(c=>c.sites.map(site=>c.placements.filter(p=>p.site===site).length))):1;
    const rowHeight=22+26*maxStack+Math.max(0,maxStack-1)*2;
    return {widths,offsets,total:offsets.at(-1),height:Math.max(360,maxSites*rowHeight+(maxSites-1)*6+70)};
  }

  static render(app,scene,items,selected,onInspect,options = {}) {
    const section = app.element('section','','setup-deck');section.dataset.region = 'loading-deck';
    section.setAttribute('aria-label',options.label || scene.label+' loading overview');
    section.append(app.element('h4',scene.label),app.element('p',
      options.description || 'Track numbers run left to right. Widths and site spacing are expanded for readability. Blue items belong to this loading checklist.','note'));
    const viewport = app.element('div','','setup-deck-scroll');viewport.tabIndex = 0;
    viewport.setAttribute('aria-label','Scroll the complete deck horizontally');
    const board = app.element('div','','setup-deck-board');
    if (options.stacked) board.dataset.stacked='true';
    const presentation=this.presentation(scene,options.stacked);
    board.style.setProperty('--deck-tracks',scene.positions.length);board.style.minWidth=`${presentation.total}px`;board.style.height=`${presentation.height}px`;
    const rails = app.element('div','','setup-deck-rails');rails.setAttribute('aria-hidden','true');
    rails.style.gridTemplateColumns=presentation.widths.map(width=>`${width}fr`).join(' ');
    scene.positions.forEach(position => rails.append(app.element('span',position.label || position.id,'setup-deck-track')));
    board.append(rails);
    const legend = app.element('ul','','setup-deck-legend');
    scene.carriers.forEach((carrier,index) => {
      const tag = 'C'+(index+1),range = carrier.first === carrier.last ? carrier.first : `${carrier.first}–${carrier.last}`;
      const frame = app.element('section','','setup-deck-carrier');
      if(options.highlightedCarriers?.includes(carrier.id)) frame.dataset.highlighted='true';
      frame.dataset.carrierId = carrier.id;frame.dataset.trackStart = carrier.first;frame.dataset.trackSpan = carrier.span;
      frame.style.left = `calc(${presentation.offsets[carrier.start]/presentation.total*100}% + 2px)`;
      frame.style.width = `calc(${(presentation.offsets[carrier.start+carrier.span]-presentation.offsets[carrier.start])/presentation.total*100}% - 4px)`;
      frame.dataset.compact=String(carrier.span<3);
      frame.setAttribute('aria-label',`${carrier.id}, tracks ${range}, ${carrier.model}`);
      const header = app.element('div',tag,'setup-deck-carrier-tag');header.title = `${carrier.id} · ${carrier.model} · tracks ${range}`;frame.append(header);
      const sites = app.element('div','','setup-deck-sites');
      carrier.sites.forEach(site => {
        if (options.stacked) {
          const stack=carrier.placements.filter(p=>p.site===site),slot=app.element('div','','setup-deck-stack');slot.dataset.site=site;
          if(carrier.span>=3)slot.append(app.element('span',site,'setup-deck-stack-label'));
          if(!stack.length) {
            if(options.onSelectSite) {
              const empty=app.configButton(carrier.span<3 ? site:'＋',()=>options.onSelectSite(carrier.id,site),'',
                {action:'workstation.select-labware-site',entity:carrier.id+'/'+site});
              empty.setAttribute('aria-label',`Place labware · ${carrier.id} · site ${site}`);empty.title=`Empty position · ${carrier.id} · site ${site}`;slot.append(empty);
            } else slot.append(app.element('span','—','note'));
          }
          for(const placed of stack) {
            const required=items.some(item=>item.id===placed.id);
            const cell=app.element(required ? 'button':'div',carrier.span<3 ? site:placed.id,'setup-deck-site');
            cell.dataset.labwareId=placed.id;cell.dataset.required=String(required || options.highlighted?.includes(placed.id));cell.dataset.association=placed.association;
            cell.title=placed.id;cell.setAttribute('aria-label',`Inspect deck item ${placed.id} · carrier ${carrier.id} · site ${site}`);
            if(required) {
              cell.type='button';cell.setAttribute('aria-pressed',String(placed.id===selected));
              app.interaction.identify(cell,{action:options.action || 'setup.inspect-deck-item',entity:placed.id});
              cell.addEventListener('click',()=>onInspect(placed.id));
            }
            slot.append(cell);
          }
          sites.append(slot);return;
        }
        const placed = carrier.placements.find(p => p.site === site),item = items.find(row => row.id === placed?.id);
        const label = placed ? placed.id : options.unplacedLabel || 'No labware declared';
        const cell = app.element(item ? 'button':'div',carrier.span < 3 ? site : `${site} · ${label}`,'setup-deck-site');
        cell.dataset.site = site;cell.title = `Site ${site} · ${label}`;
        if (item) {
          cell.type = 'button';cell.dataset.labwareId = item.id;cell.dataset.required = 'true';
          cell.setAttribute('aria-label',`Inspect deck item ${item.id} · carrier ${carrier.id} · site ${site}`);
          cell.setAttribute('aria-pressed',String(item.id === selected));
          app.interaction.identify(cell,{action:options.action || 'setup.inspect-deck-item',entity:item.id});
          cell.addEventListener('click',() => onInspect(item.id));
        } else {cell.dataset.required = 'false';cell.setAttribute('aria-label',`Site ${site} · ${label}; ${options.inactiveScope || 'outside this loading checklist'}`);}
        if(!placed && options.onSelectSite) {
          const empty=app.configButton(carrier.span<3 ? '＋':`${site} · Empty`,()=>options.onSelectSite(carrier.id,site),'',
            {action:'workstation.select-labware-site',entity:carrier.id+'/'+site});
          empty.setAttribute('aria-label',`Place labware · ${carrier.id} · site ${site}`);sites.append(empty);
        } else sites.append(cell);
      });
      frame.append(sites);board.append(frame);
      legend.append(app.element('li',`${tag} · ${carrier.id} · tracks ${range} · ${carrier.model}`));
    });
    const key=app.element('details','','setup-deck-key');key.append(app.element('summary','Rack names and track ranges'),legend);
    viewport.append(board);section.append(viewport,key,app.element('p',
      options.footer || 'Unhighlighted sites show declared layout only; their current physical contents have not been detected. Use the commissioned labware orientation.','note'));
    return section;
  }
}

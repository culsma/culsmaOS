import {RunSetupDeck} from './setup-deck.js';

/** Generic recorded-instance projection supplied by an installed driver. */
export class LayoutInstancesView {
  static render(app,view,selected,onSelect) {
    const section=app.element('section','','loading-layout');section.dataset.region='instance-layout';
    section.setAttribute('aria-label','Recorded instrument layout');
    const rows=view.objects || [];const active=rows.find(row=>row.id===selected) || rows.find(row=>row.category==='labware') || rows[0];
    section.append(app.element('h3',view.label || 'Instrument layout'),app.element('p',`${rows.length} recorded objects · original coordinates, rotations and stacked positions preserved`,'note'));
    if(!active) return section;
    const select=id=>{
      const previous=section.querySelector('.setup-deck-scroll')?.scrollLeft || 0;
      const next=this.render(app,view,id,onSelect);next.dataset.region=section.dataset.region;section.replaceWith(next);
      const viewport=next.querySelector('.setup-deck-scroll');
      if(viewport) {
        viewport.scrollLeft=previous;
        const button=[...viewport.querySelectorAll('[data-labware-id]')].find(row=>row.dataset.labwareId===id);
        if(button) {const v=viewport.getBoundingClientRect(),b=button.getBoundingClientRect();
          if(b.left<v.left) viewport.scrollLeft+=b.left-v.left-8;
          else if(b.right>v.right) viewport.scrollLeft+=b.right-v.right+8;
        }
      }
      if(onSelect) onSelect(id);
    };
    if(view.diagram?.schema==='culsma_layout_diagram_v1') {
      section.append(RunSetupDeck.render(app,view.diagram.scene,rows,active.id,select,{
        stacked:true,action:'configuration.inspect-recorded-object',
        description:'Tracks run left to right. Each frame is a carrier or a track-mounted rack; stacked plates and lids remain visible within their site.',
        footer:'Schematic site spacing. Free-standing objects may be grouped by recorded coordinates for display; their native parent and execution bindings remain unchanged.'}));
      const other=app.element('details','','layout-equipment');other.open=view.diagram.groups.some(group=>group.objects.includes(active.id));
      other.append(app.element('summary','Fixed equipment and placements outside the track deck'));
      const grid=app.element('div','','layout-equipment-grid');
      for(const group of view.diagram.groups) {
        const card=app.element('section','','layout-equipment-card');card.append(app.element('h4',group.label));
        for(const id of group.objects) {
          const button=app.element('button',id);button.type='button';button.dataset.objectId=id;
          button.setAttribute('aria-label',`Inspect recorded object ${id}`);button.setAttribute('aria-pressed',String(id===active.id));
          app.interaction.identify(button,{action:'configuration.inspect-recorded-object',entity:id});button.addEventListener('click',()=>select(id));card.append(button);
        }
        grid.append(card);
      }
      other.append(grid);section.append(other);
    } else section.append(app.element('p','Reimport the source layout to refresh its deck drawing. All saved instance records remain available below.','note'));
    const field=app.element('label','','config-field'),picker=app.element('select');
    field.append(app.element('span','Recorded object'));picker.setAttribute('aria-label','Recorded object');
    app.interaction.identify(picker,{field:'/layout/recorded-object'});
    for(const id of [...new Set([active.id,...rows.map(row=>row.id)])]) {const option=app.element('option',id);option.value=id;picker.append(option);}
    picker.value=active.id;picker.addEventListener('change',()=>select(picker.value));field.append(picker);
    section.append(field);
    const panel=app.element('section','','loading-inspector');panel.dataset.region='recorded-object-selection';panel.dataset.objectId=active.id;
    panel.append(app.element('h4',active.id),app.table(['Setting','Value'],[
      ['Model',active.model],['Category',active.category],['Parent / site',`${active.parent} / ${active.site || '(free placement)'}`],
      ['Origin (mm)',active.origin_mm.join(', ')],['Angle',`${active.angle_deg}°`]]));
    section.append(panel,app.element('p',view.scope,'note'));return section;
  }
}

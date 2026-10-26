/** Generic recorded-instance projection supplied by an installed driver. */
export class LayoutInstancesView {
  static render(app,view,selected,onSelect) {
    const section=app.element('section','','loading-layout');section.dataset.region='instance-layout';
    section.setAttribute('aria-label','Recorded instrument layout');
    const rows=view.objects || [];const active=rows.find(row=>row.id===selected) || rows.find(row=>row.category==='labware') || rows[0];
    section.append(app.element('h3',view.label || 'Instrument layout'),app.element('p',`${rows.length} recorded objects · original coordinates, rotations and stacked positions preserved`,'note'));
    section.append(app.element('p','Top view of recorded origins. Overlapping marks may represent stacks. Select an object to inspect its height; this diagram does not establish collision clearance.','note'));
    if(!active) return section;
    const select=id=>{const next=this.render(app,view,id,onSelect);next.dataset.region=section.dataset.region;section.replaceWith(next);if(onSelect) onSelect(id);};
    const xs=rows.map(row=>row.origin_mm[0]),ys=rows.map(row=>row.origin_mm[1]);
    const minX=Math.min(0,...xs)-30,maxX=Math.max(...xs)+60,minY=Math.min(0,...ys)-30,maxY=Math.max(...ys)+60;
    const scroll=app.element('div','','instance-layout-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','Scroll recorded object coordinates');
    const board=app.element('div','','instance-layout-board');board.setAttribute('aria-label','Recorded X and Y origins in millimetres');
    board.append(app.element('span',`X: ${Math.ceil(minX)}–${Math.ceil(maxX)} mm · Y: ${Math.ceil(minY)}–${Math.ceil(maxY)} mm`,'instance-layout-axis'));
    rows.forEach((row,index)=>{
      const dot=app.element('button',String(index+1),'instance-layout-point');dot.type='button';dot.dataset.objectId=row.id;dot.dataset.category=row.category;
      dot.style.left=`${5+(row.origin_mm[0]-minX)/(maxX-minX)*90}%`;dot.style.top=`${8+(maxY-row.origin_mm[1])/(maxY-minY)*82}%`;
      dot.title=`${row.id} · ${row.origin_mm.join(', ')} mm`;dot.setAttribute('aria-label',`Inspect recorded object ${row.id}`);dot.setAttribute('aria-pressed',String(row.id===active.id));
      app.interaction.identify(dot,{action:'configuration.inspect-recorded-object',entity:row.id});dot.addEventListener('click',()=>select(row.id));board.append(dot);
    });
    scroll.append(board);
    const field=app.element('label','','config-field'),picker=app.element('select');
    field.append(app.element('span','Recorded object'));picker.setAttribute('aria-label','Recorded object');
    app.interaction.identify(picker,{field:'/layout/recorded-object'});
    for(const id of [...new Set([active.id,...rows.map(row=>row.id)])]) {const option=app.element('option',id);option.value=id;picker.append(option);}
    picker.value=active.id;picker.addEventListener('change',()=>select(picker.value));field.append(picker);
    section.append(scroll,field);
    const panel=app.element('section','','loading-inspector');panel.dataset.region='recorded-object-selection';panel.dataset.objectId=active.id;
    panel.append(app.element('h4',active.id),app.table(['Setting','Value'],[
      ['Model',active.model],['Category',active.category],['Parent / site',`${active.parent} / ${active.site || '(free placement)'}`],
      ['Origin (mm)',active.origin_mm.join(', ')],['Angle',`${active.angle_deg}°`]]));
    section.append(panel,app.element('p',view.scope,'note'));return section;
  }
}

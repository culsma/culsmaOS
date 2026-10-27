import {RunSetupDeck} from './setup-deck.js';
import {ConsoleLabware} from './labware.js';

/** Configured geometry with direct position editing through the driver catalogue. */
export class WorkstationLayoutView {
  constructor(app) {this.app=app;this.selected=null;this.fingerprint=null;this.editor=new ConsoleLabware(app);}

  static entries(layout) {
    const {definition,configuration}=layout;
    if(definition.schema==='culsma_layout_instances_v1') return definition.objects || [];
    const rows=[];
    for(const collection of definition.collections || []) {
      const value=RunSetupDeck.at(configuration,collection.path);
      for(const [id,item] of collection.keyed ? Object.entries(value || {}):value ? [[collection.id,value]]:[]) {
        rows.push({id,model:item[collection.model_field],category:collection.category,
          site:item[collection.position_field],parent:collection.parent_field ? item[collection.parent_field]:null});
      }
    }
    for(const row of rows) if(row.parent && !row.site) row.site=rows.find(item=>item.id===row.parent)?.site;
    return rows;
  }

  static slots(layout, entries) {
    const definition=layout.definition,variant=definition.variants?.[RunSetupDeck.at(layout.configuration,definition.selector_path)];
    if(!variant || !Number.isInteger(variant.width) || variant.width<1 || variant.width>16 ||
        !Number.isInteger(variant.height) || variant.height<1 || variant.height>16 || !Array.isArray(variant.positions) || variant.positions.length>256) return null;
    if(variant.positions.some(p=>!Number.isInteger(p.x) || !Number.isInteger(p.y) || p.x<0 || p.y<0 || p.x>=variant.width || p.y>=variant.height)) return null;
    return {...variant,positions:variant.positions.map(position=>({...position,items:entries.filter(row=>{
      const footprint=definition.catalogue?.find(model=>model.id===row.model)?.footprints?.[row.site];
      return row.site===position.id || Array.isArray(footprint) && footprint.includes(position.id);
    })}))};
  }

  render(envelope) {
    const a=this.app,card=a.card('Workstation layout');card.dataset.region='workstation-layout';
    if(envelope?.status!=='available' || !envelope.layout) {
      card.append(a.element('p','The current driver has not supplied a configured layout. No imported file or past run is substituted.','empty'));return card;
    }
    if(this.fingerprint!==envelope.configuration_fingerprint) {this.selected=null;this.fingerprint=envelope.configuration_fingerprint;this.editor.reset();}
    const layout=envelope.layout,rows=WorkstationLayoutView.entries(layout),scene=RunSetupDeck.scene({layout});
    card.dataset.configurationFingerprint=envelope.configuration_fingerprint;card.dataset.source=envelope.source;
    card.append(a.element('p','Current host configuration · declared geometry, not detected hardware or contents.','note'));
    const select=id=>{this.selected=id;this.editor.selectItem(id,rows.find(row=>row.id===id)?.model);};
    const redraw=()=>{const scroll=card.querySelector('.setup-deck-scroll')?.scrollLeft || 0;const next=this.render(envelope);card.replaceWith(next);const viewport=next.querySelector('.setup-deck-scroll');if(viewport) viewport.scrollLeft=scroll;};
    this.editor.bind(envelope,redraw);
    if(scene) {
      card.append(RunSetupDeck.render(a,scene,rows,this.selected,select,{stacked:scene.stacked,
        onSelectSite:(parent,site)=>this.editor.selectSite(parent,site),
        action:'workstation.inspect-layout-item',label:'Configured workstation deck',
        description:'Click a rack position to choose its plate, reservoir or tip rack, or leave it empty.',
        footer:'Schematic site spacing. Experiment-specific loading and confirmation are recorded separately.'}));
      const groups=layout.definition.diagram?.groups || [];
      if(groups.length) {
        const other=a.element('details');other.append(a.element('summary','Fixed equipment and placements outside the track deck'));
        for(const group of groups) {other.append(a.element('h3',group.label));for(const id of group.objects) other.append(a.configButton(id,()=>select(id),'',{action:'workstation.inspect-layout-item',entity:id}));}
        card.append(other);
      }
    } else {
      const slots=WorkstationLayoutView.slots(layout,rows);
      if(!slots) {card.append(a.element('p','The driver layout does not provide supported schematic geometry.','notice'));return card;}
      const board=a.element('div','','workstation-slot-grid');board.style.gridTemplateColumns=`repeat(${slots.width},minmax(0,1fr))`;
      board.setAttribute('aria-label',slots.label);
      for(const position of slots.positions) {
        const slot=a.element('section','','workstation-slot');slot.style.gridColumn=String(position.x+1);slot.style.gridRow=String(position.y+1);
        slot.append(a.element('h3',position.label || position.id));
        if(position.fixed_label) slot.append(a.element('p',position.fixed_label,'note'));
        for(const row of position.items) {
          const button=a.configButton(row.id,()=>select(row.id),'',{action:'workstation.inspect-layout-item',entity:row.id});
          button.setAttribute('aria-label',`Inspect configured item ${row.id} · slot ${position.id}`);button.setAttribute('aria-pressed',String(this.selected===row.id));slot.append(button);
        }
        if(!position.items.length && !position.fixed_label) slot.append(a.element('p','Empty','note'));
        board.append(slot);
      }
      card.append(board);
    }
    if(this.editor.open) card.append(this.editor.render());
    const link=a.element('a','System Settings: rack layout','action-link');link.href='#configuration';card.append(link);
    return card;
  }
}

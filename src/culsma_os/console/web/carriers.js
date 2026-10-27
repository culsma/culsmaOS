import {RunSetupDeck} from './setup-deck.js';

/** Driver-declared carrier choices. Application uses the existing configuration gate. */
export class ConsoleCarriers {
  constructor(app) {this.app=app;this.catalogue=null;this.identity=null;this.target='';this.model='';this.proposal=null;this.busy=false;this.error=null;}
  redraw() {this.app.renderConfiguration();}
  async load(force=false) {
    const identity=this.app.activation.view?.active?.fingerprint;
    if(this.busy || !identity || !force && this.catalogue && identity===this.identity) return;
    if(identity!==this.identity) {this.catalogue=null;this.target='';this.model='';this.proposal=null;}
    this.identity=identity;this.busy=true;this.error=null;
    try {
      const result=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'catalogue',expected_fingerprint:identity});
      if(identity===this.app.activation.view?.active?.fingerprint) this.catalogue=result.catalogue;
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;}
  }
  select(label,value,options,onChange,field) {
    const a=this.app,wrap=a.element('label','','config-field'),select=a.element('select');
    wrap.append(a.element('span',label));select.setAttribute('aria-label',label);a.interaction.identify(select,{field});
    const empty=a.element('option','Select…');empty.value='';select.append(empty);
    for(const [id,text] of options) {const item=a.element('option',text);item.value=id;select.append(item);}
    select.value=value;select.disabled=this.busy || !!a.activation.pending();
    select.addEventListener('change',()=>{onChange(select.value);this.proposal=null;this.error=null;this.redraw();});
    wrap.append(select);return wrap;
  }
  render() {
    const a=this.app,card=a.card('Racks and carriers');card.dataset.region='carrier-settings';
    card.append(a.element('p','Replace a rack at its current track. Compatible contents keep their identifiers and sites; occupied tracks and dependent equipment are checked by the driver.','note'));
    if(this.error) {const error=a.element('p',this.error,'notice');error.setAttribute('role','alert');card.append(error);}
    const pending=a.activation.pending();
    if(pending) {
      card.append(a.element('p','A configuration application is awaiting its outcome. Check it before making another change.','notice'),
        a.configButton('Check configuration status',async()=>{await a.activation.refresh();await a.refreshConfiguration();},'',{action:'system.check-carrier-status'}));
    }
    if(!this.catalogue) {
      card.append(a.element('p',this.busy ? 'Reading rack catalogue…':'Rack editing is unavailable while the station is busy or the driver does not provide a catalogue.','notice'),
        a.configButton('Reload rack settings',async()=>{await this.load(true);this.redraw();},'',{action:'system.reload-carriers'}));return card;
    }
    const targets=this.catalogue.targets.filter(row=>row.kind==='carrier').sort((a,b)=>a.site.localeCompare(b.site,'en',{numeric:true}));
    if(!targets.length) {card.append(a.element('p','The installed driver does not expose rack replacement for this platform.','note'));return card;}
    card.append(this.select('Installed rack',this.target,targets.map(row=>[row.id,row.label]),id=>{this.target=id;this.model='';},'/carriers/target'));
    const target=targets.find(row=>row.id===this.target);
    if(!target) return card;
    card.dataset.currentModel=target.current_model;card.dataset.rackId=target.occupants[0];
    const models=this.catalogue.models;
    card.append(a.details([['Current model',models.find(m=>m.id===target.current_model)?.label || target.current_model],
      ['Starting track',target.site],['Width (tracks)',target.span ?? 'Not recorded'],['Contents',target.contents?.join(', ') || 'Empty']]));
    if(target.reason) card.append(a.element('p',target.reason,'notice'));
    else {
      card.append(this.select('Replacement rack',this.model,target.models.map(id=>[id,models.find(m=>m.id===id)?.label || id]),id=>this.model=id,'/carriers/model'));
      const button=a.configButton('Check rack replacement',()=>this.check(),'',{action:'system.check-carrier',entity:target.id});
      button.disabled=this.busy || !!pending || !this.model;card.append(button);
    }
    if(target.blocked_models?.length) {const reasons=a.element('details');reasons.append(a.element('summary','Why other racks are unavailable'),
      a.table(['Rack','Reason'],target.blocked_models.map(row=>[models.find(m=>m.id===row.id)?.label || row.id,row.reason])));card.append(reasons);}
    if(this.proposal) {
      const section=a.element('section','','loading-inspector');section.dataset.region='carrier-proposal';
      section.append(a.element('h3','Checked rack replacement · not applied'),
        a.details([['Rack identifier',target.occupants[0]],['Current',models.find(m=>m.id===target.current_model)?.label || target.current_model],
          ['Replacement',models.find(m=>m.id===this.model)?.label || this.model],['Starting track',target.site],
          ['Retained contents',target.contents?.join(', ') || 'None']]),
        a.element('p','Review the proposed deck, then apply this configuration. Physical replacement and experiment loading must be checked at the station.','note'));
      const scene=RunSetupDeck.scene({layout:this.proposal.layout});
      if(scene) section.append(RunSetupDeck.render(a,scene,[],null,()=>{},{stacked:scene.stacked,highlightedCarriers:target.occupants,label:'Proposed rack layout',description:'The blue frame is the rack being replaced. Its width follows the proposed track footprint.',footer:'Surrounding racks and compatible contents retain their identifiers. Physical installation is checked separately.'}));
      const apply=a.configButton('Apply rack replacement',()=>this.apply(),'',{action:'system.apply-carrier',entity:target.id});
      apply.disabled=this.busy || !!pending || this.identity!==a.activation.view?.active?.fingerprint;section.append(apply);card.append(section);
    }
    return card;
  }
  attachPreview() {
    this.resizeObserver?.disconnect();
    const viewport=this.app.content.querySelector('[data-region="carrier-proposal"] .setup-deck-scroll');
    const frame=viewport?.querySelector('[data-highlighted=true]');
    if(!viewport || !frame) return;
    const reveal=()=>{
      const view=viewport.getBoundingClientRect(),item=frame.getBoundingClientRect();
      if(item.left<view.left || item.right>view.right)
        viewport.scrollLeft+=item.left-view.left-(viewport.clientWidth-item.width)/2;
    };
    reveal();this.resizeObserver=new ResizeObserver(reveal);this.resizeObserver.observe(viewport);
  }
  async check() {
    if(this.busy || this.app.activation.pending() || !this.model) return;
    this.busy=true;this.error=null;this.proposal=null;this.redraw();
    try {
      if(this.app.configWorking && this.app.configDirty()) throw new Error('Save or discard the advanced configuration edits before replacing a rack.');
      this.proposal=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'prepare',expected_fingerprint:this.identity,
        change:{action:'replace-carrier',target:this.target,model:this.model}});
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;this.redraw();}
  }
  async apply() {
    const a=this.app;
    if(this.busy || !this.proposal || a.activation.pending()) return;
    this.busy=true;this.error=null;this.redraw();
    const payload={action:'apply',draft_id:this.proposal.draft.draft_id,revision:this.proposal.draft.revision,
      expected_fingerprint:this.proposal.expected_fingerprint,request_id:crypto.randomUUID()};
    try {
      a.activation.remember(payload);
      await a.configurationFetch('/api/v1/configuration/activation',payload);
      a.interaction.result('system.apply-carrier','acknowledged','Rack configuration requested. Wait for applied status before using the new layout.',{requestId:payload.request_id});
      await a.activation.refresh();
    } catch(error) {
      this.error=error.message;
      if(Number.isInteger(error.httpStatus) && error.httpStatus<500) a.activation.remember(null);
    } finally {this.busy=false;await a.refreshConfiguration();}
  }
}

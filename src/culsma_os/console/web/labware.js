import {RunSetupDeck} from './setup-deck.js';

/** Shared semantic controls; all catalogue and placement decisions belong to the driver port. */
export class ConsoleLabware {
  constructor(app) {this.app=app;this.reset();}
  reset() {this.open=false;this.catalogue=null;this.target=null;this.model='';this.category='';this.proposal=null;this.error=null;this.busy=false;this.name='';this.pending=null;this.message=null;this.selectedItem=null;}
  bind(envelope,redraw) {this.envelope=envelope;this.redraw=redraw;}
  selectItem(id) {
    this.selectedItem=id;
    if(!this.open || !this.catalogue) return;
    const target=this.catalogue.targets.find(t=>t.occupants.includes(id));
    if(target) this.select(target.id);
  }
  selectSite(parent,site) {const target=this.catalogue?.targets.find(t=>t.parent===parent && t.site===site);if(target) this.select(target.id);}
  select(id) {this.target=id;this.model='';this.category='';this.name=this.catalogue?.targets.find(t=>t.id===id)?.suggested_name || '';this.proposal=null;this.error=null;}
  toolbar() {
    const a=this.app,bar=a.element('div','','config-actions');
    const button=a.configButton(this.open ? 'Close labware editor':'Edit labware',()=>this.toggle(),'',{action:'workstation.edit-labware'});
    button.disabled=this.busy || (!this.open && this.envelope.editing_ready===false);bar.append(button);
    if(this.envelope.editing_ready===false) bar.append(a.element('p','Labware editing is available when the station is ready and the run queue is empty.','note'));return bar;
  }
  async toggle() {
    if(this.open) {this.open=false;this.redraw();return;}
    this.open=true;this.busy=true;this.redraw();
    const identity=this.envelope.configuration_fingerprint;
    try {
      const result=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'catalogue',expected_fingerprint:identity});
      if(identity!==this.envelope.configuration_fingerprint) return;
      this.catalogue=result.catalogue;this.error=null;
      if(this.selectedItem) this.selectItem(this.selectedItem);
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;this.redraw();}
  }
  choice(label,value,choices,onChange,field) {
    const a=this.app,wrap=a.element('label','','config-field'),select=a.element('select');
    wrap.append(a.element('span',label));select.setAttribute('aria-label',label);a.interaction.identify(select,{field});
    const empty=a.element('option','Select…');empty.value='';select.append(empty);
    for(const [id,text] of choices) {const option=a.element('option',text);option.value=id;select.append(option);}
    select.value=value || '';select.disabled=this.busy || !!this.pending;
    select.addEventListener('change',()=>{onChange(select.value);this.proposal=null;this.redraw();});wrap.append(select);return wrap;
  }
  render() {
    const a=this.app,box=a.element('section','','loading-inspector labware-editor');box.dataset.region='labware-editor';
    box.setAttribute('aria-label','Labware placement editor');box.append(a.element('h3','Place or replace labware'));
    box.append(a.element('p','Keep racks fixed. Choose a compatible plate, reservoir or tip rack. Check the proposed layout, then apply it. Reagents and physical loading are confirmed separately.','note'));
    if(this.error) {const alert=a.element('p',this.error,'notice');alert.setAttribute('role','alert');box.append(alert);}
    if(this.message) {const message=a.element('p',this.message,'notice');message.setAttribute('role','status');box.append(message);}
    if(!this.catalogue) {box.append(a.element('p',this.busy ? 'Reading driver catalogue…':'Labware editing is unavailable for this station.','note'));return box;}
    box.append(this.choice('Rack site',this.target,this.catalogue.targets.map(t=>[t.id,t.label+(t.occupants.length ? ' · '+t.occupants.join(', '):' · Empty')]),id=>this.select(id),'/labware/target'));
    const target=this.catalogue.targets.find(t=>t.id===this.target);
    if(!target) return box;
    if(target.reason) {box.append(a.element('p',target.reason,'notice'));return box;}
    const models=this.catalogue.models.filter(m=>target.models.includes(m.id));
    box.append(this.choice('Labware category',this.category,[...new Set(models.map(m=>m.category))].map(c=>[c,c]),value=>{this.category=value;this.model='';},'/labware/category'));
    box.append(this.choice('Labware model',this.model,models.filter(m=>m.category===this.category).map(m=>[m.id,m.label]),value=>this.model=value,'/labware/model'));
    if(!target.occupants.length) {
      const label=a.element('label','','config-field'),input=a.element('input');input.value=this.name;
      label.append(a.element('span','Labware identifier'));input.setAttribute('aria-label','Labware identifier');
      a.interaction.identify(input,{field:'/labware/name'});input.disabled=this.busy || !!this.pending;
      input.addEventListener('input',()=>{this.name=input.value;this.proposal=null;box.querySelector('[data-region="labware-proposal"]')?.remove();});label.append(input);box.append(label);
    }
    const actions=a.element('div','','config-actions');
    const check=a.configButton(target.occupants.length ? 'Check replacement':'Check placement',()=>this.prepare(target.occupants.length ? 'replace':'place'),'',{action:'workstation.check-labware',entity:target.id});
    check.disabled=this.busy || !!this.pending || !this.model;actions.append(check);
    if(target.occupants.length) {const remove=a.configButton('Check removal',()=>this.prepare('remove'),'',{action:'workstation.remove-labware',entity:target.id});remove.disabled=this.busy || !!this.pending;actions.append(remove);}
    box.append(actions);
    if(this.proposal) {
      const preview=a.element('section','','labware-proposal');preview.dataset.region='labware-proposal';
      preview.append(a.element('h4','Checked proposal · not applied'),a.element('p','This changes the declared layout only. It does not load labware, replenish tips or confirm contents.','note'));
      const change=this.proposal.change;
      preview.append(a.details([['Change',change.action],['Rack site',target.label],['Labware',target.occupants[0] || change.name],['Model',change.model || 'Remove from declared layout']]));
      const scene=RunSetupDeck.scene({layout:this.proposal.layout});
      if(scene) preview.append(RunSetupDeck.render(a,scene,[],null,()=>{},{stacked:scene.stacked,highlighted:[target.occupants[0] || change.name],label:'Proposed labware layout',description:'Review the proposed placement before application.'}));
      const apply=a.configButton(this.pending ? 'Check apply status':'Apply checked change',()=>this.apply(),'',{action:'workstation.apply-labware',entity:this.proposal.draft.draft_id});apply.disabled=this.busy || this.envelope.editing_ready===false;preview.append(apply);box.append(preview);
    }
    return box;
  }
  async prepare(action) {
    if(this.busy || this.pending) return;
    this.busy=true;this.proposal=null;this.error=null;this.redraw();
    const identity=this.envelope.configuration_fingerprint;
    try {
      const change={action,target:this.target};if(action!=='remove') change.model=this.model;if(action==='place') change.name=this.name;
      const proposal=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'prepare',expected_fingerprint:identity,change});
      if(identity===this.envelope.configuration_fingerprint) this.proposal={...proposal,change};
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;this.redraw();}
  }
  async apply() {
    if(this.busy || !this.proposal) return;
    this.busy=true;this.error=null;this.redraw();
    try {
      if(this.pending) {await this.app.activation.refresh();this.message='Apply status: '+(this.app.activation.view?.receipt?.status || 'unavailable');return;}
      const payload={action:'apply',draft_id:this.proposal.draft.draft_id,revision:this.proposal.draft.revision,
        expected_fingerprint:this.proposal.expected_fingerprint,request_id:crypto.randomUUID()};
      this.pending=payload;this.app.activation.remember(payload);
      const receipt=await this.app.configurationFetch('/api/v1/configuration/activation',payload);
      this.message='Apply request '+receipt.status+'. Wait for the station to report ready; no experiment was started.';
      await this.app.activation.refresh();
    } catch(error) {this.error=error.message;if(Number.isInteger(error.httpStatus) && error.httpStatus<500) {this.pending=null;this.app.activation.remember(null);}}
    finally {this.busy=false;this.redraw();}
  }
}

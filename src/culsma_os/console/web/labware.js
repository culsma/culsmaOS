/** Shared semantic controls; all catalogue and placement decisions belong to the driver port. */
export class ConsoleLabware {
  constructor(app) {this.app=app;this.reset();}
  reset() {this.open=false;this.catalogue=null;this.target=null;this.model='';this.category='';this.proposal=null;this.error=null;this.busy=false;this.applying=false;this.name='';this.pending=null;this.message=null;this.desired=null;this.focus=null;this.requestVersion=(this.requestVersion || 0)+1;}
  bind(envelope,redraw) {
    const becameReady=this.envelope?.editing_ready===false && envelope.editing_ready!==false;
    this.envelope=envelope;this.redraw=redraw;
    if(this.pending && !this.app.activation.pending() && this.app.activation.view?.receipt?.request_id===this.pending.request_id) this.pending=null;
    if(becameReady && this.open && !this.catalogue && !this.busy && this.desired)
      queueMicrotask(()=>{if(this.open && this.envelope.editing_ready!==false)this.edit(this.desired);});
  }
  update(focus=null) {
    const active=document.activeElement;
    if(focus) this.focus=focus;
    else if(active?.closest('[data-region="labware-editor"]')) this.focus={field:active.dataset.field,action:active.dataset.action};
    this.redraw();
  }
  selectItem(id,model) {return this.edit({item:id,model});}
  selectSite(parent,site) {return this.edit({parent,site});}
  select(id) {
    const target=this.catalogue?.targets.find(t=>t.id===id);
    const current=this.catalogue?.models.find(m=>m.id===this.desired?.model);
    this.target=id;this.model=current?.id || '';this.category=target?.occupants.length ? current?.category || '':'empty';
    this.name=target?.suggested_name || '';this.proposal=null;this.error=null;
  }
  resolveSelection() {
    const desired=this.desired || {};
    const target=this.catalogue?.targets.find(t=>desired.item ? t.occupants.includes(desired.item):t.parent===desired.parent && t.site===desired.site);
    if(target) this.select(target.id);
    else {this.target=null;this.error='This position is read-only in the installed driver.';}
  }
  async edit(selection) {
    if(this.pending || this.busy && this.catalogue) {
      this.open=true;this.message='Finish checking the current change before editing another position.';this.update();return;
    }
    this.open=true;this.desired=selection;this.target=null;this.proposal=null;this.error=null;this.message=null;this.focus=null;
    if(this.envelope.editing_ready===false) {this.error='The station must be ready with an empty run queue before changing labware.';this.update();return;}
    if(this.catalogue) {this.resolveSelection();this.update();return;}
    if(this.busy) {this.update();return;}
    this.busy=true;this.update();
    const identity=this.envelope.configuration_fingerprint,version=this.requestVersion;
    try {
      const result=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'catalogue',expected_fingerprint:identity});
      if(version!==this.requestVersion || identity!==this.envelope.configuration_fingerprint) return;
      this.catalogue={...result.catalogue,targets:result.catalogue.targets.filter(t=>t.kind!=='carrier')};
      this.resolveSelection();
    } catch(error) {if(version===this.requestVersion)this.error=error.message;}
    finally {if(version===this.requestVersion){this.busy=false;this.update();}}
  }
  close() {
    this.open=false;this.focus=null;this.update();
    const desired=this.desired || {};
    queueMicrotask(()=>{
      const buttons=[...this.app.content.querySelectorAll('[data-action]')];
      buttons.find(node=>desired.item ? node.dataset.entityId===desired.item:
        node.dataset.entityId===desired.parent+'/'+desired.site)?.focus({preventScroll:true});
    });
  }
  present(dialog) {
    queueMicrotask(()=>{
      if(!this.open || !dialog.isConnected) return;
      if(!dialog.open) dialog.showModal();
      const focus=this.focus;
      const control=[...dialog.querySelectorAll('[data-field],[data-action]')].find(node=>
        focus?.field ? node.dataset.field===focus.field:focus?.action && node.dataset.action===focus.action);
      if(control && !control.disabled) {control.focus({preventScroll:true});if(focus?.action==='workstation.apply-labware')control.scrollIntoView({block:'nearest'});}
    });
  }
  choice(label,value,choices,onChange,field) {
    const a=this.app,wrap=a.element('label','','config-field'),select=a.element('select');
    wrap.append(a.element('span',label));select.setAttribute('aria-label',label);a.interaction.identify(select,{field});
    const empty=a.element('option','Select…');empty.value='';select.append(empty);
    for(const [id,text] of choices) {const option=a.element('option',text);option.value=id;select.append(option);}
    select.value=value || '';select.disabled=this.busy || !!this.pending;
    select.addEventListener('change',()=>{onChange(select.value);this.proposal=null;this.update();});wrap.append(select);return wrap;
  }
  render() {
    const a=this.app,dialog=a.element('dialog','','labware-dialog');dialog.dataset.region='labware-editor';
    dialog.setAttribute('aria-labelledby','labware-editor-title');
    dialog.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    const top=a.element('div','','content-heading'),heading=a.element('h2','Edit rack position');heading.id='labware-editor-title';
    const close=a.configButton('Close',()=>this.close(),'',{action:'workstation.close-labware'});top.append(heading,close);dialog.append(top);
    const box=a.element('div','','labware-dialog-body');dialog.append(box);
    const target=this.catalogue?.targets.find(t=>t.id===this.target);
    const location=target?.label || (this.desired?.parent ? this.desired.parent+' · site '+this.desired.site:this.desired?.item);
    if(location) box.append(a.element('p',location,'loading-location'));
    if(this.error) {const alert=a.element('p',this.error,'notice');alert.setAttribute('role','alert');box.append(alert);}
    if(this.pending || a.activation.pending()) {
      box.append(a.element('p','A layout change is awaiting its outcome. Check its status before making another change.','notice'),
        a.configButton('Check apply status',()=>this.checkApplyStatus(),'',{action:'workstation.check-labware-status'}));
    }
    if(this.message) {const message=a.element('p',this.message,'notice');message.setAttribute('role','status');box.append(message);}
    if(this.busy) box.append(a.element('p',this.applying ? 'Applying the layout change…':this.catalogue ? 'Checking the change…':'Loading choices for this position…','note'));
    if(!this.catalogue && !this.busy && this.envelope.editing_ready!==false) box.append(a.configButton('Retry loading choices',()=>this.edit(this.desired),'',{action:'workstation.retry-labware'}));
    if(target) {
      box.append(a.details([['Current contents',target.occupants.join(', ') || 'Empty'],
        ...(this.desired?.model ? [['Current model',this.catalogue.models.find(m=>m.id===this.desired.model)?.label || this.desired.model]]:[])]));
      if(target.note) box.append(a.element('p',target.note,'note'));
      if(target.reason) box.append(a.element('p',target.reason,'notice'));
      else if(this.envelope.editing_ready!==false) {
        const models=this.catalogue.models.filter(m=>target.models.includes(m.id));
        const labels={plate:'Plate',reservoir:'Reservoir',tips:'Tip rack'};
        box.append(this.choice('Contents',this.category,[['empty','Empty position'],...[...new Set(models.map(m=>m.category))].map(c=>[c,labels[c] || c])],value=>{this.category=value;const choices=models.filter(m=>m.category===value);this.model=choices.length===1 ? choices[0].id:'';},'/labware/category'));
        if(this.category && this.category!=='empty') {
          box.append(this.choice('Labware model',this.model,models.filter(m=>m.category===this.category).map(m=>[m.id,m.label]),value=>this.model=value,'/labware/model'));
          if(!target.occupants.length) {
            const advanced=a.element('details');advanced.append(a.element('summary','Advanced identification'));
            const label=a.element('label','','config-field'),input=a.element('input');input.value=this.name;
            label.append(a.element('span','Labware identifier'));input.setAttribute('aria-label','Labware identifier');
            a.interaction.identify(input,{field:'/labware/name'});input.disabled=this.busy || !!this.pending;
            input.addEventListener('input',()=>{this.name=input.value;this.proposal=null;box.querySelector('[data-region="labware-proposal"]')?.remove();});label.append(input);advanced.append(label);box.append(advanced);
          }
        }
        const empty=this.category==='empty',action=empty ? 'remove':target.occupants.length ? 'replace':'place';
        const check=a.configButton(empty ? 'Check removal':target.occupants.length ? 'Check replacement':'Check placement',()=>this.prepare(action),'',{action:empty ? 'workstation.remove-labware':'workstation.check-labware',entity:target.id});
        check.disabled=this.busy || !!this.pending || !this.category || (empty ? !target.occupants.length:!this.model || target.occupants.length && this.model===this.desired?.model);box.append(check);
        if(empty && !target.occupants.length) box.append(a.element('p','This position is already empty.','note'));
        if(this.proposal) {
          const preview=a.element('section','','labware-proposal');preview.dataset.region='labware-proposal';
          preview.append(a.element('h3','Checked proposal · not applied'));
          const change=this.proposal.change;
          preview.append(a.details([['Position',target.label],['Change',change.action],['Contents',change.action==='remove' ? 'Empty':models.find(m=>m.id===change.model)?.label || change.model]]),
            a.element('p',change.action==='remove' ? 'This position has not changed yet. Confirm removal below to leave it empty.':'Apply to update this position in the layout. Physical loading is confirmed before an experiment runs.','note'));
          if(this.proposal.impact?.length) {const effects=a.element('section');effects.setAttribute('aria-label','Related configuration changes');effects.append(a.element('h4','Related configuration changes'));const list=a.element('ul');for(const item of this.proposal.impact)list.append(a.element('li',item));effects.append(list);preview.append(effects);}
          const apply=a.configButton(change.action==='remove' ? 'Confirm removal':'Apply checked change',()=>this.apply(),'',{action:'workstation.apply-labware',entity:this.proposal.draft.draft_id});
          apply.disabled=this.busy || this.envelope.editing_ready===false;if(!this.pending && !a.activation.pending())preview.append(apply);box.append(preview);
        }
      }
    }
    this.present(dialog);return dialog;
  }
  async checkApplyStatus() {
    if(this.busy) return;
    this.busy=true;this.update();
    try {
      await this.app.activation.refresh();
      this.message='Apply status: '+(this.app.activation.view?.receipt?.status || 'unavailable');
      if(!this.app.activation.pending()) this.pending=null;
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;this.update();this.app.renderKey=null;this.app.refresh();}
  }
  async prepare(action) {
    if(this.busy || this.pending || this.app.activation.pending() || !this.target || this.envelope.editing_ready===false) return;
    this.busy=true;this.proposal=null;this.error=null;this.update();
    const identity=this.envelope.configuration_fingerprint;
    try {
      const change={action,target:this.target};if(action!=='remove') change.model=this.model;if(action==='place') change.name=this.name;
      const proposal=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'prepare',expected_fingerprint:identity,change});
      if(identity===this.envelope.configuration_fingerprint) this.proposal={...proposal,change};
    } catch(error) {this.error=error.message;}
    finally {this.busy=false;this.update(this.proposal?.change.action==='remove' ? {action:'workstation.apply-labware'}:null);}
  }
  async apply() {
    if(this.busy || !this.proposal) return;
    this.busy=true;this.applying=true;this.error=null;this.update();
    try {
      if(this.pending) {await this.app.activation.refresh();this.message='Apply status: '+(this.app.activation.view?.receipt?.status || 'unavailable');return;}
      const payload={action:'apply',draft_id:this.proposal.draft.draft_id,revision:this.proposal.draft.revision,
        expected_fingerprint:this.proposal.expected_fingerprint,request_id:crypto.randomUUID()};
      this.pending=payload;this.app.activation.remember(payload);
      const receipt=await this.app.configurationFetch('/api/v1/configuration/activation',payload);
      this.message='Apply request '+receipt.status+'. Wait for the station to report ready; no experiment was started.';
      await this.app.activation.refresh();
    } catch(error) {this.error=error.message;if(Number.isInteger(error.httpStatus) && error.httpStatus<500) {this.pending=null;this.app.activation.remember(null);}}
    finally {this.busy=false;this.applying=false;this.update();}
  }
}

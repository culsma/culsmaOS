/** Shared semantic controls; all catalogue and placement decisions belong to the driver port. */
export class ConsoleLabware {
  constructor(app) {this.app=app;this.reset();}
  reset() {this.open=false;this.catalogue=null;this.target=null;this.model='';this.category='';this.proposal=null;this.error=null;this.busy=false;this.saving=false;this.confirmed=null;this.name='';this.pending=null;this.message=null;this.desired=null;this.focus=null;this.requestVersion=(this.requestVersion || 0)+1;}
  bind(envelope,redraw) {
    const becameReady=this.envelope?.editing_ready===false && envelope.editing_ready!==false;
    this.envelope=envelope;this.redraw=redraw;
    if(this.confirmed)queueMicrotask(()=>this.completeSave());
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
    if(this.pending || this.saving) {
      this.open=true;this.message='Finish saving the current position before editing another one.';this.update();return;
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
      if(control && !control.disabled) control.focus({preventScroll:true});
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
  changed(target) {
    return !!this.category && (this.category==='empty' ? target.occupants.length>0:
      !!this.model && (!target.occupants.length || this.model!==this.desired?.model));
  }
  render() {
    const a=this.app,dialog=a.element('dialog','','labware-dialog');dialog.dataset.region='labware-editor';
    dialog.setAttribute('aria-labelledby','labware-editor-title');dialog.setAttribute('aria-busy',String(this.saving));
    dialog.addEventListener('cancel',event=>{event.preventDefault();this.close();});
    const top=a.element('div','','content-heading'),heading=a.element('h2','Edit rack position');heading.id='labware-editor-title';
    const close=a.configButton('×',()=>this.close(),'',{action:'workstation.close-labware'});close.classList.add('labware-close');close.setAttribute('aria-label','Close');
    top.append(heading,close);dialog.append(top);
    const box=a.element('div','','labware-dialog-body');dialog.append(box);
    const target=this.catalogue?.targets.find(t=>t.id===this.target);
    const location=target?.label || (this.desired?.parent ? this.desired.parent+' · site '+this.desired.site:this.desired?.item);
    if(location) box.append(a.element('p',location,'loading-location'));
    if(this.error) {const alert=a.element('p',this.error,'notice');alert.setAttribute('role','alert');box.append(alert);}
    if(this.message) {const message=a.element('p',this.message,'note');message.setAttribute('role','status');box.append(message);}
    if(this.busy) {const progress=a.element('p',this.saving ? 'Saving changes…':'Loading choices for this position…','note');progress.setAttribute('role','status');box.append(progress);}
    if((this.pending || a.activation.pending()) && !this.saving) {
      box.append(a.element('p','The save result is not confirmed. Check its status before saving again.','notice'),
        a.configButton('Check save status',()=>this.checkSaveStatus(),'',{action:'workstation.check-labware-status'}));
    }
    if(!this.catalogue && !this.busy && this.envelope.editing_ready!==false) box.append(a.configButton('Retry loading choices',()=>this.edit(this.desired),'',{action:'workstation.retry-labware'}));
    if(target) {
      box.append(a.details([['Current contents',target.occupants.join(', ') || 'Empty'],
        ...(this.desired?.model ? [['Current model',this.catalogue.models.find(m=>m.id===this.desired.model)?.label || this.desired.model]]:[])]));
      if(target.note) box.append(a.element('p',target.note,'note'));
      if(target.reason) box.append(a.element('p',target.reason,'notice'));
      else if(this.envelope.editing_ready!==false || this.saving || this.pending) {
        const fields=a.element('div','','labware-fields'),models=this.catalogue.models.filter(m=>target.models.includes(m.id));
        const labels={plate:'Plate',reservoir:'Reservoir',tips:'Tip rack'};
        fields.append(this.choice('Contents',this.category,[['empty','Empty position'],...[...new Set(models.map(m=>m.category))].map(c=>[c,labels[c] || c])],value=>{this.category=value;const choices=models.filter(m=>m.category===value);this.model=choices.length===1 ? choices[0].id:'';},'/labware/category'));
        if(this.category && this.category!=='empty') {
          fields.append(this.choice('Labware model',this.model,models.filter(m=>m.category===this.category).map(m=>[m.id,m.label]),value=>this.model=value,'/labware/model'));
          if(!target.occupants.length) {
            const advanced=a.element('details');advanced.append(a.element('summary','Advanced identification'));
            const label=a.element('label','','config-field'),input=a.element('input');input.value=this.name;
            label.append(a.element('span','Labware identifier'));input.setAttribute('aria-label','Labware identifier');
            a.interaction.identify(input,{field:'/labware/name'});input.disabled=this.busy || !!this.pending;
            input.addEventListener('input',()=>{this.name=input.value;this.proposal=null;});label.append(input);advanced.append(label);fields.append(advanced);
          }
        }
        box.append(fields);
        if(target.occupants.length && this.changed(target)) box.append(a.element('p','Changing these contents also clears any linked program bindings and liquid or tip settings. Configure those again before running an affected experiment.','note'));
        if(this.proposal?.impact?.length && this.error) {
          const effects=a.element('section');effects.setAttribute('aria-label','Related configuration changes');effects.append(a.element('h3','Related configuration changes'));
          const list=a.element('ul');for(const item of this.proposal.impact)list.append(a.element('li',item));effects.append(list);box.append(effects);
        }
        const actions=a.element('div','','labware-actions');
        const cancel=a.configButton('Cancel',()=>this.close(),'',{action:'workstation.cancel-labware'});
        const save=a.configButton(this.saving ? 'Saving…':'Save changes',()=>this.save(),'',{action:'workstation.save-labware',entity:target.id});
        save.classList.add('primary');save.disabled=this.busy || !!this.pending || !!a.activation.pending() || this.envelope.editing_ready===false || !this.changed(target);
        actions.append(cancel,save);box.append(actions);
      }
    }
    this.present(dialog);return dialog;
  }
  observeActivation(view) {
    if(!this.pending || view?.receipt?.request_id!==this.pending.request_id) return;
    const receipt=view.receipt;
    if(receipt.status==='applied') {
      this.confirmed={receipt,fingerprint:view.active.fingerprint};this.saving=true;this.busy=true;
      this.app.renderKey=null;this.app.refresh();this.completeSave();
    } else if(['failed','interrupted'].includes(receipt.status)) {
      this.pending=null;this.saving=false;this.busy=false;
      this.error='Layout could not be saved: '+(receipt.error || receipt.status)+'. Inspect the station before trying again.';this.update();
      this.app.renderKey=null;this.app.refresh();
    }
  }
  completeSave() {
    if(!this.confirmed || this.envelope.configuration_fingerprint!==this.confirmed.fingerprint || this.envelope.editing_ready===false)return;
    const target=this.target,impact=this.proposal?.impact || [],receipt=this.confirmed.receipt;
    this.reset();this.update();
    this.app.interaction.result('workstation.save-labware','succeeded','Layout saved.'+(impact.length ? ' '+impact.join(' '):''),{entity:target,requestId:receipt.request_id});
  }
  async checkSaveStatus() {
    if(this.busy) return;
    this.busy=true;this.update();
    try {await this.app.activation.refresh();}
    catch(error) {this.error=error.message;}
    finally {this.busy=false;this.update();this.app.renderKey=null;this.app.refresh();}
  }
  async save() {
    const target=this.catalogue?.targets.find(t=>t.id===this.target);
    if(this.busy || this.pending || this.app.activation.pending() || !target || !this.changed(target) || this.envelope.editing_ready===false) return;
    this.busy=true;this.saving=true;this.proposal=null;this.error=null;this.message=null;this.update();
    const identity=this.envelope.configuration_fingerprint;
    try {
      const action=this.category==='empty' ? 'remove':target.occupants.length ? 'replace':'place';
      const change={action,target:target.id};if(action!=='remove')change.model=this.model;if(action==='place')change.name=this.name;
      const proposal=await this.app.configurationFetch('/api/v1/configuration/labware',{action:'prepare',expected_fingerprint:identity,change});
      if(identity!==this.envelope.configuration_fingerprint)throw new Error('The station layout changed. Reopen this position before saving.');
      this.proposal={...proposal,change};
      const payload={action:'apply',draft_id:proposal.draft.draft_id,revision:proposal.draft.revision,
        expected_fingerprint:proposal.expected_fingerprint,request_id:crypto.randomUUID()};
      this.pending=payload;this.app.activation.remember(payload);
      await this.app.configurationFetch('/api/v1/configuration/activation',payload);
      await this.app.activation.refresh();
    } catch(error) {
      this.error=error.message;
      if(this.pending && Number.isInteger(error.httpStatus) && error.httpStatus<500) {this.pending=null;this.app.activation.remember(null);}
      this.saving=false;this.busy=false;
      // An unknown response is reconciled by identity, never by resending the change.
      if(this.pending) {try {await this.app.activation.refresh();} catch {}}
    } finally {
      if(!this.pending || !this.saving)this.busy=false;
      this.update();
    }
  }
}

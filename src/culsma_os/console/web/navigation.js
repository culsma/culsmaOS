/** Navigation is presentation state only; changing pages never issues a command. */
export class ConsoleNavigation {
  static groups = [
    {label:'Workstation',items:[['Overview','#station'],['Current State','#workstation-state'],['Layout','#configuration']]},
    {label:'Experiment Runs',items:[['New Run','#programs'],['Active Runs and Queue','#runs'],['Run History','#history']]},
    {label:'System Information',items:[['Platform and Equipment','#system'],['Drivers and Capabilities','#system/drivers'],
      ['Runtime Environment','#system/runtime'],['Service and Connection','#system/service']]}
  ];
  static terminal = new Set(['completed','cancelled','failed','rejected']);

  static resolve(hash) {
    const route=hash || '#station';
    const run=route.match(/^#run\/([^/]+)(?:\/(preparation|execution|results))?$/);
    if(run) return {page:'run',section:run[2] || null,runId:decodeURIComponent(run[1]),group:'Experiment Runs'};
    for(const group of this.groups) for(const [label,href] of group.items) if(href===route) {
      const page=group.label==='System Information' ? 'system' : href==='#configuration' ? 'configuration'
        : href==='#programs' ? 'programs' : ['#runs','#history'].includes(href) ? 'runs':'station';
      return {page,section:href==='#history' ? 'history':href==='#workstation-state' ? 'state':href.split('/')[1] || 'overview',group:group.label,label};
    }
    return {page:'station',section:'overview',group:'Workstation',label:'Overview'};
  }

  static phase(run, requested) {
    if(['preparation','execution','results'].includes(requested)) return requested;
    return run.status==='awaiting_setup' ? 'preparation' : this.terminal.has(run.status) ? 'results':'execution';
  }

  static runs(records, history=false) {
    return records.filter(run=>this.terminal.has(run.status)===history);
  }

  constructor(app) {
    this.app=app;
    const nav=document.querySelector('#console-navigation');
    for(const group of ConsoleNavigation.groups) {
      const section=app.element('section','','navigation-group');
      section.append(app.element('h2',group.label));section.dataset.navigationGroup=group.label;
      for(const [label,href] of group.items) {
        const link=app.element('a',label);link.href=href;
        app.interaction.identify(link,{action:'navigate.'+ConsoleNavigation.resolve(href).page,entity:href});
        section.append(link);
      }
      nav.append(section);
    }
    const toggle=document.querySelector('#navigation-toggle');
    toggle.addEventListener('click',()=>{
      const expanded=toggle.getAttribute('aria-expanded')!=='true';
      toggle.setAttribute('aria-expanded',String(expanded));nav.classList.toggle('menu-open',expanded);
    });
  }

  select() {
    const current=ConsoleNavigation.resolve(location.hash);
    for(const link of document.querySelectorAll('#console-navigation a')) {
      const active=link.hash===(location.hash || '#station');
      if(active) link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    }
    for(const group of document.querySelectorAll('[data-navigation-group]')) group.dataset.active=String(group.dataset.navigationGroup===current.group);
    document.querySelector('#page-context').textContent=current.group+(current.page==='run' ? ' / Run Details':current.label ? ' / '+current.label:'');
  }

  restoreFocus() {
    if(this.pendingFocus) {document.getElementById(this.pendingFocus)?.focus({preventScroll:true});this.pendingFocus=null;}
  }

  runTabs(run, phase) {
    const a=this.app,tabs=a.element('div','','section-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Run stages');
    for(const name of ['preparation','execution','results']) {
      const tab=a.configButton(name[0].toUpperCase()+name.slice(1),()=>{this.pendingFocus='run-tab-'+name;location.hash=`#run/${encodeURIComponent(run.run_id)}/${name}`;},'',
        {action:'run.stage',entity:name});
      tab.id='run-tab-'+name;tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(phase===name));
      tab.setAttribute('aria-controls','run-panel-'+name);tab.tabIndex=phase===name ? 0:-1;
      tab.addEventListener('keydown',event=>{
        const keys=['ArrowLeft','ArrowRight','Home','End'];if(!keys.includes(event.key)) return;
        event.preventDefault();const names=['preparation','execution','results'];
        const next=event.key==='Home' ? 0:event.key==='End' ? 2:(names.indexOf(name)+(event.key==='ArrowRight' ? 1:2))%3;
        this.pendingFocus='run-tab-'+names[next];location.hash=`#run/${encodeURIComponent(run.run_id)}/${names[next]}`;
      });tabs.append(tab);
    }
    return tabs;
  }
}

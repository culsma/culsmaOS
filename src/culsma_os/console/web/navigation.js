/** Navigation is presentation state only; changing pages never issues a command. */
export class ConsoleNavigation {
  static groups = [
    {label:'Workstation',items:[['Workstation','#station']]},
    {label:'System Settings',items:[['System Settings','#configuration']]},
    {label:'System Info',items:[['System Info','#system']]}
  ];
  static terminal = new Set(['completed','cancelled','failed','rejected']);

  static resolve(hash) {
    const route=hash || '#station';
    const run=route.match(/^#run\/([^/]+)(?:\/(preparation|execution|results))?$/);
    if(run) return {page:'run',section:run[2] || null,runId:decodeURIComponent(run[1]),group:'Workstation'};
    if(route==='#configuration') return {page:'configuration',section:'layout',group:'System Settings',label:'System Settings'};
    if(/^#system(?:\/(drivers|runtime|service))?$/.test(route)) return {page:'system',section:route.split('/')[1] || 'overview',group:'System Info',label:'System Info'};
    const aliases={'#programs':['programs','new'],'#runs':['runs','active'],'#history':['runs','history'],'#workstation-state':['station','state']};
    const [page,section]=aliases[route] || ['station','overview'];
    return {page,section,group:'Workstation',label:'Workstation'};
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
      section.dataset.navigationGroup=group.label;
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
      const active=ConsoleNavigation.resolve(link.hash).group===current.group;
      if(active) link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
    }
    for(const group of document.querySelectorAll('[data-navigation-group]')) group.dataset.active=String(group.dataset.navigationGroup===current.group);
    document.querySelector('#page-context').textContent='Local laboratory workspace';
  }

}

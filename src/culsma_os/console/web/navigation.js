/** Navigation is presentation state only; changing pages never issues a command. */
export class ConsoleNavigation {
  static terminal = new Set(['completed','cancelled','failed','rejected']);

  static resolve(hash) {
    const route=hash || '#programs';
    if(route==='#desktop') return {page:'desktop',group:'Desktop',label:'Desktop'};
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

  constructor(app) { this.app=app; }

  select() {
    const current=ConsoleNavigation.resolve(location.hash);
    const context=document.querySelector('#page-context');
    if(context) context.textContent=current.page==='run' ? 'Experiment execution':'Local laboratory workspace';
  }
}

/** Visible, protected station configuration requests; no device/session implementation. */
export class ConsoleActivation {
  constructor(app) { this.app = app;this.view = null;this.confirmed = false;this.timer = null; }

  pending() {
    try { return JSON.parse(sessionStorage.getItem('culsma-console:activation') || 'null'); }
    catch { return null; }
  }

  remember(value) {
    if (value) sessionStorage.setItem('culsma-console:activation',JSON.stringify(value));
    else sessionStorage.removeItem('culsma-console:activation');
  }

  async refresh() {
    const pending = this.pending();
    this.view = await this.app.configurationFetch(pending ? '/api/v1/configuration/activation':'/api/v1/configuration/active',
      pending ? {action:'status',request_id:pending.request_id}:null);
    if (pending && this.view.receipt?.request_id === pending.request_id && ['applied','failed','interrupted'].includes(this.view.receipt.status)) {
      this.remember(null);
      this.app.interaction.result('configuration.apply',this.view.receipt.status,
        this.view.receipt.status === 'applied' ? 'Saved configuration applied. The station is ready.':'Configuration application did not complete. Inspect the station state before continuing.',
        {entity:this.view.receipt.draft_id,revision:this.view.receipt.revision,requestId:pending.request_id});
    }
    this.schedule();
    return this.view;
  }

  schedule() {
    clearTimeout(this.timer);
    if (!this.view || !['accepted','starting'].includes(this.view.receipt?.status)) return;
    this.timer = setTimeout(async () => {
      try {
        await this.refresh();
        if (location.hash === '#configuration') this.app.renderConfiguration();
      } catch (error) {
        this.app.interaction.result('configuration.apply','unavailable','Configuration status unavailable. The request ID is retained; no automatic apply retry.');
      }
    },700);
  }

  render() {
    const a = this.app;const card = a.card('Active station configuration');
    card.dataset.region = 'active-configuration';
    if (!this.view) { card.append(a.element('p','Station configuration status is unavailable.','notice'));return card; }
    const active = this.view.active;
    card.dataset.configurationFingerprint = active.fingerprint;
    card.dataset.hostState = this.view.host.status;
    card.append(a.badge(this.view.host.status),a.details([
      ['Selected configuration',active.origin ? `${active.origin.title} · r${active.origin.revision}`:'Service startup configuration'],
      ['Configuration identity',a.element('span',active.fingerprint,'mono')]
    ]));
    if (this.view.receipt) {
      const receipt = this.view.receipt;
      card.append(a.details([['Last apply request',receipt.request_id],['Application state',receipt.status],['Problem',receipt.error || 'None']]));
    }
    card.append(a.element('p','Application rebuilds the simulated execution session when the station is idle. Run history, tip accounting and unresolved resources are retained. It does not rearrange a physical deck or replenish supplies.','note'));
    return card;
  }

  controls() {
    const a = this.app;const wrapper = a.element('div','','config-actions');
    const pending = this.pending();
    const label = a.element('label','','config-field');
    const checkbox = a.element('input');checkbox.type = 'checkbox';checkbox.checked = this.confirmed;
    checkbox.setAttribute('aria-label','Confirm application of this saved configuration');
    a.interaction.identify(checkbox,{field:'/activation-confirmation'});
    checkbox.addEventListener('change',() => {this.confirmed = checkbox.checked;this.updateActions();});
    label.append(checkbox,a.element('span','Apply this saved revision to the idle simulated station'));
    wrapper.append(label,a.configButton(pending ? 'Retry same apply request':'Apply saved configuration',() => this.apply(),
      'apply-configuration',{action:'configuration.apply',entity:a.configDraft?.draft_id,revision:a.configDraft?.revision}));
    if (pending) wrapper.append(a.element('p','A previous apply response is unresolved. Retry retains its original request identity.','notice'));
    return wrapper;
  }

  updateActions() {
    const a = this.app;const button = document.querySelector('#apply-configuration');
    if (button) button.disabled = !!(a.configSaving || a.configDirty() || !a.configValidation?.valid || !this.confirmed
      || !this.view?.active?.fingerprint || !['ready','failed'].includes(this.view?.host.status));
  }

  async apply() {
    const a = this.app;
    if (a.configSaving || !a.configDraft || a.configDirty() || !a.configValidation?.valid || !this.confirmed) return;
    a.configSaving = true;a.syncBusy();a.updateConfigActions();
    let payload;
    try {
      payload = this.pending() || {action:'apply',draft_id:a.configDraft.draft_id,revision:a.configDraft.revision,
        expected_fingerprint:this.view.active.fingerprint,request_id:crypto.randomUUID()};
      this.remember(payload);
      a.interaction.result('configuration.apply','pending','Configuration application request pending.',{entity:payload.draft_id,revision:payload.revision,requestId:payload.request_id});
      const receipt = await a.configurationFetch('/api/v1/configuration/activation',payload);
      a.interaction.result('configuration.apply',receipt.status,'Apply request accepted. Wait for the station to report ready and applied.',
        {entity:payload.draft_id,revision:payload.revision,requestId:payload.request_id});
      await this.refresh();
      this.confirmed = false;a.showAlert(null);
    } catch (error) {
      if (Number.isInteger(error.httpStatus) && error.httpStatus < 500) this.remember(null);
      a.interaction.result('configuration.apply',a.interaction.responseOutcome(error),error.message,
        {entity:payload?.draft_id,revision:payload?.revision,requestId:payload?.request_id});
      a.showAlert(error.message);
    } finally {
      a.configSaving = false;a.syncBusy();
      if (location.hash === '#configuration') a.renderConfiguration();
    }
  }
}

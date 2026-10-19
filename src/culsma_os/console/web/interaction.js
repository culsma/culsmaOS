/** Presentation identity for the same native controls used by people and browser agents. */
export class ConsoleInteraction {
  constructor(content, status) {
    this.content = content;
    this.status = status;
  }

  pointer(parts) {
    return '/'+parts.map(part => String(part).replaceAll('~','~0').replaceAll('/','~1')).join('/');
  }

  identify(node, identity = {}) {
    for (const [key,value] of Object.entries(identity)) {
      const attribute = {action:'action',field:'field',entity:'entityId',collection:'collection',revision:'revision'}[key];
      if (attribute && value !== undefined && value !== null) node.dataset[attribute] = String(value);
    }
    if (identity.field) node.name = identity.field;
    return node;
  }

  view(page, values = {}) {
    if (this.content.dataset.page !== page) {
      for (const key of ['hostState','runId','runState','draftId','revision','dirty','validationState','programId','snapshotId']) delete this.content.dataset[key];
    }
    this.content.dataset.page = page;
    for (const [key,value] of Object.entries(values)) {
      if (value === null || value === undefined) delete this.content.dataset[key];
      else this.content.dataset[key] = String(value);
    }
  }

  busy(value) {
    this.content.setAttribute('aria-busy',String(Boolean(value)));
  }

  result(action, state, message, context = {}) {
    const key = JSON.stringify([action,state,message,context]);
    if (this.lastResult === key) return;
    this.lastResult = key;
    for (const key of ['entityId','revision','requestId']) delete this.status.dataset[key];
    this.status.dataset.action = action;
    this.status.dataset.outcome = state;
    if (context.entity) this.status.dataset.entityId = String(context.entity);
    if (context.revision) this.status.dataset.revision = String(context.revision);
    if (context.requestId) this.status.dataset.requestId = String(context.requestId);
    this.status.textContent = message;
    if (context.requestId) {
      const receipt = document.createElement('small');
      receipt.textContent = `Request: ${context.requestId}`;this.status.append(receipt);
    }
    this.status.hidden = false;
  }

  responseOutcome(error, readOnly = false) {
    if (Number.isInteger(error.httpStatus) && error.httpStatus < 500) return 'rejected';
    return readOnly ? 'unavailable':'response_unknown';
  }

  focus(action, entity = null) {
    const node = [...this.content.querySelectorAll('[data-action]')].find(item =>
      item.dataset.action === action && (!entity || item.dataset.entityId === entity));
    if (node && !node.disabled) node.focus({preventScroll:true});
  }

  diagnostics(values) {
    for (const input of this.content.querySelectorAll('[data-field]')) {
      const pointer = input.dataset.field.replace(/^\/configuration/,'');
      const invalid = values.some(item => item.path !== '/' && item.path === pointer);
      input.setAttribute('aria-invalid',String(invalid));
      if (invalid) input.setAttribute('aria-describedby','draft-validation');
      else input.removeAttribute('aria-describedby');
    }
  }
}

import {WorkstationLayoutView} from './workstation-layout.js';

/** Read-only presentation of existing OS resource observations. */
export class ConsoleWorkstation {
  constructor(app) {this.app=app;this.layout=new WorkstationLayoutView(app);}

  resourceTable(title, rows, columns) {
    const a=this.app,card=a.card(title);
    card.append(a.table(columns.map(item=>item[0]),(rows || []).map(row=>columns.map(item=>row[item[1]])),'No records in this snapshot.'));
    return card;
  }

  device(device) {
    const a=this.app,card=a.card(device.device_id);
    card.append(a.details([['Mode',device.mode],['Evidence accounting',a.badge(device.evidence_accounting)],
      ['Position basis',a.badge(device.positions?.status)]]));
    card.append(a.element('h3','Consumables'),a.table(['Resource','Known used','Available from records'],
      Object.entries(device.consumables || {}).map(([name,item])=>[name,item.known_consumed,item.available_from_records ?? 'Unknown'])));
    card.append(a.element('h3','Recorded plate locations'),a.table(['Labware','Recorded position'],Object.entries(device.positions?.current || {}),
      device.positions?.status==='unknown' ? 'Positions are unknown. Isolation is retained.':'No positions declared.'));
    card.append(a.element('h3','Unresolved operations'),a.table(['Run','Step','Operation','Status'],(device.unresolved_operations || []).map(row=>[
      a.runLink(row.run_id),row.step_id,row.operation_kind,row.status]),'No unresolved operations recorded.'));
    const reasons=device.positions?.unresolved_motion || [];
    if(reasons.length) card.append(a.element('p','Position uncertainty: '+reasons.join(', '),'notice'));
    return card;
  }

  render(data, section) {
    const a=this.app,host=data.host,inspection=data.devices || {},devices=inspection.devices || [],resources=inspection.resources || {};
    a.interaction.view('station',{loadState:'ready',hostState:host.status,section});
    if(section==='state') {
      const basis=a.card('Observation source');
      basis.append(a.element('p','Recorded OS state. Hardware presence and physical contents have not been detected.','note'),
        a.details([['Device records',inspection.registration],['Local resource accounting',resources.local_accounting],['Station resource accounting',resources.station_accounting]]));
      a.content.replaceChildren(basis,...devices.map(device=>this.device(device)),
        this.resourceTable('Station reservations',resources.station_reservations,[['Run','run_id'],['Owner','owner_id'],['State','status']]),
        this.resourceTable('Station locks',resources.station_locks,[['Resource','resource_id'],['Run','run_id']]),
        this.resourceTable('Local locks',resources.locks,[['Resource','resource_id'],['Attempt','attempt_id']]),
        this.resourceTable('Active permits',resources.permits,[['Attempt','attempt_id'],['Effect','effect_id'],['Status','status']]));
      const modules=a.card('Module state details');modules.append(a.badge('planned'),a.element('p','A shared module observation interface is not available yet. Device command parameters and receipts remain under each run.','note'));a.content.append(modules);
    } else {
      const grid=a.element('div','','grid'),service=a.card('Resident service'),queue=a.card('Active runs'),owned=a.card('Resource ownership');
      service.append(a.badge(host.blocked_run ? 'blocked':host.status));
      queue.append(a.element('div',data.runs.filter(row=>!a.navigation.constructor.terminal.has(row.status)).length,'metric'));
      owned.append(a.element('div',(resources.station_reservations || []).length,'metric'),a.element('p','Recorded station reservations','label'));
      grid.append(service,queue,owned);
      const layout=this.layout.render(data.layout);
      const current=a.card('Active runs and queue');current.append(a.runTable(data.runs.filter(row=>!a.navigation.constructor.terminal.has(row.status))));
      const equipment=a.card('Device summary');equipment.append(a.table(['Device','Mode','Position state','Unresolved operations'],devices.map(device=>[
        device.device_id,device.mode,device.positions?.status,(device.unresolved_operations || []).length])));
      a.content.replaceChildren(layout,grid,equipment,current);
    }
    a.showAlert(host.blocked_run ? `Run ${host.blocked_run} retains the queue: ${a.display(host.blocked_reason)}. Inspect its evidence before further action.`:host.worker_error);
  }
}

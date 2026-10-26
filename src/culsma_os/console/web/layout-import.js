import {RunSetupDeck} from './setup-deck.js';
import {LayoutInstancesView} from './layout-instances.js';

/** Configuration import review. Native decoding belongs to the installed profile. */
export class ConfigurationLayoutImport {
  constructor(app) {this.app = app;this.result = null;this.busy = false;}

  render(driver) {
    const a = this.app,node = a.element('section','','config-advanced');node.dataset.region = 'layout-import';
    node.append(a.element('h3','Import instrument layout'),a.element('p',
      'Choose the installed profile above, then select its native layout file. The driver converts it into configuration data for review; importing does not change the station.','note'));
    const upload = a.element('input');upload.type = 'file';
    upload.accept = [...new Set(a.configProfiles.flatMap(profile => profile.layout_import_extensions || []))].join(',');
    upload.disabled = this.busy;upload.setAttribute('aria-label','Import native instrument layout');
    a.interaction.identify(upload,{action:'configuration.import-layout',field:'/layout-source'});
    upload.addEventListener('change',async () => {
      if (this.busy) return;
      this.result = null;
      try {
        const file = upload.files[0];if (!file) return;
        const selected = driver(),profile = a.configProfiles.find(row => row.driver === selected);
        if (profile?.layout_import_supported !== true) throw new Error('Selected profile does not support native layout import.');
        if (file.size > 1024*1024) throw new Error('LAYOUT_IMPORT_TOO_LARGE');
        this.busy = true;upload.disabled = true;
        const bytes = new Uint8Array(await file.arrayBuffer());let raw = '';
        for (let i = 0; i < bytes.length; i += 32768) raw += String.fromCharCode(...bytes.subarray(i,i+32768));
        this.result = await a.configurationFetch('/api/v1/configuration/layout-import',
          {driver:selected,layout_source:{name:file.name,encoding:'base64',content:btoa(raw)}});
        a.interaction.result('configuration.import-layout',this.result.import_report.complete ? 'converted':'review_required',
          this.result.import_report.complete ? 'Layout converted. Review before creating a configuration.':'Conversion is incomplete. Review the retained objects and diagnostics.');
      } catch (error) {a.showAlert(error.message);}
      finally {this.busy = false;a.renderConfiguration();}
    });
    node.append(upload);
    if (this.result) node.append(this.review());
    return node;
  }

  updateActions() {
    const a = this.app,upload = a.content.querySelector('[data-action="configuration.import-layout"]');
    const use = a.content.querySelector('[data-action="configuration.use-imported-layout"]');
    if (upload) upload.disabled = !!a.configSaving || this.busy;
    if (use) use.disabled = !!a.configSaving || this.result?.import_report.complete !== true;
  }

  preview() {
    const a = this.app,report = this.result.import_report;
    if (report.candidate_configuration.layout?.schema === 'culsma_layout_instances_v1') {
      const region = LayoutInstancesView.render(a,report.candidate_configuration.layout,this.selected,id => {this.selected=id;});
      region.dataset.region='import-layout-preview';return region;
    }
    const profile = a.configProfiles.find(row => row.driver === this.result.driver);
    const scene = RunSetupDeck.scene({layout:{definition:profile?.layout,configuration:report.candidate_configuration}});
    const region = a.element('section','','loading-layout');region.dataset.region = 'import-layout-preview';
    region.setAttribute('aria-label','Converted layout preview');
    region.append(a.element('h3','Converted layout preview'));
    if (!scene) {region.append(a.element('p','No graphical preview is available for this configuration profile.','note'));return region;}
    const items = scene.carriers.flatMap(carrier => carrier.placements);
    const selected = items.find(row => row.id === this.selected) || items[0];
    this.selected = selected?.id;
    region.append(a.element('p',`${scene.carriers.length} converted carriers · ${items.length} converted labware · ${report.objects.length} source objects retained for review`,'note'));
    if (!report.complete) region.append(a.element('p','Partial configuration preview. This is not the complete source layout; native placement differences remain unresolved.','notice'));
    const inspect = id => {
      const previous = region.querySelector('.setup-deck-scroll')?.scrollLeft || 0;
      this.selected = id;const next = this.preview();region.replaceWith(next);
      const viewport = next.querySelector('.setup-deck-scroll');viewport.scrollLeft = previous;
      const button = [...next.querySelectorAll('[data-labware-id]')].find(row => row.dataset.labwareId === id);
      if (button) {
        const view = viewport.getBoundingClientRect(),target = button.getBoundingClientRect();
        if (target.left < view.left) viewport.scrollLeft += target.left-view.left-8;
        else if (target.right > view.right) viewport.scrollLeft += target.right-view.right+8;
      }
    };
    region.append(RunSetupDeck.render(a,scene,items,selected?.id,inspect,{
      label:'Converted configuration deck preview',action:'configuration.inspect-imported-labware',
      description:'Positions and carrier widths come from the converted configuration. Blue sites have converted objects; vertical spacing is schematic.',
      unplacedLabel:'No converted object',inactiveScope:'not represented in this candidate',
      footer:'Blank areas may contain unconverted source objects. This preview does not certify source coordinates or physical loading.'}));
    if (selected) {
      region.append(a.configField('Preview object',selected.id,inspect,items.map(row => row.id),{field:'/layout-import/preview-object'}));
      const source = report.objects.find(row => row.id === selected.id);
      const carrier = scene.carriers.find(row => row.placements.some(item => item.id === selected.id));
      const panel = a.element('section','','loading-inspector');panel.dataset.region = 'import-layout-selection';panel.dataset.objectId = selected.id;
      panel.append(a.element('h4',selected.id),a.table(['Setting','Value'],[
        ['Model',selected.model],['Candidate carrier',carrier.id],['Candidate tracks',`${carrier.first}–${carrier.last}`],
        ['Candidate site',selected.site],['Source origin (mm)',source?.origin_mm.join(', ') || 'Not recorded'],
        ['Source angle',source?.angle_deg ?? 'Not recorded']]));
      const diagnostics = report.diagnostics.filter(row => row.object_id === selected.id);
      if (diagnostics.length) panel.append(a.element('p','Source placement needs review; the candidate is not a verified reproduction.','notice'),
        a.table(['Code','Reason'],diagnostics.map(row => [row.code,row.message])));
      region.append(panel);
    }
    return region;
  }

  review() {
    const a = this.app,report = this.result.import_report,node = a.element('section','','config-advanced');
    node.dataset.region = 'layout-import-review';node.dataset.complete = String(report.complete);
    node.append(a.badge(report.complete ? 'converted':'incomplete'),a.element('p',report.source.name+' · '+this.result.driver),
      a.element('p','Source SHA-256: '+report.source.sha256,'mono'),a.element('p',report.scope,'note'));
    if (!report.complete) node.append(a.element('p',
      'This file cannot yet become an accepted configuration. Unsupported objects and native differences are retained in this review.','notice'));
    node.append(this.preview());
    const counts = new Map();
    for (const row of report.diagnostics) counts.set(row.code,(counts.get(row.code) || 0)+1);
    node.append(a.table(['Diagnostic','Count'],[...counts],'All native fields are represented by the regenerated configuration.'));
    if (report.diagnostics.length) {
      const diagnostics = a.element('details','','config-advanced');diagnostics.append(a.element('summary',`${report.diagnostics.length} conversion diagnostics`));
      diagnostics.append(a.table(['Object','Code','Reason'],report.diagnostics.map(row => [row.object_id || 'Layout',row.code,row.message])));node.append(diagnostics);
    }
    const objects = a.element('details','','config-advanced');objects.dataset.region = 'layout-import-objects';objects.append(a.element('summary',`${report.objects.length} layout objects`));
    objects.append(a.table(['Object','Model','Parent / site','Origin (mm)','Angle','Represented'],report.objects.map(row => [
      row.id,row.model,`${row.parent} / ${row.site}`,row.origin_mm.join(', '),row.angle_deg,row.mapped ? 'yes':'no'])));node.append(objects);
    const proposal = a.element('details','','config-advanced');proposal.append(a.element('summary','Converted configuration candidate'));
    proposal.append(a.element('pre',JSON.stringify(report.candidate_configuration,null,2),'record-json'));node.append(proposal);
    const use = a.configButton('Use converted layout as configuration',() => {
      if (!report.complete) return;
      if (a.configWorking && a.configDirty()) {a.showAlert('Save or discard current edits before using another configuration.');return;}
      a.startConfigDraft(this.result.driver,report.configuration,report.source.name);
    },'',{action:'configuration.use-imported-layout',entity:report.source.sha256});
    use.disabled = !report.complete;node.append(use);
    return node;
  }
}

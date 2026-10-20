"""Presentation behavior over immutable configuration records; Node is test-only."""
import shutil
import subprocess

import pytest

from tests.support.paths import ROOT


class ConfigurationNavigationHarness:
    def run(self, script):
        node = shutil.which('node')
        if not node:
            pytest.skip('Node is an optional presentation test dependency')
        imports = "import assert from 'node:assert/strict';\nimport {ConsoleConfiguration,ConsoleSystemInformation} from './src/culsma_os/console/web/configuration.js';\n"
        result = subprocess.run([node, '--input-type=module', '-e', imports + script],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


def test_navigation_uses_plugin_metadata_without_vendor_names():
    ConfigurationNavigationHarness().run("""
const controller = new ConsoleConfiguration({});
const profile = {fields:[{path:['custom_parameter'],section:'transfer',options:['custom']}],
 maps:[{path:['custom_layout'],section:'layout',columns:['place']}],
 summaries:[{path:['module_data'],section:'instruments',columns:['kind']} ]};
const before = structuredClone(profile);
assert.equal(controller.section(profile,'transfer').fields[0].path[0], 'custom_parameter');
assert.equal(controller.section(profile,'layout').maps[0].path[0], 'custom_layout');
assert.equal(controller.section(profile,'instruments').summaries[0].path[0], 'module_data');
assert.deepEqual(controller.section({},'layout'), {fields:[],maps:[],summaries:[]});
assert.deepEqual(profile,before);
""")


def test_current_configuration_requires_exact_origin():
    ConfigurationNavigationHarness().run("""
const record={draft_id:'station',revision:2,fingerprint:'saved',driver:'external',configuration:{value:2}};
const active={fingerprint:'host',origin:{draft_id:'station',revision:2,configuration_fingerprint:'saved'}};
const calls=[];let starts=0;
const app={activation:{view:{active}},configWorking:null,
 configurationFetch:async (path,payload)=>{calls.push(payload);return {draft:record};},
 startConfigDraft:()=>{starts++;}};
const controller=new ConsoleConfiguration(app);
await controller.readCurrent(false);assert.equal(starts,0);
await controller.readCurrent();
assert.deepEqual(calls.at(-1),{action:'get',draft_id:'station',revision:2});
assert.equal(starts,1);
for (const change of [{revision:3},{draft_id:'another'},{fingerprint:'changed'}]) {
 assert.equal(controller.matchesOrigin({...record,...change},active),false);
}
app.configWorking={value:'unsaved'};
await controller.readCurrent();assert.equal(starts,1);assert.equal(app.configWorking.value,'unsaved');
app.configurationFetch=async()=>({draft:{...record,revision:3}});
await assert.rejects(()=>controller.readCurrent(),/IDENTITY_MISMATCH/);
assert.equal(controller.activeRecord,null);
app.activation.view.active={fingerprint:'startup',origin:null};
const count=calls.length;await controller.readCurrent();assert.equal(calls.length,count);
""")


def test_configuration_navigation_preserves_typed_edits():
    ConfigurationNavigationHarness().run("""
const app={configWorking:{policy:{rate:10},layout:{well:'A3'}},
 interaction:{pointer:parts=>'/'+parts.join('/')},renderConfiguration:()=>{},
 configPath:(value,path)=>path.reduce((target,key)=>target?.[key],value),
 setConfigPath:(path,value)=>{app.configWorking[path[0]][path[1]]=value;}};
const controller=new ConsoleConfiguration(app);
const rate={path:['policy','rate'],type:'number',optional:true};
assert.equal(controller.editValue(rate,'12.5'),true);assert.equal(app.configWorking.policy.rate,12.5);
controller.section({},'layout');
assert.equal(app.configWorking.policy.rate,12.5);assert.equal(app.configWorking.layout.well,'A3');
assert.equal(controller.editValue(rate,'Infinity'),false);
assert.equal(controller.invalidFields.size,1);assert.equal(app.configWorking.policy.rate,12.5);
assert.equal(controller.editValue(rate,'',true),false);assert.equal(app.configWorking.policy.rate,12.5);
assert.equal(controller.editValue(rate,''),true);assert.equal(Object.hasOwn(app.configWorking.policy,'rate'),false);
assert.equal(controller.invalidFields.size,0);
controller.editJSON('{"layout":{"well":"A4"}}');
controller.section({},'layout');
assert.equal(controller.jsonEdited,true);
assert.equal(controller.jsonText,'{"layout":{"well":"A4"}}');
assert.equal(app.configWorking.layout.well,'A3');
assert.throws(()=>controller.proposeJSON('[]'),/CONFIGURATION_JSON_INVALID/);
assert.equal(app.configWorking.layout.well,'A3');
controller.proposeJSON(controller.jsonText);
assert.equal(app.configWorking.layout.well,'A4');assert.equal(controller.jsonEdited,false);
""")


def test_configuration_change_summary_preserves_values():
    ConfigurationNavigationHarness().run("""
const controller=new ConsoleConfiguration({});
const before={bindings:{target:{well:'A2'}},rate:null,count:0,enabled:false,list:[1,2],removed:'value'};
const after={bindings:{target:{well:'A3'}},rate:3,count:0,enabled:false,list:[2,1]};
const copy=structuredClone(before);
const changes=controller.changes(before,after);
assert.deepEqual(changes.map(item=>item.path),[['bindings','target','well'],['list'],['rate'],['removed']]);
assert.equal(changes[0].before,'A2');assert.equal(changes[0].after,'A3');
assert.equal(changes.at(-1).after,undefined);assert.deepEqual(before,copy);
assert.deepEqual(controller.changes(before,before),[]);
""")


def test_system_information_uses_active_record_not_proposal():
    ConfigurationNavigationHarness().run("""
const record={draft_id:'station',revision:2,fingerprint:'saved',driver:'device-plugin',
 configuration:{machine:'configured-model',mount:'right',modules:{heater:{kind:'thermal'}}}};
const active={fingerprint:'host',origin:{draft_id:'station',revision:2,configuration_fingerprint:'saved'}};
const profile={driver:'device-plugin',label:'Installed plugin',fields:[
 {path:['machine'],label:'Model',section:'platform',options:['supported-a','supported-b']},
 {path:['mount'],label:'Mount',section:'instruments'},
 {path:['flow'],label:'Flow rate',section:'transfer',options:['default']}],
 summaries:[{path:['modules'],section:'instruments',label:'Modules',columns:['kind']}]};
const app={activation:{view:{active}},configProfiles:[profile],
 configWorking:{machine:'unsaved-model',mount:'left'},
 configPath:(value,path)=>path.reduce((target,key)=>target?.[key],value),
 display:value=>value ?? 'Not recorded'};
app.configuration=new ConsoleConfiguration(app);app.configuration.activeRecord=record;
const view=new ConsoleSystemInformation(app);
const model=view.model();
assert.deepEqual(model.configured,[['Model','configured-model'],['Mount','right']]);
assert.deepEqual(model.modules[0].rows,[['heater','thermal']]);
assert.deepEqual(model.definitions[0].rows,[['Model','supported-a, supported-b']]);
assert.equal(app.configWorking.machine,'unsaved-model');
app.configuration.activeRecord={...record,revision:3};
assert.deepEqual(view.model().configured,[]);
assert.equal(view.model().record,null);
""")

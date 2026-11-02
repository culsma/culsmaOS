"""Real stdio Profile management; no resident or instrument is started."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import Client, StdioServerParameters


async def execute(root, configuration_path):
    root = Path(root)
    configuration = json.loads(Path(configuration_path).read_text())
    server = StdioServerParameters(command=sys.executable, args=['-m', 'culsma_os.cli', 'mcp',
        '--socket', str(root/'absent.sock'), '--home', str(root/'Home'),
        '--program-store', str(root/'snapshots'), '--drafts-db', str(root/'drafts.sqlite3')], env=dict(os.environ))
    async with Client(server, read_timeout_seconds=15) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        names = {'instrument_profile_catalogue', 'list_instrument_profiles', 'read_instrument_profile',
                 'validate_instrument_profile', 'save_instrument_profile'}
        assert names <= tools.keys()
        assert tools['save_instrument_profile'].annotations.read_only_hint is False
        assert tools['instrument_profile_catalogue'].annotations.read_only_hint is True
        async def call(name, arguments):
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            return result.structured_content
        draft = (await call('create_configuration', dict(title='Profile SDK test', driver='hamilton-local',
            configuration=configuration)))['draft']
        context = dict(draft_id=draft['draft_id'], configuration_revision=1, device_id=configuration['device_id'])
        catalogue = await call('instrument_profile_catalogue', context)
        assert {m['kind'] for m in catalogue['modules']} == {'magnet', 'pipetting'}
        parameters = {'aspiration_height_mm': 4.0, 'dispense_height_mm': 5.0}
        applicability = {'operation': 'magnetic_flowthrough_transfer',
            'source_models': ['Ham_DW_Rgt_96_L'], 'destination_models': ['RGT_CONT_60ML_BC_A00'],
            'tip_models': ['HTF_L'], 'per_aspiration_volume_uL': {'minimum': 10, 'maximum': 300},
            'required_source_conditions': ['magnetically_held']}
        values = dict(**context, module_id=configuration['execution']['channel']['id'],
            profile_id='sdk-supernatant', method_id='positioned_pipetting', definition_revision='1',
            display_name='SDK profile', parameters=parameters, applicability=applicability)
        assert (await call('validate_instrument_profile', values))['valid']
        first = (await call('save_instrument_profile', values))['profile']
        second = (await call('save_instrument_profile', {**values, 'expected_revision': first['reference']['revision'],
            'parameters': {**parameters, 'aspiration_height_mm': 6.0}}))['profile']
        result = await client.call_tool('save_instrument_profile', values)
        assert result.is_error and 'PROFILE_REVISION_CONFLICT' in str(result.content)
        scope = dict(device_id=context['device_id'], module_id=values['module_id'])
        assert len((await call('list_instrument_profiles', scope))['profiles']) == 2
        read = await call('read_instrument_profile', {**scope, 'profile_id': values['profile_id'],
            'profile_revision': first['reference']['revision']})
        assert read['profile'] == first and read['activation'] == 'not_applied'
        assert (await call('read_configuration', {'draft_id': draft['draft_id']}))['draft'] == draft
        assert second['parameters']['aspiration_height_mm'] == 6
        assert first['applicability'] == second['applicability'] == applicability
        assert 'liquid_class' not in first['parameters']
        print(json.dumps({'profile_tools': len(names), 'saved_revisions': 2, 'hardware_operations': 0}))


if __name__ == '__main__': asyncio.run(execute(*sys.argv[1:]))

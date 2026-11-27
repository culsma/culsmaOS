"""Isolated local resident and HTTP console; Hamilton execution is a labelled double."""
from tests.support.paths import HAMILTON_TRANSFER
import pytest
import json
import os
from contextlib import ExitStack
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.console.models import ConsoleSettings
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.models import HostBuildContext
from tests.support.integration.resident_host import ResidentHarness
from tests.support.integration.hamilton import HamiltonOperationTestBackend
from tests.support.console.http import ConsoleHTTPHarness


class SharedSetupHarness(ResidentHarness):
    def __init__(self,directory,submit=True,programs=False):
        super().__init__(directory)
        pytest.importorskip('culsma_driver_hamilton', reason='Optional Hamilton driver is not installed')
        data=json.loads((HAMILTON_TRANSFER/'setup.json').read_text())
        self.resources = ExitStack()
        self.source=directory/'transfer.culs'
        self.source.write_text((HAMILTON_TRANSFER/'transfer.culs').read_text())
        config=directory/'device.json'
        config.write_text(json.dumps({'schema':'culsma_hamilton_device_v1','device_id':'shared-console-test','mode':'simulation',
            'layout':data['layout'],'execution':data['execution'],'bindings':{},'well_positions':{},'agent':{}}))
        self.context=HostBuildContext(directory/'os.sqlite3','hamilton-agent',config,directory/'artifacts',station_root=directory/'stations')
        self.settings=ResidentHostSettings(self.context,self.endpoint,0.01)
        self.backend=HamiltonOperationTestBackend()
        self.http=None
        self.directory=directory
        self.submit_on_start=submit
        self.program_root=directory/'programs' if programs else None
        if self.program_root is not None:
            self.program_root.mkdir()
            (self.program_root/self.source.name).write_text(self.source.read_text())

    def serve(self):
        try:
            from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
            self.host=OSApplicationFactory({'hamilton-agent':HamiltonOSDeviceFactory(backend_factory=self.backend)}).build_resident_host(self.settings)
            self.host.serve()
        except BaseException as error:
            self.errors.append(error)

    def __enter__(self):
        try:
            self.start()
            self.resources.callback(self.stop)
            server=ConsoleApplicationFactory().build(ConsoleSettings(self.endpoint,0,self.directory/'drafts.sqlite3',
                self.program_root,self.directory/'program-store'))
            self.http=self.resources.enter_context(ConsoleHTTPHarness(server))
            self.url=server.url
            self.headers={'Origin':self.url,'Authorization':'Bearer '+server.sessions.execute()['access_token'],'Content-Type':'application/json'}
            if not self.submit_on_start:
                return self
            receipt=self.client.execute({'action':'submit','source':str(self.source)})
            self.run_id=receipt['run_id']
            self.wait(lambda:self.status(self.run_id)['status']=='awaiting_setup')
            return self
        except BaseException:
            self.resources.close()
            raise

    def __exit__(self,*args):
        return self.resources.__exit__(*args)

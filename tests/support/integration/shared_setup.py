"""Isolated local resident and HTTP console; Hamilton execution is a labelled double."""
from pathlib import Path
import json
from culsma_os.bootstrap import OSApplicationFactory
from culsma_os.console.providers import ConsoleApplicationFactory
from culsma_os.console.models import ConsoleSettings
from culsma_os.lifecycle_manager.models import ResidentHostSettings
from culsma_os.program_manager.models import HostBuildContext
from tests.support.integration.resident_host import ResidentHarness
from tests.support.integration.hamilton import HamiltonOperationTestBackend
from tests.support.console.http import ConsoleHTTPHarness


class SharedSetupHarness(ResidentHarness):
    def __init__(self,directory):
        super().__init__(directory)
        import culsma_driver_hamilton
        driver=Path(culsma_driver_hamilton.__file__).resolve().parents[2]
        data=json.loads((driver/'examples/os-transfer-input/setup.json').read_text())
        self.source=directory/'transfer.culs'
        self.source.write_text((driver/'examples/os-transfer-input/transfer.culs').read_text())
        config=directory/'device.json'
        config.write_text(json.dumps({'schema':'culsma_hamilton_device_v1','device_id':'shared-console-test','mode':'simulation',
            'layout':data['layout'],'execution':data['execution'],'bindings':{},'well_positions':{},'agent':{}}))
        self.context=HostBuildContext(directory/'os.sqlite3','hamilton-agent',config,directory/'artifacts',station_root=directory/'stations')
        self.settings=ResidentHostSettings(self.context,self.endpoint,0.01)
        self.backend=HamiltonOperationTestBackend()
        self.http=None
        self.directory=directory

    def serve(self):
        try:
            from culsma_hamilton_os.providers import HamiltonOSDeviceFactory
            self.host=OSApplicationFactory({'hamilton-agent':HamiltonOSDeviceFactory(backend_factory=self.backend)}).build_resident_host(self.settings)
            self.host.serve()
        except BaseException as error:
            self.errors.append(error)

    def __enter__(self):
        self.start()
        try:
            server=ConsoleApplicationFactory().build(ConsoleSettings(self.endpoint,0,self.directory/'drafts.sqlite3',
                None,self.directory/'program-store'))
        except BaseException:
            self.stop()
            raise
        self.http=ConsoleHTTPHarness(server).__enter__()
        self.url=server.url
        self.headers={'Origin':self.url,'Authorization':'Bearer '+server.sessions.execute()['access_token'],'Content-Type':'application/json'}
        receipt=self.client.execute({'action':'submit','source':str(self.source)})
        self.run_id=receipt['run_id']
        self.wait(lambda:self.status(self.run_id)['status']=='awaiting_setup')
        return self

    def __exit__(self,*args):
        try:
            if self.http is not None: self.http.__exit__(*args)
        finally:
            self.stop()

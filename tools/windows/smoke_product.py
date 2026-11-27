"""Run with the packaged Python in isolation; never dispatch a hardware method."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


class WindowsProductSmoke:
    def run(self, product):
        sources = json.loads((product/'Product.json').read_text(encoding='utf-8'))['sources']
        assert len(sources['culsma']) == 40
        expected = {'culsma-os':'0.2.3','culsma':sources['culsma_version'],'culsma-driver-hamilton':'0.1.2',
                    'mcp':'2.3.0'}
        for name, version in expected.items():
            assert importlib.metadata.version(name) == version, name
        assert importlib.util.find_spec('culsma_hamilton_agent') is None
        assert Path(sys.executable).is_relative_to(product/'runtime')
        from culsma_os.console.adapters.mcp import MCPServerAdapter
        assert callable(MCPServerAdapter.set_physical_execution)
        assert callable(MCPServerAdapter.set_native_debug)
        from culsma.runtime.material.contents_state import MaterialIndexedPartsStateManager
        assert callable(MaterialIndexedPartsStateManager.apply_magnetic_group)
        from mcp.server.mcpserver import MCPServer
        assert callable(MCPServer.streamable_http_app)
        specification = importlib.util.spec_from_file_location('windows_product', product/'launch.py')
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='culsma-product-smoke-') as temporary:
            base = Path(temporary)
            app = module.WindowsProduct(product, state=base/'state', home=base/'home')
            station = app.initialize()
            assert station['driver'] == 'hamilton-local'
            from culsma_os.file_system.repository import LocalFileWorkspaceRepository
            files = LocalFileWorkspaceRepository(app.home/'projects')
            initial = files.write_document('smoke.culs', '// \u4e2d\u6587\r\n'.encode(), None)
            assert files.read_document('smoke.culs')['content'] == '// \u4e2d\u6587\r\n'
            files.write_document('smoke.culs', b'// changed\n', initial['revision'])
            from culsma_os.bootstrap import OSApplicationFactory
            from culsma_os.program_manager.models import HostBuildContext
            from culsma_os.lifecycle_manager.models import ResidentHostSettings
            from culsma_os.program_manager.adapters.resident import ResidentClientAdapter
            context = HostBuildContext(app.state/'os.sqlite3','hamilton-local',app.state/'deck.json',app.state/'runs')
            host = None
            errors = []
            def serve():
                nonlocal host
                try:
                    host = OSApplicationFactory().build_resident_host(ResidentHostSettings(context, app.socket))
                    host.serve()
                except BaseException as error: errors.append(str(error))
            thread = threading.Thread(target=serve)
            thread.start()
            client = ResidentClientAdapter(app.socket, 2)
            try:
                for _ in range(100):
                    if errors: raise RuntimeError(errors)
                    try:
                        state = client.execute({'action':'host-status'})
                        if state['status'] == 'failed': raise RuntimeError(state)
                        if state['status'] == 'ready': break
                    except OSError: pass
                    time.sleep(0.1)
                else: raise AssertionError('Packaged resident did not become ready')
                assert client.execute({'action':'runs'})['runs'] == []
                client.execute({'action':'shutdown'})
            finally:
                if host is not None: host.request_stop()
                thread.join(15)
            assert not thread.is_alive() and not errors, errors
            resident_result = 'Hamilton local simulation ready and controlled shutdown'
            self.venus_probe(base)
        print(json.dumps({'state':'passed','packages':expected,'resident':resident_result,
                          'files':'UTF-8 CRLF edit preserved','venus':'direct driver loaded and station permission checked',
                          'hardware_dispatched':False,'native_ui_tested':False}))

    def venus_probe(self, base):
        from culsma_hamilton_os.providers import HamiltonVenusBackendFactory
        settings = {
            'mode': 'simulation',
            'venus': {'port': 1, 'trace_directory': str(base / 'traces')},
        }
        backend = HamiltonVenusBackendFactory().build(settings, base / 'venus')
        backend.check_ready()
        assert backend.physical_permission()['enabled'] is False
        assert backend.physical_permission(True)['enabled'] is True
        assert backend.physical_permission(False)['enabled'] is False


if __name__ == '__main__':
    WindowsProductSmoke().run(Path(sys.argv[1]).resolve())

import ast
from tests.support.paths import ROOT


def test_native_migration_has_no_vendor_or_worker_implementation_in_views():
    root=ROOT/'frontend/console/lib/features/console'
    for file in root.rglob('*.dart'):
        source=file.read_text()
        assert not any(name in source for name in ['HamiltonDevice','OpentronsDevice','RunSchedulerInteractor','SqliteTaskRepository','Process.start(','Process.run('])
    controls=(root/'interactor/run_control_interactor.dart').read_text()
    assert "'control-status'" in controls and "repository!.save('control:$id', payload)" in controls
    assert controls.index("repository!.save('control:$id', payload)")<controls.index('await send(id)')
    info=(root/'interactor/system_information_interactor.dart').read_text()
    assert 'proposal' not in info.split('class NativeSystemInformationInteractor',1)[1]
    assert "'/api/v1/configuration/active'" in info and 'matches(current, origin)' in info
    tree=(root/'interactor/protocol_tree_interactor.dart').read_text()
    assert 'dart:io' not in tree and 'ConsoleApi' not in tree
    mcp=ast.parse((ROOT/'src/culsma_os/console/adapters/mcp.py').read_text())
    owner=next(n for n in ast.walk(mcp) if isinstance(n,ast.FunctionDef) and n.name=='control_request_status')
    assert len(owner.body)==1 and isinstance(owner.body[0],ast.Return)

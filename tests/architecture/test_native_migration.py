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
    browser=(root/'interactor/file_browser_interactor.dart').read_text()
    assert 'dart:io' not in browser and 'action: \'start\'' not in browser
    assert "'/api/v1/files'" in browser
    mcp=ast.parse((ROOT/'src/culsma_os/console/adapters/mcp.py').read_text())
    owner=next(n for n in ast.walk(mcp) if isinstance(n,ast.FunctionDef) and n.name=='control_request_status')
    assert len(owner.body)==1 and isinstance(owner.body[0],ast.Return)


def test_run_outcome_reads_backend_guidance_instead_of_classifying_vendor_error_strings():
    source=(ROOT/'frontend/console/lib/features/console/view/run_outcome_view.dart').read_text()
    assert "run['user_guidance']" in source
    assert 'BATCH_PREPARATION_REJECTED' not in source and 'No available tip positions' not in source
    owner=ROOT/'src/culsma_os/program_manager/interactors/guidance.py'
    tree=ast.parse(owner.read_text())
    imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
    assert not any('adapters' in n or 'repositories' in n for n in imports)

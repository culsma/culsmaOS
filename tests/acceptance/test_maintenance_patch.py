"""Explicit backend overlays preserve the installed UI and reject unrelated paths."""
import hashlib
import json
import zipfile
from pathlib import Path
import pytest
from tools.windows import prepare_maintenance_patch as patch


def test_explicit_driver_overlay_manifest_matches_packaged_bytes(tmp_path, monkeypatch):
    os_root = tmp_path/'os'; driver = tmp_path/'driver'
    (os_root/'tools/windows').mkdir(parents=True)
    (os_root/'tools/windows/install.ps1').write_text('# installer')
    source = 'src/culsma_driver_hamilton/interactors/balance.py'
    path = driver/source; path.parent.mkdir(parents=True); path.write_bytes(b'balanced = True\n')
    monkeypatch.setattr(patch, 'working_source_changes', lambda *args: set())
    monkeypatch.setattr(patch, 'resolve_revision', lambda repo, revision: 'a' * 40)
    monkeypatch.setattr(patch, 'committed_files', lambda *args: {'baseline.py': b'baseline'})
    output = tmp_path/'output'
    manifest = patch.prepare(output, os_root, driver, (source,))
    with zipfile.ZipFile(output/'Backend.zip') as archive:
        for name, digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert json.loads(archive.read('maintenance-patch.json')) == manifest
    assert manifest['native_ui'] == 'retained_installed'
    assert manifest['driver_source_overrides'] == [source]


@pytest.mark.parametrize('name', ['../secrets.py', '/etc/passwd', 'src/other.py', 'src/culsma_driver_hamilton/../../secret.py'])
def test_driver_overlay_rejects_paths_outside_driver_source(tmp_path, monkeypatch, name):
    monkeypatch.setattr(patch, 'working_source_changes', lambda *args: set())
    monkeypatch.setattr(patch, 'resolve_revision', lambda repo, revision: 'a' * 40)
    monkeypatch.setattr(patch, 'committed_files', lambda *args: {})
    with pytest.raises(ValueError, match='Explicit driver'):
        patch.prepare(tmp_path/'output', tmp_path, tmp_path, (name,))


def test_full_committed_tree_includes_unchanged_files_and_freezes_revision(tmp_path):
    import subprocess
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-q')
    (tmp_path/'src/pkg').mkdir(parents=True)
    (tmp_path/'src/pkg/old.py').write_text('old = True\n')
    git('add', '.')
    git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','first')
    (tmp_path/'src/pkg/new.py').write_text('new = True\n')
    git('add', '.')
    git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','second')
    revision = patch.resolve_revision(tmp_path, 'HEAD')
    assert len(revision) == 40
    assert set(patch.committed_files(tmp_path, revision, 'src/')) == {'pkg/old.py','pkg/new.py'}
    (tmp_path/'src/pkg/old.py').write_text('modified = True')
    (tmp_path/'src/pkg/untracked.py').write_text('new')
    assert patch.working_source_changes(tmp_path, revision, ('src/',)) == {'src/pkg/old.py','src/pkg/untracked.py'}
    with pytest.raises(ValueError, match='Unselected working source'):
        patch.require_source_selection(tmp_path, revision, ('src/',), ['src/pkg/old.py'])
    patch.require_source_selection(tmp_path, revision, ('src/',), ['src/pkg/old.py','src/pkg/untracked.py'])


def test_os_and_venus_overlays_include_exact_working_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(patch, 'working_source_changes', lambda *args: set())
    monkeypatch.setattr(patch, 'resolve_revision', lambda root, revision: revision + '-resolved')
    monkeypatch.setattr(patch, 'committed_files', lambda *args: {})
    (tmp_path/'tools/windows').mkdir(parents=True)
    (tmp_path/'tools/windows/install.ps1').write_text('# installer')
    names = ['src/culsma_os/setup.py','src/culsma_driver_hamilton/venus/progress.py']
    for name in names:
        path = tmp_path/name; path.parent.mkdir(parents=True); path.write_bytes(name.encode())
    result = patch.prepare(tmp_path/'bundle',tmp_path,tmp_path,[names[1]],os_sources=[names[0]],
                           os_revision='release',driver_revision='driver-release')
    assert result['os_backend'] == 'release-resolved'
    assert result['hamilton_backend'] == 'driver-release-resolved'
    assert result['os_source_overrides'] == [names[0]]
    with zipfile.ZipFile(tmp_path/'bundle/Backend.zip') as archive:
        assert archive.read('culsma_os/setup.py') == names[0].encode()
        assert archive.read('culsma_driver_hamilton/venus/progress.py') == names[1].encode()
    assert patch.source_overlays(tmp_path,[names[0]],('src/culsma_os/',)) == {'culsma_os/setup.py':names[0].encode()}


def test_overlay_rejects_symlink_escape(tmp_path):
    root=tmp_path/'repo'; (root/'src/culsma_os').mkdir(parents=True)
    outside=tmp_path/'outside.py'; outside.write_text('outside')
    (root/'src/culsma_os/escaped.py').symlink_to(outside)
    with pytest.raises(ValueError,match='inside its repository'):
        patch.source_overlays(root,['src/culsma_os/escaped.py'],('src/culsma_os/',))

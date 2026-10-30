"""Installed-product setup uses real temporary files, preserving user data."""
import importlib.util
import json
from pathlib import Path
import pytest
from tests.support.paths import ROOT

spec=importlib.util.spec_from_file_location('mac_preview_launch', ROOT/'tools/desktop/launch.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
MacPreviewProduct=module.MacPreviewProduct


def product(tmp_path):
    resources=tmp_path/'Applications/CulsmaOS Preview.app/Contents/Resources'
    defaults=resources/'defaults';defaults.mkdir(parents=True)
    (defaults/'deck.json').write_text('{"mode":"simulation"}')
    (defaults/'transfer.culs').write_text('let sample=tube(capacity=200uL);return sample;')
    home=tmp_path/'User';home.mkdir()
    return MacPreviewProduct(resources,home,tmp_path)


def test_initialize_seeds_once_and_preserves_existing_protocols_and_config(tmp_path):
    p=product(tmp_path);p.initialize()
    source=p.programs/'Transfer/transfer.culs';deck=p.state/'deck.json'
    assert source.read_text().startswith('let sample=')
    source.write_text('edited protocol');deck.write_text('edited config')
    p.initialize()
    assert source.read_text()=='edited protocol' and deck.read_text()=='edited config'
    assert not (p.workspace/'src').exists() and not (p.workspace/'tools').exists()


def test_mcp_and_desktop_share_paths_and_configuration_database(tmp_path):
    p=product(tmp_path);p.initialize();p.write_connection_settings()
    gui=p.command('desktop');mcp=p.command('mcp')
    for flag,value in [('--home',p.workspace),('--program-root',p.programs)]:
        assert gui[gui.index(flag)+1]==mcp[mcp.index(flag)+1]==str(value)
    assert gui[gui.index('--resident-socket')+1]==mcp[mcp.index('--socket')+1]==str(p.socket)
    assert mcp[mcp.index('--drafts-db')+1]==str(p.drafts)
    assert mcp[mcp.index('--program-store')+1]==str(p.snapshots)
    config=json.loads((p.state/'mcp-config.json').read_text())
    assert config==p.connection_settings()
    assert config['mcpServers']['culsmaOS']['command']==str(p.mcp)
    assert not any(word in json.dumps(config) for word in ['token','Bearer','access_token'])
    assert (p.state/'mcp-config.json').stat().st_mode & 0o777 == 0o600


def test_bootstrap_rejects_linked_workspace_and_seed_files(tmp_path):
    p=product(tmp_path);outside=tmp_path/'outside';outside.mkdir()
    p.workspace.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='PREVIEW_DIRECTORY_IS_LINK'):p.initialize()
    p.workspace.unlink();p.initialize()
    source=p.programs/'Transfer/transfer.culs';source.unlink();source.symlink_to(outside/'source')
    with pytest.raises(ValueError,match='PREVIEW_FILE_IS_LINK'):p.initialize()
    assert not (outside/'source').exists()


def test_invalid_command_never_initializes_files(tmp_path):
    p=product(tmp_path)
    with pytest.raises(ValueError,match='PREVIEW_COMMAND_INVALID'):p.run('unexpected')
    assert not p.workspace.exists() and not p.state.exists()


def test_service_and_stop_use_the_product_endpoint(tmp_path):
    p=product(tmp_path)
    for mode in ['service','status','stop']:
        args=p.command(mode)
        assert args[args.index('--socket')+1]==str(p.socket)
    assert p.command('stop')[0]=='host-stop'


def test_endpoint_is_short_and_rejects_links_or_shared_permissions(tmp_path):
    p=product(tmp_path);p.initialize_endpoint()
    normal=MacPreviewProduct(p.resources,p.user_home/('long-home-name-'*20))
    assert len(str(normal.socket).encode()) < 104
    p.endpoint.chmod(0o755)
    with pytest.raises(ValueError,match='PREVIEW_ENDPOINT_NOT_PRIVATE'):p.initialize_endpoint()
    p.endpoint.chmod(0o700);p.endpoint.rmdir()
    outside=tmp_path/'outside';outside.mkdir();p.endpoint.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='PREVIEW_ENDPOINT_NOT_PRIVATE'):p.initialize_endpoint()


def test_builder_cleans_build_paths_and_retains_license_metadata(tmp_path):
    spec=importlib.util.spec_from_file_location('mac_builder',ROOT/'tools/build_mac_product.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    packages=tmp_path/'packages'
    for env in ('simulator','mcp'):
        site=packages/env;metadata=site/'example-1.2.dist-info';metadata.mkdir(parents=True)
        (metadata/'METADATA').write_text('Name: example\nVersion: 1.2\nLicense: MIT\n')
        (metadata/'LICENSE').write_text('license text')
        (metadata/'RECORD').write_text('example-1.2.dist-info/LICENSE,,\n')
        (metadata/'direct_url.json').write_text('{"url":"file:///private/build"}')
        scripts=site/'bin';scripts.mkdir();(scripts/'example').write_text('#!/private/build/python')
        cache=site/'__pycache__';cache.mkdir();(cache/'example.pyc').write_bytes(b'build path')
    subject=builder.MacProductBuilder();subject.clean_python_tree(tmp_path)
    assert not list(packages.rglob('direct_url.json')) and not list(packages.rglob('*.pyc'))
    assert not (packages/'mcp/bin').exists()
    inventory=subject.package_inventory(packages)
    assert inventory['mcp']==[{'name':'example','version':'1.2','license':'MIT','license_files':['example-1.2.dist-info/LICENSE']}]
    assert (packages/'mcp/example-1.2.dist-info/LICENSE').read_text()=='license text'


def test_product_launchers_disable_bundle_bytecode_writes(tmp_path):
    spec=importlib.util.spec_from_file_location('mac_builder',ROOT/'tools/build_mac_product.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    launcher=tmp_path/'culsma-mcp';builder.MacProductBuilder().write_shell(launcher,'mcp')
    assert ' -I -B ' in launcher.read_text()
    assert launcher.stat().st_mode & 0o111
    assert '"-I", "-B"' in (ROOT/'tools/desktop/Launcher.swift').read_text()


def test_builder_rejects_personal_native_build_paths(tmp_path):
    spec=importlib.util.spec_from_file_location('mac_builder',ROOT/'tools/build_mac_product.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    files=['Contents/MacOS/culsma_console','Contents/Frameworks/App.framework/Versions/A/App']
    for name in files:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'neutral build')
    subject=builder.MacProductBuilder();subject.validate_native_paths(tmp_path)
    (tmp_path/files[1]).write_bytes(('file://'+str(Path.home())+'/developer/project.dart').encode())
    with pytest.raises(ValueError,match='NATIVE_PERSONAL_BUILD_PATH'):subject.validate_native_paths(tmp_path)

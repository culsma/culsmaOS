"""Exercise real Windows handles as well as unchanged POSIX repository contracts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest
from culsma_os.platform_support import HostFileIO, ProcessFileLock, WindowsFileHandles
from culsma_os.file_system.repository import LocalFileWorkspaceRepository
from culsma_os.program_manager.adapters.resident import ResidentSocketAdapter, ResidentProtocolAdapter, LocalResidentEndpoint


@pytest.mark.parametrize('name', ['C:', 'a:b.culs', 'CON.culs', 'COM1', 'NUL', 'x.', 'x ', '..', 'a/b', 'a\\b', 'a\x00b'])
def test_windows_aliases_and_streams_are_rejected(name):
    with pytest.raises(OSError):
        WindowsFileHandles.component(name)


def test_lock_excludes_a_second_process_and_releases(tmp_path):
    path = tmp_path/'guard'
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    script = tmp_path/'probe.py'
    script.write_text('import os,sys\nfrom culsma_os.platform_support import ProcessFileLock\nf=os.open(sys.argv[1],os.O_RDWR)\ntry: ProcessFileLock.acquire(f)\nexcept BlockingIOError: sys.exit(17)\nos.close(f)\n')
    try:
        ProcessFileLock.acquire(fd)
        assert subprocess.run([sys.executable, str(script), str(path)]).returncode == 17
        ProcessFileLock.release(fd)
        assert subprocess.run([sys.executable, str(script), str(path)]).returncode == 0
    finally:
        os.close(fd)


def test_loopback_transport_refuses_missing_or_wrong_capability(tmp_path):
    class Commands:
        calls = 0
        def execute(self, request):
            self.calls += 1
            return {'state':'ready'}
    commands = Commands()
    server = ResidentSocketAdapter(tmp_path/'endpoint', commands)
    server.open_windows()
    value = LocalResidentEndpoint.read(server.path)
    try:
        for supplied, allowed in [(None, False), ('wrong', False), (value['token'], True)]:
            worker = threading.Thread(target=server.handle_one)
            worker.start()
            with socket.create_connection(('127.0.0.1', value['port'])) as connection:
                request = {'action':'status'}
                if supplied is not None: request['transport_auth'] = supplied
                ResidentProtocolAdapter.send(connection, request)
                response = ResidentProtocolAdapter.receive(connection)
            worker.join(3)
            assert response['ok'] is allowed
        assert commands.calls == 1
    finally:
        server.close()
    assert not server.path.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows reparse points and sharing rules')
def test_windows_junction_escape_and_rename_are_blocked(tmp_path):
    root = tmp_path/'workspace';root.mkdir()
    outside = tmp_path/'outside';outside.mkdir()
    (outside/'secret.culs').write_text('not in workspace')
    junction = root/'junction'
    subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)], check=True, capture_output=True)
    repository = LocalFileWorkspaceRepository(root)
    from culsma_os.file_system.models import FileReadError
    try:
        with pytest.raises(FileReadError): repository.read_document('junction/secret.culs')
        directory = root/'child'; directory.mkdir()
        fd = repository.reader.directory_descriptor('programs','child')
        try:
            with pytest.raises(OSError): directory.rename(root/'moved')
        finally: HostFileIO.close(fd)
        directory.rename(root/'moved')
    finally:
        os.rmdir(junction)


@pytest.mark.skipif(os.name != 'nt', reason='Windows alternate data streams')
def test_windows_import_rejects_drive_and_stream_escapes_before_staging(tmp_path):
    from culsma_os.file_system.models import FileReadError
    repository = LocalFileWorkspaceRepository(tmp_path/'workspace')
    for path in ('C:/outside.culs', 'test.culs:secret', 'NUL.culs'):
        with pytest.raises(FileReadError): repository.receive_files([(path,b'bad')])


def test_snapshot_preserves_exact_newlines_and_utf8_bytes(tmp_path):
    from culsma_os.program_manager.repositories.sources import FileProgramSourceRepository
    repository = FileProgramSourceRepository(tmp_path/'sources', tmp_path/'store')
    content = '// \u4e2d\u6587\r\nprotocol Example() {}\r\n'
    snapshot = repository.store_snapshot({'example.culs':content})
    assert (snapshot.directory/'example.culs').read_bytes() == content.encode('utf-8')
    assert repository.read_source(snapshot, 'example.culs') == content

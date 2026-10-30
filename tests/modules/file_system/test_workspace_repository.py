"""Repository behavior against actual files and independent repository instances."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
import os
import pytest
from culsma_os.file_system.models import FileReadError
from culsma_os.file_system.repository import LocalFileWorkspaceRepository


@pytest.fixture
def files(tmp_path):return LocalFileWorkspaceRepository(tmp_path/'Experiments')


@pytest.mark.parametrize('content,code',[(b'\xff','FILE_DOCUMENT_NOT_TEXT'),(b'a\0b','FILE_DOCUMENT_NOT_TEXT'),(b'x'*250001,'FILE_DOCUMENT_TOO_LARGE')])
def test_external_uneditable_files_are_reported_without_modification(files,content,code):
    files.ensure_root();path=files.root/'external.culs';path.write_bytes(content)
    with pytest.raises(FileReadError,match=code):files.read_document('external.culs')
    assert path.read_bytes()==content


def test_missing_deleted_file_and_special_file_do_not_create_or_block(files):
    with pytest.raises(FileReadError,match='FILE_NOT_FOUND'):files.read_document('missing.culs')
    created=files.write_document('deleted.culs',b'original',None)
    (files.root/'deleted.culs').unlink()
    with pytest.raises(FileReadError,match='FILE_REVISION_CONFLICT'):
        files.write_document('deleted.culs',b'edited',created['revision'])
    assert not (files.root/'deleted.culs').exists()
    os.mkfifo(files.root/'fifo.culs')
    with pytest.raises(FileReadError,match='FILE_PREVIEW_NOT_REGULAR'):files.read_document('fifo.culs')
    assert not list(files.root.glob('.save-*'))


def test_lock_contention_is_explicit_and_releases_after_error(files):
    other=LocalFileWorkspaceRepository(files.root)
    with files.write_lock():
        with pytest.raises(FileReadError,match='FILE_WORKSPACE_BUSY'):other.write_document('a.culs',b'a',None)
    assert not (files.root/'.culsma-write-lock').exists()
    other.write_document('a.culs',b'a',None)
    with pytest.raises(FileReadError,match='FILE_ALREADY_EXISTS'):files.write_document('a.culs',b'b',None)
    assert not (files.root/'.culsma-write-lock').exists()
    assert not list(files.root.glob('.save-*'))


def test_independent_concurrent_editors_never_overwrite_each_other(files):
    initial=files.write_document('shared.culs',b'initial',None);barrier=Barrier(2)
    def save(content):
        repository=LocalFileWorkspaceRepository(files.root);barrier.wait()
        try:return repository.write_document('shared.culs',content,initial['revision'])
        except FileReadError as error:return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[b'first',b'second']))
    assert sum(isinstance(result,dict) for result in results)==1
    assert next(result for result in results if isinstance(result,str)) in {'FILE_WORKSPACE_BUSY','FILE_REVISION_CONFLICT'}
    assert files.read_document('shared.culs')['content'] in {'first','second'}
    assert not list(files.root.glob('.*'))


def test_import_rolls_back_new_folders_and_preserves_existing_data(files):
    files.ensure_root();(files.root/'occupied').mkdir();(files.root/'occupied/original.csv').write_bytes(b'original')
    with pytest.raises(FileReadError,match='FILE_ALREADY_EXISTS'):
        files.receive_files([('new/deep/main.culs',b'new'),('occupied/original.csv',b'replacement')])
    assert sorted(path.name for path in files.root.iterdir())==['occupied']
    assert (files.root/'occupied/original.csv').read_bytes()==b'original'


def test_destination_file_symlink_never_reads_or_overwrites_outside(files,tmp_path):
    files.ensure_root();outside=tmp_path/'outside.culs';outside.write_bytes(b'outside')
    (files.root/'linked.culs').symlink_to(outside)
    for action in (lambda:files.read_document('linked.culs'),lambda:files.write_document('linked.culs',b'new',sha256(b'outside').hexdigest()),lambda:files.receive_files([('linked.culs',b'new')])):
        with pytest.raises(FileReadError):action()
    assert outside.read_bytes()==b'outside'
    assert (files.root/'linked.culs').is_symlink()
    assert not list(files.root.glob('.save-*'))
    assert not list(files.root.glob('.incoming-*'))

import os
from pathlib import Path
import pytest
from culsma_os.auth.interactors import TokenInteractor, AuthorizedInteractor
from culsma_os.auth.repository import SessionCredentialRepository
from culsma_os.auth.models import ConsoleAccessError
from culsma_os.file_system.interactors import FileReadInteractor, InstallationRootInteractor
from culsma_os.file_system.repository import LocalFileReadRepository
from culsma_os.file_system.models import FileReadRequest, FileReadError


@pytest.fixture
def browser(tmp_path):
    root=tmp_path/'installation';root.mkdir()
    programs=tmp_path/'projects';programs.mkdir()
    store=root/'snapshots';store.mkdir()
    repo=LocalFileReadRepository({'installation':root,'programs':programs},(store,))
    tokens=TokenInteractor(SessionCredentialRepository())
    return root,programs,repo,tokens,FileReadInteractor(tokens,repo,programs)


def test_authorization_precedes_every_read(browser,monkeypatch):
    root,programs,repo,tokens,interactor=browser
    monkeypatch.setattr(repo,'roots',lambda:pytest.fail('unauthorized filesystem access'))
    for credential in (None,'Bearer invalid','Bearer '+tokens.issue_renderer_session()):
        with pytest.raises(ConsoleAccessError):interactor.execute(credential,FileReadRequest('roots'))
    assert interactor.execute is not None and FileReadInteractor.execute is AuthorizedInteractor.execute


def test_roots_sorting_program_identity_and_excluded_state(browser):
    root,programs,repo,tokens,interactor=browser
    (root/'z-folder').mkdir();(root/'a.txt').write_text('text');(root/'run.culs').write_text('source')
    (root/'.hidden').write_text('private');(programs/'experiment.culs').write_text('source')
    credential='Bearer '+tokens.issue_automation_session()
    roots=interactor.execute(credential,FileReadRequest('roots'))
    assert roots['default_root']=='installation'
    assert roots['roots'][0]['path']==str(root)
    listing=interactor.execute(credential,FileReadRequest('list'))
    assert [v['name'] for v in listing['entries']]==['z-folder','a.txt','run.culs']
    assert listing['entries'][-1]['program']=={'program_id':'run.culs','source_scope':'installation'}
    assert interactor.execute(credential,FileReadRequest('list',root='programs'))['entries'][0]['program']['source_scope']=='programs'
    with pytest.raises(FileReadError):repo.list_directory('installation','snapshots',0)


@pytest.mark.parametrize('path',['../secret','/etc/passwd','a/../b','a//b','./file','.hidden','a/.hidden','a\\b','a\x00b'])
def test_paths_are_contained_and_hidden_entries_not_accessible(browser,path):
    with pytest.raises(FileReadError):browser[2].preview('installation',path)


def test_links_and_fifo_never_open_or_follow(browser,tmp_path):
    root,_,repo,_,_=browser
    outside=tmp_path/'outside';outside.mkdir();(outside/'secret').write_text('secret')
    (root/'linked').symlink_to(outside,target_is_directory=True)
    (root/'file-link').symlink_to(outside/'secret')
    os.mkfifo(root/'pipe')
    for path in ('linked/secret','file-link','pipe'):
        with pytest.raises(FileReadError):repo.preview('installation',path)
    with pytest.raises(FileReadError):repo.list_directory('installation','linked',0)
    assert all(not x['openable'] for x in repo.list_directory('installation','',0)['entries'])


def test_bounded_utf8_preview_binary_metadata_and_pagination(browser):
    root,_,repo,_,_=browser
    (root/'text').write_text('hello'+chr(0x03bb)*40000)
    result=repo.preview('installation','text')
    assert result['truncated'] and result['content'].startswith('hello') and len(result['content'].encode())<=repo.preview_bytes
    (root/'binary').write_bytes(b'\x00\xff')
    result=repo.preview('installation','binary')
    assert result['preview']=='binary' and result['content'] is None
    for i in range(205):(root/f'item-{i:03}').write_text('')
    first=repo.list_directory('installation','',0);second=repo.list_directory('installation','',first['next_offset'])
    assert first['total']==207 and len(first['entries'])==200 and second['next_offset'] is None
    assert not {x['path'] for x in first['entries']} & {x['path'] for x in second['entries']}


@pytest.mark.parametrize('payload',[FileReadRequest('delete'),FileReadRequest('list',offset=True),FileReadRequest('roots',path='x'),FileReadRequest('preview'),FileReadRequest('list',root='outside')])
def test_invalid_operations_rejected(browser,payload):
    with pytest.raises(FileReadError):browser[4].execute('Bearer '+browser[3].issue_console_session(),payload)


def test_installation_root_uses_checkout_or_installed_package():
    resolver=InstallationRootInteractor()
    assert resolver.resolve('/application/src/culsma_os')==Path('/application')
    assert resolver.resolve('/environment/site-packages/culsma_os')==Path('/environment/site-packages/culsma_os')

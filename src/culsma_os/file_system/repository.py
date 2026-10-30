"""Read-only access to server-selected roots; never follow links or special files."""
import codecs
import os
from pathlib import Path
import stat
from typing import Protocol
from .models import FileReadError


class FileReadRepository(Protocol):
    def roots(self) -> list[dict]: ...
    def list_directory(self,root: str,path: str,offset: int) -> dict: ...
    def preview(self,root: str,path: str) -> dict: ...


class LocalFileReadRepository:
    page_size=200
    max_entries=50000
    preview_bytes=64000
    def __init__(self,roots,excluded=(),home=None):
        self.paths={key:Path(value).resolve() for key,value in roots.items() if value is not None}
        self.home=Path(home).expanduser().resolve() if home is not None else None
        self.excluded=tuple(Path(value).resolve() for value in excluded)

    def initialize_home(self):
        if self.home is None:return
        try:
            for path in (self.home,self.home/'projects',self.home/'results'):
                if path.is_symlink():raise FileReadError('FILE_LOCATION_UNAVAILABLE','unavailable')
                path.mkdir(parents=True,exist_ok=True,mode=0o700)
        except OSError as error:raise FileReadError('FILE_LOCATION_UNAVAILABLE','unavailable') from error

    def roots(self):
        self.initialize_home()
        return [{'id':key,'path':str(path),'available':path.is_dir()} for key,path in self.paths.items()]

    def validate_path(self,path):
        if not isinstance(path,str) or len(path)>1024 or '\x00' in path or '\\' in path or path.startswith('/') or path and any(not part or part in {'.','..'} or part.startswith('.') for part in path.split('/')):
            raise FileReadError('FILE_PATH_INVALID')

    def selected_path(self,root,path):
        self.validate_path(path)
        if root not in self.paths:raise FileReadError('FILE_ROOT_NOT_FOUND','not_found')
        target=self.paths[root]/path
        if any(target==value or target.is_relative_to(value) for value in self.excluded):
            raise FileReadError('FILE_LOCATION_UNAVAILABLE','forbidden')
        return target

    def directory_descriptor(self,root,path):
        self.selected_path(root,path)
        self.initialize_home()
        descriptor=os.open(self.paths[root],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in path.split('/') if path else ():
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
                os.close(descriptor);descriptor=child
            return descriptor
        except BaseException:
            os.close(descriptor);raise

    def describe(self,root,path,name,info):
        kind='directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'link' if stat.S_ISLNK(info.st_mode) else 'special'
        result={'name':name,'path':path,'kind':kind,'size':info.st_size if kind=='file' else None,'modified_ns':info.st_mtime_ns,'extension':Path(name).suffix.lower(),'openable':kind in {'file','directory'}}
        return result

    def list_directory(self,root,path,offset):
        descriptor=None
        try:
            descriptor=self.directory_descriptor(root,path);rows=[]
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    if entry.name.startswith('.'):continue
                    child=f'{path}/{entry.name}' if path else entry.name
                    if any((self.paths[root]/child)==p or (self.paths[root]/child).is_relative_to(p) for p in self.excluded):continue
                    try:info=entry.stat(follow_symlinks=False)
                    except FileNotFoundError:continue
                    rows.append(self.describe(root,child,entry.name,info))
                    if len(rows)>self.max_entries:raise FileReadError('FILE_DIRECTORY_TOO_LARGE','unavailable')
            rows.sort(key=lambda r:(r['kind']!='directory',r['name'].casefold(),r['name']))
            return {'root':root,'root_path':str(self.paths[root]),'path':path,'parent':path.rpartition('/')[0] if path else None,'entries':rows[offset:offset+self.page_size],'total':len(rows),'next_offset':offset+self.page_size if offset+self.page_size<len(rows) else None,'hidden_files':False,'read_only':True}
        except FileReadError:raise
        except FileNotFoundError as e:raise FileReadError('FILE_NOT_FOUND','not_found') from e
        except OSError as e:raise FileReadError('FILE_LOCATION_UNAVAILABLE','unavailable') from e
        finally:
            if descriptor is not None:os.close(descriptor)

    def preview(self,root,path):
        directory,_,name=path.rpartition('/');descriptor=None
        self.selected_path(root,path)
        try:
            descriptor=self.directory_descriptor(root,directory)
            child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
            with os.fdopen(child,'rb') as stream:
                info=os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):raise FileReadError('FILE_PREVIEW_NOT_REGULAR','forbidden')
                raw=stream.read(self.preview_bytes+1)
            result=self.describe(root,path,name,info)
            try:
                if b'\x00' in raw:raise UnicodeError('binary')
                result.update(preview='text',content=codecs.getincrementaldecoder('utf-8')().decode(raw[:self.preview_bytes],final=len(raw)<=self.preview_bytes),truncated=len(raw)>self.preview_bytes)
            except UnicodeError:result.update(preview='binary',content=None,truncated=False)
            return result
        except FileReadError:raise
        except FileNotFoundError as e:raise FileReadError('FILE_NOT_FOUND','not_found') from e
        except OSError as e:raise FileReadError('FILE_PREVIEW_UNAVAILABLE','unavailable') from e
        finally:
            if descriptor is not None:os.close(descriptor)


class FileWorkspaceRepository(Protocol):
    def read_document(self,path: str) -> dict: ...
    def write_document(self,path: str,content: bytes,expected_revision: str | None) -> dict: ...
    def receive_files(self,entries: list[tuple[str,bytes]]) -> dict: ...


class LocalFileWorkspaceRepository:
    """User experiment files only; descriptor-relative access and atomic replacements."""
    max_document_bytes=250000

    def __init__(self,root):
        self.root=Path(root).resolve()
        self.reader=LocalFileReadRepository({'programs':self.root})

    def ensure_root(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.is_symlink():raise FileReadError('FILE_PATH_INVALID')

    def read_document(self,path):
        from hashlib import sha256
        parent,_,name=path.rpartition('/')
        self.reader.selected_path('programs',path)
        self.ensure_root()
        descriptor=None
        try:
            descriptor=self.reader.directory_descriptor('programs',parent)
            child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
            with os.fdopen(child,'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise FileReadError('FILE_PREVIEW_NOT_REGULAR')
                data=stream.read(self.max_document_bytes+1)
            if len(data)>self.max_document_bytes:raise FileReadError('FILE_DOCUMENT_TOO_LARGE')
            content=data.decode('utf-8')
            if '\x00' in content:raise FileReadError('FILE_DOCUMENT_NOT_TEXT')
            return {'path':path,'content':content,'revision':sha256(data).hexdigest()}
        except FileNotFoundError as error:raise FileReadError('FILE_NOT_FOUND','not_found') from error
        except UnicodeError as error:raise FileReadError('FILE_DOCUMENT_NOT_TEXT') from error
        except OSError as error:raise FileReadError('FILE_LOCATION_UNAVAILABLE','unavailable') from error
        finally:
            if descriptor is not None:os.close(descriptor)

    def write_lock(self):
        from contextlib import contextmanager
        @contextmanager
        def acquire():
            self.ensure_root()
            descriptor=self.reader.directory_descriptor('programs','')
            try:
                try:os.mkdir('.culsma-write-lock',mode=0o700,dir_fd=descriptor)
                except FileExistsError as error:raise FileReadError('FILE_WORKSPACE_BUSY','conflict') from error
                try:yield
                finally:os.rmdir('.culsma-write-lock',dir_fd=descriptor)
            finally:os.close(descriptor)
        return acquire()

    def write_document(self,path,content,expected_revision):
        from hashlib import sha256
        from uuid import uuid4
        parent,_,name=path.rpartition('/')
        self.reader.selected_path('programs',path)
        descriptor=None
        with self.write_lock():
            try:
                descriptor=self.reader.directory_descriptor('programs',parent)
                try:current=self.read_document(path)
                except FileReadError as error:
                    if error.code!='FILE_NOT_FOUND':raise
                    current=None
                if expected_revision is None and current is not None:raise FileReadError('FILE_ALREADY_EXISTS','conflict')
                if expected_revision is not None and (current is None or current['revision']!=expected_revision):
                    raise FileReadError('FILE_REVISION_CONFLICT','conflict')
                temporary='.save-'+uuid4().hex
                child=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=descriptor)
                try:
                    with os.fdopen(child,'wb') as stream:
                        stream.write(content);stream.flush();os.fsync(stream.fileno())
                    if expected_revision is None:
                        try:os.link(temporary,name,src_dir_fd=descriptor,dst_dir_fd=descriptor,follow_symlinks=False)
                        except FileExistsError as error:raise FileReadError('FILE_ALREADY_EXISTS','conflict') from error
                    else:os.replace(temporary,name,src_dir_fd=descriptor,dst_dir_fd=descriptor)
                finally:
                    try:os.unlink(temporary,dir_fd=descriptor)
                    except FileNotFoundError:pass
                return {'path':path,'revision':sha256(content).hexdigest()}
            except FileReadError:raise
            except OSError as error:raise FileReadError('FILE_WRITE_FAILED','unavailable') from error
            finally:
                if descriptor is not None:os.close(descriptor)

    def receive_files(self,entries):
        """Stage all bytes before publishing; collisions never overwrite existing files."""
        from uuid import uuid4
        import shutil
        created_files=[];created_directories=[]
        with self.write_lock():
            staging=self.root/('.incoming-'+uuid4().hex)
            staging.mkdir(mode=0o700)
            try:
                for path,data in entries:
                    self.reader.selected_path('programs',path)
                    target=staging/path;target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(data)
                # Inspect every ancestor through no-follow descriptors before any publication.
                for path,_ in entries:
                    parts=path.split('/');relative=''
                    for part in parts[:-1]:
                        parent=relative;relative=f'{relative}/{part}' if relative else part
                        fd=self.reader.directory_descriptor('programs',parent)
                        try:
                            try:os.mkdir(part,mode=0o700,dir_fd=fd);created_directories.append(relative)
                            except FileExistsError:pass
                        finally:os.close(fd)
                        fd=self.reader.directory_descriptor('programs',relative);os.close(fd)
                    fd=self.reader.directory_descriptor('programs',relative)
                    try:
                        try:os.stat(parts[-1],dir_fd=fd,follow_symlinks=False)
                        except FileNotFoundError:pass
                        else:raise FileReadError('FILE_ALREADY_EXISTS','conflict')
                    finally:os.close(fd)
                for path,_ in entries:
                    parent,_,name=path.rpartition('/');fd=self.reader.directory_descriptor('programs',parent)
                    try:
                        # link is exclusive: even external writers cannot be overwritten.
                        os.link(staging/path,name,dst_dir_fd=fd,follow_symlinks=False)
                        created_files.append(path)
                    finally:os.close(fd)
                return {'paths':[path for path,_ in entries],'count':len(entries)}
            except BaseException as error:
                for path in reversed(created_files):
                    fd=self.reader.directory_descriptor('programs',path.rpartition('/')[0])
                    try:os.unlink(path.rpartition('/')[2],dir_fd=fd)
                    finally:os.close(fd)
                for path in reversed(created_directories):
                    try:(self.root/path).rmdir()
                    except OSError:pass
                if isinstance(error,FileReadError):raise
                if isinstance(error,OSError):raise FileReadError('FILE_RECEIVE_FAILED','unavailable') from error
                raise
            finally:shutil.rmtree(staging)

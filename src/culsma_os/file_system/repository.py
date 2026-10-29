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
    def __init__(self,roots,excluded=()):
        self.paths={key:Path(value).resolve() for key,value in roots.items() if value is not None}
        self.excluded=tuple(Path(value).resolve() for value in excluded)

    def roots(self):
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

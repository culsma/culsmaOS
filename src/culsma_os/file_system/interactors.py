from pathlib import Path
from culsma_os.auth.interactors import AuthorizedInteractor
from .models import FileReadRequest,FileReadError
from .repository import FileReadRepository


class UserWorkspaceRootInteractor:
    def resolve(self,home=None):
        return Path(home).expanduser().resolve() if home is not None else Path.home()/'Culsma'


class FileReadInteractor(AuthorizedInteractor):
    required_capability='files:read'
    def __init__(self,tokens,repository:FileReadRepository,program_root=None):
        super().__init__(tokens);self.repository=repository
        self.program_root=Path(program_root).resolve() if program_root else None
    def perform_authorized(self,caller,request):
        if not isinstance(request,FileReadRequest) or request.action not in {'roots','list','preview'} or not isinstance(request.root,str) or not isinstance(request.path,str) or type(request.offset) is not int or not 0<=request.offset<=50000:
            raise FileReadError('FILE_REQUEST_INVALID')
        if request.action=='roots':
            if request.path or request.offset or request.root!='installation':raise FileReadError('FILE_REQUEST_INVALID')
            return {'roots':[{**row,'label':'culsmaOS' if row['id']=='installation' else 'Experiments'} for row in self.repository.roots()],'default_root':'installation'}
        if request.action=='preview':
            if not request.path or request.offset:raise FileReadError('FILE_REQUEST_INVALID')
            return self.project_entry(request.root,self.repository.preview(request.root,request.path))
        result=self.repository.list_directory(request.root,request.path,request.offset)
        return {**result,'entries':[self.project_entry(request.root,row,result['root_path']) for row in result['entries']]}

    def project_entry(self,root,entry,root_path=None):
        result=dict(entry)
        if root=='installation' and entry['kind']=='directory':
            if root_path is None:
                root_path=next(row['path'] for row in self.repository.roots() if row['id']==root)
            target=Path(root_path)/entry['path']
            if self.program_root is not None and target==self.program_root:
                result['name']='Experiments'
            elif entry['path']=='results':
                result['name']='Results'
        if entry['kind']!='file' or not entry['name'].endswith('.culs'):
            return result
        if root=='programs':
            result['program']={'program_id':entry['path'],'source_scope':'programs'}
        elif root=='installation':
            if root_path is None:
                root_path=next(row['path'] for row in self.repository.roots() if row['id']==root)
            target=Path(root_path)/entry['path']
            result['program']=({'program_id':target.relative_to(self.program_root).as_posix(),'source_scope':'programs'}
                if self.program_root is not None and target.is_relative_to(self.program_root)
                else {'program_id':entry['path'],'source_scope':'installation'})
        return result


class DocumentInspectionInteractor:
    def __init__(self,repository):self.repository=repository

    def read(self,path):
        if not isinstance(path,str) or not path.endswith('.culs'):raise FileReadError('FILE_DOCUMENT_TYPE_INVALID')
        return self.repository.read_document(path)


class FileWorkspaceInteractor(AuthorizedInteractor):
    required_capability='files:write'

    def __init__(self,tokens,repository):
        super().__init__(tokens);self.repository=repository
        self.documents=DocumentInspectionInteractor(repository)

    def perform(self,request):
        from .models import FileWorkspaceRequest
        if not isinstance(request,FileWorkspaceRequest) or request.action not in {'read','create','save','receive'}:
            raise FileReadError('FILE_REQUEST_INVALID')
        self.validate_path(request.path,allow_empty=request.action=='receive')
        if request.action=='read':
            if any(v is not None for v in (request.content,request.expected_revision,request.entries)):
                raise FileReadError('FILE_REQUEST_INVALID')
            return self.documents.read(request.path)
        if request.action=='receive':
            if request.content is not None or request.expected_revision is not None:raise FileReadError('FILE_REQUEST_INVALID')
            return self.repository.receive_files(self.decode_entries(request.path,request.entries))
        try:content=request.content.encode('utf-8') if isinstance(request.content,str) else None
        except UnicodeError as error:raise FileReadError('FILE_DOCUMENT_INVALID') from error
        if (request.entries is not None or content is None or '\x00' in request.content
                or len(content)>250000 or not request.path.endswith('.culs')):
            raise FileReadError('FILE_DOCUMENT_INVALID')
        if request.action=='create' and request.expected_revision is not None:raise FileReadError('FILE_REQUEST_INVALID')
        if request.action=='save' and (not isinstance(request.expected_revision,str)
                or len(request.expected_revision)!=64 or any(c not in '0123456789abcdef' for c in request.expected_revision)):
            raise FileReadError('FILE_REVISION_REQUIRED')
        return self.repository.write_document(request.path,content,request.expected_revision)

    def validate_path(self,path,allow_empty=False):
        if isinstance(path,str):
            try:path.encode('utf-8')
            except UnicodeError as error:raise FileReadError('FILE_PATH_INVALID') from error
        if (not isinstance(path,str) or not path and not allow_empty or len(path)>1024 or '\x00' in path
                or '\\' in path or path.startswith('/') or ':' in path
                or path and any(not part or part in {'.','..'} or part.startswith('.') for part in path.split('/'))):
            raise FileReadError('FILE_PATH_INVALID')
        if path.endswith('.culs') and len(path)>240:raise FileReadError('FILE_PATH_INVALID')

    def decode_entries(self,directory,entries):
        import base64
        if not isinstance(entries,list) or not 1<=len(entries)<=200:raise FileReadError('FILE_RECEIVE_INVALID')
        decoded=[];seen=set();total=0
        for entry in entries:
            if not isinstance(entry,dict) or set(entry)!={'path','data'}:raise FileReadError('FILE_RECEIVE_INVALID')
            self.validate_path(entry['path'])
            if not isinstance(entry['data'],str) or len(entry['data'])>5600000:raise FileReadError('FILE_RECEIVE_TOO_LARGE')
            try:data=base64.b64decode(entry['data'],validate=True)
            except (ValueError,TypeError) as error:raise FileReadError('FILE_RECEIVE_INVALID') from error
            total+=len(data)
            if total>4000000:raise FileReadError('FILE_RECEIVE_TOO_LARGE')
            path=f'{directory}/{entry["path"]}' if directory else entry['path']
            self.validate_path(path)
            if path.casefold() in seen:raise FileReadError('FILE_RECEIVE_DUPLICATE')
            seen.add(path.casefold());decoded.append((path,data))
        for path,_ in decoded:
            if any(other.casefold().startswith(path.casefold()+'/') for other,_ in decoded):
                raise FileReadError('FILE_RECEIVE_INVALID')
        return decoded

from pathlib import Path
from culsma_os.auth.interactors import AuthorizedInteractor
from .models import FileReadRequest,FileReadError
from .repository import FileReadRepository


class InstallationRootInteractor:
    def resolve(self,package):
        package=Path(package).resolve()
        checkout=package.parent.parent
        return checkout if package.parent.name=='src' else package


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

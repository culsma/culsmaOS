"""Server-selected source files and content-addressed execution snapshots only."""
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from tempfile import mkdtemp
from threading import Lock
from ..models import ConsoleProgramError, ProgramSourceSnapshot


class FileProgramSourceRepository:
    max_files = 256
    max_file_bytes = 250000
    max_total_bytes = 2000000

    def __init__(self, root, store):
        self.root = Path(root).resolve() if root is not None else None
        self.store = Path(store).resolve()
        self.lock = Lock()
        if self.root is not None and self.store.is_relative_to(self.root):
            raise ConsoleProgramError('PROGRAM_STORE_INSIDE_SOURCE_ROOT')

    def validate_id(self, value):
        if (not isinstance(value, str) or not value or len(value) > 240
                or '\\' in value or value.startswith('/')
                or any(part in {'', '.', '..'} for part in value.split('/'))
                or PurePosixPath(value).suffix != '.culs'):
            raise ConsoleProgramError('PROGRAM_ID_INVALID')
        return value

    def source_ids(self):
        if self.root is None:
            return []
        if not self.root.is_dir():
            raise ConsoleProgramError('PROGRAM_ROOT_UNAVAILABLE', 'unavailable')
        result = []
        def walk_error(error):
            raise ConsoleProgramError('PROGRAM_SOURCE_UNAVAILABLE', 'unavailable') from error
        for parent, directories, files in os.walk(self.root, followlinks=False, onerror=walk_error):
            directories[:] = sorted(name for name in directories if not name.startswith('.')
                and not (Path(parent)/name).is_symlink())
            for name in sorted(files):
                if name.startswith('.') or not name.endswith('.culs'):
                    continue
                item = (Path(parent)/name).relative_to(self.root).as_posix()
                self.validate_id(item)
                result.append(item)
                if len(result) > self.max_files:
                    raise ConsoleProgramError('PROGRAM_LIBRARY_TOO_LARGE')
        return sorted(result)

    def read_file(self, directory, name, limit=None):
        """Open every component without following symlinks, including swapped parents."""
        self.validate_id(name)
        descriptor = None
        try:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            parts = PurePosixPath(name).parts
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor); descriptor = child
            child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(child, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ConsoleProgramError('PROGRAM_SOURCE_NOT_REGULAR')
                value = stream.read((limit or self.max_file_bytes)+1)
            if len(value) > (limit or self.max_file_bytes):
                raise ConsoleProgramError('PROGRAM_SOURCE_TOO_LARGE')
            return value.decode('utf-8')
        except (OSError, UnicodeError) as error:
            raise ConsoleProgramError('PROGRAM_SOURCE_UNAVAILABLE', 'unavailable') from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def enabled(self):
        return self.root is not None

    def list(self):
        return {'enabled':self.root is not None,
                'programs':[{'program_id':name} for name in self.source_ids()]}

    def fingerprint(self, sources):
        encoded = json.dumps(sources, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()

    def capture(self):
        if self.root is None:
            raise ConsoleProgramError('PROGRAM_LIBRARY_DISABLED', 'unavailable')
        sources = {}
        total = 0
        for name in self.source_ids():
            sources[name] = self.read_file(self.root, name)
            total += len(sources[name].encode())
            if total > self.max_total_bytes:
                raise ConsoleProgramError('PROGRAM_LIBRARY_TOO_LARGE')
        snapshot_id = self.fingerprint(sources)
        with self.lock:
            self.store.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = self.store/snapshot_id
            if not target.exists():
                temporary = Path(mkdtemp(prefix='.capture-', dir=self.store))
                try:
                    for name, value in sources.items():
                        path = temporary/name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(value, encoding='utf-8')
                    (temporary/'manifest.json').write_text(json.dumps(sorted(sources)), encoding='utf-8')
                    try:
                        temporary.rename(target)
                    except OSError as error:
                        if error.errno not in {errno.EEXIST,errno.ENOTEMPTY}:
                            raise
                        # Another console captured these bytes; load verifies them below.
                finally:
                    if temporary.exists(): shutil.rmtree(temporary)
        return self.load(snapshot_id)

    def read_source(self, snapshot, program_id):
        return self.read_file(snapshot.directory,program_id)

    def load(self, snapshot_id):
        if not isinstance(snapshot_id,str) or re.fullmatch(r'[0-9a-f]{64}', snapshot_id) is None:
            raise ConsoleProgramError('PROGRAM_SNAPSHOT_INVALID')
        directory = self.store/snapshot_id
        try:
            if directory.is_symlink() or (directory/'manifest.json').is_symlink():
                raise ConsoleProgramError('PROGRAM_SNAPSHOT_INVALID')
            with (directory/'manifest.json').open('rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ConsoleProgramError('PROGRAM_SNAPSHOT_INVALID')
            names = json.loads(raw)
        except FileNotFoundError as error:
            raise ConsoleProgramError('PROGRAM_SNAPSHOT_NOT_FOUND','not_found') from error
        except (OSError, ValueError, RecursionError) as error:
            raise ConsoleProgramError('PROGRAM_SNAPSHOT_INVALID') from error
        if (not isinstance(names,list) or len(names)>self.max_files
                or not all(isinstance(name,str) for name in names) or len(set(names))!=len(names)):
            raise ConsoleProgramError('PROGRAM_SNAPSHOT_INVALID')
        sources = {name:self.read_file(directory,name) for name in names}
        if sum(len(value.encode()) for value in sources.values())>self.max_total_bytes or self.fingerprint(sources)!=snapshot_id:
            raise ConsoleProgramError('PROGRAM_SNAPSHOT_CHANGED','conflict')
        return ProgramSourceSnapshot(snapshot_id,directory,tuple(names))

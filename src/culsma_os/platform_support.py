"""Host OS primitives shared by repositories; no experiment or driver decisions."""
import errno
import os
from pathlib import Path
import time


class ProcessFileLock:
    """One-byte process lock on Windows; flock on POSIX. Closing releases either."""
    @staticmethod
    def acquire(fd, blocking=False):
        if os.name != 'nt':
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            return
        import msvcrt
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if not blocking:
                    raise BlockingIOError(errno.EAGAIN, 'File is locked') from error
                time.sleep(0.05)

    @staticmethod
    def release(fd):
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


class PinnedWindowsDirectory:
    """Open without FILE_SHARE_DELETE; retain every ancestor until children close."""
    def __init__(self, path, handle, parent=None):
        self.path, self.handle, self.parent = Path(path), handle, parent
        self.references = 1
        if parent is not None:
            parent.references += 1

    def close(self):
        self.references -= 1
        if self.references == 0:
            WindowsFileHandles.api().CloseHandle(self.handle)
            if self.parent is not None:
                self.parent.close()


class WindowsFileHandles:
    @staticmethod
    def api():
        import ctypes
        from ctypes import wintypes as w
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        api.CreateFileW.restype = w.HANDLE
        api.CloseHandle.argtypes = [w.HANDLE]
        api.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        return api

    @staticmethod
    def component(name):
        # Reject drive escapes, alternate streams, DOS devices and Windows aliases.
        value = str(name)
        base = value.split('.')[0].upper()
        if (not value or value in {'.', '..'} or any(c in value for c in '\\/:\x00<>"|?*')
                or value.endswith((' ', '.')) or any(ord(c) < 32 for c in value)
                or base in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
                or base in {prefix + n for prefix in ('COM', 'LPT') for n in '123456789¹²³'}):
            raise OSError(errno.EINVAL, 'Unsafe Windows path component', value)
        return value

    @classmethod
    def handle(cls, path, flags, *, directory=False, private=False):
        import ctypes
        from ctypes import wintypes as w
        api = cls.api()
        access = 0x81 if directory else (0xC0000000 if flags & os.O_RDWR else 0x40000000 if flags & os.O_WRONLY else 0x80000000)
        creation = 1 if flags & os.O_CREAT and flags & os.O_EXCL else 2 if flags & os.O_CREAT and flags & os.O_TRUNC else 4 if flags & os.O_CREAT else 5 if flags & os.O_TRUNC else 3
        sd = None
        security = None
        if private:
            adv = ctypes.WinDLL('advapi32', use_last_error=True)
            adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            sd = ctypes.c_void_p()
            # Protected DACL: owner and LocalSystem only. No inherited access.
            if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;FA;;;OW)(A;;FA;;;SY)', 1, ctypes.byref(sd), None):
                raise ctypes.WinError(ctypes.get_last_error())
            class Attributes(ctypes.Structure):
                _fields_ = [('length', w.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', w.BOOL)]
            security = Attributes(ctypes.sizeof(Attributes), sd, False)
        try:
            handle = api.CreateFileW(str(path), access, 3, ctypes.byref(security) if security else None,
                                     creation, 0x00200000 | (0x02000000 if directory else 0), None)
        finally:
            if sd:
                api.LocalFree.argtypes = [ctypes.c_void_p]
                api.LocalFree(sd)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        class AttributesInfo(ctypes.Structure):
            _fields_ = [('attributes', w.DWORD), ('tag', w.DWORD)]
        info = AttributesInfo()
        try:
            if not api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400:
                raise OSError(errno.ELOOP, 'Reparse points are not permitted', str(path))
            if bool(info.attributes & 0x10) != directory:
                raise OSError(errno.ENOTDIR if directory else errno.EISDIR, 'Wrong file type', str(path))
            return handle
        except BaseException:
            api.CloseHandle(handle)
            raise

    @classmethod
    def directory(cls, path, parent=None):
        if parent is not None:
            path = parent.path / cls.component(path)
            return PinnedWindowsDirectory(path, cls.handle(path, 0, directory=True), parent)
        path = Path(os.path.abspath(path))
        if not path.drive or path.drive.startswith('\\\\'):
            raise OSError(errno.EINVAL, 'A local drive is required')
        current = PinnedWindowsDirectory(path.anchor, cls.handle(path.anchor, 0, directory=True))
        try:
            for part in path.parts[1:]:
                child = cls.directory(part, current)
                current.close()
                current = child
            return current
        except BaseException:
            current.close()
            raise


class HostFileIO:
    """Descriptor-relative no-follow operations, preserving the POSIX implementation."""
    O_DIRECTORY = getattr(os, 'O_DIRECTORY', 0x10000000)
    O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0x20000000)
    O_NONBLOCK = getattr(os, 'O_NONBLOCK', 0)

    @classmethod
    def open(cls, path, flags, mode=0o600, *, dir_fd=None, private=False):
        if os.name != 'nt':
            return os.open(path, flags, mode, dir_fd=dir_fd)
        if flags & cls.O_DIRECTORY:
            return WindowsFileHandles.directory(path, dir_fd)
        import msvcrt
        parent = dir_fd
        owned = parent is None
        if owned:
            path = Path(os.path.abspath(path))
            parent = WindowsFileHandles.directory(path.parent)
            path = path.name
        try:
            target = parent.path / WindowsFileHandles.component(path)
            handle = WindowsFileHandles.handle(target, flags, private=private)
            try:
                return msvcrt.open_osfhandle(handle, (flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR | os.O_APPEND)) | os.O_BINARY)
            except BaseException:
                WindowsFileHandles.api().CloseHandle(handle)
                raise
        finally:
            if owned:
                parent.close()

    @staticmethod
    def is_link(path):
        try:
            return Path(path).is_symlink() or bool(getattr(Path(path).lstat(), 'st_file_attributes', 0) & 0x400)
        except FileNotFoundError:
            return False

    @staticmethod
    def close(fd):
        if isinstance(fd, PinnedWindowsDirectory):
            fd.close()
        else:
            os.close(fd)

    @staticmethod
    def path(name, descriptor):
        return descriptor.path / WindowsFileHandles.component(name) if descriptor is not None else name

    @classmethod
    def scandir(cls, fd):
        return os.scandir(fd.path if isinstance(fd, PinnedWindowsDirectory) else fd)

    @classmethod
    def mkdir(cls, name, mode=0o700, *, dir_fd=None):
        if os.name == 'nt':
            return os.mkdir(cls.path(name, dir_fd), mode)
        return os.mkdir(name, mode, dir_fd=dir_fd)

    @classmethod
    def rmdir(cls, name, *, dir_fd=None):
        if os.name == 'nt':
            return os.rmdir(cls.path(name, dir_fd))
        return os.rmdir(name, dir_fd=dir_fd)

    @classmethod
    def unlink(cls, name, *, dir_fd=None):
        if os.name == 'nt':
            return os.unlink(cls.path(name, dir_fd))
        return os.unlink(name, dir_fd=dir_fd)

    @classmethod
    def stat(cls, name, *, dir_fd=None, follow_symlinks=False):
        if os.name == 'nt':
            return os.stat(cls.path(name, dir_fd), follow_symlinks=follow_symlinks)
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    @classmethod
    def link(cls, source, target, *, src_dir_fd=None, dst_dir_fd=None, follow_symlinks=False):
        if os.name == 'nt':
            # Open the source no-follow and keep it pinned while linking. Never overwrite.
            source = Path(cls.path(source, src_dir_fd))
            parent = WindowsFileHandles.directory(source.parent)
            try:
                fd = cls.open(source.name, os.O_RDONLY | cls.O_NOFOLLOW, dir_fd=parent)
                try:
                    return os.link(source, cls.path(target, dst_dir_fd), follow_symlinks=False)
                finally:
                    cls.close(fd)
            finally:
                parent.close()
        return os.link(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)

    @classmethod
    def replace(cls, source, target, *, src_dir_fd=None, dst_dir_fd=None):
        if os.name == 'nt':
            return os.replace(cls.path(source, src_dir_fd), cls.path(target, dst_dir_fd))
        return os.replace(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

"""Leitor de origem: única porta de acesso à raiz indexada, somente leitura (ARCHITECTURE.md).

Esta versão só lista diretórios e lê metadados (`stat` sem seguir links). Não abre arquivos,
não lê conteúdo e não expõe operação de escrita, renomeação, exclusão ou alteração de atributos.
Diretórios são abertos com O_RDONLY | O_DIRECTORY | O_NOFOLLOW relativo ao descritor do pai,
desde '/' até a raiz permitida, depois até a fonte e durante toda a varredura. O caminho textual
nunca é reaberto: um link em qualquer componente, inclusive trocado após a validação, é recusado
pelo kernel (ELOOP/ENOTDIR).

Exige POSIX (`dir_fd`, O_NOFOLLOW). Tratamento de Windows/SMB depende de P-04.
"""
import errno
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DIR_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_POSIX_SUPPORTED = os.open in os.supports_dir_fd and bool(getattr(os, "O_NOFOLLOW", 0))


class SourceUnavailable(Exception):
    """Raiz não pôde ser aberta (offline, ausente, sem permissão ou não é diretório real)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FileEntry:
    relative_path: str  # separador '/'
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True)
class SkippedEntry:
    relative_path: str
    reason: str  # 'link' ou 'special'


@dataclass(frozen=True)
class ErrorEntry:
    relative_path: str  # '' quando o erro é na listagem da própria raiz
    code: str
    message: str  # sanitizada, sem caminho


Entry = FileEntry | SkippedEntry | ErrorEntry


def sanitized(exc: OSError) -> str:
    """Código do erro do sistema sem caminho (OSError.__str__ inclui o caminho absoluto)."""
    name = errno.errorcode.get(exc.errno, "EUNKNOWN") if exc.errno else type(exc).__name__
    return f"{name}: {exc.strerror or 'erro de sistema'}"


def _error_code(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return "vanished"
    if exc.errno == errno.ELOOP:  # link trocado no lugar de uma pasta após o stat
        return "changed_during_scan"
    return "os_error"


def _modified_at(st: os.stat_result) -> datetime:
    # Precisão de microssegundos, igual a timestamptz; evita arredondamento de float.
    return _EPOCH + timedelta(microseconds=st.st_mtime_ns // 1000)


def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


class SourceReader:
    def __init__(self, allowed_root: str, relative: str = ""):
        """`allowed_root`: raiz permitida, absoluta e normalizada; `relative`: fonte dentro dela."""
        if not _POSIX_SUPPORTED:
            raise RuntimeError("leitor de origem exige POSIX com dir_fd e O_NOFOLLOW (P-04)")
        if not os.path.isabs(allowed_root) or os.path.normpath(allowed_root) != allowed_root:
            raise ValueError("raiz permitida deve ser caminho absoluto normalizado")
        parts = [p for p in relative.split("/") if p]
        if relative.startswith("/") or any(p in (".", "..") for p in parts):
            raise ValueError("fonte deve ser caminho relativo sem '.' ou '..'")
        self._components = [p for p in allowed_root.split("/") if p] + parts

    def _open_root(self) -> int:
        """Desce de '/' até a fonte por descritores, sem seguir link em nenhum componente."""
        fd = os.open("/", _DIR_FLAGS)
        try:
            for name in self._components:
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        return fd

    def walk(self) -> Iterator[Entry]:
        """Percorre a fonte em ordem determinística (nome, por diretório), sem seguir links."""
        try:
            root_fd = self._open_root()
        except OSError as exc:
            raise SourceUnavailable(sanitized(exc)) from None
        try:
            yield from self._walk_dir(root_fd, "")
        finally:
            os.close(root_fd)

    def _walk_dir(self, dir_fd: int, prefix: str) -> Iterator[Entry]:
        try:
            with os.scandir(dir_fd) as it:
                names = sorted(entry.name for entry in it)
        except OSError as exc:
            yield ErrorEntry(prefix.rstrip("/"), _error_code(exc), sanitized(exc))
            return

        for name in names:
            rel = prefix + name
            try:
                st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError as exc:
                yield ErrorEntry(rel, _error_code(exc), sanitized(exc))
                continue

            if _is_link(st):
                yield SkippedEntry(rel, "link")
            elif stat.S_ISDIR(st.st_mode):
                yield from self._enter_dir(dir_fd, name, rel, st)
            elif stat.S_ISREG(st.st_mode):
                yield FileEntry(rel, st.st_size, _modified_at(st))
            else:
                yield SkippedEntry(rel, "special")

    def _enter_dir(self, dir_fd: int, name: str, rel: str, st: os.stat_result) -> Iterator[Entry]:
        try:
            child_fd = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
        except OSError as exc:
            yield ErrorEntry(rel, _error_code(exc), sanitized(exc))
            return
        try:
            opened = os.fstat(child_fd)
            if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
                yield ErrorEntry(rel, "changed_during_scan", "pasta substituída durante a varredura")
                return
            yield from self._walk_dir(child_fd, rel + "/")
        finally:
            os.close(child_fd)

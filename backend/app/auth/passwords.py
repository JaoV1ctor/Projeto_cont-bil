"""Hash e política de senha (S0-05; D-015, D-016, D-017).

Argon2id via argon2-cffi, formato PHC. A senha é normalizada em NFC antes de contar o
tamanho e antes do hash: NFC e NFD da mesma senha são equivalentes, mas caracteres de
compatibilidade (largura total, ligaduras) continuam distintos da forma ASCII.
Nenhuma função registra log ou inclui a senha em mensagem de exceção.
"""
import unicodedata
from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 15  # R2, D-016: login só com senha
MAX_LENGTH = 128  # D-017; limita custo de entrada e atende "pelo menos 64" (D-016)


@dataclass(frozen=True)
class HashParameters:
    time_cost: int
    memory_cost_kib: int
    parallelism: int
    hash_len: int = 32
    salt_len: int = 16


# T1 (RFC 9106, segunda opção recomendada). Ajustar só por decisão registrada após medição.
PRODUCTION_PARAMETERS = HashParameters(time_cost=3, memory_cost_kib=65536, parallelism=4)
_ARGON2ID_PREFIX = "$argon2id$"


class PasswordPolicyError(ValueError):
    """Senha recusada pela política. A mensagem nunca contém a senha."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _hasher(params: HashParameters) -> PasswordHasher:
    return PasswordHasher(
        time_cost=params.time_cost,
        memory_cost=params.memory_cost_kib,
        parallelism=params.parallelism,
        hash_len=params.hash_len,
        salt_len=params.salt_len,
        type=Type.ID,
    )


def normalize_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("senha deve ser str")
    return unicodedata.normalize("NFC", password)


def _encodable(text: str) -> bool:
    # Surrogate isolado (ex.: bytes inválidos decodificados com surrogateescape) não vira UTF-8.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def validate_password_policy(password: str) -> None:
    """Política D-016: 15 a 128 caracteres após NFC, sem regra de composição, não branca."""
    normalized = normalize_password(password)
    if not _encodable(normalized):
        raise PasswordPolicyError("invalid_encoding", "senha contém caractere inválido")
    if not normalized.strip():
        raise PasswordPolicyError("blank", "senha vazia ou só com espaços")
    if len(normalized) < MIN_LENGTH:
        raise PasswordPolicyError("too_short", f"senha deve ter pelo menos {MIN_LENGTH} caracteres")
    if len(normalized) > MAX_LENGTH:
        raise PasswordPolicyError("too_long", f"senha deve ter no máximo {MAX_LENGTH} caracteres")


def hash_password(password: str, params: HashParameters = PRODUCTION_PARAMETERS) -> str:
    """Aplica a política e gera hash Argon2id PHC de uma senha nova."""
    validate_password_policy(password)
    return _hasher(params).hash(normalize_password(password))


def verify_password(stored_hash: str, password: str) -> bool:
    """True só para senha correta contra hash PHC Argon2id.

    Hash vazio, corrompido, de outra variante (Argon2i, Argon2d) ou de outro algoritmo
    retorna False, assim como senha que não seja str. Nunca lança exceção por entrada.
    Os parâmetros vêm do próprio hash; `needs_rehash` indica se devem ser atualizados.
    """
    if not isinstance(stored_hash, str) or not stored_hash.startswith(_ARGON2ID_PREFIX):
        return False
    if not isinstance(password, str):
        return False
    normalized = normalize_password(password)
    if not normalized or len(normalized) > MAX_LENGTH or not _encodable(normalized):
        return False
    try:
        return _hasher(PRODUCTION_PARAMETERS).verify(stored_hash, normalized)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str, params: HashParameters = PRODUCTION_PARAMETERS) -> bool:
    """True quando o hash não usa os parâmetros atuais (T2); hash inválido também é True.

    Usar somente depois de `verify_password` retornar True para o mesmo hash: o rehash
    exige a senha verificada. O resultado True para hash inválido não autoriza regravar.
    """
    if not isinstance(stored_hash, str):
        return True
    try:
        return _hasher(params).check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True

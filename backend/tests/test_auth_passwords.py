"""S0-05: hash e política de senha. Testes de unidade, sem banco. Senhas fictícias."""
import logging
import time
import traceback
import unicodedata

import pytest
from argon2 import PasswordHasher, Type, extract_parameters

from app.auth import passwords
from app.auth.passwords import (
    MAX_LENGTH,
    MIN_LENGTH,
    PRODUCTION_PARAMETERS,
    HashParameters,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)

# Parâmetros reduzidos só para velocidade dos testes; produção é conferida em teste próprio.
FAST = HashParameters(time_cost=1, memory_cost_kib=1024, parallelism=1)
SECRET = "senha-ficticia-de-teste-1234"  # 28 caracteres, nunca usada fora dos testes


@pytest.fixture
def fast_hash():
    return hash_password(SECRET, FAST)


# --- parâmetros de produção (conferidos separadamente dos reduzidos) ---------------------------

def test_production_parameters_are_the_approved_values():
    assert PRODUCTION_PARAMETERS == HashParameters(
        time_cost=3, memory_cost_kib=65536, parallelism=4, hash_len=32, salt_len=16
    )
    defaults = hash_password.__defaults__ + needs_rehash.__defaults__
    assert defaults == (PRODUCTION_PARAMETERS, PRODUCTION_PARAMETERS)


def test_default_hash_uses_production_parameters_in_phc_format():
    started = time.perf_counter()
    stored = hash_password(SECRET)
    elapsed = time.perf_counter() - started

    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    params = extract_parameters(stored)
    assert (params.type, params.time_cost, params.memory_cost, params.parallelism) == (
        Type.ID, 3, 65536, 4)
    assert (params.hash_len, params.salt_len) == (32, 16)
    assert verify_password(stored, SECRET)
    assert not needs_rehash(stored)
    print(f"hash com parâmetros de produção: {elapsed:.3f}s")


def test_fast_parameters_are_not_production():
    assert FAST != PRODUCTION_PARAMETERS


# --- hash e verificação --------------------------------------------------------------------------

def test_hash_is_salted_argon2id(fast_hash):
    other = hash_password(SECRET, FAST)
    assert fast_hash.startswith("$argon2id$")
    assert fast_hash != other
    assert SECRET not in fast_hash


def test_verify_accepts_correct_password(fast_hash):
    assert verify_password(fast_hash, SECRET) is True


@pytest.mark.parametrize(
    "attempt", [SECRET + "x", SECRET[:-1], SECRET.upper(), " " + SECRET, "", "x" * (MAX_LENGTH + 1)]
)
def test_verify_rejects_wrong_password(fast_hash, attempt):
    assert verify_password(fast_hash, attempt) is False


def _corruptions(stored: str) -> list[str]:
    head, digest = stored.rsplit("$", 1)
    flipped = ("A" if digest[0] != "A" else "B") + digest[1:]
    return [
        "",
        "   ",
        stored[:-10],
        f"{head}${flipped}",
        stored.replace("$argon2id$", "$argon2x$"),
        stored.replace("$v=19$", "$v=99$"),
        "$2b$12$" + "a" * 53,
        "texto-claro",
        stored + "$extra",
    ]


def test_verify_rejects_corrupted_hash_without_exception(fast_hash):
    for bad in _corruptions(fast_hash):
        assert verify_password(bad, SECRET) is False, bad


@pytest.mark.parametrize("bad", [None, 123, b"$argon2id$"])
def test_verify_rejects_non_string_hash(bad):
    assert verify_password(bad, SECRET) is False


@pytest.mark.parametrize("variant", [Type.I, Type.D])
def test_verify_rejects_valid_argon2i_and_argon2d_hashes(variant):
    other = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1, type=variant).hash(SECRET)
    assert other.startswith(f"$argon2{'i' if variant is Type.I else 'd'}$")
    assert PasswordHasher().verify(other, SECRET)  # hash válido para a própria variante
    assert verify_password(other, SECRET) is False


@pytest.mark.parametrize("bad", [None, 123, b"senha-ficticia-de-teste-1234", ["x"]])
def test_verify_returns_false_for_non_string_password(fast_hash, bad):
    assert verify_password(fast_hash, bad) is False


def test_verify_returns_false_for_unencodable_password(fast_hash):
    assert verify_password(fast_hash, SECRET + "\udcff") is False


def test_nfc_and_nfd_verify_the_same():
    nfc = unicodedata.normalize("NFC", "Ação-fictícia-teste")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert verify_password(hash_password(nfc, FAST), nfd)
    assert verify_password(hash_password(nfd, FAST), nfc)


@pytest.mark.parametrize(
    ("ascii_password", "compatibility"),
    [
        ("Admin-ficticio-2026", "\uff21\uff44\uff4d\uff49\uff4e-ficticio-2026"),  # largura total
        ("fixo-ficticio-teste", "\ufb01xo-ficticio-teste"),  # ligadura fi
        ("senha-ficticia-x2", "senha-ficticia-x\u00b2"),  # sobrescrito
        ("senha ficticia teste", "senha\u00a0ficticia\u00a0teste"),  # espaço não separável
    ],
)
def test_compatibility_characters_do_not_match_ascii(ascii_password, compatibility):
    assert unicodedata.normalize("NFKC", compatibility) == ascii_password  # NFKC uniria
    assert not verify_password(hash_password(ascii_password, FAST), compatibility)
    assert not verify_password(hash_password(compatibility, FAST), ascii_password)


# --- rehash --------------------------------------------------------------------------------------

def test_needs_rehash_for_old_parameters(fast_hash):
    assert needs_rehash(fast_hash, PRODUCTION_PARAMETERS) is True
    assert needs_rehash(fast_hash, FAST) is False


def test_needs_rehash_for_each_changed_parameter(fast_hash):
    for changed in (
        HashParameters(2, 1024, 1), HashParameters(1, 2048, 1), HashParameters(1, 1024, 2),
        HashParameters(1, 1024, 1, hash_len=64),
    ):
        assert needs_rehash(fast_hash, changed) is True, changed


def test_needs_rehash_for_invalid_hash(fast_hash):
    for bad in _corruptions(fast_hash)[:3] + [None]:
        assert needs_rehash(bad, FAST) is True


# --- política ------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "password",
    ["a" * MIN_LENGTH, "a" * MAX_LENGTH, "frase longa sem regras", "ççççççççççççççç", "1" * 20],
)
def test_policy_accepts(password):
    validate_password_policy(password)
    assert verify_password(hash_password(password, FAST), password)


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("", "blank"),
        (" " * 20, "blank"),
        ("\t\n " * 10, "blank"),
        ("\u3000" * 20, "blank"),  # espaço ideográfico: str.strip() o remove
        ("a" * (MIN_LENGTH - 1), "too_short"),
        (unicodedata.normalize("NFD", "é") * 8, "too_short"),  # 16 code points, 8 após NFC
        ("senha-ficticia-teste\udcff", "invalid_encoding"),
        ("a" * (MAX_LENGTH + 1), "too_long"),
    ],
)
def test_policy_rejects(password, code):
    with pytest.raises(PasswordPolicyError) as info:
        validate_password_policy(password)
    assert info.value.code == code
    with pytest.raises(PasswordPolicyError):
        hash_password(password, FAST)


def test_length_counted_after_nfc():
    composed = "é" * MIN_LENGTH
    decomposed = unicodedata.normalize("NFD", composed)
    assert len(decomposed) == 2 * MIN_LENGTH
    validate_password_policy(decomposed)  # 15 caracteres após NFC


@pytest.mark.parametrize("bad", [None, 123, b"senha-ficticia-de-teste"])
def test_policy_rejects_non_string(bad):
    with pytest.raises(TypeError, match="^senha deve ser str$"):
        validate_password_policy(bad)


# --- ausência da senha em logs, exceções e repr --------------------------------------------------

def test_password_never_in_policy_errors():
    for candidate in ("curta-segredo", "s" * (MAX_LENGTH + 5)):
        with pytest.raises(PasswordPolicyError) as info:
            hash_password(candidate, FAST)
        rendered = "".join(traceback.format_exception(info.value))
        assert candidate not in str(info.value)
        assert candidate not in repr(info.value)
        assert candidate not in rendered


def test_password_never_in_logs(caplog, fast_hash):
    caplog.set_level(logging.DEBUG)
    hash_password(SECRET, FAST)
    verify_password(fast_hash, SECRET)
    verify_password(fast_hash, SECRET + "errada")
    for bad in _corruptions(fast_hash):
        verify_password(bad, SECRET)
    needs_rehash(fast_hash)
    text = caplog.text + "".join(r.getMessage() for r in caplog.records)
    assert SECRET not in text


def test_password_never_in_repr(fast_hash):
    assert SECRET not in repr(PRODUCTION_PARAMETERS)
    assert SECRET not in repr(FAST)
    assert SECRET not in repr(fast_hash)
    assert SECRET not in repr(PasswordPolicyError("too_short", "x"))


def test_ligature_counts_as_one_character():
    # Sem NFKC, a ligadura conta 1 caractere: 14 ligaduras não atingem o mínimo de 15.
    with pytest.raises(PasswordPolicyError) as info:
        validate_password_policy("\ufb01" * 14)
    assert info.value.code == "too_short"


def test_module_does_not_log():
    assert "logging" not in passwords.__dict__

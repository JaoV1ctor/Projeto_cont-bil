"""Restrições de users, associations e user_associations (migração 0003). Dados fictícios."""
import unicodedata
import uuid

import pytest
from psycopg import errors

# Valor sintético com aparência de hash; o banco não valida o formato (D-011).
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNpbnRldGljbw$" + "aGFzaHNpbnRldGljb2RldGVzdGVoYXNoc2ludGV0aWNv"


def _user(conn, login="operador.exemplo", role="operator", password_hash=HASH, created_by=None):
    return conn.execute(
        "INSERT INTO users (name, login, password_hash, role, created_by) "
        "VALUES ('Usuário Exemplo', %s, %s, %s, %s) RETURNING id",
        (login, password_hash, role, created_by),
    ).fetchone()[0]


def _association(conn, name="Associação Exemplo Aurora", cnpj=None, created_by=None):
    return conn.execute(
        "INSERT INTO associations (name, cnpj, created_by) VALUES (%s, %s, %s) RETURNING id",
        (name, cnpj, created_by),
    ).fetchone()[0]


def _grant(conn, user_id, association_id, created_by=None):
    return conn.execute(
        "INSERT INTO user_associations (user_id, association_id, created_by) "
        "VALUES (%s, %s, %s) RETURNING id",
        (user_id, association_id, created_by),
    ).fetchone()[0]


# --- users ---------------------------------------------------------------------------------------

def test_user_defaults(conn):
    user = _user(conn)
    row = conn.execute("SELECT active, role FROM users WHERE id = %s", (user,)).fetchone()
    assert row == (True, "operator")


@pytest.mark.parametrize("role", ["administrator", "operator", "viewer"])
def test_valid_roles_accepted(conn, role):
    _user(conn, role=role)


@pytest.mark.parametrize("role", ["admin", "Administrador", "consulta", "", "ADMINISTRATOR"])
def test_invalid_role_rejected(conn, role):
    with pytest.raises(errors.CheckViolation):
        _user(conn, role=role)


def test_role_required(conn):
    with pytest.raises(errors.NotNullViolation):
        _user(conn, role=None)


@pytest.mark.parametrize(
    ("first", "second"),
    [("operador.exemplo", "operador.exemplo"), ("operador.exemplo", "OPERADOR.EXEMPLO"),
     ("Operador.Exemplo", "oPERADOR.eXEMPLO"), ("joao_i", "JOAO_I"), ("Z-9", "z-9")],
)
def test_duplicate_login_rejected_ignoring_case(conn, first, second):
    _user(conn, login=first)
    with pytest.raises(errors.UniqueViolation):
        _user(conn, login=second)


@pytest.mark.parametrize(
    "login", ["a", "operador.exemplo", "Joao_Silva-2", "A" * 64, "0", ".-_"]
)
def test_ascii_identifier_login_accepted(conn, login):
    _user(conn, login=login)


@pytest.mark.parametrize(
    "login",
    [
        unicodedata.normalize("NFC", "joão.exemplo"),
        unicodedata.normalize("NFD", "joão.exemplo"),
        "e\u0301",            # NFD de 'é'
        "\u0131",             # i sem ponto (turco)
        "\u0130",             # I com ponto (turco)
        "\uff41dmin",         # 'a' de largura total
        "\u0430dmin",         # 'а' cirílico
        "\u212a",             # sinal Kelvin, minúsculo vira 'k'
        "ﬁ",                  # ligadura
        "a\u200bb",           # espaço de largura zero
        "a\u00a0b",           # espaço não separável
    ],
)
def test_unicode_login_rejected(conn, login):
    with pytest.raises(errors.CheckViolation, match="users_login_ascii"):
        _user(conn, login=login)


def test_login_rules_do_not_depend_on_lc_ctype(conn):
    """Restrição e índice fixam COLLATE "C"; o resultado não muda com o LC_CTYPE do banco."""
    check = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'users_login_ascii'"
    ).fetchone()[0]
    index = conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'users_login_unique'"
    ).fetchone()[0]
    assert 'COLLATE "C"' in check
    assert 'lower((login COLLATE "C"))' in index


@pytest.mark.parametrize(
    "login",
    ["", " ", "com espaco", " inicio", "fim ", "a" * 65, "a\n", "a\tb", "a@b", "a/b", "a+b"],
)
def test_invalid_login_rejected(conn, login):
    with pytest.raises(errors.CheckViolation):
        _user(conn, login=login)


@pytest.mark.parametrize("password_hash", ["", " ", "   ", "\t", "\n", " \t\r\n "])
def test_blank_password_hash_rejected(conn, password_hash):
    with pytest.raises(errors.CheckViolation):
        _user(conn, password_hash=password_hash)


@pytest.mark.parametrize("password_hash", [HASH, "$2b$12$" + "a" * 53, "valor-opaco"])
def test_password_hash_format_not_validated_by_database(conn, password_hash):
    # Limite documentado: o banco não reconhece hash real; geração e verificação ficam no login.
    _user(conn, password_hash=password_hash)


def test_password_hash_required(conn):
    with pytest.raises(errors.NotNullViolation):
        _user(conn, password_hash=None)


def test_no_plaintext_password_column(conn):
    columns = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
    )}
    assert "password_hash" in columns
    assert not {c for c in columns if "password" in c} - {"password_hash"}


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_user_name_rejected(conn, name):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO users (name, login, password_hash, role) VALUES (%s, 'x', %s, 'viewer')",
            (name, HASH),
        )


def test_user_created_by_must_exist(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        _user(conn, created_by=uuid.uuid4())


def test_user_referenced_as_creator_cannot_be_deleted(conn):
    admin = _user(conn, login="admin.exemplo", role="administrator")
    _user(conn, created_by=admin)
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute("DELETE FROM users WHERE id = %s", (admin,))


# --- associations --------------------------------------------------------------------------------

def test_association_defaults(conn):
    assoc = _association(conn)
    row = conn.execute(
        "SELECT status, cnpj, trade_name FROM associations WHERE id = %s", (assoc,)
    ).fetchone()
    assert row == ("active", None, None)


@pytest.mark.parametrize("cnpj", ["00000000000000", "12ABC34501DE35"])
def test_normalized_cnpj_accepted(conn, cnpj):
    _association(conn, cnpj=cnpj)


@pytest.mark.parametrize(
    "cnpj",
    ["00.000.000/0000-00", "0000000000000", "000000000000000", "12abc34501de35",
     "12ABC34501DEAB", "", " 00000000000000"],
)
def test_invalid_cnpj_format_rejected(conn, cnpj):
    with pytest.raises(errors.CheckViolation):
        _association(conn, cnpj=cnpj)


def test_duplicate_cnpj_allowed_until_inconsistency_review(conn):
    _association(conn, name="Associação Exemplo Aurora", cnpj="12ABC34501DE35")
    _association(conn, name="Instituto Exemplo Ipê", cnpj="12ABC34501DE35")
    count = conn.execute(
        "SELECT count(*) FROM associations WHERE cnpj = '12ABC34501DE35'"
    ).fetchone()[0]
    assert count == 2


def test_no_unique_index_on_cnpj(conn):
    unique_on_cnpj = conn.execute(
        "SELECT count(*) FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (i.indkey) "
        "WHERE t.relname = 'associations' AND a.attname = 'cnpj' AND i.indisunique"
    ).fetchone()[0]
    assert unique_on_cnpj == 0


def test_associations_without_cnpj_and_same_name_allowed(conn):
    _association(conn)
    _association(conn)
    assert conn.execute("SELECT count(*) FROM associations").fetchone()[0] == 2


@pytest.mark.parametrize("status", ["", "ativa", "deleted"])
def test_invalid_association_status_rejected(conn, status):
    with pytest.raises(errors.CheckViolation):
        conn.execute("INSERT INTO associations (name, status) VALUES ('A', %s)", (status,))


@pytest.mark.parametrize(("name", "trade_name"), [(" ", None), ("A", ""), ("A", "  ")])
def test_blank_association_names_rejected(conn, name, trade_name):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO associations (name, trade_name) VALUES (%s, %s)", (name, trade_name)
        )


def test_association_created_by_must_exist(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        _association(conn, created_by=uuid.uuid4())


# --- user_associations ---------------------------------------------------------------------------

def test_grant_access(conn):
    admin = _user(conn, login="admin.exemplo", role="administrator")
    user = _user(conn)
    assoc = _association(conn)
    _grant(conn, user, assoc, created_by=admin)
    assert conn.execute("SELECT count(*) FROM user_associations").fetchone()[0] == 1


def test_duplicate_pair_rejected(conn):
    user, assoc = _user(conn), _association(conn)
    _grant(conn, user, assoc)
    with pytest.raises(errors.UniqueViolation):
        _grant(conn, user, assoc)


def test_same_user_many_associations_and_vice_versa(conn):
    u1, u2 = _user(conn, login="u1"), _user(conn, login="u2")
    a1, a2 = _association(conn), _association(conn)
    for u in (u1, u2):
        for a in (a1, a2):
            _grant(conn, u, a)
    assert conn.execute("SELECT count(*) FROM user_associations").fetchone()[0] == 4


@pytest.mark.parametrize("missing", ["user", "association", "created_by"])
def test_grant_with_invalid_reference_rejected(conn, missing):
    user, assoc = _user(conn), _association(conn)
    args = {"user": user, "association": assoc, "created_by": None}
    args[missing] = uuid.uuid4()
    with pytest.raises(errors.ForeignKeyViolation):
        _grant(conn, args["user"], args["association"], args["created_by"])


@pytest.mark.parametrize("column", ["user_id", "association_id"])
def test_grant_requires_both_sides(conn, column):
    user, assoc = _user(conn), _association(conn)
    values = {"user_id": user, "association_id": assoc, column: None}
    with pytest.raises(errors.NotNullViolation):
        conn.execute(
            "INSERT INTO user_associations (user_id, association_id) VALUES (%s, %s)",
            (values["user_id"], values["association_id"]),
        )


@pytest.mark.parametrize("table", ["users", "associations"])
def test_referenced_rows_cannot_be_deleted(conn, table):
    user, assoc = _user(conn), _association(conn)
    _grant(conn, user, assoc)
    target = user if table == "users" else assoc
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(f"DELETE FROM {table} WHERE id = %s", (target,))


def test_no_cascade_foreign_keys(conn):
    rules = conn.execute(
        "SELECT rc.delete_rule, rc.update_rule FROM information_schema.referential_constraints rc "
        "JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name "
        "WHERE tc.table_name IN ('users', 'associations', 'user_associations')"
    ).fetchall()
    assert len(rules) == 5
    assert {r[0] for r in rules} == {"RESTRICT"}
    assert "CASCADE" not in {r[1] for r in rules}


def test_unreferenced_rows_can_be_deleted(conn):
    user, assoc = _user(conn), _association(conn)
    conn.execute("DELETE FROM users WHERE id = %s", (user,))
    conn.execute("DELETE FROM associations WHERE id = %s", (assoc,))

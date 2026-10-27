"""Registro central das chaves de advisory lock do PostgreSQL (pg_advisory_*).

Toda chave usada pela aplicação é declarada aqui, com valor único, para evitar que dois
fluxos compartilhem a mesma chave por acidente. Valores cabem em bigint com sinal.
Prefixo 0x434F4E54 ('CONT') + número sequencial do fluxo.
"""

# S0-06: serializa o bootstrap do primeiro administrador (T9).
FIRST_ADMIN_BOOTSTRAP = 0x434F4E54_00000001

ALL_KEYS = {
    "FIRST_ADMIN_BOOTSTRAP": FIRST_ADMIN_BOOTSTRAP,
}

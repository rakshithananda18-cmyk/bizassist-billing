"""Credential bootstrap preserves raw identities and excludes public API roles."""
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from database import security


class Result:
    def __init__(self, value=None, row=None):
        self.value, self.row = value, row

    def scalar(self):
        return self.value

    def first(self):
        return self.row

    def one(self):
        return self.row


class IdentitySession:
    """Only the raw numeric username resolves; treating it as a phone fails."""
    def __init__(self, owner_login=None):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.info = {}
        self.owner_login = owner_login
        self.owner = SimpleNamespace(id=41)
        self.calls = []

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "bizassist_owner_identifier" in sql:
            return Result(value=41 if params == {"u": "9876543210"} else None)
        if "bizassist_auth_subject" in sql:
            expected = {"u": "9876543210"}
            if ":o" in sql:
                expected["o"] = self.owner_login
            return Result(row=(41, 41, "hash", "enterprise") if params == expected else None)
        assert "set_config" in sql
        return Result()

    def get(self, model, key):
        assert self.info["business_id"] == 41 and key == 41
        return self.owner

    def query(self, *args):
        pytest.fail("PostgreSQL bootstrap must never fall back to an unscoped ORM query")


@pytest.mark.parametrize("lookup", [security.find_owner_by_identifier, security.find_user_by_identifier])
def test_postgres_lookup_preserves_numeric_username(lookup):
    db = IdentitySession()
    assert lookup(db, " 9876543210 ") is db.owner


@pytest.mark.parametrize("owner_login", [None, "919876543210"])
def test_postgres_login_preserves_raw_owner_and_staff_identifiers(monkeypatch, owner_login):
    import services.auth
    monkeypatch.setattr(services.auth, "verify_password", lambda supplied, stored: supplied == "CorrectPass1" and stored == "hash")
    db = IdentitySession(owner_login)
    owner_input = f" {owner_login} " if owner_login else None
    assert security.authenticate_identity(db, " 9876543210 ", "CorrectPass1", owner_input) is db.owner


@pytest.mark.parametrize("login,owner_login", [("", None), ("user", " ")])
def test_empty_staff_owner_does_not_turn_into_unscoped_login(login, owner_login):
    db = IdentitySession()
    assert security.authenticate_identity(db, login, "CorrectPass1", owner_login) is None
    assert db.calls == []


class InstallationConnection:
    def __init__(self, public_roles):
        self.dialect = postgresql.dialect()
        self.public_roles = set(public_roles)
        self.commands = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "current_user,rolsuper" in sql:
            return Result(row=("schema_operator", False, True, True))
        if "rolsuper,rolbypassrls" in sql:
            return Result(row=(False, False))
        assert "SELECT 1 FROM pg_roles" in sql
        return Result(value=1 if params["role"] in self.public_roles else None)

    def exec_driver_sql(self, command):
        self.commands.append(command.strip())


@pytest.mark.parametrize("public_roles", [[], ["authenticated"], ["anon", "authenticated"]])
def test_install_revokes_inherited_public_api_grants_before_private_grants(monkeypatch, public_roles):
    import sqlalchemy
    monkeypatch.setattr(sqlalchemy, "inspect", lambda connection: SimpleNamespace(get_table_names=lambda: []))
    monkeypatch.delenv("BIZASSIST_TRADE_DB_ROLE", raising=False)
    monkeypatch.delenv("BIZASSIST_ADMIN_DB_ROLE", raising=False)
    connection = InstallationConnection(public_roles)
    security.install_security(connection, "backend_runtime")
    commands = connection.commands
    functions = [command.removeprefix("ALTER FUNCTION ").split(" OWNER TO ")[0]
                 for command in commands if command.startswith("ALTER FUNCTION ")]
    assert "bizassist_auth_subject(text,text)" in functions
    assert "bizassist_google_owner(text,text)" in functions
    assert "bizassist_owner_identifier(text)" in functions
    for signature in functions:
        public_revoke = commands.index(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        operator_grant = commands.index(f'GRANT EXECUTE ON FUNCTION {signature} TO "schema_operator"')
        assert public_revoke < operator_grant
        for role in ("anon", "authenticated"):
            revoke = f'REVOKE ALL ON FUNCTION {signature} FROM "{role}"'
            if role in public_roles:
                assert commands.index(revoke) < operator_grant
            else:
                assert revoke not in commands
        if not signature.startswith("bizassist_trade_"):
            assert operator_grant < commands.index(f'GRANT EXECUTE ON FUNCTION {signature} TO "backend_runtime"')


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_api_role_cannot_be_regranted_private_credentials(role):
    connection = InstallationConnection([role])
    with pytest.raises(ValueError, match="private backend role"):
        security.install_security(connection, role)
    assert connection.commands == []

#!/usr/bin/env python3
"""Idempotently provision least-privilege PostgreSQL roles for production.

This command is intentionally separate from application startup. Existing
objects are never re-owned unless the operator explicitly opts in after a
verified backup.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Iterable

import psycopg
from psycopg import sql

from app.utils.secret_files import read_secret_file


ROLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
ROLE_PROVISION_LOCK_ID = 327_216_175_129_948_031
RELATION_KINDS = ("r", "p", "S", "v", "m", "f")
RELATION_ALTER_TYPES = {
    "r": "TABLE",
    "p": "TABLE",
    "S": "SEQUENCE",
    "v": "VIEW",
    "m": "MATERIALIZED VIEW",
    "f": "FOREIGN TABLE",
}


class RoleProvisionError(RuntimeError):
    """The requested role state is unsafe or incompatible."""


@dataclass(frozen=True)
class RoleNames:
    owner: str = "gankaigc_owner"
    migrator: str = "gankaigc_migrator"
    app: str = "gankaigc_app"
    backup: str = "gankaigc_backup"

    def validate(self) -> None:
        values = (self.owner, self.migrator, self.app, self.backup)
        if len(set(values)) != len(values):
            raise RoleProvisionError("PostgreSQL production role names must be unique")
        for role in values:
            if not ROLE_PATTERN.fullmatch(role):
                raise RoleProvisionError(f"Invalid PostgreSQL role name: {role!r}")


@dataclass(frozen=True)
class RolePasswords:
    migrator: str
    app: str
    backup: str

    def validate(self) -> None:
        for label, value in (
            ("migrator", self.migrator),
            ("app", self.app),
            ("backup", self.backup),
        ):
            if len(value) < 16:
                raise RoleProvisionError(
                    f"PostgreSQL {label} role password must be at least 16 characters"
                )


def _normalize_psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _role_attributes(cursor: psycopg.Cursor, role: str) -> tuple[bool, ...] | None:
    cursor.execute(
        """
        SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
               rolreplication, rolbypassrls
          FROM pg_roles
         WHERE rolname = %s
        """,
        (role,),
    )
    return cursor.fetchone()


def _ensure_role(
    cursor: psycopg.Cursor,
    role: str,
    *,
    can_login: bool,
    password: str | None = None,
) -> None:
    attributes = _role_attributes(cursor, role)
    if attributes is None:
        cursor.execute(
            sql.SQL("CREATE ROLE {} WITH {} INHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS").format(
                sql.Identifier(role),
                sql.SQL("LOGIN") if can_login else sql.SQL("NOLOGIN"),
            )
        )
        attributes = _role_attributes(cursor, role)

    assert attributes is not None
    actual_login, *elevated = attributes
    if actual_login != can_login:
        expected = "LOGIN" if can_login else "NOLOGIN"
        raise RoleProvisionError(
            f"Existing role {role!r} does not match expected {expected}; refusing to alter it"
        )
    if any(elevated):
        raise RoleProvisionError(
            f"Existing role {role!r} has elevated cluster attributes; refusing to downgrade it automatically"
        )

    role_sql = sql.Identifier(role)
    if can_login:
        assert password is not None
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} WITH LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(role_sql, sql.Literal(password))
        )
    else:
        cursor.execute(
            sql.SQL(
                "ALTER ROLE {} WITH NOLOGIN INHERIT NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(role_sql)
        )


def _role_memberships(cursor: psycopg.Cursor, role: str) -> set[str]:
    cursor.execute(
        """
        SELECT parent.rolname
          FROM pg_auth_members AS membership
          JOIN pg_roles AS member ON member.oid = membership.member
          JOIN pg_roles AS parent ON parent.oid = membership.roleid
         WHERE member.rolname = %s
        """,
        (role,),
    )
    return {row[0] for row in cursor.fetchall()}


def _validate_role_memberships(cursor: psycopg.Cursor, roles: RoleNames) -> None:
    expected = {
        roles.owner: set(),
        roles.migrator: {roles.owner},
        roles.app: set(),
        roles.backup: set(),
    }
    for role, allowed in expected.items():
        unexpected = _role_memberships(cursor, role) - allowed
        if unexpected:
            raise RoleProvisionError(
                f"Role {role!r} has unexpected memberships: {', '.join(sorted(unexpected))}"
            )


def _foreign_public_relations(
    cursor: psycopg.Cursor,
    owner_role: str,
) -> list[tuple[str, str, str, str]]:
    cursor.execute(
        """
        SELECT namespace.nspname, class.relname, class.relkind, owner.rolname
          FROM pg_class AS class
          JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
          JOIN pg_roles AS owner ON owner.oid = class.relowner
         WHERE namespace.nspname = 'public'
           AND class.relkind = ANY(%s)
           AND owner.rolname <> %s
           AND NOT EXISTS (
               SELECT 1
                 FROM pg_depend AS dependency
                WHERE dependency.classid = 'pg_class'::regclass
                  AND dependency.objid = class.oid
                  AND dependency.deptype = 'e'
           )
         ORDER BY class.relname
        """,
        (list(RELATION_KINDS), owner_role),
    )
    return list(cursor.fetchall())


def _foreign_public_routines(
    cursor: psycopg.Cursor,
    owner_role: str,
) -> list[tuple[str, str, str, str, str]]:
    cursor.execute(
        """
        SELECT namespace.nspname,
               procedure.proname,
               pg_get_function_identity_arguments(procedure.oid),
               procedure.prokind,
               owner.rolname
          FROM pg_proc AS procedure
          JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
          JOIN pg_roles AS owner ON owner.oid = procedure.proowner
         WHERE namespace.nspname = 'public'
           AND owner.rolname <> %s
           AND NOT EXISTS (
               SELECT 1
                 FROM pg_depend AS dependency
                WHERE dependency.classid = 'pg_proc'::regclass
                  AND dependency.objid = procedure.oid
                  AND dependency.deptype = 'e'
           )
         ORDER BY procedure.proname
        """,
        (owner_role,),
    )
    return list(cursor.fetchall())


def _reassign_public_objects(
    cursor: psycopg.Cursor,
    roles: RoleNames,
    *,
    allow_reassign: bool,
) -> None:
    relations = _foreign_public_relations(cursor, roles.owner)
    routines = _foreign_public_routines(cursor, roles.owner)
    if (relations or routines) and not allow_reassign:
        examples = [f"{schema}.{name} (owner={owner})" for schema, name, _, owner in relations[:5]]
        examples.extend(
            f"{schema}.{name}({arguments}) (owner={owner})"
            for schema, name, arguments, _, owner in routines[:5]
        )
        raise RoleProvisionError(
            "Existing public-schema objects require an explicit owner transition. "
            "Take and verify a backup, audit the object list, then rerun with "
            "POSTGRES_REASSIGN_EXISTING_OBJECTS=true. Examples: "
            + ", ".join(examples[:8])
        )

    for schema, name, relation_kind, _ in relations:
        cursor.execute(
            sql.SQL("ALTER {} {}.{} OWNER TO {}").format(
                sql.SQL(RELATION_ALTER_TYPES[relation_kind]),
                sql.Identifier(schema),
                sql.Identifier(name),
                sql.Identifier(roles.owner),
            )
        )

    for schema, name, arguments, procedure_kind, _ in routines:
        routine_type = "PROCEDURE" if procedure_kind == "p" else "FUNCTION"
        cursor.execute(
            sql.SQL("ALTER {} {}.{}({}) OWNER TO {}").format(
                sql.SQL(routine_type),
                sql.Identifier(schema),
                sql.Identifier(name),
                sql.SQL(arguments),
                sql.Identifier(roles.owner),
            )
        )


def _execute_for_roles(
    cursor: psycopg.Cursor,
    template: str,
    grantors: Iterable[str],
    *recipients: str,
) -> None:
    recipient_sql = sql.SQL(", ").join(map(sql.Identifier, recipients))
    for grantor in grantors:
        cursor.execute(
            sql.SQL(template).format(
                grantor=sql.Identifier(grantor),
                recipients=recipient_sql,
            )
        )


def _reconcile_privileges(
    cursor: psycopg.Cursor,
    database_name: str,
    roles: RoleNames,
) -> None:
    owner = sql.Identifier(roles.owner)
    migrator = sql.Identifier(roles.migrator)
    app = sql.Identifier(roles.app)
    backup = sql.Identifier(roles.backup)
    database = sql.Identifier(database_name)

    cursor.execute(sql.SQL("GRANT {} TO {}").format(owner, migrator))
    _validate_role_memberships(cursor, roles)

    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}, {}, {}").format(
        database, owner, migrator, app, backup
    ))
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    cursor.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(app, backup))

    # Revoke broad grants from known workload roles before applying the exact contract.
    cursor.execute(sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}, {}").format(app, backup))
    cursor.execute(sql.SQL("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {}, {}").format(app, backup))
    cursor.execute(sql.SQL(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
    ).format(app))
    cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(backup))
    cursor.execute(sql.SQL(
        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}"
    ).format(app))
    cursor.execute(sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(backup))

    grantors = (roles.owner, roles.migrator)
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM {recipients}",
        grantors,
        roles.app,
        roles.backup,
    )
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {recipients}",
        grantors,
        roles.app,
    )
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "GRANT SELECT ON TABLES TO {recipients}",
        grantors,
        roles.backup,
    )
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON SEQUENCES FROM {recipients}",
        grantors,
        roles.app,
        roles.backup,
    )
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {recipients}",
        grantors,
        roles.app,
    )
    _execute_for_roles(
        cursor,
        "ALTER DEFAULT PRIVILEGES FOR ROLE {grantor} IN SCHEMA public "
        "GRANT SELECT ON SEQUENCES TO {recipients}",
        grantors,
        roles.backup,
    )


def provision_roles(
    bootstrap_database_url: str,
    roles: RoleNames,
    passwords: RolePasswords,
    *,
    allow_reassign: bool = False,
) -> str:
    roles.validate()
    passwords.validate()
    with psycopg.connect(_normalize_psycopg_url(bootstrap_database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), rolsuper FROM pg_roles WHERE rolname = current_user"
            )
            database_name, is_superuser = cursor.fetchone()
            if not is_superuser:
                raise RoleProvisionError(
                    "Bootstrap connection must be a PostgreSQL superuser for one-shot role provisioning"
                )

            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ROLE_PROVISION_LOCK_ID,))
            _ensure_role(cursor, roles.owner, can_login=False)
            _ensure_role(
                cursor,
                roles.migrator,
                can_login=True,
                password=passwords.migrator,
            )
            _ensure_role(cursor, roles.app, can_login=True, password=passwords.app)
            _ensure_role(cursor, roles.backup, can_login=True, password=passwords.backup)
            _reassign_public_objects(
                cursor,
                roles,
                allow_reassign=allow_reassign,
            )
            _reconcile_privileges(cursor, database_name, roles)
        connection.commit()
    return database_name


def _required_secret(env_name: str) -> str:
    path = os.environ.get(env_name, "").strip()
    if not path:
        raise RoleProvisionError(f"{env_name} is required")
    return read_secret_file(env_name, path)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RoleProvisionError(f"{name} must be true or false")


def main() -> None:
    roles = RoleNames(
        owner=os.environ.get("POSTGRES_OWNER_ROLE", "gankaigc_owner"),
        migrator=os.environ.get("POSTGRES_MIGRATOR_ROLE", "gankaigc_migrator"),
        app=os.environ.get("POSTGRES_APP_ROLE", "gankaigc_app"),
        backup=os.environ.get("POSTGRES_BACKUP_ROLE", "gankaigc_backup"),
    )
    passwords = RolePasswords(
        migrator=_required_secret("POSTGRES_MIGRATOR_PASSWORD_FILE"),
        app=_required_secret("POSTGRES_APP_PASSWORD_FILE"),
        backup=_required_secret("POSTGRES_BACKUP_PASSWORD_FILE"),
    )
    database_name = provision_roles(
        _required_secret("DATABASE_URL_FILE"),
        roles,
        passwords,
        allow_reassign=_env_bool("POSTGRES_REASSIGN_EXISTING_OBJECTS"),
    )
    print(
        "PostgreSQL least-privilege roles reconciled for "
        f"database={database_name} owner={roles.owner} migrator={roles.migrator} "
        f"app={roles.app} backup={roles.backup}"
    )


if __name__ == "__main__":
    main()

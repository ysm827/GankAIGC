# Database Guidelines

> Executable PostgreSQL production contracts for GankAIGC.

---

## Scenario: Docker/VPS schema authority and least-privilege roles

### 1. Scope / Trigger

- Trigger: any change to `docker-compose*.yml`, `app/database.py`,
  `app/schema.py`, `migrations/`, database Secrets, backup credentials, or
  application/worker database permissions.
- PostgreSQL is the only supported database. SQLAlchemy owns runtime data
  access; Alembic is the only production DDL authority.

### 2. Signatures

- Schema commands: `python schema_migrate.py upgrade` and
  `python schema_migrate.py verify`.
- Role command: `python provision_db_roles.py`; host wrapper:
  `scripts/postgres-provision-roles.sh`.
- Required production file inputs:
  - runtime: `DATABASE_URL_FILE`;
  - provisioner: `POSTGRES_MIGRATOR_PASSWORD_FILE`,
    `POSTGRES_APP_PASSWORD_FILE`, `POSTGRES_BACKUP_PASSWORD_FILE`.
- Role names: `POSTGRES_OWNER_ROLE` (`NOLOGIN`),
  `POSTGRES_MIGRATOR_ROLE`, `POSTGRES_APP_ROLE`, and
  `POSTGRES_BACKUP_ROLE`.
- `DATABASE_SESSION_ROLE` is set only on the migrator and must name the
  provisioned owner role.

### 3. Contracts

- Production order is `postgres -> explicit role provision -> migrate -> role
  reconciliation -> app/worker/backup`.
- `app` and `worker` call `prepare_database()` and verify the single Alembic
  head; they never run production `create_all` or handwritten DDL.
- Role privileges:
  - bootstrap superuser: role provisioning only;
  - owner: owns `public` objects and cannot log in;
  - migrator: member of owner and the only login allowed to run Alembic DDL;
  - app/worker: `SELECT/INSERT/UPDATE/DELETE` on tables and
    `USAGE/SELECT/UPDATE` on sequences; no persistent DDL;
  - backup: `SELECT` on tables/sequences only and must run `pg_dump`.
- Default privileges are reconciled for owner and migrator so new migration
  objects immediately inherit app and backup grants.
- Existing public objects are never re-owned unless
  `POSTGRES_REASSIGN_EXISTING_OBJECTS=true` is explicitly set after a verified
  backup and object review.
- File Secrets must be regular UTF-8 files, at most 64 KiB, with no group/world
  permission (`0600` is the deployment standard). File values override env and
  `.env`, are passed directly into `Settings`, and are not exported to
  `os.environ` where child browser/tool processes could inherit them.
- File-backed keys are immutable from the admin UI. Rotation means updating the
  host file and recreating only affected services.

### 4. Validation & Error Matrix

- Multiple Alembic heads -> `SchemaStateError`; runtime must not start.
- Revision differs from head -> `SchemaStateError`; run the one-shot migrator.
- Unknown physical drift -> reject stamp/start; inspect a schema dump.
- Existing public objects with reassignment disabled -> rollback provisioning
  and report an object sample without changing ownership.
- Existing named role has elevated attributes, wrong login mode, or unexpected
  memberships -> fail closed; never silently downgrade/reuse it.
- Secret file is missing, empty, non-regular, oversized, undecodable, or
  group/world-readable -> fail before `Settings()` or role provisioning.
- App attempts `CREATE TABLE public.*` -> PostgreSQL
  `InsufficientPrivilege`.
- Backup attempts `INSERT/UPDATE/DELETE` -> PostgreSQL
  `InsufficientPrivilege`.

### 5. Good/Base/Bad Cases

- Good: signed production Compose mounts only service-required files,
  provisioner creates roles, migrator assumes owner, and app/backup access a
  newest-migration table with their exact grants.
- Base compatibility: local/base Compose may derive one owner URL from
  `.env.docker`; this is not the Internet-facing production contract.
- Bad: app uses the bootstrap superuser; app/worker run `create_all`; backup
  receives the application env file; a legacy database is blindly stamped;
  file Secrets are copied into process environment or command arguments.

### 6. Tests Required

- `test_postgres_roles.py`: fail-closed owner transition, app DML/DDL boundary,
  backup read-only boundary, fresh migrator upgrade, and access to
  migration-created tables.
- `test_secret_files.py`: permission/import-order gates, file precedence,
  child-process environment isolation, and admin-update rejection.
- `test_docker_compose.py`: production removes shared `env_file`; each service
  has only its required secret names and database role.
- Runtime smoke: `/ready`, non-root app/worker, actual `0600` mounts, role
  provisioning, migration, backup dump/checksum, and backup-role `pg_dump`.

### 7. Wrong vs Correct

#### Wrong

```yaml
app:
  env_file: .env.docker
  environment:
    DATABASE_URL: postgresql://superuser:${POSTGRES_PASSWORD}@postgres/app
```

#### Correct

```yaml
app:
  env_file: !reset []
  environment:
    DATABASE_URL_FILE: /run/secrets/database_url
  secrets:
    - source: app_database_url
      target: database_url
```

"""Migrations, per module, on whatever engine the application bound.

A module that owns tables says where its migrations are:

    db:
      migrations: migrations          # a folder with versions/ inside
      metadata: nest_glossary.models:Base   # for autogenerate

Each module migrates on its own, with its own version table
(``glossary_alembic_version``), in the order the plan starts modules, so a
module's migrations can rely on its dependencies' tables. Nest supplies what
Alembic's env.py would: a module has only its revision files.

When the application starts, ``NEST_MIGRATE`` decides:

* ``auto`` (the default in development) upgrades every module;
* ``check`` (the default in production) refuses to start while any module has
  migrations not applied, so a cluster runs ``nest db upgrade`` as a job first;
* ``off`` does neither.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.autogenerate.api import RevisionContext
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

log = logging.getLogger("nest.db")

TEMPLATE = Path(__file__).parent / "templates" / "script.py.mako"


class MigrationError(Exception):
    pass


def table_prefix(module: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", module.lower()).strip("_") + "_"


@dataclass
class ModuleMigrations:
    """One module's migrations: where they are and what they may touch."""

    name: str
    location: Path
    metadata: str | None
    entry: Any

    @property
    def prefix(self) -> str:
        return table_prefix(self.name)

    @property
    def version_table(self) -> str:
        return self.prefix + "alembic_version"

    def config(self) -> Config:
        cfg = Config()
        cfg.set_main_option("path_separator", "os")
        cfg.set_main_option("script_location", str(self.location))
        cfg.set_main_option("version_locations", str(self.location / "versions"))
        return cfg

    def script(self) -> ScriptDirectory:
        if not (self.location / "versions").is_dir():
            raise MigrationError(f"{self.name}: no migrations at {self.location}/versions")
        return ScriptDirectory.from_config(self.config())

    def owns(self, name: str | None) -> bool:
        return bool(name) and name.startswith(self.prefix) and name != self.version_table


def for_entry(entry: Any) -> ModuleMigrations | None:
    """A package's migrations, or None when it keeps no tables."""
    section = entry.manifest.raw.get("db")
    if not isinstance(section, dict) or not section.get("migrations"):
        return None
    return ModuleMigrations(
        name=entry.name,
        location=entry.root / str(section["migrations"]),
        metadata=section.get("metadata"),
        entry=entry,
    )


def discover(plan: Any) -> list[ModuleMigrations]:
    """Every module in the plan that declares migrations, in start order."""
    return [m for unit in plan.units if (m := for_entry(unit.entry)) is not None]


def on_forget(nest: Any, entry: Any) -> None:
    """The db interface's forget hook: a module uninstalled from the application loses its
    tables (its migrations taken down to nothing) and its version table."""
    m = for_entry(entry)
    if m is None or "nest.db" not in nest.bindings.by_interface:
        return
    db = nest.bindings.get("nest.db")
    if current(db, m):
        log.info("dropping %s's tables", m.name)
        downgrade(db, m, "base")
    with db.engine().begin() as conn:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {m.version_table}")


def _configure(env: EnvironmentContext, conn: Any, m: ModuleMigrations, **extra: Any) -> None:
    env.configure(
        connection=conn,
        version_table=m.version_table,
        render_as_batch=conn.dialect.name == "sqlite",  # SQLite alters tables by copying
        include_name=lambda name, type_, _parents: type_ != "table" or m.owns(name),
        compare_type=True,
        **extra,
    )


def current(db: Any, m: ModuleMigrations) -> set[str]:
    with db.engine().connect() as conn:
        context = MigrationContext.configure(conn, opts={"version_table": m.version_table})
        return set(context.get_current_heads())


def heads(m: ModuleMigrations) -> set[str]:
    return set(m.script().get_heads())


def pending(db: Any, m: ModuleMigrations) -> bool:
    return current(db, m) != heads(m)


def upgrade(db: Any, m: ModuleMigrations, target: str = "heads") -> None:
    script = m.script()

    def step(rev: Any, _context: Any) -> Any:
        return script._upgrade_revs(target, rev)

    with db.engine().begin() as conn, EnvironmentContext(m.config(), script, fn=step) as env:
        _configure(env, conn, m)
        with env.begin_transaction():
            env.run_migrations()


def downgrade(db: Any, m: ModuleMigrations, target: str) -> None:
    script = m.script()

    def step(rev: Any, _context: Any) -> Any:
        return script._downgrade_revs(target, rev)

    with db.engine().begin() as conn, EnvironmentContext(m.config(), script, fn=step) as env:
        _configure(env, conn, m)
        with env.begin_transaction():
            env.run_migrations()


def init(m: ModuleMigrations) -> None:
    """Create the module's migrations folder (versions/ and the revision template)."""
    (m.location / "versions").mkdir(parents=True, exist_ok=True)
    target = m.location / "script.py.mako"
    if not target.exists():
        shutil.copyfile(TEMPLATE, target)


def revision(db: Any, m: ModuleMigrations, message: str, *, autogenerate: bool) -> Path:
    """Write a new revision; with ``autogenerate``, from the module's models."""
    init(m)
    script = m.script()
    metadata = None
    if autogenerate:
        if not m.metadata:
            raise MigrationError(f"{m.name}: autogenerate needs db.metadata in its module.yml")
        from nest.loader import import_object

        base = import_object(m.metadata, m.entry)
        metadata = getattr(base, "metadata", base)
    context = RevisionContext(
        m.config(),
        script,
        {
            "message": message,
            "autogenerate": autogenerate,
            "sql": False,
            "head": "head",
            "splice": False,
            "branch_label": None,
            "version_path": None,
            "rev_id": None,
            "depends_on": None,
        },
    )
    if autogenerate:

        def step(rev: Any, ctx: Any) -> list[Any]:
            context.run_autogenerate(rev, ctx)
            return []

        with (
            db.engine().connect() as conn,
            EnvironmentContext(
                m.config(),
                script,
                fn=step,
                as_sql=False,
                template_args=context.template_args,
                revision_context=context,
            ) as env,
        ):
            _configure(env, conn, m, target_metadata=metadata)
            with env.begin_transaction():
                env.run_migrations()
    else:
        context.run_no_autogenerate(None, None)  # type: ignore[arg-type]
    made = [s for s in context.generate_scripts() if s is not None]
    if not made:
        raise MigrationError(f"{m.name}: no revision was written")
    return Path(made[0].path)


def policy(nest: Any) -> str:
    value = nest.environ.get("NEST_MIGRATE") or ("check" if nest.production else "auto")
    if value not in ("auto", "check", "off"):
        raise MigrationError(f"NEST_MIGRATE must be auto, check or off, not '{value}'")
    return value


def on_startup(nest: Any) -> None:
    """The db interface's startup hook: migrate, or refuse to run behind."""
    modules = discover(nest.plan)
    if not modules:
        return
    mode = policy(nest)
    if mode == "off":
        return
    db = nest.bindings.get("nest.db")
    behind = [m for m in modules if pending(db, m)]
    if not behind:
        return
    if mode == "check":
        names = ", ".join(m.name for m in behind)
        raise MigrationError(
            f"migrations are not applied for: {names}; run `nest db upgrade` first"
        )
    for m in behind:
        log.info("migrating %s", m.name)
        upgrade(db, m)

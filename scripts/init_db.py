# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""Postgres migrations 初始化脚本（幂等）

目标：
- 让 `docker compose up` 在一个全新 Postgres 上也能直接跑起来
- 不依赖外部 migrate 工具（flyway/alembic），仅按 `migrations/postgres/*.sql` 顺序执行

实现要点：
- 使用 `app_migrations` 表记录已应用的 migration（含 checksum）
- 使用 `pg_advisory_lock` 保证多容器并发启动时仅有一个实例在跑 migrations

可通过环境变量关闭：
- `SKIP_DB_MIGRATIONS=1`
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import os
import sys

import psycopg


# --- make repo root importable ---
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs.common.config import settings


MIGRATIONS_DIR = REPO_ROOT / "migrations" / "postgres"

# 固定 lock id（64-bit int）
MIGRATION_LOCK_ID = 786_531_245_117


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    if os.getenv("SKIP_DB_MIGRATIONS", "0") == "1":
        print("SKIP: db migrations")
        return

    files = sorted(p for p in MIGRATIONS_DIR.glob("V*.sql") if p.is_file())
    if not files:
        print("SKIP: no migration files found")
        return

    with psycopg.connect(settings.database_url) as conn:
        # 多容器并发启动时，确保只有一个实例在执行迁移
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_migrations (
                  filename   TEXT PRIMARY KEY,
                  checksum   TEXT NOT NULL,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            conn.commit()

            existing = {
                r[0]: r[1]
                for r in conn.execute("SELECT filename, checksum FROM app_migrations").fetchall()
            }

            applied = 0
            for f in files:
                sql_text = f.read_text(encoding="utf-8")
                checksum = _sha256(sql_text)
                prev = existing.get(f.name)
                if prev is not None:
                    if prev != checksum:
                        raise RuntimeError(
                            f"Migration checksum mismatch for {f.name}: db={prev} file={checksum}"
                        )
                    continue

                # 执行 migration
                conn.execute(sql_text)
                conn.execute(
                    "INSERT INTO app_migrations(filename, checksum) VALUES (%s, %s)",
                    (f.name, checksum),
                )
                conn.commit()
                applied += 1
                print(f"APPLIED: {f.name}")

            print(f"OK: db migrations ensured (new_applied={applied})")
        finally:
            # 释放锁（即使异常也尽量释放）
            try:
                conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
                conn.commit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

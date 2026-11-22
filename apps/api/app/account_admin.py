"""Interactive local commands for bootstrapping the unique BookThinking owner."""

import argparse
import getpass
import sqlite3
from datetime import datetime

from app.services.accounts import AccountRepository
from app.services.authentication import hash_password
from app.services.storage import ApplicationPaths, BookRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="bookthinking account")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-owner")
    bootstrap.add_argument("email", nargs="?")
    commands.add_parser("migrate-legacy-data-to-owner")
    args = parser.parse_args()

    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    accounts = AccountRepository(paths.database_path)
    if args.command == "bootstrap-owner":
        email = args.email or input("主账号邮箱： ").strip()
        password = getpass.getpass("主账号密码：")
        confirmation = getpass.getpass("再次输入密码：")
        if password != confirmation:
            parser.error("两次密码不一致")
        if not password:
            parser.error("密码不能为空")
        owner = accounts.bootstrap_owner(email=email, password_hash=hash_password(password))
        print(f"已创建主账号 {owner.email}。请执行 migrate-legacy-data-to-owner 迁移历史书籍。")
        return 0

    owner = next((user for user in accounts.list_users() if user.role == "owner"), None)
    if owner is None:
        parser.error("请先执行 bootstrap-owner")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = paths.root / f"book-learning.before-owner-migration-{timestamp}.sqlite3"
    with sqlite3.connect(paths.database_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    BookRepository(paths.database_path)
    migrated = accounts.migrate_legacy_books_to_owner(owner.id)
    print(f"已备份到 {backup_path}；已迁移 {migrated} 本历史书籍。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

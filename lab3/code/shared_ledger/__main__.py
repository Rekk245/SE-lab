"""Desktop and reproducible noninteractive demonstration entry points."""

import argparse
import json
import pathlib

from shared_ledger import database
from shared_ledger import demo


def main():
    """Run a desktop workspace or print a seeded database's demo outcome."""
    parser = argparse.ArgumentParser(description="多人共享记账系统")
    parser.add_argument(
        "--db", default="data/ledger.sqlite3", help="本地数据库路径"
    )
    parser.add_argument(
        "--demo", action="store_true", help="空数据库初始化演示数据"
    )
    parser.add_argument(
        "--headless-demo", action="store_true", help="打印演示结果，不打开窗口"
    )
    args = parser.parse_args()
    store = database.Database(pathlib.Path(args.db))
    if args.demo or args.headless_demo:
        result = demo.seed(store)
        if args.headless_demo:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
    from shared_ledger import ui  # Delay Tk initialization for headless checks.

    ui.LedgerApp(store).run()


if __name__ == "__main__":
    main()

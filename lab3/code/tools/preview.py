"""Open the known demo fixture for visual QA without entering user secrets."""

import argparse

from shared_ledger import database
from shared_ledger import demo
from shared_ledger import ui


def main():
    """Authenticate the generated demo account and display its workspace."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/preview.sqlite3")
    args = parser.parse_args()
    store = database.Database(args.db)
    demo.seed(store)
    app = ui.LedgerApp(store)
    app.username.set(demo.ACCOUNTS[0][0])
    app.password.set(demo.PASSWORD)
    app.login()
    app.run()


if __name__ == "__main__":
    main()

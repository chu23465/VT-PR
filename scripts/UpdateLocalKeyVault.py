#!/usr/bin/env python3

import argparse
import json
import sqlite3

from vinetrimmer.utils.AtomicSQL import AtomicSQL


class LocalVault:
    def __init__(self, vault_path):
        """
        Update local key vault to newer system.
        This should ONLY be run if you have the old structure with keys in a table named `keys`.
        It will move and update the structure of the items in `keys` to their respective new locations and structure.
        :param vault_path: sqlite db path
        """
        self.adb = AtomicSQL()
        self.ticket = self.adb.load(sqlite3.connect(vault_path))
        if not self.table_exists("keys"):
            return
        rows = self.adb.safe_execute(
            self.ticket,
            lambda db, cursor: cursor.execute("SELECT `service`, `title`, `content_keys` FROM `keys`")
        ).fetchall()
        for service, title, content_keys in rows:
            service = service.lower()
            content_keys = json.loads(content_keys)
            if not self.table_exists(service):
                self.create_table(service)
            for kid, key in [x.split(":") for x in content_keys]:
                print(f"Inserting: {kid} {key} {title}")
                existing_row, existing_title = self.row_exists(service, kid, key)
                if existing_row:
                    if title and not existing_title:
                        print(" -- exists, but the title doesn't, so ill merge")
                        self.adb.safe_execute(
                            self.ticket,
                            lambda db, cursor: cursor.execute(
                                f"UPDATE `{service}` SET `title`=? WHERE `kid`=? AND `key_`=?",
                                (title, kid, key)
                            )
                        )
                        continue
                    print("  -- skipping (exists already)")
                    continue
                self.adb.safe_execute(
                    self.ticket,
                    lambda db, cursor: cursor.execute(
                        f"INSERT INTO `{service}` (kid, key_, title) VALUES (?, ?, ?)",
                        (kid, key, title)
                    )
                )
        self.adb.commit(self.ticket)

    def row_exists(self, table, kid, key):
        return self.adb.safe_execute(
            self.ticket,
            lambda db, cursor: cursor.execute(
                f"SELECT count(id), title FROM `{table}` WHERE kid=? AND key_=?",
                [kid, key]
            )
        ).fetchone()

    def table_exists(self, name):
        return self.adb.safe_execute(
            self.ticket,
            lambda db, cursor: cursor.execute(
                "SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?",
                [name.lower()]
            )
        ).fetchone()[0] == 1

    def create_table(self, name):
        self.adb.safe_execute(
            self.ticket,
            lambda db, cursor: cursor.execute(
                """
                CREATE TABLE {} (
                    "id"        INTEGER NOT NULL UNIQUE,
                    "kid"       TEXT NOT NULL COLLATE NOCASE,
                    "key_"      TEXT NOT NULL COLLATE NOCASE,
                    "title"     TEXT NULL,
                    PRIMARY KEY("id" AUTOINCREMENT),
                    UNIQUE("kid", "key_")
                );
                """.format(name.lower())
            )
        )


parser = argparse.ArgumentParser()
parser.add_argument(
    "-i", "--input",
    help="vault",
    required=True)
args = parser.parse_args()

LocalVault(args.input)

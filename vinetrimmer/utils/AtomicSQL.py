"""
AtomicSQL - Race-condition and Threading safe SQL Database Interface.
"""

import os
import sqlite3
import time
from threading import Lock


class AtomicSQL:
    """
    Race-condition and Threading safe SQL Database Interface.
    """

    def __init__(self):
        self.master_lock = Lock()  # prevents race condition
        self.db = {}  # used to hold the database connections and commit changes and such
        self.cursor = {}  # used to execute queries and receive results
        self.session_lock = {}  # like master_lock, but per-session

    def load(self, connection):
        """
        Store SQL Connection object and return a reference ticket.
        :param connection: SQLite3 or pymysql Connection object.
        :returns: Session ID in which the database connection is referenced with.
        """
        self.master_lock.acquire()
        try:
            # obtain a unique cryptographically random session_id
            session_id = None
            while not session_id or session_id in self.db:
                session_id = os.urandom(16)
            self.db[session_id] = connection
            self.cursor[session_id] = self.db[session_id].cursor()
            self.session_lock[session_id] = Lock()
            return session_id
        finally:
            self.master_lock.release()

    def safe_execute(self, session_id, action):
        """
        Execute code on the Database Connection in a race-condition safe way.
        :param session_id: Database Connection's Session ID.
        :param action: Function or lambda in which to execute, it's provided `db` and `cursor` arguments.
        :returns: Whatever `action` returns.
        """
        if session_id not in self.db:
            raise ValueError(f"Session ID {session_id!r} is invalid.")
        self.master_lock.acquire()
        self.session_lock[session_id].acquire()
        try:
            failures = 0
            while True:
                try:
                    action(
                        db=self.db[session_id],
                        cursor=self.cursor[session_id]
                    )
                    break
                except sqlite3.OperationalError:
                    failures += 1
                    delay = 3 * failures
                    print(f"AtomicSQL.safe_execute failed, retrying in {delay} seconds...")
                    time.sleep(delay)
                if failures == 10:
                    raise ValueError("AtomicSQL.safe_execute failed too many time's. Aborting.")
            return self.cursor[session_id]
        finally:
            self.session_lock[session_id].release()
            self.master_lock.release()

    def commit(self, session_id):
        """
        Commit changes to the Database Connection immediately.
        This isn't necessary to be run every time you make changes, just ensure it's run
        at least before termination.
        :param session_id: Database Connection's Session ID.
        :returns: True if it committed.
        """
        self.safe_execute(
            session_id,
            lambda db, cursor: db.commit()
        )
        return True  # todo ; actually check if db.commit worked

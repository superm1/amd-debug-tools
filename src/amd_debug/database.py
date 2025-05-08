#!/usr/bin/python3
# SPDX-License-Identifier: MIT

from datetime import datetime
import sqlite3
import os

from amd_debug.common import read_file

SCHEMA_VERSION = 1


def migrate(cur, user_version) -> None:
    """Migrate sqlite database schema"""
    cur.execute("PRAGMA user_version")
    val = cur.fetchone()[0]
    # Schema 1
    # - add priority column
    if val == 0:
        cur.execute("ALTER TABLE debug ADD COLUMN priority INTEGER")
    # Update schema if necessary
    if val != user_version:
        cur.execute(f"PRAGMA user_version = {user_version}")


class SleepDatabase:
    """Database class to store sleep cycle data"""

    def __init__(self, dbf=None) -> None:
        self.db = None
        self.last_suspend = None
        self.cycle_data_cnt = 0
        self.debug_cnt = 0

        if not dbf:
            # if we were packaged we would have a directory in /var/lib
            path = os.path.join("/", "var", "lib", "amd-s2idle")
            if not os.path.exists(path):
                path = os.path.join("/", "var", "local", "lib", "amd-s2idle")
            os.makedirs(path, exist_ok=True)

            dbf = os.path.join(path, "data.db")
        new = not os.path.exists(dbf)
        self.db = sqlite3.connect(dbf)
        cur = self.db.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS prereq_data ("
            "t0 INTEGER,"
            "id INTEGER,"
            "message TEXT,"
            "symbol TEXT,"
            "PRIMARY KEY(t0, id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS debug ("
            "t0 INTEGER,"
            "id INTEGER,"
            "message TEXT,"
            "priority INTEGER,"
            "PRIMARY KEY(t0, id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS cycle ("
            "t0 INTEGER PRIMARY KEY,"
            "t1 INTEGER,"
            "requested INTEGER,"
            "gpio TEXT,"
            "wake_irq TEXT,"
            "kernel REAL,"
            "hw REAL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS cycle_data ("
            "t0 INTEGER,"
            "id INTEGER,"
            "message TEXT,"
            "symbol TEXT,"
            "PRIMARY KEY(t0, id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS battery ("
            "t0 INTEGER PRIMARY KEY,"
            "name TEXT,"
            "b0 INTEGER,"
            "b1 INTEGER,"
            "full INTEGER,"
            "unit TEXT)"
        )
        self.prereq_data_cnt = 0

        if new:
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        else:
            migrate(cur, SCHEMA_VERSION)

    def __del__(self) -> None:
        if self.db:
            self.db.close()

    def start_cycle(self, timestamp):
        """Start a new sleep cycle"""
        self.last_suspend = timestamp

        # increment the counters so that systemd hooks work
        cur = self.db.cursor()
        cur.execute(
            "SELECT MAX(id) FROM cycle_data WHERE t0=?",
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")),),
        )
        val = cur.fetchone()[0]
        if val is not None:
            self.cycle_data_cnt = val + 1
        else:
            self.cycle_data_cnt = 0
        cur.execute(
            "SELECT MAX(id) FROM debug WHERE t0=?",
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")),),
        )
        val = cur.fetchone()[0]
        if val is not None:
            self.debug_cnt = val + 1
        else:
            self.debug_cnt = 0

    def sync(self) -> None:
        """Sync the database to disk"""
        self.db.commit()

    def record_debug(self, message, level=6) -> None:
        """Helper function to record a message to debug database"""
        assert self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "INSERT into debug (t0, id, message, priority) VALUES (?, ?, ?, ?)",
            (
                int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                self.debug_cnt,
                message,
                level,
            ),
        )
        self.debug_cnt += 1

    def record_debug_file(self, fn):
        """Helper function to record the entire contents of a file to debug database"""
        try:
            contents = read_file(fn)
            self.record_debug(contents)
        except PermissionError:
            self.record_debug(f"Unable to capture {fn}")

    def record_battery_energy(self, name, energy, full, unit):
        """Helper function to record battery energy"""
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM battery WHERE t0=?",
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")),),
        )
        if cur.fetchone():
            cur.execute(
                "UPDATE battery SET b1=? WHERE t0=?",
                (energy, int(self.last_suspend.strftime("%Y%m%d%H%M%S"))),
            )
        else:
            cur.execute(
                """
                INSERT into battery (t0, name, b0, b1, full, unit) 
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                    name,
                    energy,
                    None,
                    full,
                    unit,
                ),
            )

    def record_cycle_data(self, message, symbol) -> None:
        """Helper function to record a message to cycle_data database"""
        assert self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT into cycle_data (t0, id, message, symbol)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                    self.cycle_data_cnt,
                    message,
                    symbol,
                )
            ),
        )
        self.cycle_data_cnt += 1

    def record_cycle(
        self,
        requested_duration=0,
        active_gpios="",
        wakeup_irqs="",
        kernel_duration=0,
        hw_sleep_duration=0,
    ) -> None:
        """Helper function to record a sleep cycle into the cycle database"""
        assert self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            """
            REPLACE INTO cycle (t0, t1, requested, gpio, wake_irq, kernel, hw)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                int(datetime.now().strftime("%Y%m%d%H%M%S")),
                requested_duration,
                str(active_gpios) if active_gpios else "",
                str(wakeup_irqs),
                kernel_duration,
                hw_sleep_duration,
            ),
        )

    def record_prereq(self, message, symbol) -> None:
        """Helper function to record a message to prereq_data database"""
        assert self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT into prereq_data (t0, id, message, symbol)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                    self.prereq_data_cnt,
                    message,
                    symbol,
                )
            ),
        )
        self.prereq_data_cnt += 1

    def report_prereq(self, t0) -> list:
        """Helper function to report the prereq_data database"""
        if t0 is None:
            return []
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM prereq_data WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_debug(self, t0) -> str:
        """Helper function to report the debug database"""
        if t0 is None:
            return ""
        cur = self.db.cursor()
        cur.execute(
            "SELECT message, priority FROM debug WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_cycle(self, t0=None) -> list:
        """Helper function to report a cycle from database"""
        if t0 is None:
            assert self.last_suspend
            t0 = self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM cycle WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_cycle_data(self, t0=None) -> str:
        """Helper function to report a table matching a timestamp from cycle_data database"""
        if t0 is None:
            t0 = self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT message, symbol FROM cycle_data WHERE t0=? ORDER BY symbol",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        data = ""
        for row in cur.fetchall():
            data += f"{row[1]} {row[0]}\n"
        return data

    def report_battery(self, t0=None) -> list:
        """Helper function to report a line from battery database"""
        if t0 is None:
            t0 = self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM battery WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def get_last_prereq_ts(self) -> int:
        """Helper function to report the last line from prereq database"""
        cur = self.db.cursor()
        cur.execute("SELECT * FROM prereq_data ORDER BY t0 DESC LIMIT 1")
        result = cur.fetchone()
        return result[0] if result else None

    def get_last_cycle(self) -> list:
        """Helper function to report the last line from battery database"""
        cur = self.db.cursor()
        cur.execute("SELECT t0 FROM cycle ORDER BY t0 DESC LIMIT 1")
        return cur.fetchone()

    def report_summary_dataframe(self, since, until) -> object:
        """Helper function to report a dataframe from the database"""
        import pandas as pd  # pylint: disable=import-outside-toplevel

        pd.set_option("display.precision", 2)
        return pd.read_sql_query(
            sql="SELECT cycle.t0, cycle.t1, hw, requested, gpio, wake_irq, b0, b1, full FROM cycle LEFT JOIN battery ON cycle.t0 = battery.t0 WHERE cycle.t0 >= ? and cycle.t0 <= ?",
            con=self.db,
            params=(
                int(since.strftime("%Y%m%d%H%M%S")),
                int(until.strftime("%Y%m%d%H%M%S")),
            ),
        )

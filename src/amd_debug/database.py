# SPDX-License-Identifier: MIT

from datetime import datetime
import json
import sqlite3
import os

from amd_debug.common import read_file

SCHEMA_VERSION = 5


TRIAGE_TABLE = (
    "CREATE TABLE IF NOT EXISTS triage ("
    "id INTEGER PRIMARY KEY, "
    "started INTEGER, "
    "updated INTEGER, "
    "stage TEXT, "
    "status TEXT, "
    "boot_id TEXT, "
    "outcome TEXT, "
    "fmt TEXT)"
)
TRIAGE_EVENT_TABLE = (
    "CREATE TABLE IF NOT EXISTS triage_event ("
    "session INTEGER, "
    "id INTEGER, "
    "ts INTEGER, "
    "kind TEXT, "
    "message TEXT, "
    "answer TEXT, "
    "PRIMARY KEY(session, id))"
)


def migrate(cur, user_version) -> None:
    """Migrate sqlite database schema"""
    cur.execute("PRAGMA user_version")
    val = cur.fetchone()[0]
    # Schema 1
    # - add priority column
    if val == 0:
        cur.execute("ALTER TABLE debug ADD COLUMN priority INTEGER")
    # Schema 2
    # - add power_rails table
    if val == 1:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS power_rails ("
            "t0 INTEGER, "
            "label TEXT, "
            "e0 REAL, "
            "e1 REAL, "
            "scale REAL, "
            "PRIMARY KEY(t0, label))"
        )
    # Schema 3
    # - add s0ix table
    if val == 2:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS s0ix ("
            "t0 INTEGER PRIMARY KEY, "
            "slp_s0 INTEGER, "
            "substates TEXT)"
        )
    # Schema 4
    # - add pci_power table
    if val == 3:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS pci_power ("
            "t0 INTEGER, "
            "slot TEXT, "
            "driver TEXT, "
            "runtime_status TEXT, "
            "d3cold_allowed TEXT, "
            "PRIMARY KEY(t0, slot))"
        )
    # Schema 5
    # - add triage and triage_event tables
    if val == 4:
        cur.execute(TRIAGE_TABLE)
        cur.execute(TRIAGE_EVENT_TABLE)
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
            path = os.path.join("/", "var", "lib", "amd-s2idle")
            os.makedirs(path, mode=0o700, exist_ok=True)
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
        cur.execute(
            "CREATE TABLE IF NOT EXISTS power_rails ("
            "t0 INTEGER,"
            "label TEXT,"
            "e0 REAL,"
            "e1 REAL,"
            "scale REAL,"
            "PRIMARY KEY(t0, label))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS s0ix ("
            "t0 INTEGER PRIMARY KEY, "
            "slp_s0 INTEGER, "
            "substates TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS pci_power ("
            "t0 INTEGER, "
            "slot TEXT, "
            "driver TEXT, "
            "runtime_status TEXT, "
            "d3cold_allowed TEXT, "
            "PRIMARY KEY(t0, slot))"
        )
        cur.execute(TRIAGE_TABLE)
        cur.execute(TRIAGE_EVENT_TABLE)
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
        assert self.db
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
        assert self.db
        self.db.commit()

    def record_debug(self, message, level=6) -> None:
        """Helper function to record a message to debug database"""
        assert self.last_suspend
        assert self.db
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
        assert self.db
        assert self.last_suspend
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

    def record_power_rail_energy(self, label, energy, scale):
        """Helper function to record power rail energy

        Args:
            label: Rail label (e.g., "CPU_VDDCR_PH1_IN_POWER_1")
            energy: Raw energy accumulator value
            scale: Scale factor to convert raw to Joules

        First call (prep): INSERT with e0
        Second call (post): UPDATE with e1
        """
        assert self.db
        assert self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT e0 FROM power_rails WHERE t0=? AND label=?",
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")), label),
        )
        result = cur.fetchone()
        if result is None:
            # First call (prep): INSERT with e0
            cur.execute(
                """
                INSERT INTO power_rails (t0, label, e0, e1, scale)
                VALUES (?, ?, ?, NULL, ?)
                """,
                (
                    int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                    label,
                    energy,
                    scale,
                ),
            )
        else:
            # Second call (post): UPDATE with e1
            cur.execute(
                "UPDATE power_rails SET e1=? WHERE t0=? AND label=?",
                (energy, int(self.last_suspend.strftime("%Y%m%d%H%M%S")), label),
            )

    def record_cycle_data(self, message, symbol) -> None:
        """Helper function to record a message to cycle_data database"""
        assert self.last_suspend
        assert self.db
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
        assert self.db
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

    def record_s0ix_baseline(self, slp_s0, substates) -> None:
        """Store the S0ix residency counters read before a suspend

        The pre-suspend counters are persisted so that the post-resume
        capture can still calculate the delta when it runs in a different
        process, e.g. from the systemd sleep hook.
        """
        assert self.last_suspend
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            """
            REPLACE INTO s0ix (t0, slp_s0, substates)
            VALUES (?, ?, ?)
            """,
            (
                int(self.last_suspend.strftime("%Y%m%d%H%M%S")),
                slp_s0,
                json.dumps(substates),
            ),
        )

    def get_s0ix_baseline(self):
        """Fetch the S0ix residency counters stored before a suspend

        Returns a tuple of (slp_s0, substates) or None when no baseline
        was recorded for the cycle.
        """
        assert self.last_suspend
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            "SELECT slp_s0, substates FROM s0ix WHERE t0 = ?",
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return (row[0], json.loads(row[1]))

    def record_pci_power_state(self, states) -> None:
        """Store the PCI device power states for the cycle

        The states are persisted so that the post-resume comparison can
        still run when it happens in a different process, e.g. from the
        systemd sleep hook.
        """
        assert self.last_suspend
        assert self.db
        cur = self.db.cursor()
        t0 = int(self.last_suspend.strftime("%Y%m%d%H%M%S"))
        cur.executemany(
            """
            REPLACE INTO pci_power (t0, slot, driver, runtime_status, d3cold_allowed)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (t0, slot, state[0], state[1], state[2])
                for slot, state in states.items()
            ],
        )

    def get_pci_power_state(self):
        """Fetch the PCI device power states stored before the suspend"""
        assert self.last_suspend
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            """
            SELECT slot, driver, runtime_status, d3cold_allowed
            FROM pci_power WHERE t0 = ?
            """,
            (int(self.last_suspend.strftime("%Y%m%d%H%M%S")),),
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    def record_prereq(self, message, symbol) -> None:
        """Helper function to record a message to prereq_data database"""
        assert self.last_suspend
        assert self.db
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
        assert self.db
        if t0 is None:
            return []
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM prereq_data WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_debug(self, t0) -> list:
        """Helper function to report the debug database"""
        assert self.db
        if t0 is None:
            return []
        cur = self.db.cursor()
        cur.execute(
            "SELECT message, priority FROM debug WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_cycle(self, t0=None) -> list:
        """Helper function to report a cycle from database"""
        assert self.db
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
        assert self.db
        if t0 is None:
            assert self.last_suspend
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
        assert self.db
        if t0 is None:
            assert self.last_suspend
            t0 = self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM battery WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def report_power_rails(self, t0=None) -> list:
        """Helper function to report power rails for a given timestamp

        Returns:
            List of tuples: (t0, label, e0, e1, scale)
        """
        assert self.db
        if t0 is None:
            assert self.last_suspend
            t0 = self.last_suspend
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM power_rails WHERE t0=?",
            (int(t0.strftime("%Y%m%d%H%M%S")),),
        )
        return cur.fetchall()

    def triage_start(self, stage, boot_id="", fmt="") -> int:
        """Start a new triage session and return its id"""
        assert self.db
        now = int(datetime.now().strftime("%Y%m%d%H%M%S"))
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO triage (started, updated, stage, status, boot_id, outcome, fmt)
            VALUES (?, ?, ?, 'ready', ?, NULL, ?)
            """,
            (now, now, stage, boot_id, fmt),
        )
        self.db.commit()
        return cur.lastrowid

    def triage_update(self, session, stage=None, status=None, boot_id=None) -> None:
        """Update the progress indicator of a triage session

        The change is committed immediately so that it survives a hang.
        """
        assert self.db
        cur = self.db.cursor()
        now = int(datetime.now().strftime("%Y%m%d%H%M%S"))
        for column, value in (
            ("stage", stage),
            ("status", status),
            ("boot_id", boot_id),
        ):
            if value is not None:
                cur.execute(
                    f"UPDATE triage SET {column}=? WHERE id=?", (value, session)
                )
        cur.execute("UPDATE triage SET updated=? WHERE id=?", (now, session))
        self.db.commit()

    def triage_complete(self, session, outcome) -> None:
        """Mark a triage session as finished"""
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            "UPDATE triage SET status='done', outcome=? WHERE id=?",
            (outcome, session),
        )
        self.db.commit()

    def triage_get(self, session=None):
        """Fetch a triage session (default: the unfinished one)

        Returns a dict with id, started, updated, stage, status, boot_id,
        outcome and fmt or None when there is no matching session.
        """
        assert self.db
        cur = self.db.cursor()
        columns = "id, started, updated, stage, status, boot_id, outcome, fmt"
        if session is None:
            cur.execute(
                f"SELECT {columns} FROM triage WHERE status != 'done' "
                "ORDER BY id DESC LIMIT 1"
            )
        else:
            cur.execute(f"SELECT {columns} FROM triage WHERE id=?", (session,))
        row = cur.fetchone()
        if row is None:
            return None
        keys = [
            "id",
            "started",
            "updated",
            "stage",
            "status",
            "boot_id",
            "outcome",
            "fmt",
        ]
        return dict(zip(keys, row))

    def triage_abandon_all(self) -> None:
        """Close any unfinished triage sessions"""
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            "UPDATE triage SET status='done', outcome='abandoned' WHERE status != 'done'"
        )
        self.db.commit()

    def triage_log(self, session, kind, message, answer=None) -> None:
        """Record an event (info, question, action, result) for a session"""
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            "SELECT COALESCE(MAX(id) + 1, 0) FROM triage_event WHERE session=?",
            (session,),
        )
        idx = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO triage_event (session, id, ts, kind, message, answer)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session,
                idx,
                int(datetime.now().strftime("%Y%m%d%H%M%S")),
                kind,
                message,
                answer,
            ),
        )
        self.db.commit()

    def triage_events(self, session) -> list:
        """Fetch the events of a session as (ts, kind, message, answer)"""
        assert self.db
        cur = self.db.cursor()
        cur.execute(
            "SELECT ts, kind, message, answer FROM triage_event "
            "WHERE session=? ORDER BY id",
            (session,),
        )
        return cur.fetchall()

    def get_last_prereq_ts(self) -> int:
        """Helper function to report the last line from prereq database"""
        assert self.db
        cur = self.db.cursor()
        cur.execute("SELECT * FROM prereq_data ORDER BY t0 DESC LIMIT 1")
        result = cur.fetchone()
        return result[0] if result else 0

    def get_last_cycle(self) -> list:
        """Helper function to report the last line from battery database"""
        assert self.db
        cur = self.db.cursor()
        cur.execute("SELECT t0 FROM cycle ORDER BY t0 DESC LIMIT 1")
        return cur.fetchone()

    def report_summary_dataframe(self, since, until) -> object:
        """Helper function to report a dataframe from the database"""
        assert self.db

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

# SPDX-License-Identifier: MIT

import os
import re
import math
import stat
import pathlib
import html
from datetime import datetime, timedelta
import numpy as np
from tabulate import tabulate
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
import pandas as pd

from amd_debug.database import SleepDatabase
from amd_debug.common import (
    AmdTool,
    Colors,
    version,
    clear_temporary_message,
    get_group_color,
    get_log_priority,
    print_color,
    print_temporary_message,
)

def confirm_overwrite_report(fname) -> bool:
    """If fname exists, prompt to overwrite. Returns True if writing can proceed."""
    if not fname or not os.path.lexists(fname):
        return True
    response = (
        input(f"Report file already exists: {fname}. Overwrite? (y/n): ")
        .strip()
        .lower()
    )
    if response != "y":
        return False
    try:
        os.unlink(fname)
    except OSError as e:
        print(f"Failed to remove existing report file {fname}: {e}")
        return False
    return True


from amd_debug.failures import (
    SpuriousWakeup,
    LowHardwareSleepResidency,
)
from amd_debug.wake import WakeIRQ, WakeGPIO


def remove_duplicates(x):
    """Remove duplicates from a string"""
    temp = re.findall(r"\d+", x)
    res = list(map(int, temp))
    return list(set(res))


def format_gpio_as_str(x):
    """Format GPIO as a nicer format"""
    ret = []
    for y in remove_duplicates(x):
        ret.append(str(WakeGPIO(y)))
    return ", ".join(ret)


def format_irq_as_str(x):
    """Format IRQ as a nicer format"""
    ret = []
    for y in remove_duplicates(x):
        ret.append(str(WakeIRQ(y)))
    return ", ".join(ret)


def format_as_human(x):
    """Format as a human readable date"""
    return datetime.strptime(str(x), "%Y%m%d%H%M%S")


def format_as_seconds(x):
    """Format as seconds"""
    return format_as_human(x).timestamp()


def format_watts(val):
    """Format watts as a nicer format"""
    return f"{val:.02f}W"


def format_percent(val):
    """Format percent as a nicer format"""
    return f"{val:.02f}%"


def format_timedelta(val):
    """Format seconds as a nicer format"""
    if math.isnan(val):
        val = 0
    return str(timedelta(seconds=val))


def parse_hw_sleep(hw):
    """Parse the hardware sleep value, throwing out garbage values"""
    if hw > 1:
        return 0
    return hw * 100


class SleepReport(AmdTool):
    """Sleep report class"""

    def __init__(self, since, until, fname, fmt, tool_debug, report_debug):
        log_prefix = "s2idle" if tool_debug else None
        super().__init__(log_prefix)

        self.db = SleepDatabase()
        self.fname = fname
        self.since = since
        self.until = until
        self.debug = report_debug
        self.format = fmt
        self.failures = []
        if since and until:
            self.df = self.db.report_summary_dataframe(self.since, self.until)
            self.pre_process_dataframe()
        else:
            self.df = pd.DataFrame(
                columns=[
                    "t0",
                    "t1",
                    "requested",
                    "hw",
                    "b0",
                    "b1",
                    "full",
                    "wake_irq",
                    "gpio",
                ]
            )
        self.battery_svg = None
        self.hwsleep_svg = None

    def analyze_duration(self, index, t0, t1, requested, hw):
        """Analyze the duration of the cycle"""
        duration = t1 - t0
        if duration.total_seconds() >= 60 and hw < 90:
            failure = LowHardwareSleepResidency(duration.seconds, hw)
            problem = failure.get_description()
            data = str(failure)
            if self.format == "html":
                self.failures.append(
                    {"cycle_num": index, "problem": problem, "data": data}
                )
            else:
                self.failures.append([index, problem, data])

        if not math.isnan(requested):
            min_suspend_duration = timedelta(seconds=requested * 0.9)
            expected_wake_time = t0 + min_suspend_duration

            if t1 < expected_wake_time:
                failure = SpuriousWakeup(requested, duration)
                problem = failure.get_description()
                data = str(failure)
                if self.format == "html":
                    self.failures.append(
                        {"cycle_num": index, "problem": problem, "data": data}
                    )
                else:
                    self.failures.append([index, problem, data])

    def calculate_power_rail_totals(self, t0, duration):
        """Calculate total power from all power rails for a given cycle

        Args:
            t0: Timestamp of cycle start
            duration: Duration of cycle in seconds

        Returns:
            Total power in watts, or None if no valid data
        """
        power_rails = self.db.report_power_rails(t0)
        if not power_rails or duration == 0:
            return None

        total_power = 0.0
        has_valid_data = False
        for rail_data in power_rails:
            _t0, label, e0, e1, scale = rail_data
            if e0 is None or e1 is None:
                continue

            # pac194x/5x reports raw*scale in mW-seconds (millijoules)
            energy_j = (e1 - e0) * scale / 1000.0
            power_w = energy_j / duration
            total_power += power_w
            has_valid_data = True

        return total_power if has_valid_data else None

    def pre_process_dataframe(self):
        """Pre-process the pandas dataframe"""
        self.df["Duration"] = self.df["t1"].apply(format_as_seconds) - self.df[
            "t0"
        ].apply(format_as_seconds)
        self.df["Duration"] = self.df["Duration"].replace(0, np.nan)
        self.df["Hardware Sleep"] = (self.df["hw"] / self.df["Duration"]).apply(
            parse_hw_sleep
        )

        # Calculate power rail totals for each cycle
        power_rail_totals = []
        for t0, duration in zip(self.df["t0"], self.df["Duration"]):
            cycle_t0 = format_as_human(t0)
            total_power = self.calculate_power_rail_totals(cycle_t0, duration)
            power_rail_totals.append(total_power)

        # Use power rail data if available, otherwise fall back to battery
        has_power_rails = any(p is not None for p in power_rail_totals)
        if has_power_rails:
            self.df["Average Power"] = power_rail_totals
        elif not self.df["b0"].isnull().all():
            self.df["Battery Start"] = self.df["b0"] / self.df["full"] * 100
            self.df["Battery Delta"] = (
                (self.df["b1"] - self.df["b0"]) / self.df["full"] * 100
            )
            self.df["Average Power"] = (
                (self.df["b1"] - self.df["b0"]) / 1000000 / (self.df["Duration"] / 3600)
            )

        # Wake sources
        self.df["Wake Pin"] = self.df["gpio"].apply(format_gpio_as_str)
        self.df["Wake Interrupt"] = self.df["wake_irq"].apply(format_irq_as_str)
        del self.df["gpio"]
        del self.df["wake_irq"]

        # Look for spurious wakeups and low hardware residency
        [
            self.analyze_duration(index, t0, t1, requested, hw)
            for index, t0, t1, requested, hw in zip(
                self.df.index,
                self.df["t0"].apply(format_as_human),
                self.df["t1"].apply(format_as_human),
                self.df["requested"],
                self.df["Hardware Sleep"],
            )
        ]
        del self.df["requested"]

        # Only keep data needed
        self.df.rename(columns={"t0": "Start Time"}, inplace=True)
        self.df["Start Time"] = self.df["Start Time"].apply(format_as_human)
        del self.df["b1"]
        del self.df["b0"]
        del self.df["full"]
        del self.df["t1"]
        del self.df["hw"]

    def post_process_dataframe(self):
        """Display pandas dataframe in a more user friendly format"""
        self.df["Duration"] = self.df["Duration"].apply(format_timedelta)
        self.df["Hardware Sleep"] = self.df["Hardware Sleep"].apply(format_percent)
        if "Battery Start" in self.df.columns:
            self.df["Battery Start"] = self.df["Battery Start"].apply(format_percent)
            self.df["Battery Delta"] = self.df["Battery Delta"].apply(format_percent)
        if "Average Power" in self.df.columns:
            self.df["Average Power"] = self.df["Average Power"].apply(format_watts)

    def convert_table_dataframe(self, content):
        """Convert a table like dataframe to an HTML table"""
        header = False
        rows = []
        for line in content.split("\n"):
            # only include header once
            if "int|active" in line:
                if header:
                    continue
                header = True
            line = line.strip("│")
            line = line.replace("├─", "└─")
            if "|" in line:
                # first column missing '|'
                rows.append(line.replace("\t", "|"))
        columns = [row.split("|") for row in rows]
        df = pd.DataFrame(columns[1:], columns=columns[0])
        return df.to_html(index=False, justify="center", col_space=30)

    def get_prereq_data(self):
        """Get the prereq data"""
        prereq = []
        prereq_debug = []
        tables = [
            "int|active",
            "ACPI name",
            "PCI Slot",
            "DMI|value",
        ]
        ts = self.db.get_last_prereq_ts()
        if not ts:
            return [], "", []
        t0 = datetime.strptime(str(ts), "%Y%m%d%H%M%S")
        for row in self.db.report_prereq(t0):
            prereq.append({"symbol": row[3], "text": row[2]})
        if self.debug:
            for row in self.db.report_debug(t0):
                content = row[0]
                if self.format == "html" and [
                    table for table in tables if table in content
                ]:
                    content = Markup(self.convert_table_dataframe(content))
                elif self.format == "html":
                    content = Markup(html.escape(content))
                prereq_debug.append({"data": content.strip()})
        return prereq, t0, prereq_debug

    def format_power_rail_data(self, t0, t1_seconds):
        """Format power rail data for display

        Args:
            t0: Timestamp of cycle start
            t1_seconds: Duration of cycle in seconds

        Returns:
            Formatted string with power rail consumption data
        """
        power_rails = self.db.report_power_rails(t0)
        if not power_rails:
            return ""

        # Build rail list first to check if we have any valid data
        rail_lines = []
        total_power = 0.0
        for rail_data in power_rails:
            _t0, label, e0, e1, scale = rail_data
            if e0 is None or e1 is None or t1_seconds == 0:
                continue

            # pac194x/5x reports raw*scale in mW-seconds (millijoules), so
            energy_j = (e1 - e0) * scale / 1000.0
            power_w = energy_j / t1_seconds
            total_power += power_w

            rail_lines.append(f"{label}: {power_w:.3f}W")

        # Only show header if we have actual rail data
        if not rail_lines:
            return ""

        output = "\n━━━ Power Rail Consumption ━━━\n"
        output += "\n".join(rail_lines) + "\n"
        output += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        output += f"Total: {total_power:.3f}W\n"

        return output

    def get_cycle_data(self):
        """Get the cycle data"""
        cycles = []
        debug = []
        tables = ["Wakeup Source"]
        num = 0
        for cycle in self.df["Start Time"]:
            if self.format == "html":
                data = ""
                for line in self.db.report_cycle_data(cycle).split("\n"):
                    data += f"<p>{html.escape(line)}</p>"
                cycles.append({"cycle_num": num, "data": Markup(data)})
            else:
                cycles.append([num, self.db.report_cycle_data(cycle)])
            if self.debug:
                messages = []
                priorities = []
                for row in self.db.report_debug(cycle):
                    content = row[0]
                    if self.format == "html" and [
                        table for table in tables if table in content
                    ]:
                        content = Markup(self.convert_table_dataframe(content))
                    elif self.format == "html":
                        content = Markup(html.escape(content))
                    messages.append(content)
                    priorities.append(get_log_priority(row[1]))

                cycle_row = self.df[self.df["Start Time"] == cycle]
                if not cycle_row.empty:
                    duration = cycle_row["Duration"].iloc[0]
                    power_rail_summary = self.format_power_rail_data(cycle, duration)
                    if power_rail_summary:
                        if self.format == "html":
                            power_rail_summary = Markup(
                                "".join(
                                    f"<p>{html.escape(line)}</p>"
                                    for line in power_rail_summary.split("\n")
                                )
                            )
                        messages.append(power_rail_summary)
                        priorities.append(get_log_priority(6))

                debug.append(
                    {"cycle_num": num, "messages": messages, "priorities": priorities}
                )
            num += 1
        return cycles, debug

    def build_template(self, inc_prereq) -> str:
        """Build the template for the report using jinja2"""
        import amd_debug  # pylint: disable=import-outside-toplevel

        # Load the template
        p = os.path.dirname(amd_debug.__file__)
        environment = Environment(
            loader=FileSystemLoader(os.path.join(p, "templates")), autoescape=True
        )
        template = environment.get_template(self.format)

        # Load the prereq data
        prereq = None
        prereq_debug = None
        prereq_date = None
        if inc_prereq:
            prereq, prereq_date, prereq_debug = self.get_prereq_data()

        # Load the cycle and/or debug data
        if not self.df.empty:
            cycles, debug = self.get_cycle_data()

            self.post_process_dataframe()
            failures = None
            if self.format == "md":
                summary = self.df.to_markdown(floatfmt=".02f")
                cycle_data = tabulate(
                    cycles, headers=["Cycle", "data"], tablefmt="pipe"
                )
                if self.failures:
                    failures = tabulate(
                        self.failures,
                        headers=["Cycle", "Problem", "Explanation"],
                        tablefmt="pipe",
                    )
            elif self.format == "txt":
                summary = tabulate(
                    self.df, headers=self.df.columns, tablefmt="fancy_grid"
                )
                cycle_data = tabulate(
                    cycles, headers=["Cycle", "data"], tablefmt="fancy_grid"
                )
                if self.failures:
                    failures = tabulate(
                        self.failures,
                        headers=["Cycle", "Problem", "Explanation"],
                        tablefmt="fancy_grid",
                    )
            elif self.format == "html":
                summary = ""
                row = 0
                # we will use javascript to highlight the high values
                for line in self.df.to_html(
                    table_id="summary", render_links=True
                ).split("\n"):
                    if "<tr>" in line:
                        line = line.replace(
                            "<tr>",
                            f'<tr class="row-low" onclick="pick_summary_cycle({row})">',
                        )
                        row = row + 1
                    summary += line
                cycle_data = cycles
                failures = self.failures
            # only show one cycle in stdout output even if we found more
            else:
                df = self.df.tail(1)
                summary = tabulate(
                    df, headers=self.df.columns, tablefmt="fancy_grid", showindex=False
                )
                if cycles[-1][0] == df.index.start:
                    cycle_data = cycles[-1][-1]
                else:
                    cycle_data = None
                if self.failures and self.failures[-1][0] == df.index.start:
                    failures = self.failures[-1][-1]
        else:
            cycles = []
            debug = []
            cycle_data = []
            summary = "No sleep cycles found in the database."
            failures = None

        # let it burn
        context = {
            "prereq": prereq,
            "prereq_date": prereq_date,
            "cycle_data": cycle_data,
            "summary": summary,
            "prereq_debug_data": prereq_debug,
            "debug_data": debug,
            "date": datetime.now(),
            "version": version(),
            "battery_svg": self.battery_svg,
            "hwsleep_svg": self.hwsleep_svg,
            "failures": failures,
        }
        if self.fname:
            try:
                resolved = pathlib.Path(self.fname).resolve()
            except (ValueError, OSError) as e:
                raise ValueError(f"Invalid report file path: {self.fname}") from e

            # Prevent symlink attack when running as root
            try:
                fd = os.open(
                    self.fname,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode=stat.S_IRUSR
                    | stat.S_IWUSR
                    | stat.S_IRGRP
                    | stat.S_IROTH,  # 0o644
                )
            except FileExistsError:
                raise FileExistsError(
                    f"Report file already exists: {self.fname}. "
                    "Please remove it or specify a different filename."
                ) from None

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(template.render(context))
                    if "SUDO_UID" in os.environ:
                        os.fchown(
                            fd, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
                        )
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise

            return "Report written to {f}".format(f=self.fname)
        else:
            return template.render(context)

    def build_battery_chart(self):
        """Build a battery chart using matplotlib and seaborn"""
        import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
        import seaborn as sns  # pylint: disable=import-outside-toplevel
        import io  # pylint: disable=import-outside-toplevel

        if "Average Power" not in self.df.columns or "Battery Delta" not in self.df.columns:
            return

        plt.set_loglevel("warning")
        _fig, ax1 = plt.subplots()
        ax1.plot(self.df["Average Power"], color="green", label="Charge/Discharge Rate")

        ax2 = ax1.twinx()
        sns.barplot(
            x=self.df.index,
            y=self.df["Battery Delta"],
            color="grey",
            label="Battery Change",
            alpha=0.3,
        )
        max_range = int(len(self.df.index) / 10)
        if max_range:
            ax1.set_xticks(range(0, len(self.df.index), max_range))
        ax1.set_xlabel("Cycle")
        ax1.set_ylabel("Rate (Watts)")
        ax1.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax2.set_ylabel("Battery Change (%)")

        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(
            lines + lines2, labels + labels2, loc="lower left", bbox_to_anchor=(0, 1)
        )
        battery_svg = io.BytesIO()
        plt.savefig(battery_svg, format="svg")
        battery_svg.seek(0)
        self.battery_svg = battery_svg.read().decode("utf-8")

    def build_hw_sleep_chart(self):
        """Build the hardware sleep chart using matplotlib and seaborn"""
        import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
        import seaborn as sns  # pylint: disable=import-outside-toplevel
        import io  # pylint: disable=import-outside-toplevel

        plt.set_loglevel("warning")
        _fig, ax1 = plt.subplots()
        ax1.plot(
            self.df["Hardware Sleep"],
            color="red",
            label="Hardware Sleep",
        )

        ax2 = ax1.twinx()
        sns.barplot(
            x=self.df.index,
            y=self.df["Duration"] / 60,
            color="grey",
            label="Cycle Duration",
            alpha=0.3,
        )

        max_range = int(len(self.df.index) / 10)
        if max_range:
            ax1.set_xticks(range(0, len(self.df.index), max_range))
        ax1.set_xlabel("Cycle")
        ax1.set_ylabel("Percent")
        ax2.set_yscale("log")
        ax2.set_ylabel("Duration (minutes)")

        lines, labels = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(
            lines + lines2, labels + labels2, loc="lower left", bbox_to_anchor=(0, 1)
        )
        hwsleep_svg = io.BytesIO()
        plt.savefig(hwsleep_svg, format="svg")
        hwsleep_svg.seek(0)
        self.hwsleep_svg = hwsleep_svg.read().decode("utf-8")

    def run(self, inc_prereq=True):
        """Run the report"""

        characters = print_temporary_message("Building report, please wait...")

        if not self.df.empty:
            # Build charts in the page for html format
            if len(self.df.index) > 1 and self.format == "html":
                self.build_battery_chart()
                self.build_hw_sleep_chart()

        # Render the template using jinja
        msg = self.build_template(inc_prereq)
        clear_temporary_message(characters)
        for line in msg.split("\n"):
            color = Colors.OK
            text = line.strip()
            if not text:
                continue
            for group in ["🗣️", "❌", "🚦", "🦟", "🚫", "○"]:
                if line.startswith(group):
                    text = line.split(group)[-1]
                    color = get_group_color(group)
                    break
            print_color(text, color)

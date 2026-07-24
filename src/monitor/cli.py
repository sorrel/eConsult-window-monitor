"""Unified `econsult` command-line interface.

Matches the sibling tools' idiom (Click + a ColouredGroup). The daemon itself
stays standard-library-only; Click is used only for this presentation layer.

    econsult view      # coloured day-by-day opening-hours table
    econsult status    # latest observed state
    econsult findings  # full findings readout
    econsult poll      # one manual read-only poll
"""
from __future__ import annotations

import textwrap

import click

from . import analyse
from . import config
from . import opening_hours
from . import store


# Window state -> display colour, shared by the status and poll commands.
_STATE_COLOUR = {"open": "green", "closed": "red", "unknown": "yellow"}


class ColouredGroup(click.Group):
    """Click group with a coloured command listing (as in the sibling CLIs)."""

    def format_commands(self, ctx, formatter):
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd.get_short_help_str(limit=150)))
        if not commands:
            return
        col_width = max(len(name) for name, _ in commands) + 2
        help_col = 4 + col_width
        help_indent = " " * help_col
        available = max(formatter.width - help_col, 20)
        with formatter.section("Commands"):
            for name, help_text in commands:
                padding = " " * (col_width - len(name))
                name_str = click.style(name, fg="cyan")
                wrapped = textwrap.wrap(help_text, width=available)
                first = wrapped[0] if wrapped else ""
                rest = ("\n" + help_indent).join(wrapped[1:])
                full = (first + "\n" + help_indent + rest) if rest else first
                formatter.write(f"    {name_str}{padding}{full}\n")


@click.group(cls=ColouredGroup)
def cli():
    """econsult — monitor a GP eConsult clinical submission window."""


@cli.command("view")
def view_command():
    """Day-by-day opening hours, with running averages."""
    days = opening_hours.assemble_days()
    if not days:
        click.echo("No days logged yet. The monitor writes to data/observations.jsonl.")
        return

    click.echo(click.style("eConsult opening hours", fg="green", bold=True))
    click.echo()
    header = f"  {'Date':10}  {'Day':6}  {'Opened':8}  {'Closed':10}  {'Open for':10}"
    click.echo(click.style(header, fg="cyan", bold=True))
    click.echo(click.style("  " + "-" * 54, fg="bright_black"))

    for row in analyse.opening_hours_rows(days):
        day_cell = row["weekday"][:3] + ("*" if row["partial"] else "")
        if not row["blocks"]:
            line = f"  {row['date']:10}  {day_cell:6}  {'—':8}  {'—':10}  {'—':10}"
            click.echo(click.style(line, fg="bright_black"))   # no open observed
            continue
        for i, block in enumerate(row["blocks"]):
            closed, dur = analyse.block_cells(block)
            note = "" if i == 0 else "  (reopened)"
            date_cell = row["date"] if i == 0 else ""
            day_col = day_cell if i == 0 else ""
            line = f"  {date_cell:10}  {day_col:6}  {block['opened']:8}  {closed:10}  {dur:10}{note}"
            if row["partial"]:
                click.echo(click.style(line, fg="yellow"))     # today / gap — provisional
            else:
                click.echo(click.style(line, fg="green"))      # a clean, reliable day

    stats = analyse.opening_hours_stats(days)
    click.echo()
    click.echo(f"  Days logged: {stats['days_logged']}   with an open observed: "
               + click.style(str(stats['days_with_open']), fg="green"))
    n = stats["reliable_count"]  # completed days that opened; non-open and provisional days excluded
    avg = click.style(analyse.fmt_duration(stats["avg"]), fg="green", bold=True)
    if n == 1:
        click.echo(f"  Open duration: {avg}  (from 1 open day so far)")
    elif n >= 2:
        click.echo(f"  Open duration over {n} open days: average {avg}, "
                   f"shortest {analyse.fmt_duration(stats['shortest'])}, "
                   f"longest {analyse.fmt_duration(stats['longest'])}")
    if stats["open_times"]:
        click.echo(f"  Open times seen: {click.style(', '.join(stats['open_times']), fg='cyan')}")
    if stats["by_weekday"]:
        click.echo("  By weekday (average open, reliable days):")
        for weekday in analyse._WEEKDAY_ORDER:
            if weekday in stats["by_weekday"]:
                click.echo(f"     {weekday:9} "
                           f"{click.style(analyse.fmt_duration(stats['by_weekday'][weekday]), fg='green')}"
                           f"  ({stats['weekday_counts'][weekday]} day)")
    if any(row["partial"] for row in analyse.opening_hours_rows(days)):
        click.echo(click.style("  * provisional day — excluded from averages", fg="bright_black"))


@cli.command("status")
def status_command():
    """Latest observed state of the window."""
    records = store.read_all(config.LOG_PATH)
    if not records:
        click.echo("No polls logged yet.")
        return
    last = records[-1]
    colour = _STATE_COLOUR.get(last["state"], "white")
    click.echo(click.style("eConsult window", fg="green", bold=True))
    click.echo(f"  State:   {click.style(last['state'].upper(), fg=colour, bold=True)}")
    click.echo(f"  As of:   {last['ts_local']}  (route {last['route']}, http {last['http_status']})")
    click.echo(f"  Polls:   {len(records)} in today's log")


@cli.command("findings")
def findings_command():
    """Full findings readout (history + today)."""
    summaries = store.read_all(config.SUMMARY_PATH)
    records = store.read_all(config.LOG_PATH)
    click.echo(analyse.format_findings(summaries, records))


@cli.command("poll")
def poll_command():
    """Do one manual, read-only poll now."""
    from . import poll as poll_mod
    obs = poll_mod.poll_once(config.CLINICAL_PATH)
    colour = _STATE_COLOUR.get(obs["state"], "white")
    click.echo(f"{obs['ts_local']}  {click.style(obs['state'].upper(), fg=colour)}  "
               f"markers={obs['matched_markers']}")


if __name__ == "__main__":
    cli()

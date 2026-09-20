# -*- coding: utf-8 -*-

"""
GitHub Actions workflow commands.

A workflow command turns a log line into an entry in the run's Annotations panel, which
is the difference between a missing secret being noticed and it scrolling past inside a
collapsed log.
"""

import click


LEVEL_COLOURS = {
    'error': 'red',
    'warning': 'yellow',
    'notice': 'green',
}


def annotate(level: str, message: str) -> None:
    """
    Emit ``::error::`` / ``::warning::`` / ``::notice::`` so it is actually recognised.

    GitHub only parses a workflow command when it starts at the beginning of a line, and
    the build's progress output deliberately leaves the cursor mid-line ("Parsing... OK"),
    so this always opens a fresh line first. A stray blank line in a log costs nothing; an
    annotation that quietly degrades into plain text costs the reader the one line they
    needed to see.
    """
    click.secho(f"\n::{level}::{message}", fg=LEVEL_COLOURS.get(level, None))

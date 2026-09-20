# -*- coding: utf-8 -*-

"""
Manifest build script.
"""

import contextlib
import json
import typing

import click

from ci import annotate
from embeds import build_weekly_embeds, enforce_embed_limits
from formats.old import generate_old_format
from formats.webhook import send_webhooks
from loader import OUTPUT_FOLDER, load_event_lanes


class ClickReporter:
    """Progress output for a human (or a GitHub Actions log) watching the build."""

    @contextlib.contextmanager
    def step(self, label: str) -> typing.Iterator[None]:
        click.secho(f"{label}... ", nl=False)
        try:
            yield
        except BaseException:
            click.secho("FAILED", fg='red')
            raise
        else:
            click.secho("OK", fg='green')

    def info(self, message: str) -> None:
        click.secho(message)

    def warn(self, message: str) -> None:
        # A workflow command, so missing secrets reach the annotations panel rather than
        # only the expanded log.
        annotate('warning', message)


def generate_preview(event_lanes) -> dict:
    """
    Render every lane's weekly embeds to plain data.

    This is what makes the schedule reviewable without a webhook: run the build locally,
    open ``output/preview.json``, and read exactly what would have been posted.
    """
    preview = {}

    for event_lane in event_lanes:
        embeds = build_weekly_embeds(event_lane, event_lanes)
        warnings = enforce_embed_limits(embeds)

        for warning in warnings:
            annotate('warning', f"[{event_lane.name}] {warning}")

        preview[event_lane.name] = {
            "characters": sum(len(embed) for embed in embeds),
            "warnings": warnings,
            "embeds": [embed.to_dict() for embed in embeds],
        }

    return preview


@click.command()
@click.option(
    '--preview/--no-preview',
    default=False,
    help="Also render every lane's embeds to output/preview.json without sending them.",
)
@click.option(
    '--send/--no-send',
    default=True,
    help="Deliver the schedule to the configured webhooks. Use --no-send for a dry run.",
)
def main(preview: bool, send: bool):
    click.secho("Reading event lane templates...", fg='blue')

    event_lanes = load_event_lanes(reporter=ClickReporter())

    # (callback, filename, ensure_ascii). The published manifests keep their original
    # ASCII-escaped encoding so existing consumers see no change; the preview is written
    # as readable UTF-8 because a human is the only thing that ever opens it.
    output_formats: list[tuple[typing.Callable, str, bool]] = [
        (generate_old_format, "old.json", True),
    ]

    if send:
        output_formats.append((send_webhooks, "webhook.json", True))
    else:
        click.secho("Skipping webhook delivery (--no-send)", fg='yellow')

    if preview:
        output_formats.append((generate_preview, "preview.json", False))

    click.secho("Generating output formats...", fg='blue')

    OUTPUT_FOLDER.mkdir(exist_ok=True)

    for callback, target_filename, ensure_ascii in output_formats:
        with ClickReporter().step(f"    Generating {target_filename}"):
            output = callback(event_lanes)

            with open(OUTPUT_FOLDER / target_filename, 'w', encoding='utf-8') as fp:
                json.dump(output, fp, indent=2, ensure_ascii=ensure_ascii)


if __name__ == '__main__':
    main()

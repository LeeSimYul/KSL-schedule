# -*- coding: utf-8 -*-

"""
The bot's view of the schedule.

Wraps the same loader the GitHub Actions build uses, adds the occurrences mirrored from
Discord Scheduled Events, and offers the couple of lookups the buttons and the reminder
loop need.
"""

import datetime
import logging
import pathlib
import typing

import discord

from definitions import EventLane, EventLaneEvent, Occurrence
from embeds import Localizer, collect_week_occurrences, week_window
from loader import TEMPLATES_FOLDER, load_event_lanes


log = logging.getLogger(__name__)


def scheduled_event_to_occurrence(
    scheduled_event: discord.ScheduledEvent,
    lane: EventLane,
) -> Occurrence | None:
    """
    Convert a Discord Scheduled Event into an occurrence the schedule can render.

    Discord scheduled events are one-off instants rather than recurring definitions, so
    the synthesised event is given an interval far beyond any schedule window - it will
    never be projected forwards into a week it does not belong to.
    """
    if scheduled_event.start_time is None:
        return None

    configuration = lane.meta.get("discord_events", {}) or {}
    name_prefix = configuration.get("name_prefix", None)

    if name_prefix and not scheduled_event.name.startswith(name_prefix):
        return None

    # The prefix is a routing marker for us, not something students need to read.
    name = scheduled_event.name
    if name_prefix:
        name = name[len(name_prefix):].strip() or scheduled_event.name

    duration = 60

    if scheduled_event.end_time is not None:
        duration = max(1, int((scheduled_event.end_time - scheduled_event.start_time).total_seconds() // 60))

    event = EventLaneEvent(
        host=scheduled_event.creator.display_name if scheduled_event.creator else "—",
        name=name,
        tags=["discord_event"],
        paused=False,
        basis=scheduled_event.start_time,
        timezone=lane.meta["default_timezone"],
        interval=100_000,
        lane_name=lane.name,
        kind=configuration.get("default_kind", "event"),
        description={"en": scheduled_event.description} if scheduled_event.description else {},
        duration=duration,
        rsvp=bool(lane.meta.get("interactions", False)),
    )

    return Occurrence(event, scheduled_event.start_time)


class ScheduleService:
    """Holds the loaded lanes and everything derived from them."""

    def __init__(self, templates_folder: pathlib.Path | None = None) -> None:
        #: Where the YAML templates live. Overridable so the bot can be run against a
        #: checkout elsewhere on disk, and so tests can point it at a fixture.
        self.templates_folder = templates_folder or TEMPLATES_FOLDER
        self.lanes: list[EventLane] = []
        #: Occurrences mirrored from Discord Scheduled Events, keyed by lane name. Kept
        #: separately so a template reload never throws them away.
        self.discord_occurrences: dict[str, list[Occurrence]] = {}

    def reload(self) -> bool:
        """
        Re-read the YAML templates from disk.

        A running bot keeps serving the schedule it already has if the new templates do
        not parse - a typo pushed to the repository should not blank out ``#schedule``
        until somebody notices. At startup there is nothing to fall back to, so the error
        is raised instead and the bot refuses to start with no schedule at all.
        """
        try:
            # Webhooks stay unresolved: the bot posts through its own token, and asking
            # for the webhook secrets here would mean deploying them somewhere they are
            # not used.
            lanes = load_event_lanes(resolve_webhooks=False, templates_folder=self.templates_folder)
        except Exception:
            if not self.lanes:
                raise

            log.exception("Could not reload templates - keeping the last known good schedule")
            return False

        self.lanes = lanes
        log.info("Loaded %d event lanes", len(self.lanes))

        return True

    def lane(self, name: str) -> EventLane | None:
        for lane in self.lanes:
            if lane.name == name:
                return lane

        return None

    def interactive_lanes(self) -> list[EventLane]:
        """Lanes that have opted into RSVP and reminder buttons."""
        return [lane for lane in self.lanes if lane.meta.get("interactions", False)]

    def set_discord_occurrences(self, lane_name: str, occurrences: typing.Sequence[Occurrence]) -> None:
        self.discord_occurrences[lane_name] = list(occurrences)

    def extra_occurrences(self, lane: EventLane) -> list[Occurrence]:
        if lane.meta.get('use_all_events', False):
            return [occurrence for occurrences in self.discord_occurrences.values() for occurrence in occurrences]

        return list(self.discord_occurrences.get(lane.name, []))

    def week_occurrences(
        self,
        lane: EventLane,
        now: datetime.datetime | None = None,
    ) -> list[Occurrence]:
        """Every occurrence in this lane's current week, flattened and time ordered."""
        _, occurrences_by_day = collect_week_occurrences(
            lane, self.lanes, now, extra_occurrences=self.extra_occurrences(lane),
        )

        return sorted(
            (occurrence for occurrences in occurrences_by_day.values() for occurrence in occurrences),
            key=lambda occurrence: occurrence.starts_at,
        )

    def upcoming_occurrences(
        self,
        lane: EventLane,
        now: datetime.datetime | None = None,
        limit: int = 25,
    ) -> list[Occurrence]:
        """
        This week's occurrences that have not started yet.

        Capped at 25 because that is the most options a Discord select menu can hold.
        """
        now = now or datetime.datetime.now(datetime.timezone.utc)

        return [
            occurrence
            for occurrence in self.week_occurrences(lane, now)
            if occurrence.starts_at > now
        ][:limit]

    def find_occurrence(
        self,
        lane_name: str,
        event_key: str,
        starts_at: datetime.datetime,
    ) -> Occurrence | None:
        """
        Recover a specific occurrence from the identifiers carried in a ``custom_id``.

        Buttons outlive the process that posted them, so this has to work from nothing
        but the lane name, the event key and the start time.
        """
        lane = self.lane(lane_name)

        if lane is None:
            return None

        candidates: typing.Iterable[EventLaneEvent] = (
            event for other in self.lanes for event in other.events
        )

        for event in candidates:
            if event.key == event_key:
                return Occurrence(event, starts_at)

        for occurrence in self.discord_occurrences.get(lane_name, []):
            if occurrence.event.key == event_key and occurrence.starts_at == starts_at:
                return occurrence

        return None

    def localizer(self, lane: EventLane) -> Localizer:
        return Localizer(lane.meta.get("localization", None))

    def week_window(self, lane: EventLane, now: datetime.datetime | None = None):
        return week_window(lane, now)

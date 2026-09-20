# -*- coding: utf-8 -*-

"""
Template loading.

Reading, validating and normalising the YAML templates used to live inside
``build_manifests.py``. It sits in its own module now so the live bot can load the exact
same schedule the GitHub Actions build publishes, rather than reimplementing the parse
and slowly drifting out of step with it.
"""

import contextlib
import datetime
import json
import os
import pathlib
import typing
from zoneinfo import ZoneInfo

import discord
import jsonschema
from yaml import load
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

from definitions import (
    EventLane,
    EventLaneClosure,
    EventLaneEvent,
    EventLaneMeta,
    EventLaneRawClosure,
    EventLaneRawEvent,
    EventLaneRawEvents,
)


SCRIPTS_FOLDER = pathlib.Path(__file__).parent
SCHEMA_FOLDER = SCRIPTS_FOLDER.parent / 'schema'
TEMPLATES_FOLDER = SCRIPTS_FOLDER.parent / 'templates'
OUTPUT_FOLDER = SCRIPTS_FOLDER.parent / 'output'


class Reporter(typing.Protocol):
    """Minimal progress sink, so loading works with or without a terminal attached."""

    def step(self, label: str) -> typing.ContextManager[None]: ...

    def info(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...


class QuietReporter:
    """Swallows progress output - what the bot uses."""

    @contextlib.contextmanager
    def step(self, label: str) -> typing.Iterator[None]:
        yield

    def info(self, message: str) -> None:
        pass

    def warn(self, message: str) -> None:
        pass


def parse_closure(raw_closure: EventLaneRawClosure) -> EventLaneClosure:
    """Resolve a raw closure entry into an inclusive date range."""
    start = datetime.date.fromisoformat(raw_closure["date"])
    end = datetime.date.fromisoformat(raw_closure["until"]) if raw_closure.get("until") else start

    if end < start:
        raise ValueError(f"Closure starting {start} ends on {end}, which is before it begins")

    return EventLaneClosure(start=start, end=end, reason=raw_closure.get("reason", {}))


def parse_event(
    raw_event: EventLaneRawEvent,
    lane_name: str,
    default_timezone: str,
) -> EventLaneEvent:
    """
    Resolve one raw event into an absolute, timezone-aware definition.

    The ``day`` field is redundant with ``basis`` on purpose: it is a human-checkable
    assertion, and mismatches are loud because a silently shifted class is worse than a
    failed build.
    """
    timezone = raw_event["schedule"].get("timezone", None) or default_timezone

    basis = datetime.datetime \
        .strptime(raw_event["schedule"]["basis"], "%Y-%m-%d") \
        .replace(
            hour=raw_event["schedule"]["hour"],
            minute=raw_event["schedule"]["minute"],
            tzinfo=ZoneInfo(timezone),
        )

    basis_day = basis.strftime("%A")
    claimed_day = raw_event["schedule"]["day"]

    assert \
        basis_day == claimed_day, \
        f"Event '{raw_event['name']}' w/ {raw_event['host']} in `{lane_name}` has basis time of {basis:%a %d %b %Y, %I:%M%p} but claims it is a {claimed_day}"

    return EventLaneEvent(
        host=raw_event['host'],
        name=raw_event['name'],
        tags=raw_event['tags'],
        paused=raw_event.get('paused', False),
        basis=basis,
        timezone=timezone,
        interval=raw_event['schedule'].get('interval', None) or 7,
        lane_name=lane_name,
        kind=raw_event.get('kind', 'class'),
        title=raw_event.get('title', {}),
        description=raw_event.get('description', {}),
        level=raw_event.get('level', None),
        role=raw_event.get('role', {}),
        platforms=tuple(raw_event.get('platforms', ())),
        hand_tracking=raw_event.get('hand_tracking', None),
        vrchat=raw_event.get('vrchat', {}),
        duration=raw_event['schedule'].get('duration', None) or 60,
        rsvp=raw_event.get('rsvp', False),
    )


def resolve_webhook(
    meta_data: EventLaneMeta,
    lane_name: str,
    reporter: Reporter,
) -> tuple[discord.SyncWebhook | None, dict | None, int | None]:
    """Turn the lane's webhook configuration into a usable client, if it is configured."""
    webhook_info = meta_data.get('webhook', None)

    if webhook_info is None:
        return None, None, None

    webhook_url = os.getenv(webhook_info['url'])
    webhook_message_id_variable = webhook_info.get('message_id', None)
    webhook_message_id = None

    if webhook_message_id_variable:
        raw_message_id = os.getenv(webhook_message_id_variable)

        if raw_message_id:
            webhook_message_id = int(raw_message_id)

    if not webhook_url:
        reporter.warn(f"Warning: no webhook URL found for {lane_name}")
        return None, webhook_info, webhook_message_id

    if not webhook_message_id:
        reporter.warn(f"Warning: no existing webhook message ID found for {lane_name}")

    return discord.SyncWebhook.from_url(webhook_url), webhook_info, webhook_message_id


def load_event_lanes(
    reporter: Reporter | None = None,
    resolve_webhooks: bool = True,
    templates_folder: pathlib.Path = TEMPLATES_FOLDER,
) -> list[EventLane]:
    """
    Read every lane template, validate it, and resolve it into absolute event definitions.

    Set ``resolve_webhooks=False`` when the caller delivers the schedule itself (the bot)
    rather than through a webhook - it avoids needing the webhook secrets at all.
    """
    reporter = reporter or QuietReporter()

    with reporter.step("  Parsing meta schema"):
        with open(SCHEMA_FOLDER / 'template_meta.schema.json', 'r', encoding='utf-8') as fp:
            meta_schema = json.load(fp)

    with reporter.step("  Parsing events schema"):
        with open(SCHEMA_FOLDER / 'template_events.schema.json', 'r', encoding='utf-8') as fp:
            events_schema = json.load(fp)

    event_lanes: list[EventLane] = []

    for meta_path in sorted(templates_folder.glob("*/meta.yaml")):
        event_lane_name = meta_path.parent.name
        events_path = meta_path.parent / 'events.yaml'
        reporter.info(f"  Found event lane `{event_lane_name}`")

        with reporter.step("    Parsing meta data"):
            with open(meta_path, 'r', encoding='utf-8') as fp:
                meta_data: EventLaneMeta = load(fp, Loader=Loader)

        with reporter.step("    Validating meta data against schema"):
            jsonschema.validate(instance=meta_data, schema=meta_schema)

        with reporter.step("    Parsing events data"):
            with open(events_path, 'r', encoding='utf-8') as fp:
                events_data: EventLaneRawEvents = load(fp, Loader=Loader)

        with reporter.step("    Validating events data against schema"):
            jsonschema.validate(instance=events_data, schema=events_schema)

        with reporter.step("    Converting events into agnostic times"):
            events = [
                parse_event(raw_event, event_lane_name, meta_data["default_timezone"])
                for raw_event in events_data["events"]
            ]

        with reporter.step("    Resolving recharging days"):
            closures = [parse_closure(raw_closure) for raw_closure in events_data.get("closures", [])]

        if resolve_webhooks:
            with reporter.step("    Resolving webhook if present"):
                webhook, webhook_info, webhook_message_id = resolve_webhook(meta_data, event_lane_name, reporter)
        else:
            webhook, webhook_info, webhook_message_id = None, meta_data.get('webhook', None), None

        event_lanes.append(EventLane(
            name=event_lane_name,
            meta=meta_data,
            events=events,
            webhook=webhook,
            webhook_info=webhook_info,
            webhook_message_id=webhook_message_id,
            closures=closures,
        ))

    return event_lanes


def find_lane(event_lanes: typing.Sequence[EventLane], name: str) -> EventLane | None:
    for event_lane in event_lanes:
        if event_lane.name == name:
            return event_lane

    return None

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
from yaml import YAMLError, load
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


class TemplateError(Exception):
    """A template could not be read, reported in terms its author can act on."""


def describe_yaml_error(path: pathlib.Path, text: str, error: YAMLError) -> str:
    """
    Turn a PyYAML parser error into something a schedule editor can fix.

    PyYAML reports the position where parsing became impossible, which is often a line or
    two after the actual mistake, and its wording ("did not find expected <document
    start>") describes the parser's state rather than the typo. So we print the offending
    line with a caret, and add a hint when the text matches a mistake we have seen before.
    """
    mark = getattr(error, 'problem_mark', None) or getattr(error, 'context_mark', None)

    try:
        display_path = path.relative_to(SCRIPTS_FOLDER.parent)
    except ValueError:
        display_path = path

    if mark is None:
        return f"{display_path}: could not be parsed as YAML\n  {error}"

    source_lines = text.splitlines()
    line_number = mark.line + 1
    column = mark.column + 1
    offending = source_lines[mark.line] if mark.line < len(source_lines) else ""

    parts = [
        f"{display_path}:{line_number}:{column}: could not be parsed as YAML",
        "",
        f"  {line_number:>4} | {offending}",
        f"       | {' ' * mark.column}^",
        "",
        f"  {error.problem if hasattr(error, 'problem') else error}",
    ]

    hint = yaml_hint(source_lines, mark.line)

    if hint:
        parts += ["", f"  힌트 / Hint: {hint}"]

    return "\n".join(parts)


def yaml_hint(source_lines: list[str], error_line: int) -> str | None:
    """
    Guess at the cause, scanning back from the position the parser reported.

    The parser usually only notices the problem on a later line - an unterminated quote
    is found at end of file, and a key that swallowed its value is found when the next
    line turns out to have nowhere to go - so the line it names is rarely the one to fix.
    """
    # Far enough back to cover the usual lag, close enough not to blame something else.
    LOOKBACK = 6

    # The mark can point past the last line, e.g. when a quote runs to end of file.
    start = min(error_line, len(source_lines) - 1)

    for index in range(start, max(-1, start - LOOKBACK), -1):
        line = source_lines[index]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if "\t" in line:
            return (
                f"{index + 1}행이 탭 문자로 들여쓰기 되어 있습니다. YAML은 탭을 허용하지 "
                f"않습니다 - 공백으로 바꿔 주세요. / Line {index + 1} is indented with a tab; "
                f"YAML requires spaces."
            )

        if stripped.count('"') % 2 or stripped.count("'") % 2:
            return (
                f"{index + 1}행의 따옴표가 닫히지 않았습니다. / "
                f"Line {index + 1} has an unclosed quote."
            )

        # A list item is still a key/value pair once its dash is removed.
        content = stripped[2:] if stripped.startswith("- ") else stripped
        head, separator, tail = content.partition(":")

        # `key:value` with no space after the colon is read as one plain string rather
        # than a mapping - which is exactly what a stray character glued onto a key looks
        # like, and the parser only complains once the following line has nowhere to go.
        if separator and tail and not tail.startswith(" "):
            return (
                f"{index + 1}행의 `{stripped}` — 콜론 뒤에 공백이 없습니다. 값이 없는 키라면 "
                f"`{head}:` 처럼 콜론으로 끝나야 하고, 값이 있다면 `{head}: {tail}` 처럼 한 칸 "
                f"띄워야 합니다. 키 뒤에 이상한 문자가 붙어 있지 않은지 확인해 주세요. / "
                f"Line {index + 1}: no space after the colon."
            )

    return None


def read_yaml(path: pathlib.Path) -> typing.Any:
    """Read one YAML template, reporting syntax errors usefully."""
    text = path.read_text(encoding='utf-8')

    try:
        return load(text, Loader=Loader)
    except YAMLError as error:
        raise TemplateError(describe_yaml_error(path, text, error)) from error


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
        role=raw_event.get('role', ''),
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
            meta_data: EventLaneMeta = read_yaml(meta_path)

        with reporter.step("    Validating meta data against schema"):
            jsonschema.validate(instance=meta_data, schema=meta_schema)

        with reporter.step("    Parsing events data"):
            events_data: EventLaneRawEvents = read_yaml(events_path)

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

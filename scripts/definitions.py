# -*- coding: utf-8 -*-

"""
Types, dataclasses, etc.

Every field added for the KSL (한국수어교실) templates is optional, so the lanes that do
not use them - ASL, BSL, DGS, JSL, LSF and the two server-wide lanes - keep rendering
exactly as they did before.
"""

import dataclasses
import datetime
import hashlib
import typing

import discord


#: A block of text carried in several languages, keyed by ISO 639-1 code, e.g.
#: ``{"ko": "별빛반 (단어)", "en": "Starlight Class (Words)"}``.
LocalizedText = dict[str, str]

#: Which headsets/platforms an event is suitable for.
Platform = typing.Literal["pcvr", "quest", "desktop", "mobile"]

#: How much an event leans on hand tracking.
HandTracking = typing.Literal["required", "recommended", "supported", "unsupported"]

#: What kind of entry this is. ``recharge`` marks a 재충전의 날 - a day the classroom is
#: deliberately closed - and is rendered with its own colour and icon.
EventKind = typing.Literal["class", "event", "social", "recharge"]


class EventLaneLanguageInfo(typing.TypedDict):
    abbreviation: str
    native_localization: str
    localized_name: dict[str, str]


class EventLaneWebhookInfo(typing.TypedDict):
    channel: str
    url: str
    message_id: typing.NotRequired[int]
    header: typing.NotRequired[str]


class EventLaneDisplayTimezone(typing.TypedDict):
    """One of the explicit "🇰🇷 06:00 AM KST" lines printed under a dynamic timestamp."""

    flag: str
    timezone: str
    label: typing.NotRequired[str]


class EventLaneLocalization(typing.TypedDict):
    """Controls the bilingual (한/영) layout."""

    #: Language shown first, e.g. ``ko``.
    primary: str
    #: Language shown second. Omit to render a single language only.
    secondary: typing.NotRequired[str]
    #: Separator placed between the two on a shared line.
    separator: typing.NotRequired[str]
    #: Localised labels for the embed's own furniture ("진행자 / Host" etc).
    labels: typing.NotRequired[dict[str, LocalizedText]]


class EventLaneLevel(typing.TypedDict):
    """A class a session belongs to - 씨앗반 / 별빛반 / 달빛반 for KSL."""

    emoji: typing.NotRequired[str]
    names: LocalizedText
    order: typing.NotRequired[int]


class EventLaneRole(typing.TypedDict):
    """An official host title - 교장선생님, 담임선생님, 학생회장 and so on."""

    emoji: typing.NotRequired[str]
    names: LocalizedText
    order: typing.NotRequired[int]


class EventLaneVRChatInfo(typing.TypedDict):
    """VRChat joining information."""

    group: typing.NotRequired[str]
    group_url: typing.NotRequired[str]
    instance_url: typing.NotRequired[str]
    world_url: typing.NotRequired[str]
    world_name: typing.NotRequired[str]


class EventLaneDiscordEventsInfo(typing.TypedDict):
    """Configuration for mirroring Discord Scheduled Events into the schedule."""

    guild: int
    #: Only mirror events whose name starts with this prefix. Omit to mirror all of them.
    name_prefix: typing.NotRequired[str]
    #: Default level/kind applied to mirrored events.
    default_kind: typing.NotRequired[EventKind]


class EventLaneMeta(typing.TypedDict):
    channels: dict[str, int]
    default_timezone: str
    use_all_events: typing.NotRequired[bool]
    language_info: typing.NotRequired[EventLaneLanguageInfo]
    webhook: typing.NotRequired[EventLaneWebhookInfo]
    display_timezones: typing.NotRequired[list[EventLaneDisplayTimezone]]
    localization: typing.NotRequired[EventLaneLocalization]
    levels: typing.NotRequired[dict[str, EventLaneLevel]]
    roles: typing.NotRequired[dict[str, EventLaneRole]]
    vrchat: typing.NotRequired[EventLaneVRChatInfo]
    discord_events: typing.NotRequired[EventLaneDiscordEventsInfo]
    #: Offer RSVP / reminder buttons for this lane (needs the bot - see docs/KSL_GUIDE.md).
    interactions: typing.NotRequired[bool]


class EventLaneRawEventSchedule(typing.TypedDict):
    timezone: typing.NotRequired[str]
    basis: str
    day: typing.Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    hour: int
    minute: int
    interval: typing.NotRequired[int]
    duration: typing.NotRequired[int]


class EventLaneRawEvent(typing.TypedDict):
    host: str
    name: str
    tags: list[str]
    paused: typing.NotRequired[bool]
    schedule: EventLaneRawEventSchedule
    kind: typing.NotRequired[EventKind]
    title: typing.NotRequired[LocalizedText]
    description: typing.NotRequired[LocalizedText]
    level: typing.NotRequired[str]
    #: A key into the lane's ``roles`` block, or inline text for a one-off guest.
    role: typing.NotRequired[str | LocalizedText]
    platforms: typing.NotRequired[list[Platform]]
    hand_tracking: typing.NotRequired[HandTracking]
    vrchat: typing.NotRequired[EventLaneVRChatInfo]
    rsvp: typing.NotRequired[bool]


class EventLaneRawClosure(typing.TypedDict):
    """A 재충전의 날 / holiday - the lane runs no classes between these dates."""

    date: str
    until: typing.NotRequired[str]
    reason: typing.NotRequired[LocalizedText]


class EventLaneRawEvents(typing.TypedDict):
    events: list[EventLaneRawEvent]
    closures: typing.NotRequired[list[EventLaneRawClosure]]


@dataclasses.dataclass(frozen=True)
class EventLaneClosure:
    """A resolved, inclusive range of days on which a lane holds no events."""

    start: datetime.date
    end: datetime.date
    reason: LocalizedText = dataclasses.field(default_factory=dict)

    def covers(self, day: datetime.date) -> bool:
        return self.start <= day <= self.end


@dataclasses.dataclass(frozen=True)
class EventLaneEvent:
    host: str
    name: str
    tags: list[str]
    paused: bool
    basis: datetime.datetime
    timezone: str
    interval: int

    # --- Optional enrichment, all defaulted so existing lanes are unaffected. ---

    #: Name of the lane this event was declared in. Lets an aggregated schedule still
    #: apply the *owning* lane's closures and level vocabulary.
    lane_name: str = ""
    kind: EventKind = "class"
    title: LocalizedText = dataclasses.field(default_factory=dict)
    description: LocalizedText = dataclasses.field(default_factory=dict)
    level: str | None = None
    role: str | LocalizedText = ""
    platforms: tuple[Platform, ...] = ()
    hand_tracking: HandTracking | None = None
    vrchat: EventLaneVRChatInfo = dataclasses.field(default_factory=dict)
    duration: int = 60
    rsvp: bool = False

    @property
    def key(self) -> str:
        """
        A short, stable identifier for this event definition.

        Stable across builds (it is derived only from authored data, never from the
        current time) and short enough to sit inside a Discord ``custom_id`` alongside an
        occurrence timestamp, which is capped at 100 characters.
        """
        digest = hashlib.blake2b(
            "\x1f".join((self.lane_name, self.host, self.name, self.basis.isoformat())).encode('utf-8'),
            digest_size=8,
        )

        return digest.hexdigest()

    def next_occurrence_after(self, target: datetime.datetime) -> typing.Optional[datetime.datetime]:
        # If paused, no next occurrence
        if self.paused:
            return None

        # Calculate the amount of days that have passed since the basis
        days_since_basis = (target - self.basis).days
        # Start search from floored interval from basis
        starting_day_offset = int(days_since_basis / self.interval) * self.interval
        needle = self.basis + datetime.timedelta(days=starting_day_offset)

        while needle < target:
            needle += datetime.timedelta(days=self.interval)

        return needle


@dataclasses.dataclass(frozen=True)
class EventLane:
    name: str
    meta: EventLaneMeta
    events: list[EventLaneEvent]
    webhook: discord.SyncWebhook | None
    webhook_info: EventLaneWebhookInfo | None
    webhook_message_id: int | None
    closures: list[EventLaneClosure] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class Occurrence:
    """A single, concrete happening of an event at an absolute instant."""

    event: EventLaneEvent
    starts_at: datetime.datetime

    @property
    def ends_at(self) -> datetime.datetime:
        return self.starts_at + datetime.timedelta(minutes=self.event.duration)

    @property
    def key(self) -> str:
        """Identifies this *occurrence*, as opposed to the recurring event behind it."""
        return f"{self.event.key}:{int(self.starts_at.timestamp())}"

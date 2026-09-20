# -*- coding: utf-8 -*-

"""
Embed construction.

Rendering used to live inside ``formats/webhook.py``. It is its own module now because
two very different callers need the exact same output: the GitHub Actions build, which
edits a schedule message through a webhook, and the live bot, which posts the same
schedule but can additionally attach RSVP buttons to it.
"""

import datetime
import typing
from zoneinfo import ZoneInfo

import discord

from definitions import (
    EventLane,
    EventLaneClosure,
    EventLaneEvent,
    EventLaneLevel,
    EventLaneLocalization,
    EventLaneRole,
    EventLaneVRChatInfo,
    LocalizedText,
    Occurrence,
    Platform,
)
from timeutil import DEFAULT_DISPLAY_TIMEZONES, DisplayTimezone, discord_timestamp_pair, timezone_lines


#: Indentation prefix - a zero width space keeps Discord from trimming the leading spaces.
INDENT = "​    "

#: Discord's hard limits. Exceeding either of them makes the API reject the whole message,
#: which for us means a schedule that silently stops updating, so we clamp before sending.
MAX_EMBED_DESCRIPTION = 4096
MAX_TOTAL_EMBED_CHARACTERS = 6000

#: A deliberately desaturated colour for 재충전의 날 - it reads as 'off' next to the
#: fully saturated rainbow used for ordinary weekdays.
RECHARGE_COLOUR = discord.Color.from_rgb(121, 134, 152)
RECHARGE_EMOJI = "\N{BATTERY}"

CLOCK_EMOJIS: list[tuple[float, str]] = [
    (-01.0, "\N{CLOCK FACE ELEVEN OCLOCK}"),
    (-00.5, "\N{CLOCK FACE ELEVEN-THIRTY}"),
    (+00.0, "\N{CLOCK FACE TWELVE OCLOCK}"),
    (+00.5, "\N{CLOCK FACE TWELVE-THIRTY}"),
    (+01.0, "\N{CLOCK FACE ONE OCLOCK}"),
    (+01.5, "\N{CLOCK FACE ONE-THIRTY}"),
    (+02.0, "\N{CLOCK FACE TWO OCLOCK}"),
    (+02.5, "\N{CLOCK FACE TWO-THIRTY}"),
    (+03.0, "\N{CLOCK FACE THREE OCLOCK}"),
    (+03.5, "\N{CLOCK FACE THREE-THIRTY}"),
    (+04.0, "\N{CLOCK FACE FOUR OCLOCK}"),
    (+04.5, "\N{CLOCK FACE FOUR-THIRTY}"),
    (+05.0, "\N{CLOCK FACE FIVE OCLOCK}"),
    (+05.5, "\N{CLOCK FACE FIVE-THIRTY}"),
    (+06.0, "\N{CLOCK FACE SIX OCLOCK}"),
    (+06.5, "\N{CLOCK FACE SIX-THIRTY}"),
    (+07.0, "\N{CLOCK FACE SEVEN OCLOCK}"),
    (+07.5, "\N{CLOCK FACE SEVEN-THIRTY}"),
    (+08.0, "\N{CLOCK FACE EIGHT OCLOCK}"),
    (+08.5, "\N{CLOCK FACE EIGHT-THIRTY}"),
    (+09.0, "\N{CLOCK FACE NINE OCLOCK}"),
    (+09.5, "\N{CLOCK FACE NINE-THIRTY}"),
    (+10.0, "\N{CLOCK FACE TEN OCLOCK}"),
    (+10.5, "\N{CLOCK FACE TEN-THIRTY}"),
    (+11.0, "\N{CLOCK FACE ELEVEN OCLOCK}"),
    (+11.5, "\N{CLOCK FACE ELEVEN-THIRTY}"),
    (+12.0, "\N{CLOCK FACE TWELVE OCLOCK}"),
    (+12.5, "\N{CLOCK FACE TWELVE-THIRTY}"),
    (+13.0, "\N{CLOCK FACE ONE OCLOCK}"),
    (+13.5, "\N{CLOCK FACE ONE-THIRTY}"),
]

#: Platform names are brand names, so they stay in one language even on a bilingual lane -
#: printing "퀘스트 · Quest" costs a line of width and tells nobody anything new.
PLATFORM_LABELS: dict[Platform, str] = {
    "pcvr":    "\N{DESKTOP COMPUTER}\N{VARIATION SELECTOR-16} PCVR",
    "quest":   "\N{GOGGLES} Quest Standalone",
    "desktop": "\N{PERSONAL COMPUTER} Desktop",
    "mobile":  "\N{MOBILE PHONE} Mobile",
}

HAND_TRACKING_LABELS: dict[str, LocalizedText] = {
    "required":    {"ko": "핸드트래킹 필수", "en": "hand tracking required"},
    "recommended": {"ko": "핸드트래킹 권장", "en": "hand tracking recommended"},
    "supported":   {"ko": "핸드트래킹 지원", "en": "hand tracking supported"},
}

#: The equipment line lists independent options, so it is separated more strongly than
#: the middle dot used to join translations of the same thing.
EQUIPMENT_SEPARATOR = " | "

#: Default vocabulary for the embed's own furniture. A lane can override any of these
#: through ``localization.labels`` in its ``meta.yaml``.
DEFAULT_LABELS: dict[str, LocalizedText] = {
    "host":          {"ko": "진행자", "en": "Host"},
    "level":         {"ko": "학급", "en": "Class"},
    "equipment":     {"ko": "권장 장비", "en": "Equipment"},
    "join":          {"ko": "참여하기", "en": "Join"},
    "group":         {"ko": "VRChat 그룹", "en": "VRChat Group"},
    "instance":      {"ko": "월드 바로가기", "en": "Join Instance"},
    "world":         {"ko": "월드 정보", "en": "World"},
    "no_events":     {"ko": "이 날은 일정이 없습니다.", "en": "No events this day."},
    "recharge":      {"ko": "재충전의 날", "en": "Recharging Day"},
    "recharge_note": {"ko": "오늘은 수업을 쉽니다. 푹 쉬어 주세요!", "en": "Classes are off today - enjoy the rest!"},
}

DEFAULT_SEPARATOR = " · "


class Localizer:
    """
    Renders bilingual (한/영) text according to a lane's ``localization`` block.

    With no configuration it degrades to "print whatever single string we were given",
    which is what every non-KSL lane wants.
    """

    def __init__(self, localization: EventLaneLocalization | None = None):
        localization = localization or {}

        self.primary: str = localization.get("primary", "en")
        self.secondary: str | None = localization.get("secondary", None)
        self.separator: str = localization.get("separator", DEFAULT_SEPARATOR)
        self.label_overrides: dict[str, LocalizedText] = localization.get("labels", {})

    @property
    def bilingual(self) -> bool:
        return self.secondary is not None

    @property
    def languages(self) -> tuple[str, ...]:
        if self.secondary is None:
            return (self.primary,)

        return (self.primary, self.secondary)

    def text(self, localized: LocalizedText | None, fallback: str = "") -> str:
        """
        Join the configured languages onto one line, e.g. ``별빛반 · Starlight Class``.

        Missing translations are skipped rather than substituted, so a half-translated
        entry degrades to the language that *is* present instead of showing a key.
        """
        localized = localized or {}

        parts = [localized[language] for language in self.languages if localized.get(language)]

        if not parts:
            return fallback

        # A translation identical to the primary adds noise without adding meaning.
        deduplicated = list(dict.fromkeys(parts))

        return self.separator.join(deduplicated)

    def lines(self, localized: LocalizedText | None, fallback: str = "") -> list[str]:
        """As :meth:`text`, but one language per line - used for longer descriptions."""
        localized = localized or {}

        parts = [localized[language] for language in self.languages if localized.get(language)]

        if not parts:
            return [fallback] if fallback else []

        return list(dict.fromkeys(parts))

    def label(self, key: str) -> str:
        return self.text(self.label_overrides.get(key) or DEFAULT_LABELS.get(key, {}), fallback=key)


def clock_emoji(moment: datetime.datetime) -> str:
    """The clock face that most closely matches this time, to the nearest half hour."""
    hour_time = (moment.hour + (moment.minute / 60)) % 12

    return min(CLOCK_EMOJIS, key=lambda pair: abs(pair[0] - hour_time))[1]


def resolve_display_timezones(lane: EventLane) -> tuple[DisplayTimezone, ...]:
    """
    Which timezones this lane spells out under each dynamic timestamp.

    A lane that configures none keeps the original server-wide set, so enabling this
    feature for KSL does not quietly drop Chicago or London from the ASL schedule.
    """
    configured = lane.meta.get("display_timezones", None)

    if not configured:
        return DEFAULT_DISPLAY_TIMEZONES

    return tuple(DisplayTimezone.from_config(entry) for entry in configured)


def format_level(
    level_key: str | None,
    levels: dict[str, EventLaneLevel],
    localizer: Localizer,
) -> str | None:
    """
    Render the class a session belongs to, e.g. ``🌱 [씨앗반 - 입문]``.

    The brackets set the class apart from the free text around it, and on a bilingual
    lane both languages sit inside the one pair rather than each getting their own.
    """
    if not level_key:
        return None

    level = levels.get(level_key, None)

    if level is None:
        # An unknown key is still worth surfacing - better a raw key in the schedule than
        # a silently missing class on a session that has one.
        return f"[{level_key}]"

    emoji = level.get("emoji", "")
    names = localizer.text(level.get("names", {}), fallback=level_key)

    return f"{emoji} [{names}]".strip()


def format_environment(event: EventLaneEvent, localizer: Localizer) -> str | None:
    """
    Render the equipment line, e.g.
    ``🖥️ PCVR | 🥽 Quest Standalone | 💻 Desktop | 🖐️ 핸드트래킹 지원``.
    """
    parts: list[str] = []

    for platform in event.platforms:
        parts.append(PLATFORM_LABELS.get(platform, platform))

    hand_tracking = HAND_TRACKING_LABELS.get(event.hand_tracking or "", None)

    if hand_tracking is not None:
        parts.append(f"\N{RAISED HAND WITH FINGERS SPLAYED}\N{VARIATION SELECTOR-16} {localizer.text(hand_tracking)}")

    if not parts:
        return None

    return EQUIPMENT_SEPARATOR.join(parts)


def resolve_vrchat(event: EventLaneEvent, lane_vrchat: EventLaneVRChatInfo | None) -> EventLaneVRChatInfo:
    """Merge lane-wide VRChat defaults with any per-event overrides."""
    merged: EventLaneVRChatInfo = dict(lane_vrchat or {})
    merged.update(event.vrchat or {})

    return merged


def format_vrchat_links(vrchat: EventLaneVRChatInfo, localizer: Localizer) -> str | None:
    """Render the VRChat group / instance links as inline markdown links."""
    parts: list[str] = []

    if vrchat.get("group_url"):
        group_label = vrchat.get("group") or localizer.label("group")
        parts.append(f"[{group_label}]({vrchat['group_url']})")

    if vrchat.get("instance_url"):
        parts.append(f"[{localizer.label('instance')}]({vrchat['instance_url']})")

    if vrchat.get("world_url"):
        world_label = vrchat.get("world_name") or localizer.label("world")
        parts.append(f"[{world_label}]({vrchat['world_url']})")

    if not parts:
        return None

    return "\N{LINK SYMBOL} " + DEFAULT_SEPARATOR.join(parts)


def resolve_role(
    role: str | LocalizedText | None,
    roles: dict[str, EventLaneRole],
    localizer: Localizer,
) -> str | None:
    """
    Render a host's official title, e.g. ``🏫 담임선생님``.

    ``role`` is normally a key into the lane's ``roles`` block, so that renaming a title
    is one edit rather than one per class. An inline mapping is still accepted for a
    one-off guest who holds no standing title.
    """
    if not role:
        return None

    if isinstance(role, str):
        entry = roles.get(role, None)

        if entry is None:
            # Better a visible unknown title than a silently missing one.
            return role

        emoji = entry.get("emoji", "")
        names = localizer.text(entry.get("names", {}), fallback=role)

        return f"{emoji} {names}".strip()

    return localizer.text(role) or None


def format_host(
    event: EventLaneEvent,
    localizer: Localizer,
    roles: dict[str, EventLaneRole] | None = None,
) -> str:
    """``진행자 · Host: Korea_Yujin (🏫 담임선생님 · Homeroom Teacher)``"""
    text = f"{localizer.label('host')}: {event.host}"
    role = resolve_role(event.role, roles or {}, localizer)

    if role:
        text = f"{text} ({role})"

    return text


def format_occurrence_block(
    occurrence: Occurrence,
    localizer: Localizer,
    levels: dict[str, EventLaneLevel],
    display_timezones: typing.Sequence[DisplayTimezone],
    lane_vrchat: EventLaneVRChatInfo | None = None,
    reference_date: datetime.date | None = None,
    roles: dict[str, EventLaneRole] | None = None,
) -> str:
    """
    One event's entry inside a day embed.

    The shape is deliberately layered: the loudest line is the class name, the time block
    sits underneath it, and everything a student only needs once (level, headset, links)
    is rendered as Discord subtext so it does not compete with the schedule itself.
    """
    event = occurrence.event
    lines: list[str] = []

    title = localizer.text(event.title, fallback=event.name)
    lines.append(f"**{title}**")
    lines.append(f"-# {format_host(event, localizer, roles)}")

    for description_line in localizer.lines(event.description):
        lines.append(f"-# {description_line}")

    # The dynamic timestamp renders in each viewer's own timezone; the explicit lines
    # below it keep the message readable in screenshots and for anyone whose client has
    # not expanded the timestamp yet.
    lines.append(f"{INDENT}{clock_emoji(occurrence.starts_at)} {discord_timestamp_pair(occurrence.starts_at)}")

    for timezone_text in timezone_lines(occurrence.starts_at, display_timezones, reference_date):
        lines.append(f"{INDENT}{timezone_text}")

    # Class and equipment get a line each. Packed onto one line they ran past the width
    # of a phone-sized embed, and the two kinds of information blurred together.
    class_line = format_level(event.level, levels, localizer)

    if class_line:
        lines.append(f"-# {class_line}")

    equipment_line = format_environment(event, localizer)

    if equipment_line:
        lines.append(f"-# {equipment_line}")

    links = format_vrchat_links(resolve_vrchat(event, lane_vrchat), localizer)

    if links:
        lines.append(f"-# {links}")

    return "\n".join(lines)


def find_closure(closures: typing.Sequence[EventLaneClosure], day: datetime.date) -> EventLaneClosure | None:
    for closure in closures:
        if closure.covers(day):
            return closure

    return None


def build_recharge_description(
    day: datetime.datetime,
    closure: EventLaneClosure,
    localizer: Localizer,
) -> str:
    """The 재충전의 날 body - its own icon, its own voice, no event list."""
    lines = [
        f"# {RECHARGE_EMOJI} {day:%A (%Y-%m-%d)}",
        "",
        f"**{localizer.label('recharge')}**",
    ]

    for reason_line in localizer.lines(closure.reason):
        lines.append(f"-# {reason_line}")

    lines.append(f"-# {localizer.label('recharge_note')}")

    return "\n".join(lines)


def calculate_notable_date_emojis(year: int) -> dict[tuple[int, int], str]:
    """
    Days that get their own icon instead of the default calendar page.

    ``year`` is accepted so that movable feasts (추석, 설날 - both lunar) can be resolved
    per year later on without changing every call site.
    """
    notable_date_emojis = {
        (1,  1):  "🎉",   # New Year's Day
        (2,  3):  "🤟",   # 한국수어의 날 / Korean Sign Language Day
        (2,  14): "❤️",   # Valentine's Day
        (3,  1):  "🇰🇷",   # 삼일절 / Independence Movement Day
        (3,  13): "🦻",   # Start of National Deaf History Month
        (3,  17): "🍀",   # St. Patrick's Day
        (4,  1):  "🥳",   # April Fools Day
        (4,  8):  "🎓",   # Anniversary of the founding of Gallaudet University
        (4,  15): "<:aslA:770863405380665345>",  # National ASL Day
        (4,  22): "🌱",   # Earth Day
        (5,  5):  "🧒",   # 어린이날 / Children's Day
        (6,  5):  "🌍",   # World Environment Day
        (7,  26): "⚖️",   # Americans with Disabilities Act (ADA) Anniversary
        (8,  15): "🇰🇷",   # 광복절 / National Liberation Day
        (9,  21): "🕊️",   # International Day of Peace
        (9,  23): "🤟",   # International Day of Sign Languages
        (10, 9):  "🇰🇷",   # 한글날 / Hangul Day
        (10, 10): "<:hhlogo:586607081000271877>",  # Helping Hands Discord Server Anniversary
        (10, 31): "🎃",   # Halloween
        (12, 24): "🎄",   # Christmas Eve
        (12, 25): "🎅",   # Christmas Day
        (12, 26): "📦",   # Boxing Day get it it's a box haha
        (12, 31): "🎆",   # New Year's Eve
    }

    return notable_date_emojis


def week_window(lane: EventLane, now: datetime.datetime | None = None) -> tuple[datetime.datetime, datetime.datetime]:
    """
    The half-open ``[start, end)`` window of the week currently on display for this lane.

    A week turns over at 5am on Monday *in the lane's own timezone*: at 4am on a Monday
    the previous week is still the one people care about, because that week's late night
    events have not finished yet.
    """
    lane_zone = ZoneInfo(lane.meta["default_timezone"])
    now = now.astimezone(lane_zone) if now is not None else datetime.datetime.now(lane_zone)

    last_monday_5am = (now - datetime.timedelta(days=now.weekday())).replace(
        hour=5, minute=0, second=0, microsecond=0,
    )

    if last_monday_5am > now:
        last_monday_5am -= datetime.timedelta(days=7)

    return last_monday_5am, last_monday_5am + datetime.timedelta(days=7)


def collect_week_occurrences(
    lane: EventLane,
    event_lanes: typing.Sequence[EventLane],
    now: datetime.datetime | None = None,
    extra_occurrences: typing.Sequence[Occurrence] = (),
) -> tuple[datetime.datetime, dict[int, list[Occurrence]]]:
    """
    Group this lane's occurrences for the current week by weekday offset from Monday.

    Occurrences falling inside a closure declared by the lane that *owns* them are
    dropped, so a KSL 재충전의 날 removes KSL classes from the combined server schedule
    too, without blanking out that day for every other language.

    ``extra_occurrences`` lets a caller fold in one-off happenings that are not declared
    in the templates at all - this is how the bot merges Discord Scheduled Events into
    the same weekly view. They are filtered by the same week window and closure rules.
    """
    lane_zone = ZoneInfo(lane.meta["default_timezone"])
    week_start, week_end = week_window(lane, now)

    closures_by_lane = {other.name: other.closures for other in event_lanes}

    if lane.meta.get('use_all_events', False):
        events: list[EventLaneEvent] = [event for other in event_lanes for event in other.events]
    else:
        events = list(lane.events)

    occurrences_by_day: dict[int, list[Occurrence]] = {offset: [] for offset in range(7)}

    for event in events:
        next_occurrence = event.next_occurrence_after(week_start)

        # No next occurrence (the event is paused), or it does not land in this week.
        if next_occurrence is None or not (week_start <= next_occurrence < week_end):
            continue

        local_occurrence = next_occurrence.astimezone(lane_zone)

        if find_closure(closures_by_lane.get(event.lane_name, []), local_occurrence.date()):
            continue

        occurrences_by_day[local_occurrence.weekday()].append(Occurrence(event, next_occurrence))

    for occurrence in extra_occurrences:
        if not (week_start <= occurrence.starts_at < week_end):
            continue

        local_occurrence = occurrence.starts_at.astimezone(lane_zone)

        if find_closure(closures_by_lane.get(occurrence.event.lane_name, lane.closures), local_occurrence.date()):
            continue

        occurrences_by_day[local_occurrence.weekday()].append(occurrence)

    for occurrences in occurrences_by_day.values():
        occurrences.sort(key=lambda occurrence: occurrence.starts_at)

    return week_start, occurrences_by_day


def build_weekly_embeds(
    lane: EventLane,
    event_lanes: typing.Sequence[EventLane],
    now: datetime.datetime | None = None,
    extra_occurrences: typing.Sequence[Occurrence] = (),
) -> list[discord.Embed]:
    """Build the full set of embeds for a lane's weekly schedule message."""
    localizer = Localizer(lane.meta.get("localization", None))
    levels = lane.meta.get("levels", {})
    roles = lane.meta.get("roles", {})
    lane_vrchat = lane.meta.get("vrchat", None)
    display_timezones = resolve_display_timezones(lane)

    week_start, occurrences_by_day = collect_week_occurrences(lane, event_lanes, now, extra_occurrences)

    embeds: list[discord.Embed] = []

    header_text = (lane.webhook_info or {}).get('header', '')

    if header_text:
        embeds.append(discord.Embed(
            color=discord.Color.from_rgb(254, 254, 254),
            description=header_text,
        ))

    notable_date_emojis = calculate_notable_date_emojis(week_start.year)

    for weekday_offset in range(0, 7):
        day = week_start + datetime.timedelta(days=weekday_offset)
        closure = find_closure(lane.closures, day.date())

        if closure is not None:
            embeds.append(discord.Embed(
                color=RECHARGE_COLOUR,
                description=build_recharge_description(day, closure, localizer),
            ))
            continue

        emoji = notable_date_emojis.get((day.month, day.day), "\N{SPIRAL CALENDAR PAD}")
        description_parts = [f"# {emoji} {day:%A (%Y-%m-%d)}"]

        if occurrences_by_day[weekday_offset]:
            description_parts.extend(
                format_occurrence_block(
                    occurrence,
                    localizer,
                    levels,
                    display_timezones,
                    lane_vrchat=lane_vrchat,
                    reference_date=day.date(),
                    roles=roles,
                )
                for occurrence in occurrences_by_day[weekday_offset]
            )
        else:
            description_parts.append(f"-# -- {localizer.label('no_events')} --")

        embeds.append(discord.Embed(
            color=discord.Color.from_hsv(weekday_offset / 7.0, 1.0, 1.0),
            description="\n\n".join(description_parts),
        ))

    return embeds


def build_occurrence_embed(
    occurrence: Occurrence,
    lane: EventLane,
    color: discord.Color | None = None,
) -> discord.Embed:
    """
    A standalone embed for a single occurrence.

    Used by the bot for announcements and reminder DMs, where there is room to give each
    attribute its own field rather than packing everything into subtext.
    """
    event = occurrence.event
    localizer = Localizer(lane.meta.get("localization", None))
    levels = lane.meta.get("levels", {})
    roles = lane.meta.get("roles", {})
    display_timezones = resolve_display_timezones(lane)

    if event.kind == "recharge":
        color = color or RECHARGE_COLOUR
    elif color is None:
        color = discord.Color.from_hsv(occurrence.starts_at.weekday() / 7.0, 0.65, 0.95)

    embed = discord.Embed(
        title=localizer.text(event.title, fallback=event.name),
        description="\n".join(f"-# {line}" for line in localizer.lines(event.description)) or None,
        color=color,
        timestamp=occurrence.starts_at,
    )

    time_lines = [discord_timestamp_pair(occurrence.starts_at)]
    time_lines.extend(timezone_lines(occurrence.starts_at, display_timezones))

    embed.add_field(
        name=localizer.label('host'),
        value=format_host(event, localizer, roles),
        inline=False,
    )
    embed.add_field(
        name=f"{clock_emoji(occurrence.starts_at)} {occurrence.starts_at:%Y-%m-%d}",
        value="\n".join(time_lines),
        inline=False,
    )

    level_text = format_level(event.level, levels, localizer)

    if level_text:
        embed.add_field(name=localizer.label('level'), value=level_text, inline=True)

    environment_text = format_environment(event, localizer)

    if environment_text:
        embed.add_field(name=localizer.label('equipment'), value=environment_text, inline=False)

    links = format_vrchat_links(resolve_vrchat(event, lane.meta.get("vrchat", None)), localizer)

    if links:
        embed.add_field(name=localizer.label('join'), value=links, inline=False)

    return embed


def enforce_embed_limits(embeds: typing.Sequence[discord.Embed]) -> list[str]:
    """
    Clamp embeds to Discord's size limits, in place, and report what had to be cut.

    Without this a busy week would grow past the 6000 character budget and the API would
    reject the edit outright - turning a slightly-too-long schedule into no schedule at
    all. Truncating the tail of the last day is the less bad failure.
    """
    warnings: list[str] = []
    budget = MAX_TOTAL_EMBED_CHARACTERS

    for index, embed in enumerate(embeds):
        description = embed.description or ""
        # Fields and titles count towards the same budget, so measure the whole embed.
        overhead = len(embed) - len(description)
        allowance = min(MAX_EMBED_DESCRIPTION, max(0, budget - overhead))

        if len(description) > allowance:
            # The ellipsis has to fit inside the allowance too, and when there is no
            # allowance left at all even that one character is one too many.
            embed.description = (description[:allowance - 1] + "\N{HORIZONTAL ELLIPSIS}") if allowance > 0 else ""
            warnings.append(
                f"Embed #{index} was truncated from {len(description)} to {allowance} characters "
                f"to stay inside Discord's limits"
            )

        budget = max(0, budget - len(embed))

    return warnings

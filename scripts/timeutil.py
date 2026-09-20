# -*- coding: utf-8 -*-

"""
Timezone / Discord timestamp helpers.

This module is deliberately dependency-free (standard library only) so that it can be
imported by the manifest build script, by the live bot, and by ad-hoc tooling alike.

The two jobs it does:

1. Turn a wall-clock string written by a human (e.g. ``"2026-09-16 20:00"`` in KST) into
   an absolute instant and a UNIX timestamp.
2. Render that instant for a global audience - as a Discord dynamic timestamp (which each
   client renders in the viewer's own locale) *and* as explicit per-region text lines for
   people reading a screenshot, a forum post, or a client that does not expand timestamps.
"""

import dataclasses
import datetime
import typing
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
UTC = datetime.timezone.utc

#: Discord dynamic timestamp styles, see
#: https://discord.com/developers/docs/reference#message-formatting-timestamp-styles
TimestampStyle = typing.Literal["t", "T", "d", "D", "f", "F", "R"]

#: Offset between an ASCII lowercase letter and its REGIONAL INDICATOR SYMBOL counterpart.
_REGIONAL_INDICATOR_OFFSET = 0x1F1E6 - ord('a')


def to_regionals(text: str) -> str:
    """Convert a two letter region code (``"KR"``) into flag emoji (``"🇰🇷"``)."""
    return ''.join(chr(ord(character) + _REGIONAL_INDICATOR_OFFSET) for character in text.lower())


def resolve_flag(flag: str) -> str:
    """
    Resolve a configured ``flag`` value into something renderable.

    A two letter ASCII code is treated as a region code and converted into a flag emoji;
    anything else (``"🌐"``, ``"<:custom:123>"``) is passed through untouched, so that
    non-country entries such as UTC can still carry an icon.
    """
    if len(flag) == 2 and flag.isascii() and flag.isalpha():
        return to_regionals(flag)

    return flag


@dataclasses.dataclass(frozen=True)
class DisplayTimezone:
    """A timezone we want to spell out explicitly underneath the dynamic timestamp."""

    flag: str
    timezone: ZoneInfo | datetime.timezone
    #: Optional override for the abbreviation. When omitted we ask the zone itself, which
    #: correctly yields e.g. PST vs PDT or CET vs CEST depending on the date.
    label: str | None = None

    @classmethod
    def from_config(cls, config: typing.Mapping[str, str]) -> "DisplayTimezone":
        timezone_name = config["timezone"]
        timezone = UTC if timezone_name.upper() == "UTC" else ZoneInfo(timezone_name)

        return cls(
            flag=resolve_flag(config["flag"]),
            timezone=timezone,
            label=config.get("label", None),
        )

    def abbreviation(self, moment: datetime.datetime) -> str:
        if self.label is not None:
            return self.label

        return moment.astimezone(self.timezone).tzname() or ""


#: The set every lane used before ``display_timezones`` became configurable. It stays the
#: default so that the ASL, BSL, DGS, JSL, LSF and server-wide lanes keep showing exactly
#: the zones their communities already read - a lane opts out by configuring its own.
DEFAULT_DISPLAY_TIMEZONES: tuple[DisplayTimezone, ...] = (
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("Pacific/Honolulu")),
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("America/Los_Angeles")),
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("America/Chicago")),
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("America/New_York")),
    DisplayTimezone(flag=to_regionals("UN"), timezone=UTC),
    DisplayTimezone(flag=to_regionals("GB"), timezone=ZoneInfo("Europe/London")),
    DisplayTimezone(flag=to_regionals("FR"), timezone=ZoneInfo("Europe/Paris")),
    DisplayTimezone(flag=to_regionals("AU"), timezone=ZoneInfo("Australia/Sydney")),
    DisplayTimezone(flag=to_regionals("KR"), timezone=ZoneInfo("Asia/Seoul")),
)

#: What a Korea-hosted lane wants instead: home timezone first, then the regions the KSL
#: classroom actually draws from, then UTC. Configured explicitly by the KSL lane rather
#: than being the global default - see ``templates/sign_language_ksl/meta.yaml``.
KSL_DISPLAY_TIMEZONES: tuple[DisplayTimezone, ...] = (
    DisplayTimezone(flag=to_regionals("KR"), timezone=ZoneInfo("Asia/Seoul")),
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("America/Los_Angeles")),
    DisplayTimezone(flag=to_regionals("US"), timezone=ZoneInfo("America/New_York")),
    DisplayTimezone(flag=to_regionals("EU"), timezone=ZoneInfo("Europe/Paris")),
    DisplayTimezone(flag=to_regionals("AU"), timezone=ZoneInfo("Australia/Sydney")),
    DisplayTimezone(flag="\N{GLOBE WITH MERIDIANS}", timezone=UTC, label="UTC"),
)


def parse_wall_clock(
    text: str,
    timezone: ZoneInfo | datetime.timezone = KST,
) -> datetime.datetime:
    """
    Parse a human written local time into an aware datetime.

    Accepts ``"2026-09-16 20:00"``, ``"2026-09-16T20:00"`` and ``"2026-09-16 20:00:00"``.
    The value is interpreted *in* ``timezone``, which is what a scheduler actually means
    when they write "8pm" - not an offset from UTC that drifts across DST boundaries.
    """
    normalised = text.strip().replace("T", " ")

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.datetime.strptime(normalised, pattern)
        except ValueError:
            continue

        return naive.replace(tzinfo=timezone)

    raise ValueError(f"Could not parse {text!r} as a 'YYYY-MM-DD HH:MM' local time")


def to_unix(moment: datetime.datetime) -> int:
    """UNIX timestamp (whole seconds) for an aware datetime."""
    if moment.tzinfo is None:
        raise ValueError("Refusing to convert a naive datetime - attach a timezone first")

    return int(moment.timestamp())


def discord_timestamp(moment: datetime.datetime, style: TimestampStyle = "f") -> str:
    """
    Render a Discord dynamic timestamp, e.g. ``<t:1789462800:f>``.

    Every Discord client renders this in the *viewer's* own timezone and locale, which is
    what makes a single schedule message readable for Korean and overseas students alike.
    """
    return f"<t:{to_unix(moment)}:{style}>"


def discord_timestamp_pair(moment: datetime.datetime) -> str:
    """
    The combination we use throughout the schedule: an absolute time followed by a
    relative countdown, e.g. ``<t:1789462800:f> (<t:1789462800:R>)``.
    """
    unix = to_unix(moment)

    return f"<t:{unix}:f> (<t:{unix}:R>)"


def timezone_line(
    moment: datetime.datetime,
    display_timezone: DisplayTimezone,
    reference_date: datetime.date | None = None,
) -> str:
    """
    One explicit "🇰🇷 06:00 AM KST" line.

    When ``reference_date`` is supplied and the instant falls on a different calendar day
    in this timezone, the weekday is appended - otherwise a 6am KST class silently looks
    like it happens "today" to a reader in Los Angeles, where it is still yesterday.
    """
    localised = moment.astimezone(display_timezone.timezone)
    text = f"{display_timezone.flag}  {localised:%I:%M %p} {display_timezone.abbreviation(moment)}"

    if reference_date is not None and localised.date() != reference_date:
        text = f"{text} ({localised:%a})"

    return text


def timezone_lines(
    moment: datetime.datetime,
    display_timezones: typing.Sequence[DisplayTimezone] = DEFAULT_DISPLAY_TIMEZONES,
    reference_date: datetime.date | None = None,
) -> list[str]:
    """Explicit time lines for every configured timezone, in configuration order."""
    return [
        timezone_line(moment, display_timezone, reference_date)
        for display_timezone in display_timezones
    ]


class ScheduleStrings(typing.TypedDict):
    """Everything needed to render one occurrence's time, in one bundle."""

    unix: int
    iso: str
    absolute: str
    relative: str
    combined: str
    timezones: list[str]


def build_schedule_strings(
    when: str | datetime.datetime,
    timezone: ZoneInfo | datetime.timezone = KST,
    display_timezones: typing.Sequence[DisplayTimezone] = KSL_DISPLAY_TIMEZONES,
) -> ScheduleStrings:
    """
    The one-call helper: local wall-clock in, everything needed to render it out.

    >>> strings = build_schedule_strings("2026-09-16 20:00")
    >>> strings["combined"]
    '<t:1789556400:f> (<t:1789556400:R>)'
    >>> strings["timezones"][0]
    '🇰🇷  08:00 PM KST'
    """
    moment = when if isinstance(when, datetime.datetime) else parse_wall_clock(when, timezone)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone)

    return ScheduleStrings(
        unix=to_unix(moment),
        iso=moment.isoformat(),
        absolute=discord_timestamp(moment, "f"),
        relative=discord_timestamp(moment, "R"),
        combined=discord_timestamp_pair(moment),
        timezones=timezone_lines(moment, display_timezones, reference_date=moment.astimezone(timezone).date()),
    )

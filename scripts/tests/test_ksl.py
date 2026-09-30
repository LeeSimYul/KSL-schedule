# -*- coding: utf-8 -*-

"""
Tests for the KSL schedule additions.

Runnable two ways, so nobody needs a test runner installed to check their change:

    python scripts/tests/test_ksl.py     # standalone
    pytest scripts/tests/test_ksl.py     # if pytest happens to be available
"""

import asyncio
import contextlib
import datetime
import json
import pathlib
import sys
import tempfile
import types
from zoneinfo import ZoneInfo

SCRIPTS_FOLDER = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_FOLDER))

import discord  # noqa: E402

import embeds  # noqa: E402
import loader  # noqa: E402
import timeutil  # noqa: E402
from definitions import EventLane, EventLaneClosure, EventLaneEvent, Occurrence  # noqa: E402


KST = ZoneInfo("Asia/Seoul")


# --- Helpers ---------------------------------------------------------------------------

@contextlib.contextmanager
def quiet_output():
    """
    Swallow stdout while a test exercises a failure path.

    The delivery code reports failures as GitHub workflow commands, so a mock 403 in a
    passing test would otherwise show up in the run's Annotations panel as a real error -
    alarming, and it buries the one annotation that matters.
    """
    import io

    captured = io.StringIO()

    with contextlib.redirect_stdout(captured):
        yield captured


@contextlib.contextmanager
def quiet_logging(logger_name: str):
    """Silence a logger while a test deliberately triggers the error it reports."""
    import logging

    logger = logging.getLogger(logger_name)
    previous = logger.disabled
    logger.disabled = True

    try:
        yield
    finally:
        logger.disabled = previous


# --- Fixtures --------------------------------------------------------------------------

def make_event(**overrides) -> EventLaneEvent:
    defaults = dict(
        host="Korea_Yujin",
        name="KSL 별빛반",
        tags=["class"],
        paused=False,
        basis=datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST),
        timezone="Asia/Seoul",
        interval=7,
        lane_name="sign_language_ksl",
        title={"ko": "별빛반 (단어)", "en": "Starlight Class (Vocabulary)"},
        level="starlight",
        role="homeroom_teacher",
        platforms=("pcvr", "quest"),
        hand_tracking="recommended",
    )
    defaults.update(overrides)

    return EventLaneEvent(**defaults)


def make_lane(events=None, closures=None, **meta_overrides) -> EventLane:
    meta = {
        "channels": {"schedule": 1276966404301652081},
        "default_timezone": "Asia/Seoul",
        "localization": {"primary": "ko", "secondary": "en"},
        "levels": {
            "seed":      {"emoji": "🌱", "order": 1, "names": {"ko": "씨앗반 - 입문", "en": "Seed Class - Introductory"}},
            "starlight": {"emoji": "⭐", "order": 2, "names": {"ko": "별빛반 - 단어", "en": "Starlight Class - Vocabulary"}},
            "moonlight": {"emoji": "🌙", "order": 3, "names": {"ko": "달빛반 - 문장", "en": "Moonlight Class - Sentences"}},
        },
        "roles": {
            "principal":        {"emoji": "👑", "names": {"ko": "교장선생님", "en": "Principal"}},
            "homeroom_teacher": {"emoji": "🏫", "names": {"ko": "담임선생님", "en": "Homeroom Teacher"}},
        },
    }
    meta.update(meta_overrides)

    return EventLane(
        name="sign_language_ksl",
        meta=meta,
        events=events if events is not None else [make_event()],
        webhook=None,
        webhook_info=None,
        webhook_message_id=None,
        closures=closures or [],
    )


# --- timeutil ----------------------------------------------------------------------------

def test_parse_wall_clock_is_read_in_the_given_zone():
    moment = timeutil.parse_wall_clock("2026-09-16 20:00")

    assert moment.tzinfo is timeutil.KST
    assert moment.hour == 20
    # 20:00 KST is 11:00 UTC - KST is a fixed +09:00 with no daylight saving.
    assert moment.astimezone(datetime.timezone.utc).hour == 11


def test_parse_wall_clock_accepts_iso_separator_and_seconds():
    assert timeutil.parse_wall_clock("2026-09-16T20:00") == timeutil.parse_wall_clock("2026-09-16 20:00:00")


def test_parse_wall_clock_rejects_nonsense():
    try:
        timeutil.parse_wall_clock("next tuesday")
    except ValueError:
        return

    raise AssertionError("Expected a ValueError for an unparseable time")


def test_discord_timestamp_pair_carries_absolute_and_relative_styles():
    moment = timeutil.parse_wall_clock("2026-09-16 20:00")
    unix = timeutil.to_unix(moment)

    assert timeutil.discord_timestamp_pair(moment) == f"<t:{unix}:f> (<t:{unix}:R>)"


def test_to_unix_refuses_naive_datetimes():
    try:
        timeutil.to_unix(datetime.datetime(2026, 9, 16, 20, 0))
    except ValueError:
        return

    raise AssertionError("Expected a ValueError for a naive datetime")


def test_daylight_saving_abbreviations_follow_the_date():
    summer = timeutil.build_schedule_strings("2026-07-16 20:00")["timezones"]
    winter = timeutil.build_schedule_strings("2026-01-16 20:00")["timezones"]

    assert any("PDT" in line for line in summer), summer
    assert any("PST" in line for line in winter), winter
    assert any("CEST" in line for line in summer), summer
    assert any("CET" in line for line in winter), winter


def test_timezone_line_flags_a_different_calendar_day():
    # 05:00 KST on a Monday is still Sunday afternoon on the US west coast.
    moment = timeutil.parse_wall_clock("2026-09-21 05:00")
    lines = timeutil.timezone_lines(
        moment, timeutil.KSL_DISPLAY_TIMEZONES, reference_date=moment.date(),
    )

    korea, los_angeles = lines[0], lines[1]

    assert "(" not in korea, korea
    assert "(Sun)" in los_angeles, los_angeles


def test_regional_indicator_conversion():
    assert timeutil.to_regionals("KR") == "\N{REGIONAL INDICATOR SYMBOL LETTER K}\N{REGIONAL INDICATOR SYMBOL LETTER R}"
    # A literal emoji is passed straight through rather than mangled.
    assert timeutil.resolve_flag("🌐") == "🌐"


# --- Localizer ----------------------------------------------------------------------------

def test_localizer_joins_both_languages():
    localizer = embeds.Localizer({"primary": "ko", "secondary": "en"})

    assert localizer.text({"ko": "별빛반", "en": "Starlight"}) == "별빛반 · Starlight"


def test_localizer_falls_back_when_a_translation_is_missing():
    localizer = embeds.Localizer({"primary": "ko", "secondary": "en"})

    assert localizer.text({"ko": "별빛반"}) == "별빛반"
    assert localizer.text({}, fallback="KSL Class") == "KSL Class"


def test_localizer_deduplicates_identical_translations():
    localizer = embeds.Localizer({"primary": "ko", "secondary": "en"})

    assert localizer.text({"ko": "PCVR", "en": "PCVR"}) == "PCVR"


def test_localizer_without_configuration_is_single_language():
    localizer = embeds.Localizer(None)

    assert not localizer.bilingual
    assert localizer.text({"en": "ASL Class", "ko": "무시됨"}) == "ASL Class"


def test_unconfigured_lanes_keep_the_original_timezone_set():
    """
    Adding display_timezones for KSL must not change what the other lanes show.

    The original set included Honolulu, Chicago and London; a lane that configures
    nothing has to keep all three.
    """
    plain = EventLane(
        name="sign_language_asl",
        meta={"channels": {}, "default_timezone": "America/New_York"},
        events=[], webhook=None, webhook_info=None, webhook_message_id=None,
    )

    zones = embeds.resolve_display_timezones(plain)
    names = [str(zone.timezone) for zone in zones]

    assert zones is timeutil.DEFAULT_DISPLAY_TIMEZONES
    assert "Pacific/Honolulu" in names
    assert "America/Chicago" in names
    assert "Europe/London" in names


def test_a_configured_lane_gets_exactly_what_it_asked_for():
    lane = make_lane(display_timezones=[
        {"flag": "KR", "timezone": "Asia/Seoul"},
        {"flag": "🌐", "timezone": "UTC", "label": "UTC"},
    ])

    zones = embeds.resolve_display_timezones(lane)

    assert len(zones) == 2
    assert zones[1].label == "UTC"


# --- Closures / recharging days ---------------------------------------------------------

def test_closure_covers_inclusive_range():
    closure = EventLaneClosure(datetime.date(2026, 9, 24), datetime.date(2026, 9, 26))

    assert not closure.covers(datetime.date(2026, 9, 23))
    assert closure.covers(datetime.date(2026, 9, 24))
    assert closure.covers(datetime.date(2026, 9, 26))
    assert not closure.covers(datetime.date(2026, 9, 27))


def test_closure_parsing_rejects_a_backwards_range():
    try:
        loader.parse_closure({"date": "2026-09-26", "until": "2026-09-24"})
    except ValueError:
        return

    raise AssertionError("Expected a ValueError for a closure that ends before it starts")


def test_recharging_day_replaces_the_day_and_lists_what_is_off():
    """
    A closed day gets the Recharging Day card, and the card names the sessions that are
    off - struck through, never as if they were running.
    """
    closure = EventLaneClosure(
        datetime.date(2026, 9, 16), datetime.date(2026, 9, 16),
        reason={"ko": "추석 연휴", "en": "Chuseok holiday"},
    )
    lane = make_lane(closures=[closure])
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    wednesday = embeds.build_weekly_embeds(lane, [lane], now=now)[2]

    assert wednesday.colour == embeds.RECHARGE_COLOUR
    assert embeds.RECHARGE_EMOJI in wednesday.description
    assert "재충전의 날" in wednesday.description
    assert "추석 연휴" in wednesday.description
    # Named as off...
    assert "이날 쉬는 수업" in wednesday.description
    assert "~~별빛반 (단어) · Starlight Class (Vocabulary)~~" in wednesday.description
    # ...and not rendered as a running session: no host line, no timezone block.
    assert "진행자" not in wednesday.description
    assert "KST" not in wednesday.description


def test_a_closed_lanes_sessions_show_as_cancelled_on_an_aggregated_schedule():
    """
    The combined server schedule has no closure of its own, so the day stays a normal
    day - but the closed lane's session is marked cancelled there rather than silently
    missing, which is the confusion this whole mechanism exists to prevent.
    """
    ksl = make_lane(closures=[EventLaneClosure(
        datetime.date(2026, 9, 16), datetime.date(2026, 9, 16),
        reason={"ko": "추석 연휴", "en": "Chuseok holiday"},
    )])
    globals_lane = EventLane(
        name="server_global",
        meta={"channels": {}, "default_timezone": "Asia/Seoul", "use_all_events": True},
        events=[],
        webhook=None,
        webhook_info=None,
        webhook_message_id=None,
    )
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    wednesday = embeds.build_weekly_embeds(globals_lane, [globals_lane, ksl], now=now)[2]

    assert wednesday.colour != embeds.RECHARGE_COLOUR
    # The global lane is single-language English, so look for the English rendering.
    assert "[Cancelled]" in wednesday.description, wednesday.description
    assert "~~Starlight Class (Vocabulary)~~" in wednesday.description
    assert "Reason: Chuseok holiday" in wednesday.description
    assert "EDT" not in wednesday.description and "UTC" not in wednesday.description, (
        "a cancelled session must not render the full timezone block"
    )


def test_a_closure_is_read_in_the_timezone_it_was_written_in():
    """
    A Korean holiday is a Korean date, even on a schedule displayed in New York time.

    Regression: a 05:00 KST Tuesday class is 16:00 Monday in New York. With the closure
    on that Monday, the combined schedule used to compare it against the New York date,
    decide the class fell on the holiday, and hide a class that was actually running.
    """
    early = make_event(
        basis=datetime.datetime(2026, 10, 6, 5, 0, tzinfo=KST),   # Tuesday 05:00 KST
        title={"ko": "별빛반 새벽반", "en": "Starlight Early"},
    )
    ksl = make_lane(events=[early], closures=[EventLaneClosure(
        datetime.date(2026, 10, 5), datetime.date(2026, 10, 5),   # Monday, in Korea
    )])
    new_york = ZoneInfo("America/New_York")
    globals_lane = EventLane(
        name="server_global",
        meta={"channels": {}, "default_timezone": "America/New_York", "use_all_events": True},
        events=[], webhook=None, webhook_info=None, webhook_message_id=None,
    )

    schedule = embeds.collect_week(
        globals_lane, [globals_lane, ksl], now=datetime.datetime(2026, 10, 5, 12, 0, tzinfo=new_york),
    )
    running = [occurrence for day in schedule.active.values() for occurrence in day]
    cancelled = [item for day in schedule.cancelled.values() for item in day]

    assert [o.event.title["en"] for o in running] == ["Starlight Early"], (running, cancelled)
    assert not cancelled


def test_an_aggregated_schedule_uses_each_lanes_own_class_and_title_names():
    """
    The combined server schedule has no class or title vocabulary of its own, so KSL
    sessions on it used to show raw keys - "(principal)", "[starlight]".
    """
    ksl = make_lane(events=[make_event(role="principal")])
    globals_lane = EventLane(
        name="server_global",
        meta={"channels": {}, "default_timezone": "Asia/Seoul", "use_all_events": True},
        events=[], webhook=None, webhook_info=None, webhook_message_id=None,
    )

    wednesday = embeds.build_weekly_embeds(
        globals_lane, [globals_lane, ksl], now=datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST),
    )[2].description

    # Resolved from the KSL lane, rendered in the global lane's language (English).
    assert "(👑 Principal)" in wednesday, wednesday
    assert "⭐ [Starlight Class - Vocabulary]" in wednesday
    assert "(principal)" not in wednesday and "[starlight]" not in wednesday


# --- Pausing a session -------------------------------------------------------------------

WEDNESDAY = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)   # a now inside that week


def rendered_wednesday(event) -> str:
    lane = make_lane(events=[event])
    return embeds.build_weekly_embeds(lane, [lane], now=WEDNESDAY)[2].description


def test_a_bare_pause_still_hides_the_session_entirely():
    """
    `paused: true` with no reason keeps its old meaning.

    Other lanes have sessions paused this way for over a year; announcing them would put
    a "cancelled" line on every week's schedule indefinitely.
    """
    description = rendered_wednesday(make_event(paused=True))

    assert "별빛반" not in description
    assert "휴강" not in description
    assert "이 날은 일정이 없습니다" in description


def test_a_pause_with_a_reason_stays_on_the_schedule_marked_cancelled():
    description = rendered_wednesday(make_event(
        paused=True,
        pause_reason={"ko": "담임선생님 개인 사정", "en": "Teacher unavailable"},
    ))

    assert "🚫 **[휴강 · Cancelled]** ~~별빛반 (단어) · Starlight Class (Vocabulary)~~" in description, description
    assert "사유 · Reason: 담임선생님 개인 사정 · Teacher unavailable" in description
    # Still identifiable as *that* slot, in each reader's own timezone...
    assert "<t:1789556400:f>" in description
    assert "Korea_Yujin" in description
    # ...but none of the running-class furniture.
    assert "(<t:1789556400:R>)" not in description, "no countdown to a session that is off"
    assert "PCVR" not in description
    assert "[별빛반 - 단어" not in description
    assert "이 날은 일정이 없습니다" not in description, "the day is not empty - the class is off"


def test_a_cancelled_session_cannot_be_signed_up_for():
    """The bot's RSVP and reminder buttons only ever offer sessions that will run."""
    event = make_event(paused=True, pause_reason={"ko": "휴강"})
    lane = make_lane(events=[event])

    _, active = embeds.collect_week_occurrences(lane, [lane], now=WEDNESDAY)
    schedule = embeds.collect_week(lane, [lane], now=WEDNESDAY)

    assert not any(active.values())
    assert [item.cause for day in schedule.cancelled.values() for item in day] == ["paused"]


def test_a_temporary_pause_ends_by_itself():
    """paused_until pauses sessions on or before the date, then the class simply resumes."""
    event = make_event(
        paused_until=datetime.date(2026, 9, 23),
        pause_reason={"ko": "담임선생님 출장", "en": "Teacher away"},
    )
    lane = make_lane(events=[event])

    def state(now):
        schedule = embeds.collect_week(lane, [lane], now=now)
        if any(schedule.active.values()):
            return "running"
        if any(schedule.cancelled.values()):
            return "cancelled"
        return "hidden"

    assert state(datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)) == "cancelled"   # Wed 9/16
    assert state(datetime.datetime(2026, 9, 22, 12, 0, tzinfo=KST)) == "cancelled"   # Wed 9/23, the last day
    assert state(datetime.datetime(2026, 9, 29, 12, 0, tzinfo=KST)) == "running"     # Wed 9/30, back


def test_a_dated_pause_wins_over_paused_true():
    """Writing both must not leave the class switched off after the intended date."""
    event = make_event(paused=True, paused_until=datetime.date(2026, 9, 23))

    assert event.is_paused_on(datetime.date(2026, 9, 23))
    assert not event.is_paused_on(datetime.date(2026, 9, 30))


def test_the_next_real_session_skips_a_temporary_pause():
    """What old.json publishes as the next session must be the one that will run."""
    event = make_event(paused_until=datetime.date(2026, 9, 23))
    after = datetime.datetime(2026, 9, 14, 0, 0, tzinfo=KST)

    assert event.next_occurrence_after(after) == datetime.datetime(2026, 9, 30, 20, 0, tzinfo=KST)
    assert make_event(paused=True).next_occurrence_after(after) is None


def test_the_resume_date_is_shown_only_while_it_is_still_ahead():
    reason = {"ko": "출장", "en": "Away"}

    description = rendered_wednesday(make_event(paused_until=datetime.date(2026, 9, 30), pause_reason=reason))
    assert "2026-09-30까지 쉬고, 그다음 수업부터 정상 진행합니다 · Resumes after 2026-09-30" in description

    # The last paused session itself: "off until today" would be noise.
    description = rendered_wednesday(make_event(paused_until=datetime.date(2026, 9, 16), pause_reason=reason))
    assert "Resumes after" not in description


def test_a_closure_can_carry_its_own_message():
    custom = EventLaneClosure(
        datetime.date(2026, 9, 16), datetime.date(2026, 9, 16),
        note={"ko": "이번 주는 재충전의 날입니다. 다음 주에 만나요!", "en": "See you next week!"},
    )
    plain = EventLaneClosure(datetime.date(2026, 9, 16), datetime.date(2026, 9, 16))

    def card(closure):
        lane = make_lane(closures=[closure])
        return embeds.build_weekly_embeds(lane, [lane], now=WEDNESDAY)[2].description

    assert "이번 주는 재충전의 날입니다. 다음 주에 만나요!" in card(custom)
    assert "오늘은 수업을 쉽니다" not in card(custom), "a custom note replaces the default"
    assert "오늘은 수업을 쉽니다" in card(plain), "no note falls back to the default"


def test_a_closure_without_a_reason_still_explains_itself_elsewhere():
    ksl = make_lane(closures=[EventLaneClosure(datetime.date(2026, 9, 16), datetime.date(2026, 9, 16))])
    globals_lane = EventLane(
        name="server_global",
        meta={"channels": {}, "default_timezone": "Asia/Seoul", "use_all_events": True},
        events=[], webhook=None, webhook_info=None, webhook_message_id=None,
    )

    wednesday = embeds.build_weekly_embeds(globals_lane, [globals_lane, ksl], now=WEDNESDAY)[2]

    assert "Reason: Recharging Day" in wednesday.description, wednesday.description


def test_pause_fields_load_from_yaml():
    folder = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    folder.mkdir(parents=True)
    (folder / "meta.yaml").write_text(
        (SCRIPTS_FOLDER.parent / "templates" / "sign_language_ksl" / "meta.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (folder / "events.yaml").write_text(
        "events:\n"
        "  - host: ExampleTeacher\n"
        "    name: KSL\n"
        "    tags: [class]\n"
        "    paused: true\n"
        "    pause_reason: { ko: 출장, en: Away }\n"
        "    paused_until: \"2026-10-20\"\n"
        "    schedule: { basis: \"2025-12-02\", day: Tuesday, hour: 5, minute: 0 }\n"
        "closures:\n"
        "  - date: \"2026-10-05\"\n"
        "    reason: { ko: 개천절 }\n"
        "    note: { ko: 다음 주에 만나요 }\n",
        encoding="utf-8",
    )

    lane = loader.load_event_lanes(resolve_webhooks=False, templates_folder=folder.parent)[0]

    assert lane.events[0].pause_reason == {"ko": "출장", "en": "Away"}
    assert lane.events[0].paused_until == datetime.date(2026, 10, 20)
    assert lane.closures[0].note == {"ko": "다음 주에 만나요"}


def test_a_malformed_resume_date_is_rejected_by_the_schema():
    import jsonschema

    schema = json.loads((SCRIPTS_FOLDER.parent / "schema" / "template_events.schema.json").read_text(encoding="utf-8"))
    event = {
        "host": "A", "name": "B", "tags": [], "paused_until": "10월 20일",
        "schedule": {"basis": "2025-12-02", "day": "Tuesday", "hour": 5, "minute": 0},
    }

    try:
        jsonschema.validate({"events": [event]}, schema)
    except jsonschema.ValidationError:
        return

    raise AssertionError("expected a non-ISO paused_until to be rejected")


def test_no_reminder_is_sent_for_a_session_that_is_off():
    from bot.schedule import ScheduleService

    service = ScheduleService()
    running = make_event()
    paused = make_event(paused=True)                                   # hidden pause is still off
    closed_day = datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST)

    service.lanes = [make_lane(events=[running, paused])]
    assert not service.is_cancelled(Occurrence(running, closed_day))
    assert service.is_cancelled(Occurrence(paused, closed_day))

    service.lanes = [make_lane(events=[running], closures=[
        EventLaneClosure(datetime.date(2026, 9, 16), datetime.date(2026, 9, 16)),
    ])]
    assert service.is_cancelled(Occurrence(running, closed_day))


def test_the_live_ksl_schedule_announces_every_pause_it_makes_visible():
    """Guards the templates themselves: an announced pause must carry text to show."""
    lanes = loader.load_event_lanes(resolve_webhooks=False)

    for lane in lanes:
        for event in lane.events:
            if event.pause_reason:
                assert any(text.strip() for text in event.pause_reason.values()), (lane.name, event.name)


# --- Week window --------------------------------------------------------------------------

def test_week_turns_over_at_five_am_monday():
    lane = make_lane()

    before = embeds.week_window(lane, datetime.datetime(2026, 9, 21, 4, 59, tzinfo=KST))[0]
    after = embeds.week_window(lane, datetime.datetime(2026, 9, 21, 5, 1, tzinfo=KST))[0]

    assert before.date() == datetime.date(2026, 9, 14), before
    assert after.date() == datetime.date(2026, 9, 21), after


# --- Embed rendering -----------------------------------------------------------------------

def test_event_block_carries_dynamic_timestamps_and_explicit_zones():
    lane = make_lane()
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    description = embeds.build_weekly_embeds(lane, [lane], now=now)[2].description

    assert "<t:1789556400:f>" in description
    assert "<t:1789556400:R>" in description
    assert "08:00 PM KST" in description
    assert "11:00 AM UTC" in description
    # Bilingual title, level and environment all present.
    assert "별빛반 (단어) · Starlight Class (Vocabulary)" in description
    assert "⭐ [별빛반 - 단어 · Starlight Class - Vocabulary]" in description
    assert "PCVR" in description and "Quest Standalone" in description


def test_lane_without_new_fields_renders_as_before():
    plain = EventLane(
        name="sign_language_asl",
        meta={"channels": {}, "default_timezone": "America/New_York"},
        events=[EventLaneEvent(
            host="Amarante", name="ASL Sign Zone", tags=["sign_zone"], paused=False,
            basis=datetime.datetime(2026, 9, 17, 15, 0, tzinfo=ZoneInfo("America/New_York")),
            timezone="America/New_York", interval=7, lane_name="sign_language_asl",
        )],
        webhook=None, webhook_info=None, webhook_message_id=None,
    )
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))

    description = embeds.build_weekly_embeds(plain, [plain], now=now)[3].description

    assert "**ASL Sign Zone**" in description
    assert "Host: Amarante" in description
    # No level, environment or link furniture when none was configured.
    assert "Level" not in description
    assert "🔗" not in description


def test_paused_events_are_not_scheduled():
    lane = make_lane(events=[make_event(paused=True)])
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    built = embeds.build_weekly_embeds(lane, [lane], now=now)

    assert all("별빛반" not in embed.description for embed in built)


def test_embed_limits_are_enforced():
    oversized = [discord.Embed(description="가" * 5000) for _ in range(3)]

    warnings = embeds.enforce_embed_limits(oversized)

    assert warnings, "expected truncation warnings"
    assert sum(len(embed) for embed in oversized) <= embeds.MAX_TOTAL_EMBED_CHARACTERS
    assert all(len(embed.description) <= embeds.MAX_EMBED_DESCRIPTION for embed in oversized)


def test_well_sized_embeds_are_left_alone():
    lane = make_lane()
    built = embeds.build_weekly_embeds(lane, [lane], now=datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST))
    before = [embed.description for embed in built]

    assert embeds.enforce_embed_limits(built) == []
    assert [embed.description for embed in built] == before


def test_occurrence_embed_has_one_field_per_attribute():
    lane = make_lane()
    occurrence = Occurrence(make_event(), datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST))

    embed = embeds.build_occurrence_embed(occurrence, lane)
    names = [field.name for field in embed.fields]

    assert embed.title == "별빛반 (단어) · Starlight Class (Vocabulary)"
    assert any("진행자" in name for name in names), names
    assert any("학급" in name for name in names), names
    assert any("장비" in name for name in names), names


def test_class_and_equipment_are_on_separate_lines():
    """
    The two belong to different questions - "which class is this?" and "what do I need
    to join?" - and packing them onto one line ran past the width of a phone embed.
    """
    lane = make_lane()
    description = embeds.build_weekly_embeds(
        lane, [lane], now=datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST),
    )[2].description

    class_lines = [line for line in description.splitlines() if "[별빛반" in line]
    equipment_lines = [line for line in description.splitlines() if "PCVR" in line]

    assert len(class_lines) == 1, class_lines
    assert len(equipment_lines) == 1, equipment_lines
    assert class_lines[0] != equipment_lines[0], "class and equipment must not share a line"
    assert "PCVR" not in class_lines[0]


def test_equipment_options_are_pipe_separated():
    lane = make_lane()
    event = make_event(platforms=("pcvr", "quest", "desktop"), hand_tracking="supported")

    line = embeds.format_environment(event, embeds.Localizer(lane.meta["localization"]))

    assert line.startswith("🖥️ PCVR | 🥽 Quest Standalone | 💻 Desktop | 🖐️"), line


def test_the_three_ksl_classes_render_with_their_own_icons():
    lane = make_lane()
    localizer = embeds.Localizer(lane.meta["localization"])
    levels = lane.meta["levels"]

    assert embeds.format_level("seed", levels, localizer).startswith("🌱 [씨앗반 - 입문")
    assert embeds.format_level("starlight", levels, localizer).startswith("⭐ [별빛반 - 단어")
    assert embeds.format_level("moonlight", levels, localizer).startswith("🌙 [달빛반 - 문장")
    assert embeds.format_level(None, levels, localizer) is None


def test_host_titles_resolve_from_the_lane_roles_block():
    lane = make_lane()
    localizer = embeds.Localizer(lane.meta["localization"])
    roles = lane.meta["roles"]

    assert embeds.resolve_role("principal", roles, localizer) == "👑 교장선생님 · Principal"
    # An inline mapping still works, for a guest who holds no standing title.
    assert embeds.resolve_role({"ko": "초청 강사"}, roles, localizer) == "초청 강사"
    assert embeds.resolve_role(None, roles, localizer) is None


def test_an_unknown_class_or_title_is_shown_rather_than_dropped():
    lane = make_lane()
    localizer = embeds.Localizer(lane.meta["localization"])

    # A typo in a key must be visible in the schedule, not silently omitted.
    assert embeds.format_level("typo", lane.meta["levels"], localizer) == "[typo]"
    assert embeds.resolve_role("typo", lane.meta["roles"], localizer) == "typo"


def test_a_session_without_a_class_shows_no_class_line():
    lane = make_lane(events=[make_event(level=None, kind="social")])
    description = embeds.build_weekly_embeds(
        lane, [lane], now=datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST),
    )[2].description

    assert "[" not in description.split("**")[-1] or "별빛반 -" not in description
    assert "PCVR" in description, "equipment should still be listed"


def test_the_ksl_lane_publishes_japan_time():
    """
    Japan time is configured for the lane, and reaches a rendered session.

    This deliberately renders a session of its own rather than whatever falls in the
    current week. Which sessions land in "this week" depends on the day CI runs, on how
    many sessions currently exist, and on whether a closure covers them - so a
    legitimately quiet week would fail a test about timezone configuration. That is
    exactly what happened over 개천절 2026, when the only two remaining sessions both fell
    inside the holiday closure and the week rendered with no sessions at all.
    """
    lanes = loader.load_event_lanes(resolve_webhooks=False)
    ksl = loader.find_lane(lanes, "sign_language_ksl")

    display_timezones = embeds.resolve_display_timezones(ksl)

    assert "Asia/Tokyo" in [str(zone.timezone) for zone in display_timezones]

    occurrence = Occurrence(make_event(), datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST))
    block = embeds.format_occurrence_block(
        occurrence,
        embeds.Localizer(ksl.meta.get("localization", None)),
        ksl.meta.get("levels", {}),
        display_timezones,
        roles=ksl.meta.get("roles", {}),
    )

    # Seoul and Tokyo are both a fixed UTC+9, so the two lines read the same time.
    assert "\N{REGIONAL INDICATOR SYMBOL LETTER J}\N{REGIONAL INDICATOR SYMBOL LETTER P}" in block, block
    assert "08:00 PM JST" in block, block
    assert "08:00 PM KST" in block, block


def test_a_week_with_no_sessions_still_renders():
    """
    A quiet week is a valid schedule, not a failure.

    Every session can legitimately fall inside a holiday closure, or be paused between
    terms. The schedule still has to publish - seven day cards, no crash, no empty
    message.
    """
    lanes = loader.load_event_lanes(resolve_webhooks=False)
    ksl = loader.find_lane(lanes, "sign_language_ksl")

    # A week far enough out that nothing in the template reaches it is not something we
    # can arrange, so suppress the sessions instead and keep the lane otherwise real.
    quiet = EventLane(
        name=ksl.name, meta=ksl.meta, events=[], webhook=None,
        webhook_info=None, webhook_message_id=None, closures=ksl.closures,
    )

    built = embeds.build_weekly_embeds(quiet, [quiet], now=datetime.datetime(2026, 9, 28, 12, 0, tzinfo=KST))

    assert len(built) == 7, "expected one embed per weekday"
    assert all(embed.description for embed in built), "no day card may be empty"
    assert embeds.enforce_embed_limits(built) == []


def test_the_ksl_lane_uses_only_the_three_official_classes():
    lanes = loader.load_event_lanes(resolve_webhooks=False)
    ksl = loader.find_lane(lanes, "sign_language_ksl")

    assert set(ksl.meta["levels"]) == {"seed", "starlight", "moonlight"}
    assert set(ksl.meta["roles"]) == {
        "principal", "homeroom_teacher", "student_council_president",
        "appreciation_head", "exploration_head",
    }

    # Every class references a real class id, and every title a real role id.
    for event in ksl.events:
        if event.level:
            assert event.level in ksl.meta["levels"], (event.name, event.level)
        if isinstance(event.role, str) and event.role:
            assert event.role in ksl.meta["roles"], (event.name, event.role)


# --- Identity ------------------------------------------------------------------------------

def test_event_keys_are_stable_and_distinct():
    assert make_event().key == make_event().key
    assert make_event().key != make_event(host="Korea_Minseo").key


def test_custom_ids_fit_discord_s_hundred_character_limit():
    occurrence = Occurrence(make_event(), datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST))
    custom_id = f"ksl:occ:remind:sign_language_ksl:{occurrence.event.key}:{int(occurrence.starts_at.timestamp())}"

    assert len(custom_id) <= 100, custom_id

    from bot.views import OccurrenceActionButton
    assert OccurrenceActionButton.__discord_ui_compiled_template__.match(custom_id)


# --- RSVP behaviour ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append(content)

    async def edit_message(self, content=None, **kwargs):
        self.messages.append(content)


class FakeInteraction:
    def __init__(self, bot, user_id=1234):
        self.client = bot
        self.user = types.SimpleNamespace(id=user_id)
        self.response = FakeResponse()


def test_rsvp_and_reminder_buttons_toggle():
    from bot.storage import Storage
    from bot.views import apply_action

    database = pathlib.Path(tempfile.mkdtemp()) / "test.sqlite3"
    storage = Storage(database)
    bot = types.SimpleNamespace(
        storage=storage,
        config=types.SimpleNamespace(reminder_lead_minutes=15),
    )

    lane = make_lane()
    occurrence = Occurrence(make_event(), datetime.datetime(2026, 9, 16, 20, 0, tzinfo=KST))

    interaction = FakeInteraction(bot)
    asyncio.run(apply_action(interaction, "rsvp", lane, occurrence))
    assert storage.get_rsvp(occurrence.key, 1234) == "going"
    assert "참석 신청이 접수" in interaction.response.messages[0]

    # Pressing again withdraws it.
    asyncio.run(apply_action(interaction, "rsvp", lane, occurrence))
    assert storage.get_rsvp(occurrence.key, 1234) is None

    asyncio.run(apply_action(interaction, "remind", lane, occurrence))
    assert storage.has_reminder(occurrence.key, 1234)

    asyncio.run(apply_action(interaction, "remind", lane, occurrence))
    assert not storage.has_reminder(occurrence.key, 1234)

    storage.close()


def test_reminders_are_due_only_inside_the_lead_and_grace_window():
    from bot.storage import Storage

    database = pathlib.Path(tempfile.mkdtemp()) / "test.sqlite3"
    storage = Storage(database)
    now = datetime.datetime(2026, 9, 16, 19, 50, tzinfo=datetime.timezone.utc)

    starts_at = now + datetime.timedelta(minutes=10)        # inside the 15 minute lead
    too_far = now + datetime.timedelta(minutes=90)          # not yet
    long_gone = now - datetime.timedelta(minutes=120)       # missed while offline

    storage.add_reminder("soon:1", 1, "ksl", "a" * 16, starts_at, 15)
    storage.add_reminder("later:1", 2, "ksl", "b" * 16, too_far, 15)
    storage.add_reminder("gone:1", 3, "ksl", "c" * 16, long_gone, 15)

    due = {reminder.occurrence_key for reminder in storage.due_reminders(now, grace_minutes=30)}

    assert due == {"soon:1"}, due
    storage.close()


# --- Loader round trip ---------------------------------------------------------------------------

def test_every_template_in_the_repository_still_loads():
    lanes = loader.load_event_lanes(resolve_webhooks=False)

    assert lanes, "expected at least one lane"
    assert loader.find_lane(lanes, "sign_language_ksl") is not None


def summarise(events) -> str:
    """One readable line per event - a dataclass dump of a whole lane tells you nothing."""
    return "\n".join(
        f"    {event.schedule_summary if hasattr(event, 'schedule_summary') else ''}"
        f"{event.basis:%a %H:%M}  {event.host:<14} {event.title.get('ko') or event.name}"
        for event in events
    )


def test_documented_examples_load_and_render():
    """
    The files under docs/examples must stay loadable, and stay documentation.

    They are never published - the build only reads templates/*/meta.yaml - so a real
    class added here silently never reaches Discord. That has happened, which is why the
    count is pinned rather than left open.
    """
    examples = SCRIPTS_FOLDER.parent / "docs" / "examples"
    staging = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    staging.mkdir(parents=True)

    (staging / "meta.yaml").write_text((examples / "meta.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (staging / "events.yaml").write_text((examples / "events.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    lanes = loader.load_event_lanes(resolve_webhooks=False, templates_folder=staging.parent)
    lane = lanes[0]

    assert len(lane.events) == 5, (
        f"docs/examples/events.example.yaml now has {len(lane.events)} events, expected 5.\n\n"
        f"{summarise(lane.events)}\n\n"
        f"  docs/examples/ is DOCUMENTATION and is never published to Discord.\n"
        f"  Adding a real class here means it never appears on the schedule.\n\n"
        f"  실제 수업을 추가하려던 것이라면 이 파일이 아니라\n"
        f"    templates/sign_language_ksl/events.yaml\n"
        f"  에 넣어야 합니다. 두 파일 이름이 같으니 경로를 확인해 주세요.\n\n"
        f"  예시 파일을 일부러 늘린 것이라면 이 테스트의 기대값 5를 함께 고쳐 주세요."
    )
    assert len(lane.closures) == 2, f"expected 2 documented closures, got {len(lane.closures)}"

    # The examples exist to demonstrate the features, so check they still do.
    assert {event.level for event in lane.events if event.level} == {"starlight", "moonlight"}
    assert any(not event.level for event in lane.events), "one example should have no class line"

    built = embeds.build_weekly_embeds(lane, lanes, now=datetime.datetime(2026, 9, 23, 12, 0, tzinfo=KST))

    assert embeds.enforce_embed_limits(built) == []
    assert any(embed.colour == embeds.RECHARGE_COLOUR for embed in built)


def test_real_sessions_are_not_parked_in_the_examples_file():
    """
    Catch a real class pasted into docs/examples instead of the live template.

    The two files are both called events.yaml, so it is easy to edit the wrong one in a
    web editor - and the symptom is silent: the class simply never appears on Discord.
    The example hosts are deliberately placeholder names, so any host that also appears
    in the live schedule is a sign the edit landed in the wrong file.
    """
    examples = SCRIPTS_FOLDER.parent / "docs" / "examples"
    staging = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    staging.mkdir(parents=True)

    (staging / "meta.yaml").write_text((examples / "meta.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (staging / "events.yaml").write_text((examples / "events.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    example_lane = loader.load_event_lanes(resolve_webhooks=False, templates_folder=staging.parent)[0]
    live_lane = loader.find_lane(loader.load_event_lanes(resolve_webhooks=False), "sign_language_ksl")

    example_hosts = {event.host for event in example_lane.events}
    live_hosts = {event.host for event in live_lane.events}
    shared = example_hosts & live_hosts

    assert not shared, (
        f"These hosts appear in BOTH the live schedule and the examples: {sorted(shared)}\n\n"
        f"  docs/examples/ is never published. If one of these is a real session, move it to\n"
        f"    templates/sign_language_ksl/events.yaml\n\n"
        f"  실제 진행자 이름이 예시 파일에 들어가 있습니다. 예시에는 가상의 이름을 써 주세요."
    )


# --- Failure handling ---------------------------------------------------------------------------

class FakeWebhook:
    """Stands in for discord.SyncWebhook, failing in whichever way a test needs."""

    def __init__(self, mode="ok"):
        self.mode = mode
        self.sent = False

    def _fail(self):
        response = types.SimpleNamespace(status=0, reason="test")

        # Bodies as Discord sends them: the JSON code is what tells the failures apart.
        if self.mode == "notfound":
            response.status = 404
            raise discord.NotFound(response, {"message": "Unknown Message", "code": 10008})
        if self.mode == "webhook_gone":
            response.status = 404
            raise discord.NotFound(response, {"message": "Unknown Webhook", "code": 10015})
        if self.mode == "bad_token":
            response.status = 401
            raise discord.HTTPException(response, {"message": "Invalid Webhook Token", "code": 50027})
        if self.mode == "forbidden":
            response.status = 403
            raise discord.Forbidden(response, {"message": "Missing Access", "code": 50001})
        if self.mode == "http":
            response.status = 400
            raise discord.HTTPException(response, {"message": "Bad Request"})

    def edit_message(self, **kwargs):
        self._fail()
        return types.SimpleNamespace(id=111)

    def send(self, **kwargs):
        self.sent = True

        # A webhook that is gone cannot post either; nothing else fails on send.
        if self.mode in ("webhook_gone", "bad_token"):
            self._fail()

        return types.SimpleNamespace(id=222)


def make_webhook_lane(name, mode, message_id=999):
    lane = make_lane()

    return EventLane(
        name=name, meta=lane.meta, events=lane.events,
        webhook=FakeWebhook(mode),
        # Carries the real secret name, so the failure messages under test name the
        # variable an operator actually has to go and set.
        webhook_info={"url": "KSL_SCHEDULE_WEBHOOK_URL", "message_id": "KSL_SCHEDULE_MESSAGE_ID"},
        webhook_message_id=message_id,
    )


def test_one_failing_lane_does_not_stop_the_others():
    from formats.webhook import send_webhooks

    lanes = [
        make_webhook_lane("ok_lane", "ok"),
        make_webhook_lane("revoked", "forbidden"),
        make_webhook_lane("api_error", "http"),
    ]

    with quiet_output():
        delivered = send_webhooks(lanes)

    assert set(delivered) == {"ok_lane"}, delivered


def test_nothing_is_posted_when_there_is_no_message_to_edit():
    """
    The schedule is one message that gets edited, not a stream of new ones.

    An unattended run that posts whenever it cannot find the stored message leaves
    duplicate schedules in the channel, and every one needs a human to notice and delete
    it. So a missing ID fails the run loudly instead.
    """
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("no_id", "ok", message_id=None)

    try:
        with quiet_output():
            send_webhooks([lane])
    except RuntimeError:
        pass

    assert not lane.webhook.sent, "nothing may be posted without allow_create"


def test_a_deleted_message_is_not_silently_replaced():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("deleted", "notfound")

    try:
        with quiet_output():
            send_webhooks([lane])
    except RuntimeError:
        pass

    assert not lane.webhook.sent, "a 404 must not quietly become a second schedule"


def test_the_failure_explains_how_to_publish_deliberately():
    from formats.webhook import deliver_lane, ScheduleMessageMissing

    lane = make_webhook_lane("no_id", "ok", message_id=None)

    try:
        deliver_lane(lane, [lane])
    except ScheduleMessageMissing as error:
        message = str(error)
        assert "allow_create" in message, message
        assert "KSL_SCHEDULE_MESSAGE_ID" in message, message
        return

    raise AssertionError("Expected ScheduleMessageMissing")


def test_allow_create_publishes_the_first_message():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("first_post", "ok", message_id=None)

    with quiet_output():
        delivered = send_webhooks([lane], allow_create=True)

    assert lane.webhook.sent
    assert delivered["first_post"] == 222


def test_allow_create_replaces_a_deleted_message():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("deleted", "notfound")

    with quiet_output():
        delivered = send_webhooks([lane], allow_create=True)

    assert lane.webhook.sent
    assert delivered["deleted"] == 222


def test_an_existing_message_is_edited_never_reposted():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("normal", "ok")

    with quiet_output():
        delivered = send_webhooks([lane])

    assert not lane.webhook.sent, "the normal path must edit, not post"
    assert delivered["normal"] == 111


def deliver_and_capture(lane, allow_create=False):
    """Deliver one lane that is expected to fail, returning what it reported."""
    from formats.webhook import send_webhooks

    with quiet_output() as captured:
        try:
            send_webhooks([lane], allow_create=allow_create)
        except RuntimeError:
            pass

    return captured.getvalue()


def test_a_deleted_webhook_is_not_mistaken_for_a_deleted_message():
    """
    Both are a 404, but the fixes are opposite.

    A deleted message is fixed by posting a replacement; a deleted webhook is fixed by
    replacing the URL secret, and "post a replacement" through it only fails again. The
    report must name the URL secret, not send the operator after the message ID.
    """
    report = deliver_and_capture(make_webhook_lane("gone", "webhook_gone"))

    assert "KSL_SCHEDULE_WEBHOOK_URL" in report, report
    assert "웹후크 자체가 삭제" in report, report
    assert "KSL_SCHEDULE_MESSAGE_ID" not in report, report


def test_a_deleted_webhook_is_reported_even_with_allow_create():
    lane = make_webhook_lane("gone", "webhook_gone")
    report = deliver_and_capture(lane, allow_create=True)

    assert "KSL_SCHEDULE_WEBHOOK_URL" in report, report
    assert "posting a replacement" not in report, "a dead webhook cannot post a replacement"


def test_a_deleted_message_still_points_at_the_message_id():
    report = deliver_and_capture(make_webhook_lane("deleted", "notfound"))

    assert "KSL_SCHEDULE_MESSAGE_ID" in report, report
    assert "allow_create" in report, report


def test_a_rejected_token_points_at_the_url_secret():
    report = deliver_and_capture(make_webhook_lane("reset", "bad_token"))

    assert "KSL_SCHEDULE_WEBHOOK_URL" in report, report
    assert "토큰" in report, report


def test_lost_channel_access_is_not_blamed_on_a_deleted_webhook():
    report = deliver_and_capture(make_webhook_lane("locked", "forbidden"))

    assert "권한" in report, report
    assert "삭제" not in report, report


def test_every_lane_failing_fails_the_build():
    from formats.webhook import send_webhooks

    try:
        with quiet_output():
            send_webhooks([make_webhook_lane("a", "forbidden"), make_webhook_lane("b", "forbidden")])
    except RuntimeError:
        return

    raise AssertionError("Expected a RuntimeError when no lane could be delivered")


def test_lanes_without_a_webhook_are_skipped_not_failed():
    from formats.webhook import send_webhooks

    with quiet_output():
        assert send_webhooks([make_lane()]) == {}


def test_a_broken_template_keeps_the_last_good_schedule():
    from bot.schedule import ScheduleService

    service = ScheduleService()
    service.reload()
    good = service.lanes

    assert good, "expected the real templates to load"

    broken = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    broken.mkdir(parents=True)
    (broken / "meta.yaml").write_text("channels: {}\ndefault_timezone: [not a string\n", encoding="utf-8")
    (broken / "events.yaml").write_text("events: []\n", encoding="utf-8")

    service.templates_folder = broken.parent

    # The failure is the point of this test, and the service logs it with a full
    # traceback. Left on, that traceback lands in every CI run of a passing test and
    # makes a real failure harder to spot.
    with quiet_logging("bot.schedule"):
        assert service.reload() is False

    # The bot keeps serving what it had rather than emptying the schedule channel.
    assert service.lanes is good


def test_a_broken_template_at_startup_is_fatal():
    from bot.schedule import ScheduleService

    broken = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    broken.mkdir(parents=True)
    (broken / "meta.yaml").write_text("channels: {}\ndefault_timezone: [not a string\n", encoding="utf-8")
    (broken / "events.yaml").write_text("events: []\n", encoding="utf-8")

    service = ScheduleService(templates_folder=broken.parent)

    try:
        service.reload()
    except Exception:
        return

    raise AssertionError("Expected a startup reload with no fallback to raise")


# --- Template syntax errors ---------------------------------------------------------------------

def broken_template(body: str) -> pathlib.Path:
    folder = pathlib.Path(tempfile.mkdtemp())
    path = folder / "events.yaml"
    path.write_text(body, encoding="utf-8")

    return path


def read_broken(body: str) -> str:
    """Read a deliberately broken template and return the error text."""
    from loader import TemplateError, read_yaml

    try:
        read_yaml(broken_template(body))
    except TemplateError as error:
        return str(error)

    raise AssertionError("Expected the template to be rejected")


def test_a_character_glued_onto_a_key_is_reported_against_the_right_line():
    """
    The real failure this came from: two box-drawing characters pasted onto `events:`.

    PyYAML blames the following line and says "did not find expected <document start>",
    which names neither the line to edit nor anything a schedule editor can act on.
    """
    message = read_broken(
        "events:\u2500\u2500\n"
        "  # \uc218\uc5c5\n"
        "  - host: Korea_Yujin\n"
        "    name: KSL\n"
    )

    assert "events.yaml:" in message
    # The hint has to name line 1, not line 3 where parsing gave up.
    assert "Line 1: no space after the colon" in message, message
    assert "events:\u2500\u2500" in message


def test_a_tab_indent_is_named_as_such():
    message = read_broken("events:\n\t- host: A\n")

    assert "Line 2 is indented with a tab" in message, message


def test_an_unclosed_quote_is_named_as_such():
    message = read_broken('events:\n  - host: "Korea_Yujin\n    name: B\n')

    assert "Line 2 has an unclosed quote" in message, message


def test_a_missing_space_inside_a_list_item_is_found():
    message = read_broken("events:\n  - host:Korea_Yujin\n    name: B\n")

    assert "Line 2: no space after the colon" in message, message


def test_the_error_report_shows_the_offending_line_with_a_caret():
    message = read_broken("events:\n\t- host: A\n")
    lines = message.splitlines()

    assert any(line.strip().startswith("2 |") for line in lines), message
    assert any(line.strip().startswith("| ") and "^" in line for line in lines), message


def test_a_forgotten_parent_key_is_named():
    """
    The real failure this came from: ko/en typed straight under `paused: true`, with
    the `pause_reason:` line between them never written. The parser only says "mapping
    values are not allowed in this context" on the ko line.
    """
    message = read_broken(
        "events:\n"
        "  - host: gom 0703\n"
        "    name: KSL\n"
        "    paused: true\n"
        "      ko: \ub2f4\uc784\uc120\uc0dd\ub2d8 \uac1c\uc778 \uc0ac\uc815\n"
        "      en: Teacher unavailable\n"
    )

    assert "Line 4 already has a value, so line 5 cannot be nested" in message, message
    assert "pause_reason:" in message, "a ko/en child should suggest the translation keys"


def test_the_parent_key_hint_stays_quiet_where_nesting_is_legal():
    from loader import missing_parent_hint

    # A block scalar is followed by deeper lines by design.
    assert missing_parent_hint(["header: |", "  # 주간 시간표"], 1) is None
    # So is a key with no value yet.
    assert missing_parent_hint(["pause_reason:", "  ko: 사유"], 1) is None
    # A sibling at the same depth is not nested at all.
    assert missing_parent_hint(["paused: true", "pause_reason:"], 1) is None
    # `key:value` is a different mistake with its own hint.
    assert missing_parent_hint(["events:\u2500\u2500", "  - host: A"], 1) is None


def test_the_parent_key_hint_names_any_key_not_only_translations():
    message = read_broken("schedule: weekly\n  hour: 5\n")

    assert "Line 1 already has a value" in message, message
    assert "pause_reason" not in message, "only a ko/en child should suggest translation keys"


def test_valid_templates_produce_no_false_hint():
    """Colons inside URLs and Korean text must not be mistaken for a missing space."""
    from loader import read_yaml

    data = read_yaml(broken_template(
        "events:\n"
        "  - host: Korea_Yujin\n"
        "    vrchat:\n"
        "      instance_url: https://vrchat.com/i/abc\n"
        "    title:\n"
        "      ko: \ubcc4\ube5b\ubc18 (\ub2e8\uc5b4)\n"
    ))

    assert data["events"][0]["vrchat"]["instance_url"] == "https://vrchat.com/i/abc"


# --- GitHub Actions annotations -------------------------------------------------------------------

def test_annotations_always_open_a_new_line():
    """
    GitHub only parses a workflow command at the start of a line.

    The build prints progress with the cursor left mid-line ("Parsing meta schema... "),
    so an annotation emitted without a leading newline silently degrades into ordinary
    log text - it still reads fine locally, which is exactly what makes it easy to miss.
    """
    import io
    import contextlib
    import ci

    captured = io.StringIO()

    with contextlib.redirect_stdout(captured):
        print("  Doing something... ", end="")
        ci.annotate("warning", "something to notice")
        print("OK")

    lines = captured.getvalue().splitlines()

    assert any(line.startswith("::warning::") for line in lines), lines


def test_the_real_build_emits_only_well_formed_annotations():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_FOLDER / "build_manifests.py"), "--no-send"],
        capture_output=True, text=True, cwd=str(SCRIPTS_FOLDER.parent),
    )

    # Without this the failure surfaces as a bare CalledProcessError, which says nothing
    # about what the build actually objected to.
    assert result.returncode == 0, (
        f"build_manifests.py exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-2000:]}"
    )

    misplaced = [
        line for line in result.stdout.splitlines()
        if ("::warning::" in line or "::error::" in line or "::notice::" in line)
        and not line.startswith("::")
    ]

    assert not misplaced, misplaced


# --- Python / JavaScript parity -------------------------------------------------------------------

def test_javascript_helper_matches_the_python_one():
    """
    The JS port renders the same strings as the Python original.

    Skipped rather than failed when Node is unavailable - the JS helper is for downstream
    clients, and not every contributor needs a Node install to work on the schedule.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")

    if node is None:
        print("      (skipped - node is not installed)")
        return

    script = SCRIPTS_FOLDER / "js" / "ksl-timeutil.mjs"
    moments = ["2026-09-16 20:00", "2026-01-16 20:00", "2026-09-21 05:00", "2026-07-04 23:30"]

    result = subprocess.run(
        [
            node, "--input-type=module", "-e",
            f"import {{ buildScheduleStrings }} from {json.dumps(script.as_uri())};"
            f"console.log(JSON.stringify({json.dumps(moments)}.map((moment) => buildScheduleStrings(moment))));",
        ],
        capture_output=True, text=True, check=True,
    )

    from_javascript = json.loads(result.stdout)

    for moment, javascript in zip(moments, from_javascript):
        python = timeutil.build_schedule_strings(moment)

        assert javascript["unix"] == python["unix"], moment
        assert javascript["combined"] == python["combined"], moment
        assert javascript["timezones"] == python["timezones"], (
            moment, javascript["timezones"], python["timezones"]
        )


# --- Runner -------------------------------------------------------------------------------------

def main() -> int:
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]

    failures = []

    for name, test in tests:
        try:
            test()
        except Exception as error:  # noqa: BLE001 - a test runner reports, it does not raise
            failures.append((name, error))
            print(f"FAIL  {name}: {error.__class__.__name__}: {error}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")

    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())

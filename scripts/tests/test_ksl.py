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


def test_recharging_day_replaces_the_day_and_suppresses_its_classes():
    # The class is on Wednesday; the closure covers that Wednesday.
    closure = EventLaneClosure(
        datetime.date(2026, 9, 16), datetime.date(2026, 9, 16),
        reason={"ko": "추석 연휴", "en": "Chuseok holiday"},
    )
    lane = make_lane(closures=[closure])
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    built = embeds.build_weekly_embeds(lane, [lane], now=now)
    wednesday = built[2]

    assert wednesday.colour == embeds.RECHARGE_COLOUR
    assert embeds.RECHARGE_EMOJI in wednesday.description
    assert "재충전의 날" in wednesday.description
    assert "추석 연휴" in wednesday.description
    # The class itself must not also be listed.
    assert "별빛반" not in wednesday.description


def test_a_lane_closure_removes_its_events_from_an_aggregated_schedule():
    ksl = make_lane(closures=[EventLaneClosure(datetime.date(2026, 9, 16), datetime.date(2026, 9, 16))])
    globals_lane = EventLane(
        name="server_global",
        meta={"channels": {}, "default_timezone": "Asia/Seoul", "use_all_events": True},
        events=[],
        webhook=None,
        webhook_info=None,
        webhook_message_id=None,
    )
    now = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=KST)

    built = embeds.build_weekly_embeds(globals_lane, [globals_lane, ksl], now=now)
    wednesday = built[2]

    # The global lane has no closure of its own, so the day is a normal day...
    assert wednesday.colour != embeds.RECHARGE_COLOUR
    # ...but the closed lane's class is still gone from it.
    assert "별빛반" not in wednesday.description


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

        if self.mode == "notfound":
            response.status = 404
            raise discord.NotFound(response, {"message": "Unknown Message"})
        if self.mode == "forbidden":
            response.status = 403
            raise discord.Forbidden(response, {"message": "Missing Access"})
        if self.mode == "http":
            response.status = 400
            raise discord.HTTPException(response, {"message": "Bad Request"})

    def edit_message(self, **kwargs):
        self._fail()
        return types.SimpleNamespace(id=111)

    def send(self, **kwargs):
        self.sent = True
        return types.SimpleNamespace(id=222)


def make_webhook_lane(name, mode, message_id=999):
    lane = make_lane()

    return EventLane(
        name=name, meta=lane.meta, events=lane.events,
        webhook=FakeWebhook(mode), webhook_info={}, webhook_message_id=message_id,
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


def test_a_deleted_schedule_message_is_reposted():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("deleted", "notfound")
    with quiet_output():
        delivered = send_webhooks([lane])

    assert lane.webhook.sent, "expected a fresh message to be posted after the 404"
    assert delivered["deleted"] == 222


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

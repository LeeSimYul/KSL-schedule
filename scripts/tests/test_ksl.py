# -*- coding: utf-8 -*-

"""
Tests for the KSL schedule additions.

Runnable two ways, so nobody needs a test runner installed to check their change:

    python scripts/tests/test_ksl.py     # standalone
    pytest scripts/tests/test_ksl.py     # if pytest happens to be available
"""

import asyncio
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
        level="root",
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
        "levels": {"root": {"emoji": "🌱", "names": {"ko": "뿌리 (초급)", "en": "Root (Beginner)"}}},
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
    assert "뿌리 (초급) · Root (Beginner)" in description
    assert "PCVR" in description and "Quest" in description


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
    assert any("난이도" in name for name in names), names


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


def test_documented_examples_load_and_render():
    examples = SCRIPTS_FOLDER.parent / "docs" / "examples"
    staging = pathlib.Path(tempfile.mkdtemp()) / "sign_language_ksl"
    staging.mkdir(parents=True)

    (staging / "meta.yaml").write_text((examples / "meta.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (staging / "events.yaml").write_text((examples / "events.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    lanes = loader.load_event_lanes(resolve_webhooks=False, templates_folder=staging.parent)
    lane = lanes[0]

    assert len(lane.events) == 5, lane.events
    assert len(lane.closures) == 2

    built = embeds.build_weekly_embeds(lane, lanes, now=datetime.datetime(2026, 9, 23, 12, 0, tzinfo=KST))

    assert embeds.enforce_embed_limits(built) == []
    assert any(embed.colour == embeds.RECHARGE_COLOUR for embed in built)


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

    delivered = send_webhooks(lanes)

    assert set(delivered) == {"ok_lane"}, delivered


def test_a_deleted_schedule_message_is_reposted():
    from formats.webhook import send_webhooks

    lane = make_webhook_lane("deleted", "notfound")
    delivered = send_webhooks([lane])

    assert lane.webhook.sent, "expected a fresh message to be posted after the 404"
    assert delivered["deleted"] == 222


def test_every_lane_failing_fails_the_build():
    from formats.webhook import send_webhooks

    try:
        send_webhooks([make_webhook_lane("a", "forbidden"), make_webhook_lane("b", "forbidden")])
    except RuntimeError:
        return

    raise AssertionError("Expected a RuntimeError when no lane could be delivered")


def test_lanes_without_a_webhook_are_skipped_not_failed():
    from formats.webhook import send_webhooks

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

# -*- coding: utf-8 -*-

"""
Buttons and select menus.

Everything here is built on :class:`discord.ui.DynamicItem`, which reconstructs a
component from its ``custom_id`` when it is clicked. That matters because the schedule
message is rewritten every fifteen minutes and survives bot restarts: a view held in
memory would stop responding the moment the process did, whereas a dynamic item is
rebuilt on demand from the id embedded in the message itself.

Discord caps a ``custom_id`` at 100 characters, which is why the ids below carry a short
event digest and a UNIX timestamp rather than a readable name.
"""

import datetime
import logging
import re
import typing

import discord

from definitions import EventLane, Occurrence
from embeds import Localizer


log = logging.getLogger(__name__)

RSVP_LABEL = {"ko": "참석 신청", "en": "RSVP"}
REMIND_LABEL = {"ko": "{minutes}분 전 알림 받기", "en": "Remind me {minutes}m before"}

#: Lane names come from directory names, so this is the full alphabet they can use.
LANE_PATTERN = r"[A-Za-z0-9_\-]{1,32}"


def rsvp_label(localizer: Localizer) -> str:
    return localizer.text(RSVP_LABEL, fallback="RSVP")[:80]


def remind_label(localizer: Localizer, minutes: int) -> str:
    template = {language: text.format(minutes=minutes) for language, text in REMIND_LABEL.items()}

    return localizer.text(template, fallback=f"Remind me {minutes}m before")[:80]


def occurrence_option_label(occurrence: Occurrence, localizer: Localizer) -> str:
    title = localizer.text(occurrence.event.title, fallback=occurrence.event.name)

    return f"{occurrence.starts_at:%a %H:%M} · {title}"[:100]


class OccurrenceSelect(discord.ui.Select):
    """
    Pick which class to act on.

    The weekly schedule message covers a whole week, and Discord allows at most 25
    components on a message - far fewer than two buttons per class would need. So the
    message carries one pair of buttons, and each opens this menu privately.
    """

    def __init__(self, action: str, lane: EventLane, occurrences: typing.Sequence[Occurrence], localizer: Localizer):
        self.action = action
        self.lane = lane
        self.occurrences = {occurrence.key: occurrence for occurrence in occurrences}

        super().__init__(
            placeholder=localizer.text(
                {"ko": "수업을 선택하세요", "en": "Choose a class"},
                fallback="Choose a class",
            )[:150],
            options=[
                discord.SelectOption(
                    label=occurrence_option_label(occurrence, localizer),
                    value=occurrence.key,
                    description=f"{occurrence.event.host}"[:100],
                )
                for occurrence in occurrences
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        occurrence = self.occurrences.get(self.values[0], None)

        if occurrence is None:
            await interaction.response.edit_message(
                content="That class is no longer on the schedule. / 해당 수업이 시간표에서 사라졌습니다.",
                view=None,
            )
            return

        await apply_action(interaction, self.action, self.lane, occurrence, edit=True)


class OccurrencePickerView(discord.ui.View):
    """The short-lived, private view wrapping :class:`OccurrenceSelect`."""

    def __init__(self, action: str, lane: EventLane, occurrences: typing.Sequence[Occurrence], localizer: Localizer):
        super().__init__(timeout=180)
        self.add_item(OccurrenceSelect(action, lane, occurrences, localizer))


async def apply_action(
    interaction: discord.Interaction,
    action: str,
    lane: EventLane,
    occurrence: Occurrence,
    edit: bool = False,
) -> None:
    """
    Record an RSVP or a reminder subscription and confirm it privately.

    Both actions toggle: pressing the button again withdraws what the first press
    recorded, which is the behaviour people expect and saves us a second button.
    """
    bot = typing.cast(typing.Any, interaction.client)
    storage = bot.storage
    localizer = Localizer(lane.meta.get("localization", None))
    title = localizer.text(occurrence.event.title, fallback=occurrence.event.name)
    timestamp = discord.utils.format_dt(occurrence.starts_at, 'f')

    if action == "rsvp":
        if storage.get_rsvp(occurrence.key, interaction.user.id) == "going":
            storage.clear_rsvp(occurrence.key, interaction.user.id)
            message = (
                f"참석 신청을 취소했습니다 — **{title}** ({timestamp})\n"
                f"-# Your RSVP has been withdrawn."
            )
        else:
            storage.set_rsvp(
                occurrence.key, interaction.user.id, lane.name,
                occurrence.event.key, occurrence.starts_at, "going",
            )
            going = storage.count_rsvps(occurrence.key)
            message = (
                f"참석 신청이 접수되었습니다 — **{title}** ({timestamp})\n"
                f"-# You're on the list. {going} attending so far."
            )
    else:
        lead = bot.config.reminder_lead_minutes

        if storage.has_reminder(occurrence.key, interaction.user.id):
            storage.remove_reminder(occurrence.key, interaction.user.id)
            message = (
                f"알림을 취소했습니다 — **{title}** ({timestamp})\n"
                f"-# You will no longer be reminded."
            )
        else:
            storage.add_reminder(
                occurrence.key, interaction.user.id, lane.name,
                occurrence.event.key, occurrence.starts_at, lead,
            )
            remind_at = occurrence.starts_at - datetime.timedelta(minutes=lead)
            message = (
                f"알림을 신청했습니다 — **{title}**\n"
                f"-# We'll DM you at {discord.utils.format_dt(remind_at, 'f')}, "
                f"{lead} minutes before it starts. "
                f"Make sure DMs from this server are enabled, or the reminder cannot reach you."
            )

    if edit:
        await interaction.response.edit_message(content=message, view=None)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class ScheduleActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"ksl:sched:(?P<action>rsvp|remind):(?P<lane>{LANE_PATTERN})$",
):
    """A button on the weekly schedule message, covering every class in that week."""

    def __init__(self, action: str, lane: EventLane, localizer: Localizer, lead_minutes: int):
        self.action = action
        self.lane_name = lane.name

        label = rsvp_label(localizer) if action == "rsvp" else remind_label(localizer, lead_minutes)

        super().__init__(
            discord.ui.Button(
                label=label,
                emoji="\N{RAISED HAND}" if action == "rsvp" else "\N{ALARM CLOCK}",
                style=discord.ButtonStyle.primary if action == "rsvp" else discord.ButtonStyle.secondary,
                custom_id=f"ksl:sched:{action}:{lane.name}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> "ScheduleActionButton":
        bot = typing.cast(typing.Any, interaction.client)
        lane = bot.service.lane(match["lane"])

        # A lane that has been renamed or removed leaves orphaned buttons behind on old
        # messages. Rebuilding against a placeholder lets the callback answer politely
        # rather than raising out of the interaction handler.
        if lane is None:
            raise ValueError(f"Unknown lane {match['lane']!r} in custom_id")

        return cls(match["action"], lane, Localizer(lane.meta.get("localization", None)),
                   bot.config.reminder_lead_minutes)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = typing.cast(typing.Any, interaction.client)
        lane = bot.service.lane(self.lane_name)

        if lane is None:
            await interaction.response.send_message(
                "This schedule is no longer available. / 이 시간표는 더 이상 제공되지 않습니다.",
                ephemeral=True,
            )
            return

        localizer = Localizer(lane.meta.get("localization", None))
        occurrences = bot.service.upcoming_occurrences(lane)

        if not occurrences:
            await interaction.response.send_message(
                localizer.text(
                    {"ko": "이번 주에 남은 수업이 없습니다.", "en": "No classes left this week."},
                    fallback="No classes left this week.",
                ),
                ephemeral=True,
            )
            return

        # One class left is not worth a menu - act on it directly.
        if len(occurrences) == 1:
            await apply_action(interaction, self.action, lane, occurrences[0])
            return

        await interaction.response.send_message(
            localizer.text(
                {"ko": "어떤 수업인가요?", "en": "Which class?"},
                fallback="Which class?",
            ),
            view=OccurrencePickerView(self.action, lane, occurrences, localizer),
            ephemeral=True,
        )


class OccurrenceActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=(
        rf"ksl:occ:(?P<action>rsvp|remind):(?P<lane>{LANE_PATTERN})"
        r":(?P<event>[0-9a-f]{16}):(?P<ts>[0-9]{1,12})$"
    ),
):
    """
    A button attached to a single class's own embed.

    Used for announcements and reminder DMs, where there is exactly one class in play and
    a menu would be an extra click for nothing.
    """

    def __init__(self, action: str, lane: EventLane, occurrence: Occurrence, localizer: Localizer, lead_minutes: int):
        self.action = action
        self.lane_name = lane.name
        self.occurrence = occurrence

        label = rsvp_label(localizer) if action == "rsvp" else remind_label(localizer, lead_minutes)

        super().__init__(
            discord.ui.Button(
                label=label,
                emoji="\N{RAISED HAND}" if action == "rsvp" else "\N{ALARM CLOCK}",
                style=discord.ButtonStyle.primary if action == "rsvp" else discord.ButtonStyle.secondary,
                custom_id=(
                    f"ksl:occ:{action}:{lane.name}:{occurrence.event.key}"
                    f":{int(occurrence.starts_at.timestamp())}"
                ),
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> "OccurrenceActionButton":
        bot = typing.cast(typing.Any, interaction.client)
        lane = bot.service.lane(match["lane"])

        if lane is None:
            raise ValueError(f"Unknown lane {match['lane']!r} in custom_id")

        starts_at = datetime.datetime.fromtimestamp(int(match["ts"]), datetime.timezone.utc)
        occurrence = bot.service.find_occurrence(match["lane"], match["event"], starts_at)

        if occurrence is None:
            raise ValueError(f"Unknown event {match['event']!r} in custom_id")

        return cls(match["action"], lane, occurrence,
                   Localizer(lane.meta.get("localization", None)),
                   bot.config.reminder_lead_minutes)

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = typing.cast(typing.Any, interaction.client)
        lane = bot.service.lane(self.lane_name)

        if lane is None:
            await interaction.response.send_message(
                "This class is no longer available. / 이 수업은 더 이상 제공되지 않습니다.",
                ephemeral=True,
            )
            return

        await apply_action(interaction, self.action, lane, self.occurrence)


def build_schedule_view(lane: EventLane, localizer: Localizer, lead_minutes: int) -> discord.ui.View | None:
    """The RSVP + reminder row that sits under a weekly schedule message."""
    if not lane.meta.get("interactions", False):
        return None

    view = discord.ui.View(timeout=None)
    view.add_item(ScheduleActionButton("rsvp", lane, localizer, lead_minutes))
    view.add_item(ScheduleActionButton("remind", lane, localizer, lead_minutes))

    # Lane-wide VRChat links, alongside the interactive buttons.
    vrchat = lane.meta.get("vrchat", None) or {}

    for url_key, label in (
        ("group_url", vrchat.get("group") or localizer.label("group")),
        ("instance_url", localizer.label("instance")),
    ):
        if vrchat.get(url_key):
            view.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link, url=vrchat[url_key], label=label[:80],
            ))

    return view


def build_occurrence_view(lane: EventLane, occurrence: Occurrence, lead_minutes: int) -> discord.ui.View | None:
    """The RSVP + reminder row that sits under a single class's embed."""
    if not (lane.meta.get("interactions", False) and occurrence.event.rsvp):
        return None

    localizer = Localizer(lane.meta.get("localization", None))
    view = discord.ui.View(timeout=None)
    view.add_item(OccurrenceActionButton("rsvp", lane, occurrence, localizer, lead_minutes))
    view.add_item(OccurrenceActionButton("remind", lane, occurrence, localizer, lead_minutes))

    return view


__all__ = [
    "OccurrenceActionButton",
    "ScheduleActionButton",
    "build_occurrence_view",
    "build_schedule_view",
]

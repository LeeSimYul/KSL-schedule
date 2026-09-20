# -*- coding: utf-8 -*-

"""
The bot's background work, as three cogs.

``SchedulePoster``   keeps the weekly schedule message current, with its buttons attached.
``ReminderSender``   DMs people before the class they asked to be reminded about.
``ScheduledEventSync`` mirrors the guild's Discord Scheduled Events into the schedule.
"""

import datetime
import logging

import discord
from discord.ext import commands, tasks

from definitions import EventLane
from embeds import Localizer, build_occurrence_embed, build_weekly_embeds, enforce_embed_limits
from .schedule import scheduled_event_to_occurrence
from .views import build_occurrence_view, build_schedule_view


log = logging.getLogger(__name__)


class SchedulePoster(commands.Cog):
    """
    Posts and refreshes one schedule message per interactive lane.

    The message is edited in place rather than reposted, so the channel does not fill up
    and any pin, link or bookmark to it keeps working.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.refresh.change_interval(minutes=self.bot.config.refresh_interval_minutes)
        self.refresh.start()

    async def cog_unload(self) -> None:
        self.refresh.cancel()

    @tasks.loop(minutes=15)
    async def refresh(self) -> None:
        for lane in self.bot.service.interactive_lanes():
            try:
                await self.refresh_lane(lane)
            except Exception:  # noqa: BLE001 - a deleted channel, a revoked permission,
                # or bad data in one lane must not stop the others from updating.
                log.exception("Failed to refresh schedule for lane %s", lane.name)

    @refresh.before_loop
    async def before_refresh(self) -> None:
        await self.bot.wait_until_ready()

    @refresh.error
    async def on_refresh_error(self, error: BaseException) -> None:
        # discord.py stops a task loop that raises. Restarting means a transient failure
        # costs one cycle instead of silently freezing the schedule until a redeploy.
        log.exception("Schedule refresh loop stopped unexpectedly, restarting", exc_info=error)
        self.refresh.restart()

    async def refresh_lane(self, lane: EventLane) -> None:
        channel_id = lane.meta.get("channels", {}).get("schedule", None)

        if not channel_id:
            log.warning("Lane %s has interactions enabled but no schedule channel", lane.name)
            return

        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.abc.Messageable):
            log.warning("Schedule channel %s for lane %s is not messageable", channel_id, lane.name)
            return

        localizer = Localizer(lane.meta.get("localization", None))
        embeds = build_weekly_embeds(
            lane, self.bot.service.lanes,
            extra_occurrences=self.bot.service.extra_occurrences(lane),
        )

        for warning in enforce_embed_limits(embeds):
            log.warning("Lane %s: %s", lane.name, warning)

        view = build_schedule_view(lane, localizer, self.bot.config.reminder_lead_minutes)
        existing = self.bot.storage.get_schedule_message(lane.name)

        if existing is not None and existing[0] == channel_id:
            try:
                message = await channel.fetch_message(existing[1])
                await message.edit(embeds=embeds, view=view)
                return
            except discord.NotFound:
                # Somebody deleted the message - fall through and post a fresh one.
                log.info("Schedule message for %s is gone, reposting", lane.name)
                self.bot.storage.forget_schedule_message(lane.name)

        message = await channel.send(embeds=embeds, view=view)
        self.bot.storage.set_schedule_message(lane.name, channel_id, message.id)
        log.info("Posted schedule message %s for lane %s", message.id, lane.name)


class ReminderSender(commands.Cog):
    """Delivers the "15 minutes before" DMs people signed up for."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.sweep.start()

    async def cog_unload(self) -> None:
        self.sweep.cancel()

    @tasks.loop(minutes=1)
    async def sweep(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        due = self.bot.storage.due_reminders(now, self.bot.config.reminder_grace_minutes)

        for reminder in due:
            # Mark first. A DM that fails is better than a DM that sends twice because the
            # loop crashed between sending and recording it.
            self.bot.storage.mark_reminder_sent(reminder.occurrence_key, reminder.user_id, now)

            try:
                await self.send_reminder(reminder)
            except Exception:  # noqa: BLE001 - one undeliverable DM must not stop the rest
                log.exception("Failed to send reminder for %s to %s", reminder.occurrence_key, reminder.user_id)

    @sweep.before_loop
    async def before_sweep(self) -> None:
        await self.bot.wait_until_ready()

    @sweep.error
    async def on_sweep_error(self, error: BaseException) -> None:
        log.exception("Reminder loop stopped unexpectedly, restarting", exc_info=error)
        self.sweep.restart()

    async def send_reminder(self, reminder) -> None:
        lane = self.bot.service.lane(reminder.lane)

        if lane is None:
            return

        occurrence = self.bot.service.find_occurrence(reminder.lane, reminder.event_key, reminder.starts_at)

        if occurrence is None:
            log.info("Reminder %s refers to an event that no longer exists", reminder.occurrence_key)
            return

        user = self.bot.get_user(reminder.user_id) or await self.bot.fetch_user(reminder.user_id)
        localizer = Localizer(lane.meta.get("localization", None))
        minutes = self.bot.config.reminder_lead_minutes

        content = localizer.text(
            {
                "ko": f"곧 수업이 시작됩니다! ({minutes}분 전)",
                "en": f"Your class starts in about {minutes} minutes.",
            },
            fallback=f"Your class starts in about {minutes} minutes.",
        )

        try:
            await user.send(
                content=content,
                embed=build_occurrence_embed(occurrence, lane),
                view=build_occurrence_view(lane, occurrence, minutes),
            )
        except discord.Forbidden:
            # Closed DMs are the single most common reason a reminder cannot land. It is
            # not an error on our side, so log it quietly rather than raising.
            log.info("Cannot DM user %s - their DMs are closed", reminder.user_id)


class ScheduledEventSync(commands.Cog):
    """
    Mirrors Discord Scheduled Events into the schedule message.

    Staff create an event through Discord's own UI, and it appears in ``#schedule``
    alongside the YAML-defined classes, with the same timestamps and the same buttons -
    no second place to keep up to date.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.sync.start()

    async def cog_unload(self) -> None:
        self.sync.cancel()

    @tasks.loop(minutes=15)
    async def sync(self) -> None:
        await self.sync_all()

    @sync.before_loop
    async def before_sync(self) -> None:
        await self.bot.wait_until_ready()

    @sync.error
    async def on_sync_error(self, error: BaseException) -> None:
        log.exception("Scheduled event sync stopped unexpectedly, restarting", exc_info=error)
        self.sync.restart()

    async def sync_all(self) -> None:
        for lane in self.bot.service.lanes:
            configuration = lane.meta.get("discord_events", None)

            if not configuration:
                continue

            guild = self.bot.get_guild(configuration["guild"])

            if guild is None:
                log.warning("Lane %s wants events from guild %s, which the bot is not in",
                            lane.name, configuration["guild"])
                continue

            occurrences = []

            for scheduled_event in list(guild.scheduled_events):
                if scheduled_event.status not in (
                    discord.EventStatus.scheduled,
                    discord.EventStatus.active,
                ):
                    continue

                occurrence = scheduled_event_to_occurrence(scheduled_event, lane)

                if occurrence is not None:
                    occurrences.append(occurrence)

            self.bot.service.set_discord_occurrences(lane.name, occurrences)
            log.info("Mirrored %d scheduled events into lane %s", len(occurrences), lane.name)

    async def resync_and_refresh(self) -> None:
        # Driven by gateway events, so an exception here would propagate into discord.py's
        # event dispatcher rather than a task loop that knows how to restart itself.
        try:
            await self.sync_all()

            poster = self.bot.get_cog("SchedulePoster")

            if poster is not None:
                await poster.refresh()
        except Exception:  # noqa: BLE001
            log.exception("Failed to resync after a scheduled event changed")

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent) -> None:
        await self.resync_and_refresh()

    @commands.Cog.listener()
    async def on_scheduled_event_update(
        self,
        before: discord.ScheduledEvent,
        after: discord.ScheduledEvent,
    ) -> None:
        await self.resync_and_refresh()

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent) -> None:
        await self.resync_and_refresh()

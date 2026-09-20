# -*- coding: utf-8 -*-

"""
Bot entrypoint.

    python -m bot          (from the scripts/ directory, with KSL_BOT_TOKEN set)

Intents: this bot needs ``guild_scheduled_events`` to mirror Discord's own events, and
``guilds`` to resolve channels. It deliberately does not ask for ``message_content`` -
it never reads what anybody types, so requesting that privileged intent would be asking
for access it has no use for.
"""

import asyncio
import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands

from embeds import Localizer, build_occurrence_embed
from .cogs import ReminderSender, SchedulePoster, ScheduledEventSync
from .config import BotConfig
from .schedule import ScheduleService
from .storage import Storage
from .views import OccurrenceActionButton, ScheduleActionButton, build_occurrence_view


log = logging.getLogger(__name__)


class KSLBot(commands.Bot):
    def __init__(self, config: BotConfig):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_scheduled_events = True

        super().__init__(command_prefix=commands.when_mentioned, intents=intents)

        self.config = config
        self.storage = Storage(config.database_path)
        self.service = ScheduleService()

    async def setup_hook(self) -> None:
        self.service.reload()

        # Registering the dynamic items is what lets buttons on messages posted by a
        # previous run of this process keep working after a restart.
        self.add_dynamic_items(ScheduleActionButton, OccurrenceActionButton)

        await self.add_cog(ScheduledEventSync(self))
        await self.add_cog(SchedulePoster(self))
        await self.add_cog(ReminderSender(self))

        await self.tree.sync()

    async def close(self) -> None:
        await super().close()
        self.storage.close()

    async def on_ready(self) -> None:
        log.info("Signed in as %s (%s)", self.user, self.user.id if self.user else "?")


bot_commands = app_commands.Group(
    name="ksl",
    description="한국수어교실 시간표 / KSL schedule",
)


@bot_commands.command(name="next", description="다음 수업을 확인합니다 / Show the next class")
@app_commands.describe(lane="Which schedule to read. Defaults to the KSL lane.")
async def next_class(interaction: discord.Interaction, lane: str = "sign_language_ksl") -> None:
    bot: KSLBot = interaction.client  # type: ignore[assignment]
    event_lane = bot.service.lane(lane)

    if event_lane is None:
        await interaction.response.send_message(f"No such schedule: `{lane}`", ephemeral=True)
        return

    upcoming = bot.service.upcoming_occurrences(event_lane, limit=1)

    if not upcoming:
        localizer = Localizer(event_lane.meta.get("localization", None))
        await interaction.response.send_message(
            localizer.text(
                {"ko": "이번 주에 남은 수업이 없습니다.", "en": "No classes left this week."},
                fallback="No classes left this week.",
            ),
            ephemeral=True,
        )
        return

    occurrence = upcoming[0]

    await interaction.response.send_message(
        embed=build_occurrence_embed(occurrence, event_lane),
        view=build_occurrence_view(event_lane, occurrence, bot.config.reminder_lead_minutes),
        ephemeral=True,
    )


@bot_commands.command(name="attendees", description="참석 신청자를 확인합니다 / List who has RSVP'd")
@app_commands.default_permissions(manage_events=True)
@app_commands.describe(lane="Which schedule to read. Defaults to the KSL lane.")
async def attendees(interaction: discord.Interaction, lane: str = "sign_language_ksl") -> None:
    bot: KSLBot = interaction.client  # type: ignore[assignment]
    event_lane = bot.service.lane(lane)

    if event_lane is None:
        await interaction.response.send_message(f"No such schedule: `{lane}`", ephemeral=True)
        return

    localizer = Localizer(event_lane.meta.get("localization", None))
    lines = []

    for occurrence in bot.service.upcoming_occurrences(event_lane):
        user_ids = bot.storage.list_attendees(occurrence.key)

        if not user_ids:
            continue

        title = localizer.text(occurrence.event.title, fallback=occurrence.event.name)
        mentions = ", ".join(f"<@{user_id}>" for user_id in user_ids)
        lines.append(f"**{title}** — {discord.utils.format_dt(occurrence.starts_at, 'f')}\n-# {mentions}")

    if not lines:
        await interaction.response.send_message(
            "아직 참석 신청자가 없습니다. / Nobody has RSVP'd yet.", ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "\n\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot_commands.command(name="refresh", description="시간표를 다시 게시합니다 / Rebuild the schedule message")
@app_commands.default_permissions(manage_guild=True)
async def refresh(interaction: discord.Interaction) -> None:
    bot: KSLBot = interaction.client  # type: ignore[assignment]

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        # Pick up template edits that were pushed since the bot started. Returns False
        # when the new templates did not parse and the previous ones are still in use.
        reloaded = bot.service.reload()

        sync_cog = bot.get_cog("ScheduledEventSync")

        if sync_cog is not None:
            await sync_cog.sync_all()

        poster = bot.get_cog("SchedulePoster")

        if poster is not None:
            await poster.refresh()

        removed = bot.storage.purge_expired(datetime.datetime.now(datetime.timezone.utc))
    except Exception as error:  # noqa: BLE001 - report to the operator, never 500 at them
        log.exception("Manual refresh failed")
        await interaction.followup.send(
            f"갱신에 실패했습니다. / Refresh failed: `{error!r}`\n"
            f"-# The previous schedule is still in place. Check the bot logs for details.",
            ephemeral=True,
        )
        return

    warning = "" if reloaded else (
        "\n-# ⚠️ 템플릿을 읽지 못해 이전 시간표를 유지했습니다. / "
        "Templates failed to parse - the previous schedule was kept."
    )

    await interaction.followup.send(
        f"시간표를 갱신했습니다. / Schedule rebuilt. ({removed} expired records pruned){warning}",
        ephemeral=True,
    )


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config = BotConfig.from_environment()
    bot = KSLBot(config)
    bot.tree.add_command(bot_commands)

    async with bot:
        await bot.start(config.token)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

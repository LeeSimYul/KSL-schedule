# -*- coding: utf-8 -*-

"""Runtime configuration, read from the environment."""

import dataclasses
import os
import pathlib


DEFAULT_DATABASE_PATH = pathlib.Path(__file__).parent.parent.parent / 'data' / 'ksl_bot.sqlite3'


@dataclasses.dataclass(frozen=True)
class BotConfig:
    token: str
    database_path: pathlib.Path = DEFAULT_DATABASE_PATH
    #: How long before an event a reminder is sent. The brief asks for 15 minutes; it is
    #: configurable because a 90 minute class and a 15 minute drop-in want different notice.
    reminder_lead_minutes: int = 15
    #: How stale a pending reminder may be before it is dropped instead of sent. Without
    #: this, a bot that was offline over a weekend would wake up and DM everyone about
    #: classes that finished days ago.
    reminder_grace_minutes: int = 30
    #: How often the schedule message is rebuilt, in minutes.
    refresh_interval_minutes: int = 15

    #: Accepted names for the bot token, in order of preference. ``DISCORD_BOT_TOKEN`` is
    #: the conventional name and is accepted so a host's existing secret works unchanged;
    #: ``KSL_BOT_TOKEN`` wins when both are set, for a host running several bots.
    TOKEN_VARIABLES = ("KSL_BOT_TOKEN", "DISCORD_BOT_TOKEN")

    @classmethod
    def from_environment(cls) -> "BotConfig":
        token = next((value for value in map(os.getenv, cls.TOKEN_VARIABLES) if value), "")

        if not token:
            raise RuntimeError(
                f"No bot token found. Set one of {' or '.join(cls.TOKEN_VARIABLES)}: create an "
                f"application at https://discord.com/developers/applications, copy its bot "
                f"token, and put it in the environment before starting the bot. "
                f"Never commit the token to the repository."
            )

        database_path = os.getenv("KSL_BOT_DATABASE", "")

        return cls(
            token=token,
            database_path=pathlib.Path(database_path) if database_path else DEFAULT_DATABASE_PATH,
            reminder_lead_minutes=int(os.getenv("KSL_REMINDER_LEAD_MINUTES", "15")),
            reminder_grace_minutes=int(os.getenv("KSL_REMINDER_GRACE_MINUTES", "30")),
            refresh_interval_minutes=int(os.getenv("KSL_REFRESH_INTERVAL_MINUTES", "15")),
        )

# -*- coding: utf-8 -*-

"""
Webhook, technically not a format, but allows us to send webhook messages.

The embeds themselves are built in ``embeds.py`` - this module is only responsible for
getting them in front of people.

A note on buttons: Discord only accepts *link* buttons on a webhook message
(``SyncWebhook views can only contain URL buttons``), because anything clickable that
needs a reply has to be answered by a running application within three seconds, and this
build is a cron job that exits. The RSVP and reminder buttons therefore live in the bot
(``scripts/bot/``); what we can and do attach here are the VRChat join links.
"""

import typing

import click
import discord

from definitions import EventLane
from embeds import Localizer, build_weekly_embeds, enforce_embed_limits


def build_link_buttons(event_lane: EventLane) -> discord.ui.View | None:
    """
    Lane-wide VRChat links as buttons under the schedule message.

    Only link buttons are possible here, and they are message-wide rather than per-event,
    so this uses the lane's own VRChat block - the per-event links stay inline in the
    embeds where they can be attributed to the right class.
    """
    vrchat = event_lane.meta.get("vrchat", None)

    if not vrchat:
        return None

    localizer = Localizer(event_lane.meta.get("localization", None))
    view = discord.ui.View()

    candidates: tuple[tuple[str, str], ...] = (
        ("group_url", vrchat.get("group") or localizer.label("group")),
        ("instance_url", localizer.label("instance")),
        ("world_url", vrchat.get("world_name") or localizer.label("world")),
    )

    for url_key, label in candidates:
        url = vrchat.get(url_key, None)

        if not url:
            continue

        # Discord rejects button labels over 80 characters outright.
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, url=url, label=label[:80]))

    if not view.children:
        return None

    return view


def send_webhooks(event_lanes: list[EventLane]) -> dict:
    lane_messages = {}

    for event_lane in event_lanes:
        # We can't work with no webhook..
        if not event_lane.webhook:
            continue

        weekday_embeds = build_weekly_embeds(event_lane, event_lanes)

        for warning in enforce_embed_limits(weekday_embeds):
            click.secho(f"    Warning ({event_lane.name}): {warning}", fg='yellow')

        view = build_link_buttons(event_lane)
        extra: dict[str, typing.Any] = {} if view is None else {"view": view}

        # If a message exists update it, otherwise post a new one.
        if event_lane.webhook_message_id:
            message = event_lane.webhook.edit_message(
                message_id=event_lane.webhook_message_id,
                embeds=weekday_embeds,
                **extra,
            )
        else:
            message = event_lane.webhook.send(
                embeds=weekday_embeds,
                wait=True,
                **extra,
            )

        lane_messages[event_lane.name] = message.id

    return lane_messages

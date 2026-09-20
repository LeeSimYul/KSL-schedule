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

import discord

from ci import annotate as emit_annotation
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


def annotate(level: str, lane_name: str, message: str) -> None:
    """Report a lane-scoped problem into the Actions run's annotations panel."""
    emit_annotation(level, f"[{lane_name}] {message}")


def deliver_lane(event_lane: EventLane, event_lanes: list[EventLane]) -> int:
    """
    Render and deliver one lane's schedule, returning the message ID it now lives at.

    Editing is preferred over posting so the message keeps its place, its pins and its
    links - but a message someone deleted can never be edited again, so a 404 falls back
    to posting a fresh one rather than failing this lane forever.
    """
    weekday_embeds = build_weekly_embeds(event_lane, event_lanes)

    for warning in enforce_embed_limits(weekday_embeds):
        annotate('warning', event_lane.name, warning)

    view = build_link_buttons(event_lane)
    extra: dict[str, typing.Any] = {} if view is None else {"view": view}

    if event_lane.webhook_message_id:
        try:
            message = event_lane.webhook.edit_message(
                message_id=event_lane.webhook_message_id,
                embeds=weekday_embeds,
                **extra,
            )
            return message.id
        except discord.NotFound:
            annotate(
                'warning', event_lane.name,
                f"Schedule message {event_lane.webhook_message_id} no longer exists - posting a new one. "
                f"Update the message ID secret to the new value printed below.",
            )

    message = event_lane.webhook.send(embeds=weekday_embeds, wait=True, **extra)

    # Posting is a one-off: every later run should edit this message instead of adding
    # another one. That only happens once the ID is stored, so the ID is raised as an
    # annotation - naming the exact secret - rather than logged where it would be missed.
    secret_name = (event_lane.webhook_info or {}).get('message_id', '<message id secret>')

    annotate(
        'notice', event_lane.name,
        f"Posted a NEW schedule message: {message.id} - "
        f"set the secret {secret_name}={message.id} so future runs edit it instead of "
        f"posting another copy.",
    )

    return message.id


def send_webhooks(event_lanes: list[EventLane]) -> dict:
    """
    Deliver every configured lane, in isolation from one another.

    discord.py already retries rate limits (429) and server errors (5xx) internally, so
    what reaches us here is terminal: a revoked webhook, a missing permission, or a bug in
    one lane's data. None of those are a reason to abandon the other lanes, and none are a
    reason to abandon the manifest either - the VRChat side reads ``old.json`` and does
    not care whether Discord accepted the embeds. So failures are annotated loudly and the
    build continues, unless every single lane failed, which means something systemic.
    """
    lane_messages = {}
    attempted = 0
    failures: list[str] = []

    for event_lane in event_lanes:
        # We can't work with no webhook..
        if not event_lane.webhook:
            continue

        attempted += 1

        try:
            lane_messages[event_lane.name] = deliver_lane(event_lane, event_lanes)
        except discord.Forbidden:
            failures.append(event_lane.name)
            annotate(
                'error', event_lane.name,
                "Discord refused the request (403). The webhook was probably deleted or "
                "regenerated - create a new one and update this lane's URL secret.",
            )
        except discord.HTTPException as error:
            failures.append(event_lane.name)
            annotate(
                'error', event_lane.name,
                f"Discord rejected the schedule after retries (HTTP {error.status}): {error.text}",
            )
        except Exception as error:  # noqa: BLE001 - one lane's data must not sink the rest
            failures.append(event_lane.name)
            annotate('error', event_lane.name, f"Could not build or deliver this schedule: {error!r}")

    if attempted and len(failures) == attempted:
        raise RuntimeError(
            f"Every configured webhook failed ({', '.join(failures)}). "
            f"This usually means the secrets are wrong or Discord is unreachable."
        )

    return lane_messages

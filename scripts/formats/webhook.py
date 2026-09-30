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


# Discord's JSON error codes. A 404 alone does not say *what* is missing, and the fix for a
# deleted message (post a replacement) is the wrong one for a deleted webhook (replace the
# URL secret) - posting through a webhook that no longer exists fails the same way again.
UNKNOWN_MESSAGE = 10008
UNKNOWN_WEBHOOK = 10015
INVALID_WEBHOOK_TOKEN = 50027


def explain_delivery_error(error: discord.HTTPException, webhook_info: dict | None) -> str:
    """Say what a terminal Discord error means for this lane and which secret fixes it."""
    webhook_info = webhook_info or {}
    url_secret = webhook_info.get('url', '<webhook url secret>')
    detail = f"HTTP {error.status}, code {error.code}: {error.text}"

    if error.code == UNKNOWN_WEBHOOK:
        return (
            f"The webhook itself no longer exists ({detail}) - it was deleted in Discord, or "
            f"{url_secret} points at an old one. Create a webhook in the schedule channel "
            f"(Channel settings > Integrations > Webhooks), put its URL in {url_secret}, then "
            f"re-run with \"allow_create\" once, since messages belong to the webhook that "
            f"posted them.\n"
            f"  웹후크 자체가 삭제되었습니다(메시지가 아니라 웹후크). 채널 설정 > 연동 > 웹후크에서 "
            f"새로 만들어 {url_secret} 시크릿에 넣고, allow_create 를 켜서 한 번 실행한 뒤 "
            f"새 메시지 ID를 등록해 주세요."
        )

    if error.status == 401 or error.code == INVALID_WEBHOOK_TOKEN:
        return (
            f"Discord did not accept the webhook's token ({detail}) - the webhook was "
            f"reset, or {url_secret} was pasted incompletely. Copy the URL again from the "
            f"webhook's settings into {url_secret}.\n"
            f"  웹후크 토큰이 맞지 않습니다. 웹후크 URL이 재발급되었거나 잘려서 저장된 것 같습니다. "
            f"URL 전체를 다시 복사해 {url_secret} 에 넣어 주세요."
        )

    if isinstance(error, discord.Forbidden):
        return (
            f"Discord refused the request ({detail}) - the webhook has lost access to its "
            f"channel, usually because the channel's permissions changed or its thread was "
            f"archived or locked.\n"
            f"  웹후크가 채널에 접근할 권한을 잃었습니다. 채널 권한 변경이나 스레드 보관/잠금을 "
            f"확인해 주세요."
        )

    return f"Discord rejected the schedule after retries ({detail})"


class ScheduleMessageMissing(Exception):
    """
    There is no schedule message to edit, and posting one was not permitted.

    Raised rather than silently posting: an unattended run that posts whenever it cannot
    find the stored message leaves a trail of duplicate schedules in the channel, and
    every duplicate needs a human to notice and delete it.
    """


def deliver_lane(
    event_lane: EventLane,
    event_lanes: list[EventLane],
    allow_create: bool = False,
) -> int:
    """
    Render and deliver one lane's schedule, returning the message ID it now lives at.

    The schedule is a single message that gets edited in place, so it keeps its position
    in the channel along with any pins and links to it. Posting a new one is therefore a
    deliberate, one-off act - it is only done when ``allow_create`` says so, which the
    scheduled build never does.
    """
    weekday_embeds = build_weekly_embeds(event_lane, event_lanes)

    for warning in enforce_embed_limits(weekday_embeds):
        annotate('warning', event_lane.name, warning)

    view = build_link_buttons(event_lane)
    extra: dict[str, typing.Any] = {} if view is None else {"view": view}
    secret_name = (event_lane.webhook_info or {}).get('message_id', '<message id secret>')

    if event_lane.webhook_message_id:
        try:
            message = event_lane.webhook.edit_message(
                message_id=event_lane.webhook_message_id,
                embeds=weekday_embeds,
                **extra,
            )
            return message.id
        except discord.NotFound as error:
            # Only a missing *message* is solved by posting a new one. Anything else that is
            # missing - the webhook, above all - is left to send_webhooks to explain.
            if error.code not in (UNKNOWN_MESSAGE, 0):
                raise

            if not allow_create:
                raise ScheduleMessageMissing(
                    f"Schedule message {event_lane.webhook_message_id} no longer exists, so there "
                    f"is nothing to edit. Nothing was posted - re-run the workflow manually with "
                    f"\"allow_create\" enabled to publish a replacement, then update {secret_name}.\n"
                    f"  기존 시간표 메시지를 찾을 수 없습니다. 중복을 막기 위해 새로 게시하지 "
                    f"않았습니다. 새 메시지가 필요하면 Actions에서 allow_create 를 켜고 수동 "
                    f"실행한 뒤 {secret_name} 시크릿을 갱신해 주세요."
                ) from None

            annotate(
                'warning', event_lane.name,
                f"Schedule message {event_lane.webhook_message_id} no longer exists - "
                f"posting a replacement because allow_create is enabled.",
            )

    elif not allow_create:
        raise ScheduleMessageMissing(
            f"No schedule message to edit: the secret {secret_name} is empty. Nothing was "
            f"posted, so no duplicate was created. Re-run the workflow manually with "
            f"\"allow_create\" enabled to publish the first message, then store its ID in "
            f"{secret_name}.\n"
            f"  {secret_name} 시크릿이 비어 있습니다. 중복 방지를 위해 새로 게시하지 "
            f"않았습니다. 첫 메시지를 만들려면 Actions에서 allow_create 를 켜고 수동 실행한 뒤, "
            f"출력된 ID를 {secret_name} 에 등록해 주세요."
        )

    message = event_lane.webhook.send(embeds=weekday_embeds, wait=True, **extra)

    # Posting is a one-off: every later run edits this message instead of adding another.
    # That only happens once the ID is stored, so it is raised as an annotation naming the
    # exact secret, rather than logged where it would scroll past.
    annotate(
        'notice', event_lane.name,
        f"Posted a NEW schedule message: {message.id} - "
        f"set the secret {secret_name}={message.id} now, so future runs edit it instead of "
        f"posting another copy.",
    )

    return message.id


def send_webhooks(event_lanes: list[EventLane], allow_create: bool = False) -> dict:
    """
    Deliver every configured lane, in isolation from one another.

    discord.py already retries rate limits (429) and server errors (5xx) internally, so
    what reaches us here is terminal: a revoked webhook, a missing permission, or a bug in
    one lane's data. None of those are a reason to abandon the other lanes, and none are a
    reason to abandon the manifest either - the VRChat side reads ``old.json`` and does
    not care whether Discord accepted the embeds. So failures are annotated loudly and the
    build continues, unless every single lane failed, which means something systemic.

    ``allow_create`` permits posting a schedule message where there is none to edit. It
    stays off for scheduled and push-triggered runs, so an unattended build can never add
    a second copy of the schedule to the channel.
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
            lane_messages[event_lane.name] = deliver_lane(event_lane, event_lanes, allow_create)
        except ScheduleMessageMissing as error:
            failures.append(event_lane.name)
            annotate('error', event_lane.name, str(error))
        except discord.HTTPException as error:
            failures.append(event_lane.name)
            annotate('error', event_lane.name, explain_delivery_error(error, event_lane.webhook_info))
        except Exception as error:  # noqa: BLE001 - one lane's data must not sink the rest
            failures.append(event_lane.name)
            annotate('error', event_lane.name, f"Could not build or deliver this schedule: {error!r}")

    if attempted and len(failures) == attempted:
        raise RuntimeError(
            f"Every configured webhook failed ({', '.join(failures)}). "
            f"This usually means the secrets are wrong or Discord is unreachable."
        )

    return lane_messages

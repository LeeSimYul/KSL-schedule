# -*- coding: utf-8 -*-

"""
The KSL schedule bot.

Everything in this package needs a running Discord application, which is what separates
it from the rest of the repository. The GitHub Actions build is a cron job that renders
the schedule and exits; that is enough to publish embeds through a webhook, but it can
never answer a button press, read a guild's scheduled events, or send a DM - all three
need a bot token and a process that is still alive when the user acts.

See ``docs/KSL_GUIDE.md`` for how to deploy it.
"""

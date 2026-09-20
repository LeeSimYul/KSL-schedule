// KSL schedule - timezone and Discord timestamp helpers.
//
// A port of scripts/timeutil.py for the JavaScript side of the project: the web view
// that reads output/old.json, and anything else that needs to turn a KST wall-clock time
// into a Discord timestamp without running Python.
//
// No dependencies - everything here is built on Intl, which every current browser and
// Node 18+ ships with a full timezone database for.
//
// The Python module remains authoritative for what actually gets published; this is for
// clients rendering the same data.

/** Korea Standard Time. A fixed +09:00 - Korea observes no daylight saving. */
export const KST = 'Asia/Seoul';

/**
 * The offset, in milliseconds, of `timeZone` from UTC at a given instant.
 *
 * Intl has no API that returns this directly, so we format the instant *in* the zone and
 * read the wall-clock time back out: the difference between that and the instant itself
 * is the offset. This is what makes the rest of the module DST-correct rather than
 * assuming a fixed offset per zone.
 */
function zoneOffsetMs(utcMs, timeZone) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(utcMs)).map(({ type, value }) => [type, value]),
  );

  const asIfUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second),
  );

  return asIfUtc - utcMs;
}

/**
 * Whether `timeZone` is on daylight saving time at this instant.
 *
 * Decided by comparing the offset now against the smaller of the January and July
 * offsets, which identifies the zone's standard time in either hemisphere.
 */
function isDaylightSaving(utcMs, timeZone) {
  const year = new Date(utcMs).getUTCFullYear();
  const january = zoneOffsetMs(Date.UTC(year, 0, 1), timeZone);
  const july = zoneOffsetMs(Date.UTC(year, 6, 1), timeZone);

  return zoneOffsetMs(utcMs, timeZone) > Math.min(january, july);
}

/**
 * Parse a human written local time into a `Date`.
 *
 * Accepts "2026-09-16 20:00", "2026-09-16T20:00" and "2026-09-16 20:00:00", reading them
 * *in* `timeZone` rather than in the machine's own locale - which is the whole point,
 * since the person writing the schedule means 8pm in Seoul, not 8pm wherever the build
 * happens to run.
 */
export function parseWallClock(text, timeZone = KST) {
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(text).trim());

  if (!match) {
    throw new RangeError(`Could not parse "${text}" as a 'YYYY-MM-DD HH:MM' local time`);
  }

  const [, year, month, day, hour, minute, second = '00'] = match;
  const naiveUtc = Date.UTC(+year, +month - 1, +day, +hour, +minute, +second);

  // First pass using the offset at the guessed instant, then one correction - which only
  // matters within the hour either side of a DST transition, but that hour is exactly
  // when a naive implementation silently lands an event on the wrong side of the change.
  const firstOffset = zoneOffsetMs(naiveUtc, timeZone);
  let utcMs = naiveUtc - firstOffset;

  const correctedOffset = zoneOffsetMs(utcMs, timeZone);

  if (correctedOffset !== firstOffset) {
    utcMs = naiveUtc - correctedOffset;
  }

  return new Date(utcMs);
}

/** UNIX timestamp, in whole seconds - the unit Discord's timestamp markup expects. */
export function toUnix(date) {
  return Math.floor(date.getTime() / 1000);
}

/**
 * A Discord dynamic timestamp, e.g. `<t:1789556400:f>`.
 *
 * Styles: t (time), T (time with seconds), d (date), D (long date), f (short date+time),
 * F (full), R (relative). Every Discord client renders these in the viewer's own
 * timezone, which is what lets one schedule message serve Seoul and San Francisco alike.
 */
export function discordTimestamp(date, style = 'f') {
  return `<t:${toUnix(date)}:${style}>`;
}

/** The pairing the schedule uses everywhere: absolute time, then a relative countdown. */
export function discordTimestampPair(date) {
  const unix = toUnix(date);

  return `<t:${unix}:f> (<t:${unix}:R>)`;
}

/**
 * The timezones spelled out under each dynamic timestamp.
 *
 * `labels` is `[standard, daylight]`. It is given explicitly because Intl's short
 * timezone names are inconsistent across zones and ICU builds - en-US renders
 * America/Los_Angeles as "PDT" but Asia/Seoul as "GMT+9". Naming them keeps the output
 * identical to the Python side, and the pair keeps PST/PDT and CET/CEST switching over
 * on the right date instead of being frozen to whichever was true when it was written.
 */
export const KSL_DISPLAY_TIMEZONES = [
  { flag: '🇰🇷', timeZone: 'Asia/Seoul',          labels: ['KST', 'KST'] },
  { flag: '🇺🇸', timeZone: 'America/Los_Angeles', labels: ['PST', 'PDT'] },
  { flag: '🇺🇸', timeZone: 'America/New_York',    labels: ['EST', 'EDT'] },
  { flag: '🇪🇺', timeZone: 'Europe/Paris',        labels: ['CET', 'CEST'] },
  { flag: '🇦🇺', timeZone: 'Australia/Sydney',    labels: ['AEST', 'AEDT'] },
  { flag: '🌐', timeZone: 'UTC',                  labels: ['UTC', 'UTC'] },
];

function abbreviation(date, { timeZone, labels }) {
  if (!labels) {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'short' })
      .formatToParts(date);

    return parts.find((part) => part.type === 'timeZoneName')?.value ?? '';
  }

  return labels[isDaylightSaving(date.getTime(), timeZone) ? 1 : 0];
}

/**
 * One explicit line, e.g. "🇰🇷  08:00 PM KST".
 *
 * When `referenceTimeZone` is given and the instant falls on another calendar day there,
 * the weekday is appended - without it, a 6am Seoul class looks like it happens "today"
 * to a reader in Los Angeles, where it is still the previous evening.
 */
export function timeZoneLine(date, displayTimeZone, referenceTimeZone = null) {
  const { flag, timeZone } = displayTimeZone;

  const time = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(date);

  let line = `${flag}  ${time} ${abbreviation(date, displayTimeZone)}`;

  if (referenceTimeZone) {
    const dayIn = (zone) => new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(date);

    if (dayIn(timeZone) !== dayIn(referenceTimeZone)) {
      const weekday = new Intl.DateTimeFormat('en-US', { timeZone, weekday: 'short' }).format(date);
      line = `${line} (${weekday})`;
    }
  }

  return line;
}

/** Explicit time lines for every configured timezone, in configuration order. */
export function timeZoneLines(date, zones = KSL_DISPLAY_TIMEZONES, referenceTimeZone = KST) {
  return zones.map((zone) => timeZoneLine(date, zone, referenceTimeZone));
}

/**
 * The one-call helper: a local wall-clock string in, everything needed to render it out.
 *
 *   buildScheduleStrings('2026-09-16 20:00')
 *   // {
 *   //   unix: 1789556400,
 *   //   iso: '2026-09-16T11:00:00.000Z',
 *   //   absolute: '<t:1789556400:f>',
 *   //   relative: '<t:1789556400:R>',
 *   //   combined: '<t:1789556400:f> (<t:1789556400:R>)',
 *   //   timezones: ['🇰🇷  08:00 PM KST', '🇺🇸  04:00 AM PDT', ...],
 *   // }
 */
export function buildScheduleStrings(when, timeZone = KST, zones = KSL_DISPLAY_TIMEZONES) {
  // `array.map(buildScheduleStrings)` hands us the index and the array as extra
  // arguments, which would otherwise reach Intl as the timezone "0" and be mistaken for
  // a list of zones. Accept only a zone name and well-formed zone descriptors.
  const zone = typeof timeZone === 'string' ? timeZone : KST;
  const wellFormed = Array.isArray(zones)
    && zones.length > 0
    && zones.every((entry) => entry && typeof entry.timeZone === 'string');
  const displayZones = wellFormed ? zones : KSL_DISPLAY_TIMEZONES;

  const date = when instanceof Date ? when : parseWallClock(when, zone);

  return {
    unix: toUnix(date),
    iso: date.toISOString(),
    absolute: discordTimestamp(date, 'f'),
    relative: discordTimestamp(date, 'R'),
    combined: discordTimestampPair(date),
    timezones: timeZoneLines(date, displayZones, zone),
  };
}

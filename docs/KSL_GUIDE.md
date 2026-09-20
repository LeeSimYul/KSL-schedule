# KSL 시간표 적용 가이드 / KSL Schedule Guide

VRChat 한국수어교실(KSL) 일정을 디스코드에 전 세계 시간대로 자동 표시하기 위한 가이드입니다.

This guide covers the KSL-specific additions to the schedule generator: Discord dynamic
timestamps, the bilingual class embed, Recharging Days, and the optional bot that adds
RSVP buttons, reminder DMs and Discord Scheduled Events sync.

---

## 0. 먼저 알아야 할 구조 / The one thing to understand first

이 저장소는 **두 개의 서로 다른 프로그램**으로 나뉩니다. 무엇을 어디에 설정해야 하는지가
여기서 갈립니다.

| | 빌드 (GitHub Actions) | 봇 (별도 호스팅) |
|---|---|---|
| 실행 방식 | 하루 몇 번 실행 후 종료 | 항상 켜져 있음 |
| 필요한 것 | 웹훅 URL (secrets) | 봇 토큰 |
| 할 수 있는 것 | 임베드 게시/수정, **동적 타임스탬프**, 다국어, 재충전의 날, **링크 버튼** | 위의 전부 + **RSVP 버튼**, **알림 DM**, **디스코드 이벤트 연동** |
| 코드 위치 | `scripts/build_manifests.py` | `scripts/bot/` |

**왜 웹훅으로는 RSVP 버튼을 만들 수 없나요?**
디스코드는 웹훅 메시지에 **링크 버튼만** 허용합니다 (discord.py도
`SyncWebhook views can only contain URL buttons` 로 거부합니다). 클릭에 응답하는 버튼은
3초 안에 응답할 살아있는 애플리케이션이 필요한데, GitHub Actions는 렌더링 후 종료되는
크론 작업이라 그 시점에 이미 존재하지 않습니다. DM 발송과 디스코드 이벤트 읽기도 동일하게
봇 토큰이 필요합니다.

따라서 **1~4단계는 지금 바로 적용 가능**하고, **5단계(RSVP·알림·이벤트 연동)는 봇 배포가
선행**되어야 합니다.

---

## 1. 동적 타임스탬프와 타임존 / Dynamic timestamps and timezones

### 결과물 / What it renders

```
**별빛반 (단어) · Starlight Class (Vocabulary)**
-# 진행자 · Host: Korea_Yujin (담임 · Teacher)
    🕗 <t:1789556400:f> (<t:1789556400:R>)
    🇰🇷  08:00 PM KST
    🇺🇸  04:00 AM PDT
    🇺🇸  07:00 AM EDT
    🇪🇺  01:00 PM CEST
    🇦🇺  09:00 PM AEST
    🌐  11:00 AM UTC
```

`<t:...:f>` 는 **보는 사람의 디스코드 설정 시간대**로 자동 표시되고, `<t:...:R>` 는
"3시간 후" 같은 상대 시간을 보여줍니다. 아래 국가별 줄은 스크린샷·포럼 인용처럼 타임스탬프가
펼쳐지지 않는 곳과, 여러 시간대를 한눈에 비교할 때를 위해 함께 남겨 둡니다.

### 설정 / Configuration

`templates/sign_language_ksl/meta.yaml`:

```yaml
display_timezones:
  - { flag: KR, timezone: Asia/Seoul }
  - { flag: US, timezone: America/Los_Angeles }
  - { flag: US, timezone: America/New_York }
  - { flag: EU, timezone: Europe/Paris }
  - { flag: AU, timezone: Australia/Sydney }
  - { flag: "🌐", timezone: UTC, label: UTC }
```

- `flag`: 두 글자 국가 코드(자동으로 국기 이모지로 변환) 또는 이모지 그대로.
- `label` 을 **생략**하면 그 시간대가 스스로 약어를 보고합니다. 그래서 PST↔PDT,
  CET↔CEST 가 서머타임에 맞춰 **자동으로** 바뀝니다. 직접 적어 넣으면 반년 뒤 틀립니다.

### 헬퍼 함수 / Helper functions

KST 시각 문자열 하나로 필요한 모든 문자열을 만듭니다.

**Python — `scripts/timeutil.py`**

```python
from timeutil import build_schedule_strings

strings = build_schedule_strings("2026-09-16 20:00")   # KST로 해석

strings["unix"]      # 1789556400
strings["combined"]  # '<t:1789556400:f> (<t:1789556400:R>)'
strings["timezones"] # ['🇰🇷  08:00 PM KST', '🇺🇸  04:00 AM PDT', ...]
```

개별 함수도 사용할 수 있습니다.

```python
parse_wall_clock("2026-09-16 20:00", KST)  # tz-aware datetime
to_unix(moment)                            # 1789556400
discord_timestamp(moment, "R")             # '<t:1789556400:R>'
discord_timestamp_pair(moment)             # 절대 + 상대
timezone_lines(moment, KSL_DISPLAY_TIMEZONES, reference_date=...)
```

**JavaScript — `scripts/js/ksl-timeutil.mjs`** (의존성 없음, 동일한 출력)

```js
import { buildScheduleStrings } from './scripts/js/ksl-timeutil.mjs';

const strings = buildScheduleStrings('2026-09-16 20:00');
strings.unix;      // 1789556400
strings.combined;  // '<t:1789556400:f> (<t:1789556400:R>)'
strings.timezones; // ['🇰🇷  08:00 PM KST', ...]
```

두 구현이 같은 결과를 내는지는 테스트(`test_javascript_helper_matches_the_python_one`)가
매번 확인합니다.

> **주의**: `parse_wall_clock` 은 입력을 **해당 시간대의 벽시계 시각으로** 읽습니다.
> UTC 오프셋을 직접 계산해 넣지 마세요 — 서머타임 경계에서 한 시간씩 어긋납니다.

---

## 2. KSL 수업 정보 / The class embed

`templates/sign_language_ksl/events.yaml` 의 이벤트에 아래 필드를 추가합니다.
**전부 선택 사항**이고, 넣지 않은 필드는 임베드에 아예 나타나지 않습니다.

```yaml
- host: Korea_Yujin
  name: "KSL 별빛반"          # 기존 필드 - 번역이 없을 때의 대체 이름
  tags: ["class", "vocabulary"]
  kind: class                 # class | event | social | recharge
  level: root                 # meta.yaml의 levels 키
  role:                       # 진행자 구분
    ko: 담임
    en: Teacher
  platforms: ["pcvr", "quest"]      # 권장/필수 VR 환경
  hand_tracking: recommended        # required | recommended | supported | unsupported
  vrchat:
    instance_url: https://vrchat.com/home/launch?worldId=wrld_...&instanceId=12345
  schedule:
    basis: "2025-12-03"
    day: Wednesday
    hour: 20
    minute: 0
    duration: 90              # 분 단위. 알림·디스코드 이벤트에 사용
```

### 난이도 / Levels

난이도는 `meta.yaml` 에서 한 번 정의하고 이벤트에서는 키로만 참조합니다. 이름을 고치면
모든 수업에 한 번에 반영됩니다.

```yaml
levels:
  seed:      { emoji: "🌰", order: 1, names: { ko: 씨앗 (입문),      en: Seed (Introductory) } }
  root:      { emoji: "🌱", order: 2, names: { ko: 뿌리 (초급),      en: Root (Beginner) } }
  stem:      { emoji: "🎋", order: 3, names: { ko: 줄기 (중급),      en: Stem (Intermediate) } }
  cotyledon: { emoji: "🍀", order: 4, names: { ko: 떡잎 (고급),      en: Cotyledon (Advanced) } }
  sprout:    { emoji: "🌿", order: 5, names: { ko: 새싹 (자유 소통), en: Sprout (Free conversation) } }
```

### VRChat 접속 정보 / Joining

`meta.yaml` 의 `vrchat` 블록은 레인 전체 기본값이고, 이벤트의 `vrchat` 이 개별 항목을
덮어씁니다. 그룹·월드는 보통 공통이고 인스턴스 링크만 수업마다 다르므로 이 조합이
편합니다.

```yaml
vrchat:
  group: KSL 한국수어교실
  group_url: https://vrchat.com/home/group/grp_...
  world_url: https://vrchat.com/home/world/wrld_...
  world_name: KSL Classroom
```

`group_url` 과 `instance_url` 은 스케줄 메시지 하단에 **링크 버튼**으로도 붙습니다
(웹훅에서도 동작합니다).

---

## 3. 한국어/영어 이중 표기 / Bilingual layout

```yaml
localization:
  primary: ko
  secondary: en
  separator: " · "
```

- `primary` 가 먼저 표시됩니다. `secondary` 를 지우면 단일 언어로 돌아갑니다.
- 제목/설명은 이벤트의 `title`, `description` 에 언어별로 적습니다.
- 한쪽 언어 번역이 없으면 **키가 아니라 있는 쪽 언어가** 표시됩니다. 번역이 반쯤 된 상태도
  깨지지 않습니다.
- 두 언어가 같은 문자열이면 한 번만 표시됩니다 (`PCVR · PCVR` 방지).
- 임베드 자체의 문구("진행자", "난이도" 등)는 기본 제공되며, 필요하면
  `localization.labels` 로 덮어쓸 수 있습니다.

```yaml
  labels:
    no_events:
      ko: 이 날은 수업이 없습니다.
      en: No classes this day.
```

---

## 4. 재충전의 날 / Recharging Days

운영진 휴무일은 `events.yaml` 의 `closures` 에 적습니다.

```yaml
closures:
  - date: "2026-09-24"
    until: "2026-09-26"      # 생략하면 하루. 지정 시 끝날 포함
    reason:
      ko: 추석 연휴
      en: Chuseok holiday
```

해당 날짜는 전용 스타일로 바뀝니다.

```
🔋 Thursday (2026-09-24)

재충전의 날 · Recharging Day
-# 추석 연휴
-# Chuseok holiday
-# 운영진 휴무로 수업을 쉽니다. 다음 시간에 만나요!
```

- 아이콘 `🔋`, 색상은 요일별 무지개와 구분되는 **채도 낮은 회청색**이라 한눈에 "쉬는 날"로
  읽힙니다.
- 그날 예정된 이 레인의 수업은 **표시되지 않습니다**.
- 서버 통합 시간표(`server_global`)에서도 KSL 수업만 빠지고, 다른 언어 수업은 그대로
  남습니다.

---

## 5. 봇 배포 / Deploying the bot

RSVP 버튼, 15분 전 알림 DM, 디스코드 이벤트 연동은 여기서부터입니다.

### 5-1. 애플리케이션 만들기

1. https://discord.com/developers/applications 에서 애플리케이션 생성 → Bot 추가
2. 봇 토큰 복사
3. 서버 초대 시 필요한 권한: `View Channel`, `Send Messages`, `Embed Links`,
   `Manage Events`(읽기용), 그리고 슬래시 명령을 위한 `applications.commands` 스코프
4. **인텐트**: 이 봇은 `guilds` 와 `guild_scheduled_events` 만 사용합니다.
   `message_content` 는 **요청하지 마세요** — 봇은 사용자가 입력한 내용을 읽지 않습니다.

### 5-2. 실행

```bash
export KSL_BOT_TOKEN="..."            # 필수
export KSL_REMINDER_LEAD_MINUTES=15   # 기본 15
export KSL_BOT_DATABASE=./data/ksl_bot.sqlite3

cd scripts
python -m bot
```

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `KSL_BOT_TOKEN` | (필수) | 봇 토큰 |
| `KSL_BOT_DATABASE` | `data/ksl_bot.sqlite3` | RSVP·알림 저장 위치 |
| `KSL_REMINDER_LEAD_MINUTES` | `15` | 몇 분 전에 알릴지 |
| `KSL_REMINDER_GRACE_MINUTES` | `30` | 봇이 꺼져 있던 동안 놓친 알림을 몇 분까지 늦게 보낼지 |
| `KSL_REFRESH_INTERVAL_MINUTES` | `15` | 시간표 메시지 갱신 주기 |

> **주의**: 봇이 시간표를 직접 게시하므로, 같은 채널에 웹훅 빌드도 게시하면 시간표가 두 벌
> 생깁니다. 봇을 쓰기로 했다면 해당 레인의 `webhook` 블록을 지우거나, 봇을 다른 채널에
> 두세요.

### 5-3. 레인에서 켜기

```yaml
interactions: true      # RSVP / 알림 버튼

discord_events:         # 디스코드 이벤트 연동
  guild: 1276966404301652081
  name_prefix: "[KSL]"  # 이 접두사가 붙은 이벤트만 가져옴 (생략 시 전부)
  default_kind: event
```

개별 수업에 버튼을 달려면 이벤트에도 `rsvp: true` 를 추가합니다.

### 5-4. 동작 방식

- **RSVP / 알림 버튼**: 주간 시간표 메시지 하단에 한 쌍이 붙습니다. 한 주에 수업이 여러 개면
  버튼을 눌렀을 때 **본인에게만 보이는** 선택 메뉴가 열립니다. (디스코드는 메시지당 컴포넌트
  25개가 상한이라, 수업마다 버튼 두 개를 다는 방식은 금방 한계에 부딪힙니다.)
- **토글**: 같은 버튼을 다시 누르면 신청이 취소됩니다.
- **알림 DM**: 1분 주기로 확인해 시작 15분 전에 DM을 보냅니다. **DM이 닫혀 있으면 알림이
  닿지 않으며**, 신청 시 안내 문구에 그 내용이 포함됩니다.
- **재시작 안전**: 버튼은 `custom_id` 에서 매번 복원되므로(`discord.ui.DynamicItem`),
  봇을 재시작해도 이전에 게시된 메시지의 버튼이 계속 동작합니다.
- **디스코드 이벤트 연동**: 15분 주기 + 이벤트 생성/수정/삭제 시 즉시 동기화되어, YAML로
  정의한 수업과 같은 시간표에 함께 표시됩니다.

### 5-5. 슬래시 명령

| 명령 | 권한 | 설명 |
|---|---|---|
| `/ksl next` | 누구나 | 다음 수업을 본인에게만 표시 |
| `/ksl attendees` | `Manage Events` | 참석 신청자 목록 |
| `/ksl refresh` | `Manage Server` | 템플릿 다시 읽고 시간표 재게시 |

---

## 6. 로컬에서 확인하기 / Previewing locally

디스코드에 아무것도 보내지 않고 결과를 확인할 수 있습니다.

```bash
pip install -r scripts/requirements.txt

# 웹훅 전송 없이 렌더링만 → output/preview.json
python scripts/build_manifests.py --no-send --preview

# 테스트 (pytest 없이도 실행됩니다)
python scripts/tests/test_ksl.py
```

`output/preview.json` 에는 레인별로 실제 전송될 임베드 JSON과 글자 수가 들어 있습니다.
디스코드는 메시지 하나당 임베드 총합 6000자가 상한이며, 이를 넘으면 **수정 요청 자체가
거부되어 시간표가 갱신되지 않습니다**. 빌드는 상한을 넘기 전에 잘라내고 경고를 출력하므로,
경고가 보이면 수업 설명을 줄이거나 표시 시간대 수를 줄이세요.

---

## 7. 파일 지도 / File map

| 파일 | 역할 |
|---|---|
| `scripts/timeutil.py` | 시간대 변환, 디스코드 타임스탬프 (표준 라이브러리만 사용) |
| `scripts/js/ksl-timeutil.mjs` | 위와 동일한 기능의 JS 포트 |
| `scripts/definitions.py` | 타입·데이터클래스 정의 |
| `scripts/loader.py` | YAML 템플릿 읽기·검증 (빌드와 봇이 공유) |
| `scripts/embeds.py` | 임베드 생성 — 시간표, 재충전의 날, 단일 수업 |
| `scripts/formats/webhook.py` | 웹훅으로 시간표 게시/수정 |
| `scripts/formats/old.py` | `vrsl.withdevon.xyz` 형식 매니페스트 |
| `scripts/build_manifests.py` | GitHub Actions 진입점 |
| `scripts/bot/` | 봇 — 버튼, 알림, 디스코드 이벤트 연동 |
| `scripts/tests/test_ksl.py` | 테스트 |
| `schema/*.schema.json` | YAML 스키마 (에디터 자동완성·검증) |
| `docs/examples/` | 모든 옵션이 채워진 설정 예시 |

---

## 8. 자주 막히는 지점 / Troubleshooting

**시간표가 갱신되지 않아요**
→ Actions 로그에서 `Warning: no webhook URL found` 를 확인하세요. 해당 레인의 secret이
비어 있습니다. 6000자 초과 경고도 확인하세요.

**시간이 한 시간씩 어긋나요**
→ `basis` 는 **해당 시간대의 벽시계 날짜**여야 합니다. `day` 와 실제 요일이 다르면 빌드가
실패하도록 되어 있으니, 그 오류 메시지가 가리키는 날짜를 믿으세요.

**PST인데 PDT로 나와요 (또는 반대)**
→ 정상입니다. 서머타임에 따라 자동으로 바뀝니다. `label` 을 직접 지정했다면 지우세요.

**알림 DM이 오지 않아요**
→ 서버 멤버의 DM이 닫혀 있으면 봇이 DM을 보낼 수 없습니다. 봇 로그에
`Cannot DM user ... their DMs are closed` 가 남습니다.

**버튼이 "상호작용 실패"를 냅니다**
→ 봇이 꺼져 있거나, 레인 이름이 바뀌어 예전 메시지의 `custom_id` 가 더 이상 해석되지 않는
경우입니다. `/ksl refresh` 로 다시 게시하세요.

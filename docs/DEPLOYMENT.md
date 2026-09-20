# 배포 · 보안 · 병합 가이드 / Deployment, Secrets and Merge Guide

`claude/serene-johnson-mqcuhy` 브랜치를 `main` 으로 병합하고, KSL 디스코드 서버에서
안전하게 운영하기 위한 설정을 모았습니다.

---

## 1. 시크릿 설정 / GitHub Secrets

### 1-1. 원칙

이 저장소에는 **토큰·웹훅 URL이 단 한 줄도 하드코딩되어 있지 않습니다.** 코드가 읽는
값은 전부 환경 변수이고, 환경 변수는 GitHub Secrets에서만 주입됩니다.

```python
# scripts/loader.py - 웹훅 URL은 '변수 이름'만 YAML에 적고, 값은 환경에서 읽습니다
webhook_url = os.getenv(webhook_info['url'])

# scripts/bot/config.py - 봇 토큰
token = next((value for value in map(os.getenv, cls.TOKEN_VARIABLES) if value), "")
```

`templates/*/meta.yaml` 에 들어가는 것은 **값이 아니라 변수 이름**입니다. 이 파일들은
공개 저장소에 그대로 커밋되므로, 절대 URL을 직접 적지 마세요.

```yaml
webhook:
  url: KSL_SCHEDULE_WEBHOOK_URL        # ✅ 환경 변수 '이름'
  # url: https://discord.com/api/webhooks/...   # ❌ 절대 금지
```

### 1-2. 등록 위치

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

### 1-3. 필요한 시크릿

**KSL만 운영한다면 아래 두 개면 충분합니다.**

| 시크릿 이름 | 필수 | 값 | 얻는 곳 |
|---|:--:|---|---|
| `KSL_SCHEDULE_WEBHOOK_URL` | ✅ | `https://discord.com/api/webhooks/...` | 디스코드 `#schedule` 채널 → 편집 → 연동 → 웹훅 |
| `KSL_SCHEDULE_MESSAGE_ID` | ⬜ | 시간표 메시지 ID (숫자) | 아래 1-4 참고 |

나머지 레인(`ASL_`, `BSL_`, `DGS_`, `JSL_`, `LSF_`, `GLOBAL_`, `MISC_`)의 시크릿은
**등록하지 않아도 됩니다.** 시크릿이 없으면 해당 레인은 경고 한 줄을 남기고 건너뜁니다 —
빌드는 정상 종료되고, 디스코드에는 아무것도 게시되지 않습니다.

```
Warning: no webhook URL found for sign_language_asl
```

> **봇 토큰은 GitHub Secrets에 넣을 필요가 없습니다.** Actions는 봇을 실행하지 않습니다.
> 토큰은 봇을 띄우는 호스트(VPS·Docker·Railway 등)의 환경 변수로만 설정하세요.
> 저장소에 두면 유출 표면만 넓어집니다.

### 1-4. `MESSAGE_ID` 채우는 순서

1. `KSL_SCHEDULE_WEBHOOK_URL` 만 등록하고 워크플로를 한 번 실행합니다
   (`Actions` → `Build schedule manifests` → `Run workflow`).
2. 로그에 새 메시지 ID가 찍힙니다.
   ```
   [sign_language_ksl] posted new schedule message: 1234567890123456789
   ```
3. 그 숫자를 `KSL_SCHEDULE_MESSAGE_ID` 시크릿으로 등록합니다.
4. 이후 실행부터는 **새 메시지를 만들지 않고 기존 메시지를 수정**합니다.

메시지를 누군가 삭제하면 빌드가 실패하는 대신 새로 게시하고 새 ID를 로그에 남깁니다.
그때 시크릿만 갱신하면 됩니다.

### 1-5. 토큰이 유출되었다면

1. Developer Portal → `Bot` → `Reset Token` (**즉시**. 이전 토큰이 바로 무효화됩니다)
2. 웹훅이 유출됐다면 디스코드 채널 설정에서 해당 웹훅 삭제 후 재생성
3. 호스트/시크릿의 값을 새 값으로 교체

커밋 히스토리에 들어간 비밀은 되돌려도 남습니다. 삭제가 아니라 **재발급**이 유일한 해결책
입니다.

---

## 2. 디스코드 봇 설정 / Discord Developer Portal

봇(RSVP·알림·이벤트 연동)을 쓸 때만 필요합니다. 시간표 게시만 할 거라면 1장까지로 충분합니다.

### 2-1. 인텐트 (Privileged Gateway Intents)

Developer Portal → `Bot` → `Privileged Gateway Intents`

| 인텐트 | 설정 | 이유 |
|---|:--:|---|
| Presence Intent | **끄기** | 사용하지 않습니다 |
| Server Members Intent | **끄기** | 사용하지 않습니다 |
| Message Content Intent | **끄기** | **봇은 사용자가 쓴 글을 읽지 않습니다** |

**셋 다 꺼 두세요.** 이 봇이 요청하는 인텐트는 코드에 다음과 같이 고정되어 있고, 전부
비특권(non-privileged) 인텐트입니다.

```python
# scripts/bot/__main__.py
intents = discord.Intents.none()
intents.guilds = True                   # 채널 조회
intents.guild_scheduled_events = True   # 디스코드 이벤트 연동
```

필요 없는 권한을 요청하지 않는 것 자체가 방어입니다. 나중에 봇이 100개 서버를 넘기면
특권 인텐트는 디스코드 심사 대상이 되는데, 여기에는 해당 사항이 없습니다.

### 2-2. OAuth2 초대 권한

`OAuth2` → `URL Generator`

**스코프 (Scopes)**
- `bot`
- `applications.commands` ← 없으면 `/ksl` 슬래시 명령이 보이지 않습니다

**봇 권한 (Bot Permissions)**

| 권한 | 용도 |
|---|---|
| View Channels | `#schedule` 채널 접근 |
| Send Messages | 시간표 최초 게시 |
| Embed Links | 임베드 표시 |
| Read Message History | 기존 시간표 메시지를 찾아 수정 |
| Manage Events | 디스코드 이벤트 **읽기** (연동용) |

`Administrator` 는 주지 마세요. 위 다섯 개면 충분합니다.

> **DM 알림 주의**: 알림은 DM으로 갑니다. 서버 멤버가 `개인정보 보호 설정` →
> `서버 멤버의 다이렉트 메시지 허용` 을 꺼 두면 봇이 DM을 보낼 수 없습니다. 이건 서버
> 설정으로 우회할 수 없고, 봇은 로그만 남기고 조용히 넘어갑니다. 알림 신청 시 안내 문구에
> 이 내용이 포함되어 있습니다.

### 2-3. 봇 실행

```bash
export DISCORD_BOT_TOKEN="..."        # 또는 KSL_BOT_TOKEN
export KSL_BOT_DATABASE=/var/lib/ksl/ksl_bot.sqlite3
export KSL_REMINDER_LEAD_MINUTES=15

pip install -r scripts/requirements.txt
cd scripts && python -m bot
```

봇을 켠 뒤 `templates/sign_language_ksl/meta.yaml` 에 아래를 추가해야 버튼이 나타납니다.

```yaml
interactions: true
```

> **중복 게시 주의**: 봇과 웹훅 빌드가 **같은 채널**에 게시하면 시간표가 두 벌 생깁니다.
> 봇을 쓰기로 했다면 `meta.yaml` 의 `webhook:` 블록을 지우거나, 둘을 다른 채널에 두세요.

---

## 3. `main` 병합 가이드 / Merging to main

### 3-1. GitHub UI (권장)

1. 저장소 상단의 **`Compare & pull request`** 배너를 누릅니다.
   (배너가 사라졌다면 `Pull requests` → `New pull request`)
2. **base 저장소를 반드시 확인하세요.** 포크이기 때문에 GitHub가 기본으로
   `HelpingHandsVR/schedule` 을 base로 잡습니다.

   ```
   base repository: LeeSimYul/KSL-schedule   ← 이걸로 바꿔야 합니다
   base: main  ←  compare: claude/serene-johnson-mqcuhy
   ```

   이 한 줄을 놓치면 **원본 저장소에 PR이 열립니다.**
3. `Create pull request` → CI(`Build schedule manifests`)가 초록색인지 확인
4. `Merge pull request`
   - **Squash and merge** 권장 — `main` 히스토리가 커밋 하나로 깔끔하게 남습니다.
5. 병합 후 브랜치 삭제 (`Delete branch`)

### 3-2. 명령줄

```bash
git checkout main
git pull origin main

# 히스토리를 남기고 싶다면
git merge --no-ff claude/serene-johnson-mqcuhy

# 커밋 하나로 합치고 싶다면 (UI의 Squash and merge와 동일)
# git merge --squash claude/serene-johnson-mqcuhy && git commit

git push origin main
```

### 3-3. 병합 직후 확인

`main` 에 푸시되면 워크플로가 실행됩니다(`on: push: branches: [main]`) — **단, Actions가
켜져 있어야 합니다.**

> 포크된 저장소는 Actions가 기본적으로 꺼져 있습니다. 실제로 이 저장소의 워크플로는
> 등록만 되어 있고 **실행 이력이 0건**입니다. `Actions` 탭에 들어가
> `I understand my workflows, go ahead and enable them` 이 보이면 눌러서 켜 주세요.
> 예약(cron) 실행은 포크에서는 켜도 동작하지 않습니다 — 4장을 참고하세요.

1. `Actions` 탭에서 `Build schedule manifests` 가 초록색인지 확인
   (자동 실행이 안 됐다면 `Run workflow` 로 수동 실행)
2. 첫 실행 로그에 이렇게 찍히면 정상입니다.
   ```
   ::notice::deploy branch does not exist yet - creating it
   ```
3. `deploy` 브랜치가 생기고 `output/old.json`, `output/webhook.json` 이 들어 있는지 확인

> 시크릿을 아직 등록하지 않았다면 디스코드에는 아무것도 게시되지 않고, 매니페스트만
> 생성됩니다. 안전하게 먼저 돌려 보기 좋은 상태입니다.

---

## 4. 독립 저장소 전환 / Going standalone

### 4-1. 먼저: 지금 워크플로는 한 번도 실행된 적이 없습니다

확인 결과입니다.

```
워크플로 등록  : Build schedule manifests (state: active, 2025-11-28 등록)
실행 이력      : 0건
```

매일 도는 cron(`17 5 * * *`)이 등록되어 있는데도 실행 이력이 0건인 이유는 버그가 아니라
GitHub 정책입니다.

> **포크된 저장소에서는 예약(`schedule`) 워크플로가 기본적으로 비활성화됩니다.**
> 포크의 Actions 자체도 기본적으로 꺼져 있습니다.

즉 **독립 저장소로 전환하는 것은 단순한 정리가 아니라, 자동 갱신을 실제로 동작시키는
전제 조건**입니다. 포크 상태로 두면 손으로 `Run workflow` 를 누를 때만 시간표가 갱신됩니다.

전환 후 `Actions` 탭에서 워크플로가 활성 상태인지 한 번 확인하고, 첫 회는
`Run workflow` 로 수동 실행해 보는 것을 권합니다.

### 4-2. 방법 1 — 새 저장소로 이전 (권장)

GitHub는 **포크 관계 해제를 UI나 API로 제공하지 않습니다.** 셀프 서비스로 가능한 길은
새 저장소를 만들어 밀어 넣는 것입니다.

```bash
# 0) 먼저 브랜치를 main 으로 합칩니다 (3장 참고)

# 1) GitHub에서 새 저장소를 만듭니다.
#    - 이름: KSL-schedule  (원하는 이름)
#    - Public / Private 선택
#    - README, .gitignore, license 는 모두 체크 해제 (빈 저장소여야 합니다)

# 2) 현재 저장소를 미러로 받습니다 (모든 브랜치·태그 포함)
cd /tmp
git clone --mirror https://github.com/LeeSimYul/KSL-schedule.git ksl-mirror
cd ksl-mirror

# 3) 새 저장소로 전부 밀어 넣습니다
git remote set-url --push origin https://github.com/LeeSimYul/<새-저장소-이름>.git
git push --mirror

# 4) 평소 쓰던 작업 폴더의 remote 를 새 저장소로 바꿉니다
cd ~/KSL-schedule
git remote set-url origin https://github.com/LeeSimYul/<새-저장소-이름>.git
git remote -v                      # 새 주소인지 확인
git fetch origin && git status
```

`--mirror` 는 모든 브랜치와 태그, 전체 커밋 이력을 그대로 옮깁니다. **원본에 대한 기여
이력이 사라지지 않으므로 출처 표기 측면에서도 이 방법이 가장 정직합니다.**

전환 뒤 할 일:

```bash
# 원본을 upstream 으로 남겨 두고 싶다면 (선택)
git remote add upstream https://github.com/HelpingHandsVR/schedule.git
git remote set-url --push upstream DISABLED     # 실수로 원본에 push 하는 것 방지
```

- **시크릿은 따라오지 않습니다.** 새 저장소에 다시 등록해야 합니다 (1장).
- Actions가 켜져 있는지 확인합니다: `Settings` → `Actions` → `General` →
  `Allow all actions and reusable workflows`.
- `Settings` → `Actions` → `General` → `Workflow permissions` 는
  `Read and write permissions` 가 아니어도 됩니다. 워크플로에 `permissions: contents: write`
  가 명시되어 있습니다.
- 기존 저장소는 아카이브(`Settings` → `Archive this repository`)하고 README에 새 주소를
  적어 두면 링크가 끊기지 않습니다.

> **잃게 되는 것**: 스타·워치·포크 수, 기존 이슈/PR, 원본과의 `Sync fork` 버튼.
> 커밋 이력과 코드는 전부 보존됩니다.

### 4-3. 방법 2 — GitHub 지원팀에 포크 해제 요청

저장소 주소와 스타·이슈를 **그대로 유지**하면서 포크 관계만 끊고 싶다면, GitHub Support에
요청할 수 있습니다.

1. https://support.github.com/request 접속
2. 카테고리에서 저장소 관련 항목 선택
3. 요청 예시:
   > Please detach `LeeSimYul/KSL-schedule` from its upstream fork network
   > (`HelpingHandsVR/schedule`). The repository has diverged substantially and is now
   > maintained as an independent project.
4. 처리까지 보통 며칠 걸립니다.

원본 저장소가 비공개거나 조직 정책에 걸리면 거절될 수 있습니다. 급하지 않다면 이 방법이
가장 깔끔하고, 급하다면 4-2가 확실합니다.

### 4-4. 라이선스 정리 (공개 운영 전 필수)

`NOTICE` 파일에 적어 둔 대로, **원본 저장소에는 라이선스가 없습니다.** 포크를 떠나 독립
프로젝트로 공개 운영하려면 이 부분을 먼저 정리하는 편이 안전합니다.

1. 원저작자(Devon)에게 연락합니다. 원본 README에 연락 안내가 있고, Helping Hands 디스코드
   서버를 통해서도 닿을 수 있습니다.
2. 요청 내용 예시:
   > Hi Devon — we've built a Korean Sign Language (KSL) version of your schedule tool for
   > the VRChat 한국수어교실 community, and we'd like to run it as its own repository.
   > Would you be willing to add a license (MIT or Apache-2.0) to
   > HelpingHandsVR/schedule, or give us written permission to use and publish the
   > derived work? We credit the original prominently in our README and NOTICE.
3. 답을 받으면 같은 라이선스의 `LICENSE` 파일을 추가하고, 허락 내용을 `NOTICE` 에
   기록해 둡니다.

이 저장소가 자체 `LICENSE` 파일을 넣지 않은 이유가 이것입니다 — 기반 코드의 라이선스를
정할 수 있는 사람은 원저작자뿐입니다.

### 4-5. 포크로 남기기로 했다면

원본을 계속 동기화할 생각이라면, `Sync fork` 시 아래 파일에서 충돌이 날 수 있습니다.

| 파일 | 충돌 가능성 | 해결 방향 |
|---|:--:|---|
| `scripts/formats/webhook.py` | 높음 | 렌더링이 `embeds.py` 로 빠졌습니다. 원본 변경분을 `embeds.py` 에 반영 |
| `scripts/build_manifests.py` | 높음 | 로딩이 `loader.py` 로 빠졌습니다 |
| `scripts/definitions.py` | 중간 | 추가 필드는 전부 선택 사항이라 대개 양쪽을 합치면 됩니다 |
| `schema/*.schema.json` | 중간 | 추가된 속성만 남기면 됩니다 |
| `.github/workflows/build_manifests.yml` | 중간 | `permissions:` 와 deploy 로직은 유지하세요 |
| `README.md`, `NOTICE` | 높음 | KSL 버전을 유지 |
| `templates/sign_language_ksl/*` | 낮음 | 이쪽이 정본입니다 |
| `templates/sign_language_{asl,bsl,dgs,jsl,lsf}/*`, `templates/server_*/*` | **없음** | **일부러 건드리지 않았습니다** |

다른 언어 레인의 템플릿을 **의도적으로 수정하지 않은 이유**가 이것입니다. 그대로 두면
원본이 그 파일들을 갱신해도 충돌 없이 그냥 따라옵니다.

### 4-6. 전환 후 점검

```bash
python scripts/tests/test_ksl.py                       # 38개 테스트
python scripts/build_manifests.py --no-send --preview  # 디스코드 전송 없이 렌더링
```

## 5. 자동화 안정성 요약 / Reliability

| 상황 | 동작 |
|---|---|
| 웹훅 시크릿 없음 | 경고 후 해당 레인만 건너뜀, 빌드 성공 |
| 시간표 메시지가 삭제됨 | 새로 게시하고 새 ID를 로그에 출력 |
| 웹훅이 폐기됨 (403) | `::error::` 주석을 남기고 **다른 레인은 계속 진행** |
| Rate limit (429) / 서버 오류 (5xx) | discord.py가 자동 재시도 (최대 5회) |
| 모든 레인 실패 | 빌드 실패 — 시크릿이나 네트워크 문제 신호 |
| 임베드가 6000자 초과 | 한도 내로 잘라내고 경고. 디스코드가 거부해 시간표가 멈추는 것보다 낫습니다 |
| 템플릿 문법 오류 (빌드) | 빌드 실패 — 깨진 시간표를 게시하지 않음 |
| 템플릿 문법 오류 (봇 실행 중) | **이전 시간표를 유지**하고 로그만 남김 |
| 봇의 반복 작업이 예외로 중단 | 로그를 남기고 **자동 재시작** |
| DM이 닫힌 사용자 | 로그만 남기고 다음 사람에게 계속 진행 |
| 봇이 꺼져 있던 동안 지난 알림 | 30분(기본)이 지난 건은 발송하지 않음 |

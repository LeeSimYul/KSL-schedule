# KSL Schedule

**VRChat 한국수어교실(KSL) 공식 스케줄 시스템.**
수업 일정을 디스코드에 **전 세계 시간대로 자동 표시**하여, 한국 학생과 해외 학생이 같은
메시지를 보고 같은 시각을 이해할 수 있게 합니다.

> 이 프로젝트는 [HelpingHandsVR/schedule](https://github.com/HelpingHandsVR/schedule)의
> 코드를 기반으로 출발했습니다. 훌륭한 토대를 공개해 주신 원저작자 **scarletcafe(devon)** 님과 Helping
> Hands 커뮤니티에 깊이 감사드립니다.
>
> This project is built on [HelpingHandsVR/schedule](https://github.com/HelpingHandsVR/schedule)
> by **scarletcafe(devon)**. Our sincere thanks to Devon and the Helping Hands community for making the
> original work public — the manifest pipeline, the event-lane template design and the
> `old.json` format all originate there.

---

## 📋 학급 체계 / Class system

수업은 아래 **세 개 반** 중 하나에 속합니다. `events.yaml` 에서는 **키**로만 참조합니다.

| 키 | 표시 | 반 이름 | 내용 |
|---|:--:|---|---|
| `seed` | 🌱 | **씨앗반** (입문) | 지문자, 인사말 등 수어를 처음 접하는 분 |
| `starlight` | ⭐ | **별빛반** (단어) | 단어 위주의 손 모양과 기초 수어 단어 |
| `moonlight` | 🌙 | **달빛반** (문장) | 문장 연결, 비수지 신호(표정), 실전 회화 |

임베드에는 이렇게 표시됩니다:

```
⭐ [별빛반 - 단어 · Starlight Class - Vocabulary]
```

> 수업이 아닌 모임(자유 모임, 문화 교류회 등)은 `level` 을 **생략**합니다. 학급 라인이
> 표시되지 않습니다.

## 👥 운영진 직책 / Host titles

진행자 이름 옆 괄호 안에 표시됩니다. `events.yaml` 의 `role` 에 **키**를 적습니다.

| 키 | 표시 | 직책 | English |
|---|:--:|---|---|
| `principal` | 👑 | 교장선생님 | Principal |
| `homeroom_teacher` | 🏫 | 담임선생님 | Homeroom Teacher |
| `student_council_president` | 🎗️ | 학생회장 | Student Council President |
| `appreciation_head` | 🎬 | 감상부장 | Appreciation Dept Head |
| `exploration_head` | 🧭 | 탐험부장 | Exploration Dept Head |

```
진행자 · Host: Korea_Yujin (🏫 담임선생님 · Homeroom Teacher)
```

## 🖥️ 장비 표기 / Equipment

`platforms` 와 `hand_tracking` 으로 지정하며, 학급과는 **별도 줄**에 표시됩니다.

| 값 | 표시 |
|---|---|
| `pcvr` | 🖥️ PCVR |
| `quest` | 🥽 Quest Standalone |
| `desktop` | 💻 Desktop |
| `mobile` | 📱 Mobile |
| `hand_tracking: required` / `recommended` / `supported` | 🖐️ 핸드트래킹 필수 / 권장 / 지원 |

```
🖥️ PCVR | 🥽 Quest Standalone | 🖐️ 핸드트래킹 권장 · hand tracking recommended
```

## 🕒 표시 시간대 / Timezones

디스코드 동적 타임스탬프(`<t:...:f>` / `<t:...:R>`)가 **보는 사람의 시간대**로 자동
표시되고, 그 아래에 아래 7개 지역을 명시합니다. 서머타임 약어(PST↔PDT, CET↔CEST)는
날짜에 따라 **자동으로** 바뀝니다.

🇰🇷 KST · 🇯🇵 JST · 🇺🇸 PDT · 🇺🇸 EDT · 🇪🇺 CEST · 🇦🇺 AEST · 🌐 UTC

---

## ✏️ 스케줄 수정하는 법 / Editing the schedule

수정할 파일은 **두 개**뿐입니다.

| 파일 | 무엇을 담는가 | 언제 고치나 |
|---|---|---|
| `templates/sign_language_ksl/events.yaml` | 수업 목록, 휴강일 | **수업이 바뀔 때마다** |
| `templates/sign_language_ksl/meta.yaml` | 반·직책·시간대·VRChat 링크 | 체계 자체가 바뀔 때 (드묾) |

### 수업 하나 추가하기

`events.yaml` 의 `events:` 아래에 블록을 하나 더 붙입니다.

```yaml
  - host: Korea_Yujin            # 진행자의 VRChat / 디스코드 이름
    name: "KSL 별빛반"            # 번역이 없을 때 쓰이는 대체 이름
    tags: ["class", "vocabulary"]
    kind: class                  # class | event | social | recharge
    level: starlight             # 🌱 seed · ⭐ starlight · 🌙 moonlight
    role: homeroom_teacher       # 위 직책 표의 키
    title:                       # 임베드 제목 (한/영)
      ko: 별빛반 (단어)
      en: Starlight Class (Vocabulary)
    description:                 # 한 줄 설명 (한/영)
      ko: 일상에서 가장 많이 쓰는 한국수어 단어를 익힙니다.
      en: Everyday Korean Sign Language vocabulary.
    platforms: ["pcvr", "quest"]
    hand_tracking: recommended
    schedule:
      basis: "2025-12-03"        # ⚠️ 이 수업이 실제로 열린 날짜
      day: Wednesday             # basis 의 요일과 반드시 일치
      hour: 21                   # KST 24시간제
      minute: 0
      duration: 90               # 분 단위
      # interval: 14             # 격주라면. 생략하면 매주(7일)
```

> ⚠️ **`basis` 와 `day` 는 반드시 일치해야 합니다.** 어긋나면 빌드가 실패하며, 오류
> 메시지가 실제 요일을 알려 줍니다. 잘못된 시각이 조용히 게시되는 것보다 낫습니다.
>
> ⚠️ **`basis` 는 "이 수업이 실제로 열린 어느 날"** 입니다. 격주 수업이 어느 주에
> 열리는지 판단하는 기준점이 되므로, 아무 날짜나 적으면 안 됩니다.

### 수업 잠시 쉬기

```yaml
    paused: true      # 삭제하지 않고 시간표에서만 감춥니다
```

### 휴강일(재충전의 날) 등록

`events.yaml` 맨 아래 `closures:` 에 적습니다. 그날은 🔋 전용 임베드로 바뀌고 해당
수업들이 시간표에서 빠집니다.

```yaml
closures:
  - date: "2026-09-24"
    until: "2026-09-26"      # 끝날 포함. 생략하면 하루
    reason:
      ko: 추석 연휴
      en: Chuseok holiday
```

> 설날·추석은 음력이라 해마다 날짜가 다릅니다. **매년 직접 갱신**해 주세요.

### 수정 후 확인

```bash
pip install -r scripts/requirements.txt

# 디스코드에 보내지 않고 결과만 확인 → output/preview.json
python scripts/build_manifests.py --no-send --preview

# 테스트
python scripts/tests/test_ksl.py
```

`main` 에 푸시하면 GitHub Actions가 자동으로 디스코드 `#schedule` 메시지를 갱신합니다.
모든 설정 항목이 주석과 함께 채워진 예시는 `docs/examples/` 에 있습니다.

---

## ⚙️ 동작 구조 / How it works

| | 빌드 (GitHub Actions) | 봇 (별도 호스팅, 선택) |
|---|---|---|
| 실행 | 하루 몇 번 실행 후 종료 | 항상 켜져 있음 |
| 필요한 것 | 웹훅 URL | 봇 토큰 |
| 기능 | 임베드 게시·수정, 동적 타임스탬프, 다국어, 재충전의 날, 링크 버튼 | 위의 전부 + RSVP 버튼, 알림 DM, 디스코드 이벤트 연동 |

디스코드는 웹훅 메시지에 **링크 버튼만** 허용하기 때문에, 클릭에 응답해야 하는 기능은
살아 있는 봇 프로세스가 필요합니다. 자세한 이유는
[docs/KSL_GUIDE.md](docs/KSL_GUIDE.md) 0장에 있습니다.

`main` 브랜치에는 템플릿과 빌드 코드가 있고, `deploy` 브랜치에는 GitHub Actions가 생성한
매니페스트(`output/`)가 올라갑니다. VRChat 월드나 외부 페이지는 `deploy` 쪽을 읽습니다.

## 📚 문서 / Documentation

- **[docs/KSL_GUIDE.md](docs/KSL_GUIDE.md)** — 기능별 단계 가이드, 설정 항목 설명, 문제 해결
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — GitHub Secrets, 디스코드 봇 권한/인텐트,
  `main` 병합 절차, 독립 저장소 전환
- **[docs/examples/](docs/examples/)** — 모든 설정 항목이 주석과 함께 채워진 예시 파일

## 📄 출처 및 라이선스 / Attribution & License

### 기반 코드 / Upstream

| 원본에서 온 것 | KSL에서 추가한 것 |
|---|---|
| 이벤트 레인 템플릿 구조 (`templates/`, `schema/`) | 동적 타임스탬프 · 타임존 헬퍼 (`scripts/timeutil.py`, `scripts/js/`) |
| 매니페스트 파이프라인과 `old.json` 형식 (`scripts/formats/old.py`) | 한/영 이중 표기 · KSL 임베드 (`scripts/embeds.py`) |
| 주간 시간표 임베드의 원래 레이아웃 | 학급 체계, 직책, 재충전의 날, VRChat 연동 |
| GitHub Actions 배포 구조 | RSVP·알림·디스코드 이벤트 봇 (`scripts/bot/`) |

원본의 다국어 수어 레인(ASL·BSL·DGS·JSL·LSF)과 서버 통합 레인은 **그대로 보존**되어
있습니다. 원본이 해당 파일을 갱신하더라도 충돌 없이 반영할 수 있습니다.

### 라이선스 현황 / License status

> ⚠️ **원본 저장소에는 LICENSE 파일이 없습니다.** 저장소 전체 이력을 확인했으나 라이선스
> 파일이 추가된 적이 없습니다.
>
> 라이선스가 명시되지 않은 코드는 기본적으로 **저작권자가 모든 권리를 보유**합니다.
> GitHub 이용약관은 GitHub 내부에서의 포크는 허용하지만, 그 외의 재배포나 라이선스 부여는
> 허용하지 않습니다. 따라서 **이 저장소는 아직 자체 LICENSE 파일을 추가하지 않았습니다** —
> 원저작자만이 기반 코드의 라이선스를 정할 수 있기 때문입니다.
>
> 독립 저장소로 공개 운영하기 전에 원저작자(scarletcafe(devon))에게 연락하여 (1) 원본에 라이선스를
> 추가해 달라고 요청하거나, (2) 이 저장소에 대한 명시적 사용 허락을 받으시기를 권합니다.
> 절차는 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 4-4 절에 정리되어 있습니다.

자세한 출처 기록은 [NOTICE](NOTICE) 파일을 참고하세요.

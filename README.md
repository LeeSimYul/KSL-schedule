# KSL Schedule

**VRChat 한국수어교실(KSL) 전용 디스코드 시간표 봇.**
수업 일정을 디스코드에 **전 세계 시간대로 자동 표시**하여, 한국 학생과 해외 학생이 같은
메시지를 보고 같은 시각을 이해할 수 있게 합니다.

> 이 프로젝트는 [HelpingHandsVR/schedule](https://github.com/HelpingHandsVR/schedule)의
> 코드를 기반으로 출발했습니다. 훌륭한 토대를 공개해 주신 원저작자 **Devon** 님과 Helping
> Hands 커뮤니티에 깊이 감사드립니다.
>
> This project is built on [HelpingHandsVR/schedule](https://github.com/HelpingHandsVR/schedule)
> by **Devon**. Our sincere thanks to Devon and the Helping Hands community for making the
> original work public — the manifest pipeline, the event-lane template design and the
> `old.json` format all originate there.

---

## 무엇이 들어 있나 / What's here

- **동적 타임스탬프** — `<t:...:f>` / `<t:...:R>` 로 보는 사람의 시간대에 맞춰 자동 표시되고,
  그 아래에 KST·PDT·EDT·CEST·AEST·UTC 를 명시적으로 함께 적습니다. 서머타임 약어는 날짜에
  따라 스스로 바뀝니다.
- **KSL 수업 임베드** — 난이도(씨앗/뿌리/줄기/떡잎/새싹), 진행자와 역할, 권장 VR 환경,
  VRChat 그룹·인스턴스 링크.
- **한/영 이중 표기** — 언어별 제목·설명, 번역이 없으면 있는 쪽으로 자연스럽게 축소.
- **재충전의 날** — 휴강일을 🔋 전용 스타일로 표시하고 그날 수업을 시간표에서 제외.
- **봇 (선택)** — 참석 신청(RSVP) 버튼, 시작 15분 전 DM 알림, 디스코드 이벤트 자동 연동.

## 빠르게 시작하기 / Quick start

```bash
pip install -r scripts/requirements.txt

# 디스코드에 보내지 않고 렌더링 결과만 확인 (output/preview.json)
python scripts/build_manifests.py --no-send --preview

# 테스트 (pytest 없이도 실행됩니다)
python scripts/tests/test_ksl.py
```

수업 일정은 `templates/sign_language_ksl/events.yaml`, 표시 설정은 같은 폴더의
`meta.yaml` 에서 수정합니다. 모든 옵션이 채워진 예시는 `docs/examples/` 에 있습니다.

## 동작 구조 / How it works

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

## 문서 / Documentation

- **[docs/KSL_GUIDE.md](docs/KSL_GUIDE.md)** — 기능별 단계 가이드, 설정 항목 설명, 문제 해결
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — GitHub Secrets, 디스코드 봇 권한/인텐트,
  `main` 병합 절차, 독립 저장소 전환, 원본 저장소 동기화
- **[docs/examples/](docs/examples/)** — 모든 설정 항목이 주석과 함께 채워진 예시 파일

## 출처 및 라이선스 / Attribution & License

### 기반 코드 / Upstream

이 저장소는 `HelpingHandsVR/schedule` 에서 갈라져 나왔습니다. 아래 부분은 원저작자의
저작물이며, KSL 전용 기능은 그 위에 추가된 것입니다.

| 원본에서 온 것 | KSL에서 추가한 것 |
|---|---|
| 이벤트 레인 템플릿 구조 (`templates/`, `schema/`) | 동적 타임스탬프 · 타임존 헬퍼 (`scripts/timeutil.py`, `scripts/js/`) |
| 매니페스트 파이프라인과 `old.json` 형식 (`scripts/formats/old.py`) | 한/영 이중 표기 · KSL 임베드 (`scripts/embeds.py`) |
| 주간 시간표 임베드의 원래 레이아웃 | 재충전의 날, 난이도, VRChat 연동 |
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
> 독립 저장소로 공개 운영하기 전에 원저작자(Devon)에게 연락하여 (1) 원본에 라이선스를
> 추가해 달라고 요청하거나, (2) 이 저장소에 대한 명시적 사용 허락을 받으시기를 권합니다.
> 절차는 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 4-4 절에 정리되어 있습니다.

KSL 전용으로 새로 작성된 부분의 저작권은 이 저장소 기여자에게 있으나, 기반 코드의 라이선스가
정해지기 전까지는 전체를 하나의 라이선스로 배포할 수 없습니다.

자세한 출처 기록은 [NOTICE](NOTICE) 파일을 참고하세요.

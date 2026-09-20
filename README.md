# KSL Schedule

VRChat 한국수어교실(KSL)의 수업 일정을 디스코드에 **전 세계 시간대로 자동 표시**하기 위한
저장소입니다. [HelpingHandsVR/schedule](https://github.com/HelpingHandsVR/schedule)에서
갈라져 나왔으며, 원본의 다국어 수어 레인(ASL·BSL·DGS·JSL·LSF)을 그대로 유지합니다.

This repository handles generation of the schedule manifest based on a template, with a
KSL-specific presentation layer on top: Discord dynamic timestamps, bilingual (한/영)
class embeds, Recharging Days, and an optional bot for RSVPs and reminders.

The `main` branch contains the template and the compiling code, which is manually
authored. The `deploy` branch contains automatically generated commits by GitHub Actions
that produce the schedule manifest. These are regenerated each time the template is
updated, or at regular intervals, so that they can be consumed and displayed in other
locations (e.g. VRChat or the Discord server).

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

## 문서 / Documentation

- **[docs/KSL_GUIDE.md](docs/KSL_GUIDE.md)** — 단계별 적용 가이드, 봇 배포 방법, 문제 해결
- **[docs/examples/](docs/examples/)** — 모든 설정 항목이 주석과 함께 채워진 예시 파일

원본 저장소 관련 문의는 Devon에게, KSL 관련 변경은 이 저장소의 이슈로 남겨 주세요.

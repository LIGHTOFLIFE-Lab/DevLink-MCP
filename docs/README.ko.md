# DevLink-MCP

관리하는 서버들을 한곳에서 다루는 로컬 도구.

서버 정보를 평문 파일 하나에 적어두면, DevLink-MCP 가 그것으로 MCP 서버 설정을
만들어 AI 어시스턴트가 그 장비들을 다룰 수 있게 하고, 사이트를 내려받아
쓰던 편집기로 고치게 해주고, 깃을 되돌리기 삼아 변경분을 올려줍니다.

**[내려받아 실행하기](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/releases/latest)** —
파이썬 없이 바로 씁니다. 자기 OS 용 파일을 받아서 열면 브라우저에 설정 화면이
뜹니다.

| 운영체제 | 파일 |
|---|---|
| 윈도우 10/11 | `DevLink-MCP-…-windows-x64.exe` |
| macOS (애플 실리콘) | `DevLink-MCP-…-macos-arm64.dmg` |
| macOS (인텔) | `DevLink-MCP-…-macos-x86_64.dmg` |
| Linux | `DevLink-MCP-…-linux-x86_64.tar.gz` |

**코드 서명이 되어 있지 않습니다.** 인증서 비용이 드는데 이 프로젝트에는 그
예산이 없습니다. 그래서 처음 한 번 경고가 뜹니다.

- *Windows* — SmartScreen 파란 경고창. **추가 정보** → **실행**.
- *macOS* — Gatekeeper 가 첫 실행을 막습니다. 앱을 **오른쪽 클릭 → 열기**,
  또는 `xattr -dr com.apple.quarantine /Applications/DevLink-MCP.app`.

릴리스마다 `.sha256` 이 함께 올라가니 받은 파일을 검증하실 수 있습니다.
빌드는 태그된 소스로부터 GitHub 러너에서
[읽어볼 수 있는 워크플로](../.github/workflows/release.yml)가 만듭니다.
명령줄이 편하면 `pip install devlink-mcp` 로 같은 프로그램을 쓸 수 있습니다.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/LIGHTOFLIFE-Lab/DevLink-MCP)
[![CI](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/LIGHTOFLIFE-Lab/DevLink-MCP/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](../LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](../pyproject.toml)

English: [../README.md](../README.md)

> **상태: alpha.** 여기 적힌 기능은 동작하고 테스트로 덮여 있지만
> 아직 어린 프로젝트라 세부는 바뀔 수 있습니다.

---

## 왜 만들었나

남의 웹사이트를 유지보수하다 보면 SFTP 클라이언트에 세션이 수십 개 쌓이고,
사이트마다 로컬 사본을 만드는 게 품이 아까워 결국 서버에서 직접 고치게 됩니다.
그러다 뭔가를 덮어쓰고 되돌릴 방법이 없는 날이 옵니다.

DevLink-MCP 는 일하는 방식을 바꾸지 않으면서 그 위험만 걷어내는 최소한의 장치입니다.

- **설정 하나, 소비처 여럿.** 관리하는 파일은 `servers.ini` 하나뿐입니다.
  여기서 MCP 설정과 배포 설정이 생성되므로 둘이 어긋날 수 없습니다.
- **신경 쓰지 않아도 붙는 안전장치.** 생성되는 모든 연결에 파괴적 명령 차단,
  지정한 폴더로 한정된 경로 허용, 명령 타임아웃, 출력 상한이 자동으로 붙습니다.
- **되돌릴 수 있는 배포.** 변경된 파일만 올리고, 덮어쓸 파일은 서버에 먼저
  백업하고, 배포마다 깃 태그를 남깁니다.
- **남이 서버를 만졌는지 알아챕니다.** 쓰기 전에 마지막 배포 때 기록한 상태와
  서버를 대조합니다. 동료나 고객이 서버에서 직접 고쳤다면 그 작업을 지우는 대신
  멈춥니다.

## 설치 없이 바로 해보기

위의 **Open in GitHub Codespaces** 를 누르면 컨테이너가 만들어지고 패키지가
설치된 터미널이 열립니다.

```bash
bash .devcontainer/demo.sh
```

한 사이클이 통째로 돕니다 — 사이트를 수집하고, 고치고, 배포하고, 누군가 서버를
직접 만졌을 때 배포가 거부되는 것을 보고, 되돌리기까지. 서버 역할을 하는 로컬
폴더를 상대로 하므로 SSH 도 자격증명도 필요 없고 뒷정리할 것도 없습니다.

```bash
pytest -q                                   # 전체 테스트 89개
devlink gui --port 8765 --no-browser        # 설정 화면. 포트 8765 로 전달됩니다
```

> **Codespace 에 실제 자격증명을 넣지 마세요.** `servers.ini` 는 비밀번호를
> 평문으로 저장하고, 클라우드 개발 컨테이너는 고객사 서버를 다룰 곳이 아닙니다.
> 실제 작업은 로컬에 설치해서 하세요.

## 설치

```bash
pip install devlink-mcp          # 설정 화면 + 설정 생성 + MCP 서버 (Node.js 불필요)
pip install 'devlink-mcp[sync]'  # 수집/배포/롤백까지 (paramiko 필요)
```

Python 3.9 이상. 화면과 설정 생성은 표준 라이브러리만 씁니다.
`paramiko` 는 실제로 서버에 붙을 때만 필요합니다.

## 시작하기

```bash
devlink init     # 폴더 골격 생성
devlink gui      # 브라우저에 설정 화면 열기
```

화면이 순서대로 안내합니다. 실행 환경 점검 → 서버 추가(WinSCP 에서 한 번에
가져오기 가능) → MCP 클라이언트에 등록.

터미널이 편하면:

```bash
devlink import ~/Desktop/WinSCP.ini   # 저장된 세션 가져오기
devlink check                         # 쓰지 않고 검사만
devlink build                         # MCP 설정 생성
```

## 서버 한 개는 이렇게 생겼습니다

```ini
[DEFAULT]
port    = 22
exclude = data/, uploads/, cache/, *.log, node_modules/, .env

[web1]
host     = 10.0.0.1
user     = deploy
key      = ~/.devlink/config/keys/web1.pem
remote   = /var/www/html
backup   = /var/backup/devlink
allow    = ^ls( .*)?|^cat .*|^grep .*
```

서버당 여섯 줄입니다. 이 중 `exclude` 를 제대로 잡는 게 중요합니다.
고객 업로드 파일과 로그를 작업 사본에서 빼주는데, 이게 저장소 크기가
수 MB 냐 수 GB 냐를 가릅니다.

전체 항목은 [`examples/servers.example.ini`](../examples/servers.example.ini) 참고.

## 사이트 작업

```bash
devlink pull web1                 # 서버의 현재 상태를 받아 커밋
# ... 로컬에서 고치고 원하는 만큼 커밋 ...
devlink deploy web1               # 변경분만 올리고 태그
devlink status web1               # 로컬 · 서버 · 마지막 배포 비교
devlink rollback web1             # 서버를 되돌림
```

`pull` 을 먼저 하는 건 형식이 아닙니다. 그게 `rollback` 이 돌아갈 지점을
만들어 주고, 지난번 이후 누가 서버를 건드렸는지 알게 되는 시점입니다.

## 무엇이, 언제 백업되는가

백업은 기억해서 하는 일이 아닙니다. 작업을 잃을 수 있는 모든 동작이 먼저 사본을 남깁니다.

| 시점 | 보존되는 것 | 어디에 |
|---|---|---|
| `pull` (커밋 안 한 수정이 있을 때) | 그 수정을 `wip:` 로 먼저 커밋한 뒤 작업본 교체 | 깃 이력 |
| `pull` | 그 시점의 서버 상태 | 커밋 |
| `deploy` | 덮어쓸 서버 파일들 | `backup` 경로의 아카이브 + 배포 태그 |
| `deploy` | 배포한 내용 | 깃 태그 |
| `rollback` | — | 아카이브를 복원하고, 없으면 이력에서 재구성 |

알아둘 것 두 가지:

**`backup` 경로가 없어도 되돌릴 수 있습니다.** `rollback` 이 깃 이력으로 물러나
이전 버전을 다시 배포합니다. 그래도 `backup` 을 두는 편이 낫습니다 — 서버에서
복원하는 게 빠르고 이 PC 를 잃어도 남으니까요. 그래서 `devlink check` 가 없으면 경고합니다.

**MCP 업로드도 백업됩니다.** DevLink-MCP 자체가 MCP 서버이므로, 어시스턴트가 파일을
쓰면 덮어쓰일 버전이 먼저 백업 폴더로 복사됩니다. 설정할 것도 없고 잊을 방법도 없습니다.

**다른 도구로 쓴 것은 백업되지 않습니다.** SFTP 클라이언트나 다른 MCP 서버는 이
흐름을 타지 않습니다. 다음 `deploy` 때 DevLink-MCP 가 알아채고 덮어쓰기를 거부하며
`pull` 로 깃에 들일 수는 있지만, 그 쓰기 자체에는 안전망이 없었습니다.

## WinSCP 에서 가져오기

WinSCP 는 INI 파일(도구 > 환경 설정 내보내기/백업)이나 레지스트리 덤프로
내보냅니다. 둘 다 읽으며, 확장자가 아니라 내용을 보고 형식을 판단합니다.

주소·포트·계정·키 경로·프록시가 넘어옵니다. **저장된 비밀번호도 함께 넘어옵니다.**
단 WinSCP 마스터 비밀번호가 걸린 세션은 풀 수 없으므로 빈칸으로 남습니다.

## 비밀번호에 대해

스스로 판단하실 수 있도록 두 가지를 분명히 해둡니다.

**`servers.ini` 는 비밀번호를 평문으로 저장합니다.** 그 파일을 읽을 수 있는
사람은 비밀번호를 읽을 수 있습니다. 개인키 인증을 쓰면 이 문제가 없고,
예시도 그렇게 되어 있습니다. config 폴더는 본인만 읽도록 두세요.

**DevLink-MCP 는 WinSCP 저장 비밀번호를 복호화할 수 있습니다.** 마스터 비밀번호가
없으면 WinSCP 는 비밀번호를 암호화가 아니라 가역 난독화로 저장합니다.
구현은 [`src/devlink_mcp/winscp.py`](../src/devlink_mcp/winscp.py) 에 있고 공개된
알고리즘을 보고 새로 쓴 것으로, WinSCP 코드는 들어 있지 않습니다.
세션 쉰 개를 옮기면서 비밀번호 쉰 개를 다시 타이핑하지 않기 위한 기능입니다.
이 기능이 디스크에 있는 게 싫으시면 `decrypt_password` 의 본문을 지우세요.
가져오기는 실패를 "비밀번호 없음" 으로 처리하고 빈칸으로 둡니다.

자세한 내용은 [SECURITY.md](../SECURITY.md).

## 구조

```
                    ┌──► devlink serve ──► MCP 클라이언트 ──► 어시스턴트
servers.ini ──► DevLink-MCP
                    └──► pull / deploy / rollback ──► sites/<이름>/  (깃 저장소)
```

`devlink serve` 는 그 자체가 MCP 서버입니다. stdio 로 JSON-RPC 를, paramiko 로
SSH 를 말합니다. 도구 네 개(`list-servers`, `execute-command`, `upload`,
`download`)를 제공하고 설정의 허용·차단 목록, 경로 제한, 타임아웃, 출력 상한을
적용합니다. **Node.js 가 전혀 필요 없습니다.**

`devlink build` 는 여전히 `ssh-mcp-config.json` 을 만듭니다.
[`@fangjunjie/ssh-mcp-server`](https://github.com/classfang/ssh-mcp-server) 를
쓰고 싶은 분을 위한 것인데, 그쪽은 업로드 백업이 없습니다. 그래서 직접 만들었습니다.

## 폴더 구조

`$DEVLINK_HOME` (기본값 `~/.devlink`):

```
config/
  servers.ini            직접 편집하는 파일
  keys/                  개인키. 화면에서 고르면 여기로 복사됩니다
  ssh-mcp-config.json    생성물
  sites.json             생성물
sites/<이름>/            작업 사본, 깃 저장소
repos/                   로컬 bare 미러 (선택)
logs/
```

## 기여

버그 신고와 패치 환영합니다 — [CONTRIBUTING.md](../CONTRIBUTING.md) 를 보세요.
테스트는 서버 없이 돌아갑니다. 배포 동작은 서버 역할을 하는 로컬 폴더를 상대로
실제로 실행해 검증합니다.

```bash
pip install -e '.[dev]'
pytest
```

## 라이선스

Apache License 2.0 — [LICENSE](../LICENSE), [NOTICE](../NOTICE) 참고.

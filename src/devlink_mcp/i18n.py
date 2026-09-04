# Copyright 2026 DevLink-MCP contributors
# SPDX-License-Identifier: Apache-2.0
"""Message catalogue.

English and Korean are both first-class. The language is chosen by, in order:

1. ``DEVLINK_LANG`` environment variable (``en`` or ``ko``)
2. the ``lang`` value in ``servers.ini``
3. the operating system locale
4. English

Keeping every user-visible string here means the UI and the CLI stay in sync,
and adding a language is a matter of adding one dict.
"""

from __future__ import annotations

import locale
import os

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # --- app chrome -------------------------------------------------
        "app.title": "DevLink-MCP",
        "app.subtitle": "Servers, sites, and deployments",
        "app.close": "Close this panel",
        "app.closed": "Panel closed. You can close this tab.",
        "app.recheck": "Check again",
        "update.available": "Version {latest} is available (you have {current}).",
        "update.download": "Download",
        "update.dismiss": "Not now",

        # --- environment ------------------------------------------------
        "env.title": "Environment",
        "env.node": "Node.js",
        "env.npx": "npx",
        "env.python": "Python",
        "env.git": "Git",
        "env.present": "found",
        "env.missing": "not found",
        "env.hint.node": "Install the LTS build from https://nodejs.org",
        "env.hint.npx": "Ships with Node.js",
        "env.hint.git": "Needed for pulling and deploying sites",
        "env.hint.python": "",
        "env.paramiko": "paramiko",
        "env.hint.paramiko": "Needed to reach servers. Install with: pip install 'devlink-mcp[sync]'",
        # --- server list ------------------------------------------------
        "servers.title": "Servers",
        "servers.name": "Name",
        "servers.connection": "Connection",
        "servers.auth": "Auth",
        "servers.root": "Remote root",
        "servers.empty": "No servers yet. Add one below.",
        "servers.add": "+ Add server",
        "servers.import": "Import from WinSCP",
        "servers.save": "Save and check",
        "servers.saving": "Saving…",
        "servers.edit": "Edit",
        "servers.delete": "Delete",
        "servers.confirm_delete": "Remove {name} from the list?",
        "servers.disabled": "disabled",
        "servers.auth.key": "key",
        "servers.auth.password": "password",
        "servers.auth.none": "—",
        "servers.root_missing": "not set",
        # --- editor -----------------------------------------------------
        "edit.add_title": "Add server",
        "edit.edit_title": "Edit server — {name}",
        "edit.name": "Name",
        "edit.name_hint": "How you will refer to this server",
        "edit.host": "Host",
        "edit.port": "Port",
        "edit.user": "User",
        "edit.auth": "Auth",
        "edit.password": "Password",
        "edit.password_set": "Already saved. Type only to change it.",
        "edit.key": "Key file",
        "edit.key_pick": "Choose file…",
        "edit.key_none": "— choose a key file —",
        "edit.key_manual": "Enter a path…",
        "edit.key_hint": "The file is copied into your keys folder. PuTTY .ppk files "
                         "must be converted first (PuTTYgen > Conversions > Export OpenSSH key).",
        "edit.passphrase": "Key passphrase",
        "edit.passphrase_hint": "Only if the key is passphrase-protected",
        "edit.remote": "Remote root",
        "edit.remote_hint": "Absolute path of the directory you work in",
        "edit.backup": "Backup path",
        "edit.exclude": "Exclude",
        "edit.exclude_hint": "Leave empty to use the default list",
        "edit.mode": "Transport",
        "edit.mode_exec": "Standard (exec)",
        "edit.mode_shell": "Jump host / login banner (shell) — no file transfer",
        "edit.enabled": "Enabled",
        "edit.enabled_label": "Use this server",
        "edit.ok": "OK",
        "edit.cancel": "Cancel",
        # --- import -----------------------------------------------------
        "import.title": "Import from WinSCP",
        "import.intro": "Point at a WinSCP .ini or .reg export. The format is "
                        "detected from the contents.",
        "import.method1": "Option 1 — WinSCP menu",
        "import.method1_body": "WinSCP > Tools > Export/Backup Configuration > to INI file.",
        "import.method2": "Option 2 — from the registry",
        "import.method2_body": "If WinSCP keeps its configuration in the registry, "
                               "run this in PowerShell to write a .reg file to your desktop.",
        "import.pick": "Choose file…",
        "import.none": "No file chosen",
        "import.manual": "Enter a path instead",
        "import.pw_note": "Saved passwords are imported too, unless the session is "
                          "protected by a WinSCP master password.",
        "import.result": "Imported {count} session(s).",
        "import.result_pw": "{count} password(s) came across as well.",
        "import.result_failed": "{count} password(s) could not be decrypted "
                                "(master password set). Enter those by hand.",
        "import.result_next": "Fill in the remote root, then save.",
        "import.nothing": "Nothing new to import.",
        "import.not_found": "File not found: {path}",
        "import.unreadable": "Could not read that file.",
        "import.too_big": "That file is too large (limit 4 MB).",
        "import.no_sessions": "No sessions found. Check that this is a WinSCP export "
                              "(Tools > Export/Backup Configuration > to INI file).",
        "import.skip_nohost": "{name} — no host",
        "import.skip_proto": "{name} — {proto} session, not SSH",
        "import.skip_exists": "{name} — already present",
        "import.no_file": "No file chosen.",
        # --- keys -------------------------------------------------------
        "key.saved": "Saved {name} to your keys folder.",
        "key.uploading": "Uploading…",
        "key.ppk": "PuTTY .ppk files cannot be used directly.\n"
                   "Open the key in PuTTYgen and use Conversions > Export OpenSSH key.",
        "key.not_private": "That does not look like a private key.\n"
                           "The file should begin with '-----BEGIN ... PRIVATE KEY-----'. "
                           "Make sure you picked the private key, not the .pub file.",
        # --- MCP registration -------------------------------------------
        "mcp.title": "Register with your MCP client",
        "mcp.registered": "Registered. Press again to refresh the path.",
        "mcp.not_registered": "Not registered yet. Target: {path}",
        "mcp.register": "Register",
        "mcp.reregister": "Register again",
        "mcp.done": "Registered.",
        "mcp.replaced": "Replaced the existing entry with the new path.",
        "mcp.backup": " (backup: {name})",
        "mcp.restart": "\nQuit the client completely and start it again to pick this up.",
        "mcp.bad_json": "The existing config file is not valid JSON: {error}\n"
                        "Please check it by hand: {path}",
        # --- save / validate --------------------------------------------
        "save.ok": "Saved. These servers are ready",
        "save.warn": "Saved — a few things worth checking",
        "save.errors": "Saved, but these entries cannot be used yet",
        "save.failed": "Save failed: {error}",
        "save.blocked_title": "Could not read the settings file",
        # --- config validation ------------------------------------------
        "cfg.missing_fields": "[{name}] missing required field(s): {fields}",
        "cfg.no_auth": "[{name}] needs either a password or a key",
        "cfg.placeholder_pw": "[{name}] the password is still the example value",
        "cfg.remote_abs": "[{name}] remote must be an absolute path starting with /: {value}",
        "cfg.bad_port": "[{name}] port is not a number: {value}",
        "cfg.bad_mode": "[{name}] mode must be exec or shell: {value}",
        "cfg.bad_number": "[{name}] timeout and maxoutput must be numbers",
        "cfg.dup_name": "[{name}] duplicate connection name: {value}",
        "cfg.unknown_key": "[{name}] ignoring unknown setting: {key}",
        "cfg.ppk": "[{name}] .ppk keys cannot be used directly. Convert with PuTTYgen "
                   "(Conversions > Export OpenSSH key).",
        "cfg.key_missing": "[{name}] key file not found: {path}",
        "cfg.shell_mode": "[{name}] mode = shell is only honoured by the external "
                          "ssh-mcp-server. 'devlink serve' runs commands with exec "
                          "and ignores it; file transfer is unavailable there too.",
        "cfg.no_whitelist": "[{name}] no command allowlist. A denylist is easy to work "
                            "around; consider setting 'allow' for production servers.",
        "cfg.no_backup": "[{name}] no backup path set. Deployments will still be "
                         "reversible from git history, but keeping a copy on the "
                         "server itself is faster and survives losing this machine.",
        "sync.pull_saved_local": "Uncommitted local changes were committed first "
                                 "so the pull could not destroy them.",
        "sync.rollback_from_git": "Restored from commit history (no backup archive "
                                  "was on the server).",
        "cfg.skipped": "{name} (disabled)",
        "cfg.no_servers": "No usable connections. Check your settings.",
        "cfg.ini_missing": "servers.ini not found",
        "cfg.written": "Wrote {count} connection(s) to {path}",
        "cfg.check_done": "Check complete: {servers} connection(s), {errors} error(s). "
                          "Nothing was written.",
        "cfg.no_permission": "Cannot read {path}.\n"
                             "Fix the file permissions, then reload this page.",
        "cfg.open_failed": "Could not open {path}: {error}",
        # --- sync --------------------------------------------------------
        "sync.no_site": "Unknown server: {name}",
        "sync.need_paramiko": "Remote transfer needs paramiko. Install it with:\n"
                              "    pip install 'devlink-mcp[sync]'",
        "sync.pull_start": "Collecting {name} from {host}:{remote}",
        "sync.pull_done": "Collected {count} file(s) into {path}",
        "sync.pull_first": "Collected for the first time. This is the baseline "
                           "a rollback returns to.",
        "sync.pull_nochange": "No change since the last pull.",
        "sync.pull_changed": "Remote changed since the last pull — committed as a baseline.",
        "sync.deploy_none": "Nothing to deploy: no file changes since {ref}.",
        "sync.deploy_plan": "About to deploy {count} file(s) to {host}:{remote}",
        "sync.deploy_done": "Deployed {count} file(s). Tag: {tag}",
        "sync.deploy_drift": "Refusing to deploy: the server no longer matches the last "
                             "deployment. Someone changed these files directly:\n{files}\n"
                             "Run 'devlink pull' first to bring those changes into git.",
        "sync.backup_done": "Remote backup saved: {path}",
        "sync.rollback_done": "Restored {count} file(s) from {tag}.",
        "sync.no_backup": "No remote backup found for {tag}.",
        "sync.dirty": "The working tree has uncommitted changes. Commit or stash first.",
        "sync.status_clean": "Local, remote and last deployment all agree.",
        "sync.status_drift": "The server differs from the last deployment:",
        "sync.status_undeployed": "Committed locally but not deployed:",
    },
    "ko": {
        "app.title": "DevLink-MCP",
        "app.subtitle": "서버 · 사이트 · 배포",
        "app.close": "설정 화면 닫기",
        "app.closed": "설정 화면을 닫았습니다. 이 탭을 닫으셔도 됩니다.",
        "app.recheck": "다시 확인",
        "update.available": "{latest} 버전이 나왔습니다 (현재 {current}).",
        "update.download": "받으러 가기",
        "update.dismiss": "나중에",

        "env.title": "실행 환경",
        "env.node": "Node.js",
        "env.npx": "npx",
        "env.python": "Python",
        "env.git": "Git",
        "env.present": "있음",
        "env.missing": "없음",
        "env.hint.node": "https://nodejs.org 에서 LTS 를 설치하세요",
        "env.hint.npx": "Node.js 를 설치하면 같이 들어옵니다",
        "env.hint.git": "사이트 수집·배포에 필요합니다",
        "env.hint.python": "",
        "env.paramiko": "paramiko",
        "env.hint.paramiko": "Needed to reach servers. Install with: pip install 'devlink-mcp[sync]'",
        "servers.title": "서버 목록",
        "servers.name": "이름",
        "servers.connection": "접속",
        "servers.auth": "인증",
        "servers.root": "작업 폴더",
        "servers.empty": "등록된 서버가 없습니다. 아래에서 추가하세요.",
        "servers.add": "+ 서버 추가",
        "servers.import": "WinSCP 에서 가져오기",
        "servers.save": "저장하고 검사",
        "servers.saving": "저장 중…",
        "servers.edit": "수정",
        "servers.delete": "삭제",
        "servers.confirm_delete": "{name} 을(를) 목록에서 지울까요?",
        "servers.disabled": "사용 안 함",
        "servers.auth.key": "개인키",
        "servers.auth.password": "비밀번호",
        "servers.auth.none": "—",
        "servers.root_missing": "미입력",
        "edit.add_title": "서버 추가",
        "edit.edit_title": "서버 수정 — {name}",
        "edit.name": "이름",
        "edit.name_hint": "이 서버를 부를 이름입니다",
        "edit.host": "주소",
        "edit.port": "포트",
        "edit.user": "계정",
        "edit.auth": "인증",
        "edit.password": "비밀번호",
        "edit.password_set": "이미 저장되어 있습니다. 바꿀 때만 입력하세요.",
        "edit.key": "키 파일",
        "edit.key_pick": "파일 선택…",
        "edit.key_none": "— 키 파일을 고르세요 —",
        "edit.key_manual": "직접 입력…",
        "edit.key_hint": "고른 파일은 keys 폴더로 복사됩니다. PuTTY 의 .ppk 는 그대로 못 쓰니 "
                         "PuTTYgen 에서 Conversions > Export OpenSSH key 로 변환하세요.",
        "edit.passphrase": "키 암호",
        "edit.passphrase_hint": "키에 암호가 걸려 있을 때만",
        "edit.remote": "작업 폴더",
        "edit.remote_hint": "작업 대상 폴더의 절대경로",
        "edit.backup": "백업 경로",
        "edit.exclude": "제외 목록",
        "edit.exclude_hint": "비워두면 기본값을 씁니다",
        "edit.mode": "접속 방식",
        "edit.mode_exec": "기본 (exec)",
        "edit.mode_shell": "점프서버·배너 있음 (shell) — 파일 전송 불가",
        "edit.enabled": "사용",
        "edit.enabled_label": "이 서버를 사용함",
        "edit.ok": "확인",
        "edit.cancel": "취소",
        "import.title": "WinSCP 에서 가져오기",
        "import.intro": "WinSCP 에서 내보낸 .ini 또는 .reg 파일을 고르세요. "
                        "형식은 내용을 보고 알아서 판단합니다.",
        "import.method1": "방법 1 — WinSCP 메뉴",
        "import.method1_body": "WinSCP → 도구 → 환경 설정 내보내기/백업 → INI 파일로 저장.",
        "import.method2": "방법 2 — 레지스트리에서",
        "import.method2_body": "WinSCP 가 설정을 레지스트리에 두는 경우. "
                               "PowerShell 에 붙여넣으면 바탕화면에 .reg 로 저장됩니다.",
        "import.pick": "파일 선택…",
        "import.none": "선택된 파일 없음",
        "import.manual": "경로를 직접 입력하기",
        "import.pw_note": "마스터 비밀번호가 걸린 세션이 아니라면 저장된 비밀번호도 함께 가져옵니다.",
        "import.result": "{count}개를 가져왔습니다.",
        "import.result_pw": "비밀번호 {count}개도 함께 가져왔습니다.",
        "import.result_failed": "{count}개는 비밀번호를 풀지 못했습니다"
                                "(마스터 비밀번호가 걸린 세션). 직접 입력하세요.",
        "import.result_next": "작업 폴더를 채운 뒤 저장하세요.",
        "import.nothing": "새로 가져올 세션이 없습니다.",
        "import.not_found": "파일을 찾지 못했습니다: {path}",
        "import.unreadable": "파일을 읽지 못했습니다.",
        "import.too_big": "파일이 너무 큽니다 (4MB 이하).",
        "import.no_sessions": "세션을 찾지 못했습니다. WinSCP 에서 내보낸 파일이 맞는지 "
                              "확인해 주세요. (도구 > 환경 설정 내보내기/백업 > INI 파일)",
        "import.skip_nohost": "{name} — 주소 없음",
        "import.skip_proto": "{name} — {proto} 세션 (SSH 아님)",
        "import.skip_exists": "{name} — 이미 있음",
        "import.no_file": "가져올 파일을 고르지 않았습니다.",
        "key.saved": "{name} 을(를) keys 폴더에 넣었습니다.",
        "key.uploading": "올리는 중…",
        "key.ppk": "PuTTY 의 .ppk 는 그대로 쓸 수 없습니다.\n"
                   "PuTTYgen 에서 열고 Conversions > Export OpenSSH key 로 변환하세요.",
        "key.not_private": "개인키 파일로 보이지 않습니다.\n"
                           "'-----BEGIN ... PRIVATE KEY-----' 로 시작하는 파일이어야 합니다. "
                           "공개키(.pub)가 아니라 개인키를 골라 주세요.",
        "mcp.title": "MCP 클라이언트에 등록",
        "mcp.registered": "등록되어 있습니다. 다시 누르면 경로를 새로 맞춥니다.",
        "mcp.not_registered": "아직 등록되지 않았습니다. 대상: {path}",
        "mcp.register": "등록하기",
        "mcp.reregister": "다시 등록",
        "mcp.done": "등록했습니다.",
        "mcp.replaced": "기존 항목을 새 경로로 바꿨습니다.",
        "mcp.backup": " (백업: {name})",
        "mcp.restart": "\n클라이언트를 완전히 종료했다가 다시 켜야 반영됩니다.",
        "mcp.bad_json": "기존 설정 파일이 올바른 JSON 이 아닙니다: {error}\n"
                        "직접 확인이 필요합니다: {path}",
        "save.ok": "저장 완료. 아래 서버를 쓸 수 있습니다",
        "save.warn": "저장 완료 — 확인해 볼 점이 있습니다",
        "save.errors": "저장했지만 아래 항목은 아직 쓸 수 없습니다",
        "save.failed": "저장에 실패했습니다: {error}",
        "save.blocked_title": "설정 파일을 읽지 못했습니다",
        "cfg.missing_fields": "[{name}] 필수 항목 누락: {fields}",
        "cfg.no_auth": "[{name}] password 또는 key 중 하나는 있어야 합니다",
        "cfg.placeholder_pw": "[{name}] password 가 예시값 그대로입니다",
        "cfg.remote_abs": "[{name}] remote 는 / 로 시작하는 절대경로여야 합니다: {value}",
        "cfg.bad_port": "[{name}] port 가 숫자가 아닙니다: {value}",
        "cfg.bad_mode": "[{name}] mode 는 exec 또는 shell 이어야 합니다: {value}",
        "cfg.bad_number": "[{name}] timeout / maxoutput 은 숫자여야 합니다",
        "cfg.dup_name": "[{name}] 연결 이름이 중복됩니다: {value}",
        "cfg.unknown_key": "[{name}] 모르는 항목이라 무시합니다: {key}",
        "cfg.ppk": "[{name}] .ppk 키는 그대로 못 씁니다. PuTTYgen 의 "
                   "Conversions > Export OpenSSH key 로 변환하세요.",
        "cfg.key_missing": "[{name}] 개인키 파일을 찾지 못했습니다: {path}",
        "cfg.shell_mode": "[{name}] mode = shell 은 외부 ssh-mcp-server 에서만 동작합니다. "
                          "'devlink serve' 는 exec 로 실행하며 이 설정을 무시하고, "
                          "그쪽에서는 파일 전송도 안 됩니다.",
        "cfg.no_whitelist": "[{name}] 허용 목록이 없습니다. 차단 목록은 우회가 쉬우니 "
                            "운영 서버라면 allow 설정을 권합니다.",
        "cfg.no_backup": "[{name}] 백업 경로가 없습니다. 깃 이력으로 되돌릴 수는 있지만, "
                         "서버에도 사본을 두면 더 빠르고 이 PC 를 잃어도 남습니다.",
        "sync.pull_saved_local": "커밋하지 않은 로컬 수정을 먼저 커밋했습니다. "
                                 "수집이 그것을 지우지 않도록.",
        "sync.rollback_from_git": "깃 이력에서 복원했습니다 (서버에 백업본이 없었습니다).",
        "cfg.skipped": "{name} (사용 안 함)",
        "cfg.no_servers": "사용 가능한 연결이 하나도 없습니다. 설정을 확인하세요.",
        "cfg.ini_missing": "servers.ini 가 없습니다",
        "cfg.written": "연결 {count}개 생성 -> {path}",
        "cfg.check_done": "검사 완료: 연결 {servers}개, 오류 {errors}개 (파일 쓰지 않음)",
        "cfg.no_permission": "{path} 를 읽을 권한이 없습니다.\n"
                             "파일 권한을 복구한 뒤 이 화면을 새로고침하세요.",
        "cfg.open_failed": "{path} 를 열지 못했습니다: {error}",
        "sync.no_site": "모르는 서버입니다: {name}",
        "sync.need_paramiko": "원격 전송에는 paramiko 가 필요합니다. 설치하세요:\n"
                              "    pip install 'devlink-mcp[sync]'",
        "sync.pull_start": "{name} 수집 중 — {host}:{remote}",
        "sync.pull_done": "파일 {count}개를 {path} 로 가져왔습니다",
        "sync.pull_first": "처음 수집했습니다. 롤백이 돌아갈 기준선입니다.",
        "sync.pull_nochange": "지난 수집 이후 바뀐 것이 없습니다.",
        "sync.pull_changed": "지난 수집 이후 원격이 바뀌었습니다 — 기준선으로 커밋했습니다.",
        "sync.deploy_none": "배포할 것이 없습니다: {ref} 이후 변경된 파일이 없습니다.",
        "sync.deploy_plan": "{host}:{remote} 로 파일 {count}개를 배포합니다",
        "sync.deploy_done": "파일 {count}개를 배포했습니다. 태그: {tag}",
        "sync.deploy_drift": "배포를 중단합니다: 서버가 마지막 배포 상태와 다릅니다. "
                             "누군가 아래 파일을 서버에서 직접 고쳤습니다.\n{files}\n"
                             "먼저 'devlink pull' 로 그 변경을 깃에 들여오세요.",
        "sync.backup_done": "원격 백업 저장됨: {path}",
        "sync.rollback_done": "{tag} 에서 파일 {count}개를 복원했습니다.",
        "sync.no_backup": "{tag} 에 대한 원격 백업이 없습니다.",
        "sync.dirty": "커밋하지 않은 변경이 있습니다. 먼저 커밋하거나 stash 하세요.",
        "sync.status_clean": "로컬·원격·마지막 배포가 모두 일치합니다.",
        "sync.status_drift": "서버가 마지막 배포와 다릅니다:",
        "sync.status_undeployed": "커밋했지만 아직 배포하지 않은 것:",
    },
}

_lang = ""


def detect(preferred: str = "") -> str:
    """Pick a language code. Explicit setting wins, then env, then locale."""
    for candidate in (preferred, os.environ.get("DEVLINK_LANG", "")):
        code = (candidate or "").strip().lower()[:2]
        if code in MESSAGES:
            return code
    # getdefaultlocale() is deprecated and goes away in 3.15. It read the
    # environment first, so do the same: those variables are how a person
    # states a preference, while getlocale() reports whatever setlocale() was
    # last given — often "C", which means nothing was chosen.
    sys_locale = ""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (os.environ.get(name) or "").strip()
        if value and value.split(".")[0].upper() not in ("C", "POSIX"):
            sys_locale = value
            break

    if not sys_locale:
        try:
            sys_locale = locale.getlocale()[0] or ""
        except (ValueError, TypeError):  # pragma: no cover - platform dependent
            sys_locale = ""
        if sys_locale.split(".")[0].upper() in ("C", "POSIX"):
            sys_locale = ""

    if sys_locale.lower().startswith("ko"):
        return "ko"
    return "en"


def set_language(code: str) -> str:
    global _lang
    _lang = detect(code)
    return _lang


def language() -> str:
    return _lang or detect()


def t(key: str, **kwargs) -> str:
    """Look up a message, falling back to English and then to the key itself."""
    table = MESSAGES.get(language(), MESSAGES["en"])
    text = table.get(key) or MESSAGES["en"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):  # pragma: no cover - defensive
            return text
    return text


def catalogue(code: str = "") -> dict[str, str]:
    """Full table for one language, English-filled. Handed to the web UI."""
    lang = detect(code) if code else language()
    merged = dict(MESSAGES["en"])
    merged.update(MESSAGES.get(lang, {}))
    return merged

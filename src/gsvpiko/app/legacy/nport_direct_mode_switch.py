"""
Standalone NPort web-mode switcher for the GSVpiko NPort 5110A setup.

This file intentionally does not import GSVpiko modules. It talks directly to the
NPort web console and uses the real forms discovered from the NPort HTML pages.

Use:
    py -m gsvpiko.app.nport_direct_mode_switch

Main macros are at the top of the file.
"""

from __future__ import annotations

import hashlib
import html
import http.client
import os
import re
import socket
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


WEB_FORM_SWITCH_VERSION = "2026-06-03-v2-nport-mode-names"

# ---------------------------------------------------------------------------
# User macros
# ---------------------------------------------------------------------------

REQUESTED_MODE = "tcp"  # "tcp" or "serial"
APPLY_CHANGES = True

BAUDRATE = 460800
LOCAL_TCP_PORT = 4001
COMMAND_PORT = 966
REALCOM_DATA_PORT = 950

USERNAME = "admin"
PASSWORD = "moxa"

NPORTS = (
    ("gsv_ship", "192.168.10.115"),
    ("gsv_dock", "192.168.10.113"),
)

HTTP_PORT = 80
CONNECT_TIMEOUT_S = 2.0
READ_TIMEOUT_S = 4.0
RESTART_WAIT_TIMEOUT_S = 25.0
RESTART_POLL_INTERVAL_S = 0.75

OUTPUT_DIR = Path("nport_web_switch_logs")

# Keep these values conservative. They are submitted only when the corresponding
# field exists in the active NPort HTML form.
TCP_ALIVE_CHECK_MIN = 7
MAX_CONNECTIONS = 1

# Moxa NPort 5110A web form values used by the direct mode switch.
MODE_VALUE_BY_REQUEST = {
    "serial": "2",  # Real COM Mode
    "tcp": "10",    # TCP Server Mode
}

NPORT_MODE_NAME_BY_REQUEST = {
    "serial": "Real COM Mode",
    "tcp": "TCP Server Mode",
}


def format_nport_mode(mode: str) -> str:
    return NPORT_MODE_NAME_BY_REQUEST.get(mode, mode)

BAUDRATE_VALUE_BY_RATE = {
    50: "0",
    75: "1",
    110: "2",
    134: "3",
    150: "4",
    300: "5",
    600: "6",
    1200: "7",
    1800: "8",
    2400: "9",
    4800: "10",
    7200: "11",
    9600: "12",
    19200: "13",
    38400: "14",
    57600: "15",
    115200: "16",
    230400: "17",
    460800: "18",
    921600: "19",
}


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def ensure_output_dir() -> Path:
    run_dir = OUTPUT_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", errors="replace")


def tcp_port_open(ip_address: str, port: int, timeout_s: float = CONNECT_TIMEOUT_S) -> Tuple[bool, Optional[str]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((ip_address, port))
        return True, None
    except OSError as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def detect_mode(ip_address: str) -> Tuple[str, str]:
    tcp_open, tcp_error = tcp_port_open(ip_address, LOCAL_TCP_PORT, 0.7)
    realcom_open, realcom_error = tcp_port_open(ip_address, REALCOM_DATA_PORT, 0.7)

    if tcp_open and not realcom_open:
        return "tcp", f"TCP Server data port {LOCAL_TCP_PORT} is open."
    if realcom_open and not tcp_open:
        return "serial", f"Real COM data port {REALCOM_DATA_PORT} is open."
    if tcp_open and realcom_open:
        return "ambiguous", (
            f"Both TCP Server data port {LOCAL_TCP_PORT} and Real COM data port "
            f"{REALCOM_DATA_PORT} are open."
        )
    return "unknown", (
        f"Neither TCP Server data port {LOCAL_TCP_PORT} nor Real COM data port "
        f"{REALCOM_DATA_PORT} is open. tcp_error={tcp_error}; realcom_error={realcom_error}"
    )


def wait_for_mode(ip_address: str, target_mode: str, timeout_s: float = RESTART_WAIT_TIMEOUT_S) -> Tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    last_mode = "unknown"
    last_detail = ""
    while time.monotonic() < deadline:
        last_mode, last_detail = detect_mode(ip_address)
        if last_mode == target_mode:
            return True, last_detail
        time.sleep(RESTART_POLL_INTERVAL_S)
    return False, f"Timed out waiting for {target_mode}. Last detected mode: {last_mode}. {last_detail}"


def strip_tags(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# HTTP session and NPort login
# ---------------------------------------------------------------------------

class NPortWebSession:
    def __init__(self, ip_address: str, run_dir: Path, label: str) -> None:
        self.ip_address = ip_address
        self.run_dir = run_dir
        self.label = label
        self.cookies: Dict[str, str] = {}

    def _cookie_header(self) -> str:
        return "; ".join(f"{name}={value}" for name, value in sorted(self.cookies.items()))

    def _store_set_cookie(self, headers: Iterable[Tuple[str, str]]) -> None:
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            first = value.split(";", 1)[0]
            if "=" in first:
                cname, cval = first.split("=", 1)
                self.cookies[cname.strip()] = cval.strip()

    def request(self, method: str, path: str, body: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None) -> Tuple[int, str, List[Tuple[str, str]], bytes]:
        if not path.startswith("/"):
            path = "/" + path
        req_headers = {
            "Host": self.ip_address,
            "User-Agent": f"GSVpiko-NPort-Web-Switch/{WEB_FORM_SWITCH_VERSION}",
            "Connection": "close",
        }
        if self.cookies:
            req_headers["Cookie"] = self._cookie_header()
        if headers:
            req_headers.update(headers)

        conn = http.client.HTTPConnection(self.ip_address, HTTP_PORT, timeout=READ_TIMEOUT_S)
        try:
            conn.request(method.upper(), path, body=body, headers=req_headers)
            response = conn.getresponse()
            data = response.read()
            header_list = response.getheaders()
            self._store_set_cookie(header_list)
            return response.status, response.reason, header_list, data
        finally:
            conn.close()

    def get(self, path: str) -> Tuple[int, str, List[Tuple[str, str]], str]:
        status, reason, headers, data = self.request("GET", path)
        return status, reason, headers, data.decode("utf-8", errors="replace")

    def get_with_query(self, path: str, params: Dict[str, str]) -> Tuple[int, str, List[Tuple[str, str]], str]:
        query = urllib.parse.urlencode(params)
        full_path = f"{path}?{query}"
        return self.get(full_path)

    def save_response(self, name: str, status: int, reason: str, headers: List[Tuple[str, str]], body: str) -> None:
        stem = f"{sanitize_filename(self.label)}_{self.ip_address.replace('.', '_')}_{sanitize_filename(name)}"
        write_text(self.run_dir / f"{stem}.html", body)
        header_text = "\n".join(f"{key}: {value}" for key, value in headers)
        summary = (
            f"name={name}\n"
            f"status={status}\n"
            f"reason={reason}\n"
            f"body_bytes={len(body.encode('utf-8', errors='replace'))}\n"
            f"title={extract_title(body)}\n"
            f"contains_login_form={contains_login_form(body)}\n"
            f"contains_session_expired={'Session Expired' in body}\n"
            f"cookies={self._cookie_header()}\n"
            f"\nheaders:\n{header_text}\n"
            f"\nplain_text:\n{strip_tags(body)[:2500]}\n"
        )
        write_text(self.run_dir / f"{stem}_summary.txt", summary)


def extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html.unescape(strip_tags(match.group(1)))


def contains_login_form(body: str) -> bool:
    return "InputPassword" in body or "EncPasswd" in body or "FakeChallenge" in body


def attr_map(tag: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for match in re.finditer(
        r"([A-Za-z_][A-Za-z0-9_:-]*)"
        r"(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?",
        tag,
    ):
        key = match.group(1)
        if key.lower() in {"input", "select", "option", "form", "textarea"}:
            continue
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        if value is None:
            value = ""
        attrs[key] = html.unescape(value)
    return attrs


def find_input_value(body: str, name: str) -> Optional[str]:
    for match in re.finditer(r"<input\b[^>]*>", body, flags=re.IGNORECASE):
        tag = match.group(0)
        attrs = attr_map(tag)
        if attrs.get("name") == name:
            return attrs.get("value", "")
    return None


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def encode_password_js(password: str, key: str) -> str:
    ascii_table = (
        "01234567890123456789012345678901"
        " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
    )
    md_values: List[int] = []
    for i in range(0, len(key), 2):
        md_values.append(int(key[i:i + 2], 16))

    result = list(md_values)
    for i, char in enumerate(password):
        index = ascii_table.rfind(char)
        if index < 0:
            raise ValueError(f"Character {char!r} cannot be encoded by the NPort login function.")
        result[i] = md_values[i] ^ index

    return "".join(f"{value & 0xFF:02x}" for value in result)


def login(session: NPortWebSession) -> Tuple[bool, str]:
    status, reason, headers, body = session.get("/")
    session.save_response("login_page", status, reason, headers, body)
    if status != 200:
        return False, f"Login page status was {status} {reason}."

    challenge = find_input_value(body, "FakeChallenge")
    if not challenge:
        return False, "FakeChallenge was not found in the login page."
    if len(challenge) < 32:
        return False, f"FakeChallenge looked invalid: {challenge!r}"

    enc_passwd = sha256_hex(USERNAME + PASSWORD + challenge)
    enc_user = encode_password_js(USERNAME, sha256_hex(challenge))

    payload = {
        "Username": USERNAME,
        "Password": "",
        "EncPasswd": enc_passwd,
        "EncUser": enc_user,
        "FakeChallenge": challenge,
    }
    body_bytes = urllib.parse.urlencode(payload).encode("ascii")
    status, reason, headers, response = session.request(
        "POST",
        "/",
        body=body_bytes,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response_text = response.decode("utf-8", errors="replace")
    session.save_response("post_login", status, reason, headers, response_text)

    location = get_header(headers, "Location")
    if status in {301, 302, 303, 307, 308} and location:
        redirect_path = urllib.parse.urlparse(location).path or "/"
        status2, reason2, headers2, body2 = session.get(redirect_path)
        session.save_response(f"redirect_{redirect_path.lstrip('/') or 'root'}", status2, reason2, headers2, body2)
        if "clearWebLogAction" in body2:
            ok, message = continue_after_login(session, body2)
            if not ok:
                return False, message
        return True, f"Login redirected to {location}."

    if "clearWebLogAction" in response_text:
        return continue_after_login(session, response_text)

    if contains_login_form(response_text) or "Session Expired" in response_text:
        return False, f"Login was not accepted. status={status} title={extract_title(response_text)!r}"

    return True, f"Login accepted without redirect. status={status}"


def get_header(headers: List[Tuple[str, str]], key: str) -> Optional[str]:
    key_lower = key.lower()
    for name, value in headers:
        if name.lower() == key_lower:
            return value
    return None


def continue_after_login(session: NPortWebSession, body: str) -> Tuple[bool, str]:
    csrf_token = find_input_value(body, "csrf_token")
    if not csrf_token:
        return False, "Login reached the web-log page, but csrf_token was not found."

    params = {
        "continue": "Continue",
        "setfunc": "clearWebLogAction",
        "csrf_token": csrf_token,
    }
    status, reason, headers, body2 = session.get_with_query("/action.htm", params)
    session.save_response("continue_action", status, reason, headers, body2)

    location = get_header(headers, "Location")
    if status in {301, 302, 303, 307, 308} and location:
        redirect_path = urllib.parse.urlparse(location).path or "/"
        status3, reason3, headers3, body3 = session.get(redirect_path)
        session.save_response(f"continue_redirect_{redirect_path.lstrip('/') or 'root'}", status3, reason3, headers3, body3)
        if contains_login_form(body3) or "Session Expired" in body3:
            return False, "Continue redirect returned a login/session-expired page."
        return True, f"Continue accepted; redirected to {location}."

    if contains_login_form(body2) or "Session Expired" in body2:
        return False, "Continue action returned a login/session-expired page."

    return True, "Continue accepted without redirect."


# ---------------------------------------------------------------------------
# Form parsing/submission
# ---------------------------------------------------------------------------

def first_form_fields(body: str, form_name: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
    form_pattern = re.compile(r"<form\b[^>]*>.*?</form>", flags=re.IGNORECASE | re.DOTALL)
    for form_match in form_pattern.finditer(body):
        form_html = form_match.group(0)
        open_tag_match = re.search(r"<form\b[^>]*>", form_html, flags=re.IGNORECASE)
        if not open_tag_match:
            continue
        open_attrs = attr_map(open_tag_match.group(0))
        if form_name and open_attrs.get("name") != form_name:
            continue
        action = open_attrs.get("action", "Set.htm")
        fields = parse_form_fields(form_html)
        return action, fields
    raise ValueError(f"Form {form_name or '<first>'!r} was not found.")


def parse_form_fields(form_html: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}

    # Script-generated text inputs used by the NPort pages.
    for match in re.finditer(
        r"inputText(?:Ex)?\(\s*\"([^\"]+)\"\s*,\s*[^,]+,\s*\"([^\"]*)\"",
        form_html,
        flags=re.IGNORECASE,
    ):
        fields.setdefault(match.group(1), html.unescape(match.group(2)))

    for match in re.finditer(r"<input\b[^>]*>", form_html, flags=re.IGNORECASE):
        tag = match.group(0)
        attrs = attr_map(tag)
        name = attrs.get("name")
        if not name:
            continue
        input_type = attrs.get("type", "text").lower()
        if input_type in {"submit", "button", "reset"}:
            continue
        if input_type in {"checkbox", "radio"}:
            if "checked" not in {key.lower() for key in attrs}:
                continue
        fields[name] = attrs.get("value", "")

    for match in re.finditer(
        r"<select\b([^>]*)>(.*?)</select>",
        form_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        select_attrs = attr_map("<select " + match.group(1) + ">")
        name = select_attrs.get("name")
        if not name:
            continue
        selected_value = None
        first_value = None
        for opt_match in re.finditer(r"<option\b[^>]*>", match.group(2), flags=re.IGNORECASE):
            opt_attrs = attr_map(opt_match.group(0))
            value = opt_attrs.get("value", "")
            if first_value is None:
                first_value = value
            if "selected" in {key.lower() for key in opt_attrs}:
                selected_value = value
                break
        fields[name] = selected_value if selected_value is not None else (first_value or "")

    return fields


def submit_get_form(session: NPortWebSession, action: str, fields: Dict[str, str], log_name: str) -> Tuple[int, str, List[Tuple[str, str]], str]:
    path = action if action.startswith("/") else "/" + action
    status, reason, headers, body = session.get_with_query(path, fields)
    session.save_response(log_name, status, reason, headers, body)
    return status, reason, headers, body


def apply_serial_settings(session: NPortWebSession, log: List[str]) -> bool:
    status, reason, headers, body = session.get("/CommPara.htm?Port=1")
    session.save_response("commpara_before", status, reason, headers, body)
    if status != 200 or contains_login_form(body):
        log.append(f"Serial settings page could not be loaded. status={status} reason={reason}")
        return False

    action, fields = first_form_fields(body, "serial")
    if BAUDRATE not in BAUDRATE_VALUE_BY_RATE:
        log.append(f"Unsupported BAUDRATE macro for the NPort form: {BAUDRATE}")
        return False

    fields["BaudRate"] = BAUDRATE_VALUE_BY_RATE[BAUDRATE]
    # Keep DataBits, StopBits, Parity, FlowCtrl, FIFO, interface type exactly as the page reported.

    status2, reason2, headers2, body2 = submit_get_form(session, action, fields, "commpara_set_response")
    ok = status2 in {200, 301, 302, 303, 307, 308}
    log.append(
        f"serial settings submit: ok={ok}, status={status2}, reason={reason2}, "
        f"BaudRate={fields.get('BaudRate')}"
    )
    return ok


def load_target_opmode_form(session: NPortWebSession, target_mode: str, log: List[str]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    target_value = MODE_VALUE_BY_REQUEST[target_mode]

    # This mimics the NPort page's ChangePage() JavaScript: set OpMode, submit
    # the form to opmode.htm, then receive the target-mode-specific form.
    status, reason, headers, body = session.get_with_query("/opmode.htm", {"Port": "1", "OpMode": target_value})
    session.save_response(f"opmode_target_{target_mode}_form", status, reason, headers, body)
    if status != 200 or contains_login_form(body):
        log.append(f"Target opmode form could not be loaded. status={status} reason={reason}")
        return None, None

    try:
        action, fields = first_form_fields(body, "opmode")
    except ValueError as exc:
        log.append(str(exc))
        return None, None

    fields["OpMode"] = target_value

    # Common fields, submitted only if present in the target-mode-specific form.
    if "TCPAliveCheck" in fields:
        fields["TCPAliveCheck"] = str(TCP_ALIVE_CHECK_MIN)
    if "MaxConnect" in fields:
        fields["MaxConnect"] = str(MAX_CONNECTIONS)

    # The exact TCP Server field names vary by firmware. Override only fields
    # that the target form actually exposes.
    port_overrides = {
        "LocalTCPPort": str(LOCAL_TCP_PORT),
        "LocalTcpPort": str(LOCAL_TCP_PORT),
        "LocalPort": str(LOCAL_TCP_PORT),
        "TCPPort": str(LOCAL_TCP_PORT),
        "TcpPort": str(LOCAL_TCP_PORT),
        "DataPort": str(LOCAL_TCP_PORT),
        "TCPServerPort": str(LOCAL_TCP_PORT),
        "CommandPort": str(COMMAND_PORT),
        "CmdPort": str(COMMAND_PORT),
        "TCPCommandPort": str(COMMAND_PORT),
        "ControlPort": str(COMMAND_PORT),
    }
    for key, value in port_overrides.items():
        if key in fields:
            fields[key] = value

    log.append(f"target opmode form fields: {', '.join(sorted(fields))}")
    return action, fields


def apply_operating_mode(session: NPortWebSession, target_mode: str, log: List[str]) -> bool:
    action, fields = load_target_opmode_form(session, target_mode, log)
    if action is None or fields is None:
        return False

    status, reason, headers, body = submit_get_form(session, action, fields, f"opmode_set_{target_mode}_response")
    ok = status in {200, 301, 302, 303, 307, 308}
    log.append(
        f"opmode submit: ok={ok}, status={status}, reason={reason}, "
        f"OpMode={fields.get('OpMode')}"
    )
    return ok


def save_and_restart(session: NPortWebSession, log: List[str]) -> bool:
    status, reason, headers, body = session.get("/savRst.htm")
    session.save_response("save_restart_page", status, reason, headers, body)
    if status != 200 or contains_login_form(body):
        log.append(f"Save/Restart page could not be loaded. status={status} reason={reason}")
        return False

    action, fields = first_form_fields(body, "savRst")
    status2, reason2, headers2, body2 = submit_get_form(session, action, fields, "save_restart_response")
    ok = status2 in {200, 301, 302, 303, 307, 308}
    log.append(f"save/restart submit: ok={ok}, status={status2}, reason={reason2}")
    return ok


def run_for_nport(label: str, ip_address: str, run_dir: Path) -> None:
    target_mode = REQUESTED_MODE.strip().lower()
    if target_mode not in MODE_VALUE_BY_REQUEST:
        raise ValueError(f"REQUESTED_MODE must be 'tcp' or 'serial', got {REQUESTED_MODE!r}.")

    print(f"\n{label} at {ip_address}")
    print("-" * (len(label) + len(ip_address) + 4))
    log: List[str] = []
    before_mode, before_detail = detect_mode(ip_address)
    print(f"before: {format_nport_mode(before_mode)} ({before_detail})")
    log.append(f"before={format_nport_mode(before_mode)} detail={before_detail}")

    session = NPortWebSession(ip_address=ip_address, run_dir=run_dir, label=label)
    ok, message = login(session)
    print(f"web_login_ok: {ok}")
    print(f"web_login_message: {message}")
    log.append(f"web_login_ok={ok} message={message}")
    if not ok:
        write_summary(label, ip_address, run_dir, target_mode, False, before_mode, "unknown", log)
        return

    if not APPLY_CHANGES:
        print("apply_changes: False")
        print("No settings were changed.")
        # Load target form anyway so the log shows what would be submitted.
        load_target_opmode_form(session, target_mode, log)
        write_summary(label, ip_address, run_dir, target_mode, True, before_mode, before_mode, log)
        return

    serial_ok = apply_serial_settings(session, log)
    print(f"serial_settings_submit_ok: {serial_ok}")

    opmode_ok = apply_operating_mode(session, target_mode, log)
    print(f"opmode_submit_ok: {opmode_ok}")

    if not (serial_ok and opmode_ok):
        print("Not restarting because at least one setting submit failed.")
        after_mode, after_detail = detect_mode(ip_address)
        log.append(f"after_without_restart={format_nport_mode(after_mode)} detail={after_detail}")
        write_summary(label, ip_address, run_dir, target_mode, False, before_mode, after_mode, log)
        return

    restart_ok = save_and_restart(session, log)
    print(f"save_restart_submit_ok: {restart_ok}")

    if restart_ok:
        print(f"waiting_for_mode: {target_mode}")
        reached, detail = wait_for_mode(ip_address, target_mode)
        print(f"target_mode_reached: {reached}")
        print(f"target_mode_detail: {detail}")
        log.append(f"target_mode_reached={reached} detail={detail}")
    else:
        reached = False

    after_mode, after_detail = detect_mode(ip_address)
    print(f"after: {format_nport_mode(after_mode)} ({after_detail})")
    log.append(f"after={format_nport_mode(after_mode)} detail={after_detail}")
    write_summary(label, ip_address, run_dir, target_mode, reached, before_mode, after_mode, log)


def write_summary(
    label: str,
    ip_address: str,
    run_dir: Path,
    target_mode: str,
    ok: bool,
    before_mode: str,
    after_mode: str,
    log: List[str],
) -> None:
    path = run_dir / f"{sanitize_filename(label)}_{ip_address.replace('.', '_')}_switch_summary.txt"
    write_text(
        path,
        "\n".join(
            [
                f"version={WEB_FORM_SWITCH_VERSION}",
                f"label={label}",
                f"ip_address={ip_address}",
                f"requested_mode={REQUESTED_MODE} ({format_nport_mode(target_mode)})",
                f"target_nport_mode={format_nport_mode(target_mode)}",
                f"apply_changes={APPLY_CHANGES}",
                f"baudrate={BAUDRATE}",
                f"local_tcp_port={LOCAL_TCP_PORT}",
                f"command_port={COMMAND_PORT}",
                f"before_nport_mode={format_nport_mode(before_mode)}",
                f"after_nport_mode={format_nport_mode(after_mode)}",
                f"ok={ok}",
                "",
                "log:",
                *[f"  {line}" for line in log],
                "",
            ]
        ),
    )


def main() -> int:
    run_dir = ensure_output_dir()
    requested = REQUESTED_MODE.strip().lower()
    print("NPort direct mode switch / WEB FORM SWITCH")
    print("------------------------------------------")
    print(f"web_form_switch_version: {WEB_FORM_SWITCH_VERSION}")
    print(f"requested_mode: {REQUESTED_MODE!r} -> {format_nport_mode(requested)}")
    print(f"apply_changes: {APPLY_CHANGES}")
    print(f"baudrate: {BAUDRATE}")
    print(f"local_tcp_port: {LOCAL_TCP_PORT}")
    print(f"command_port: {COMMAND_PORT}")
    print(f"realcom_data_port: {REALCOM_DATA_PORT}")
    print(f"output_dir: {run_dir}")
    print("nports:")
    for label, ip_address in NPORTS:
        print(f"  - {label}: {ip_address}")

    for label, ip_address in NPORTS:
        run_for_nport(label, ip_address, run_dir)

    print("\nDone.")
    print(f"Logs: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

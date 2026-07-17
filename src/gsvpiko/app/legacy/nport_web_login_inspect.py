
"""Inspect NPort web login and authenticated pages without changing settings.

This standalone diagnostic does not import GSVpiko modules and does not write
configuration changes to the NPort. It logs the login page, the login POST,
the redirect target, and a bounded set of authenticated GET pages for web-form
inspection.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import http.client
import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode, urljoin, urlparse


INSPECT_VERSION = "2026-06-03-v8-v6-login-menu-pages"

NPORTS = (
    ("gsv_ship", "192.168.10.115"),
    ("gsv_dock", "192.168.10.113"),
)

USERNAME = "admin"
PASSWORD = "moxa"

HTTP_PORT = 80
HTTPS_PORT = 443
TIMEOUT_S = 3.0

# Only GET requests are issued after login. No configuration-changing POSTs are sent.
CANDIDATE_AUTH_PAGES = (
    "/LoginOK.htm",
    "/home.htm",
    "/contents.htm",
    "/main.htm",
    "/overview.htm",
    "/basic.htm",
    "/Basic.htm",
    "/Network.htm",
    "/net_basic.htm",
    "/serial.htm",
    "/Serial.htm",
    "/CommPara.htm?Port=1",
    "/opmode.htm",
    "/opmode.htm?Port=1",
    "/OpMode.htm",
    "/operating.htm",
    "/operating_settings.htm",
    "/port.htm",
    "/Port.htm",
    "/sio.htm",
    "/Sio.htm",
    "/line.htm",
    "/Line.htm",
    "/IPTab.htm",
    "/restart.htm",
    "/Restart.htm",
    "/savRst.htm",
    "/Password.htm",
)

MAX_DISCOVERED_GETS = 60
MAX_BODY_SAVE_BYTES = 300_000


@dataclass
class HttpResponse:
    status: int
    reason: str
    headers: Dict[str, str]
    body: bytes
    path: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data[:MAX_BODY_SAVE_BYTES])
    else:
        path.write_text(data, encoding="utf-8", errors="replace")


def _merge_cookie(cookie_header: str, jar: Dict[str, str]) -> None:
    if not cookie_header:
        return
    # Multiple Set-Cookie headers may be joined by http.client in uncommon cases.
    for chunk in cookie_header.split(","):
        first = chunk.split(";", 1)[0].strip()
        if "=" in first:
            key, value = first.split("=", 1)
            jar[key.strip()] = value.strip()


def _cookie_header(jar: Dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in jar.items())


def _request(
    ip_address: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: Optional[Dict[str, str]] = None,
    cookie_jar: Optional[Dict[str, str]] = None,
) -> HttpResponse:
    conn = http.client.HTTPConnection(ip_address, HTTP_PORT, timeout=TIMEOUT_S)
    request_headers = {
        "Host": ip_address,
        "User-Agent": f"nport-web-login-inspect/{INSPECT_VERSION}",
        "Connection": "close",
    }
    if headers:
        request_headers.update(headers)
    if cookie_jar:
        cookie = _cookie_header(cookie_jar)
        if cookie:
            request_headers["Cookie"] = cookie
    conn.request(method, path, body=body, headers=request_headers)
    resp = conn.getresponse()
    raw_body = resp.read()
    response_headers: Dict[str, str] = {}
    for key, value in resp.getheaders():
        # Preserve the last visible value for summaries. Cookie handling below
        # still sees the value returned by http.client.
        response_headers[key] = value
        if key.lower() == "set-cookie" and cookie_jar is not None:
            _merge_cookie(value, cookie_jar)
    conn.close()
    return HttpResponse(resp.status, resp.reason, response_headers, raw_body, path)


def _title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not match:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())


def _contains_login_form(text: str) -> bool:
    return bool(re.search(r"name\s*=\s*['\"]?InputPassword['\"]?", text, re.I)) or (
        "EncPasswd" in text and "FakeChallenge" in text
    )


def _extract_input_value(input_tag: str, name: str) -> Optional[str]:
    # Handles value=ABC, value="ABC", value='ABC'.
    value_match = re.search(r"\bvalue\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", input_tag, re.I)
    if not value_match:
        return None
    return next(group for group in value_match.groups() if group is not None)


def _extract_fake_challenge(text: str) -> Optional[str]:
    for match in re.finditer(r"<input\b[^>]*>", text, re.I | re.S):
        tag = match.group(0)
        if re.search(r"\bname\s*=\s*(?:\"FakeChallenge\"|'FakeChallenge'|FakeChallenge)\b", tag, re.I):
            value = _extract_input_value(tag, "FakeChallenge")
            if value and len(value) >= 32:
                return value
    # Fallback: narrowly search for name=FakeChallenge followed by value=...
    fallback = re.search(
        r"name\s*=\s*(?:\"FakeChallenge\"|'FakeChallenge'|FakeChallenge)\b[^>]*\bvalue\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        text,
        re.I | re.S,
    )
    if fallback:
        value = next(group for group in fallback.groups() if group is not None)
        if value and len(value) >= 32:
            return value
    return None




def _extract_first_form(text: str, *, setfunc_value: str | None = None) -> Optional[str]:
    for match in re.finditer(r"<form\b.*?</form>", text, re.I | re.S):
        form = match.group(0)
        if setfunc_value is None or re.search(rf"\bname\s*=\s*(?:\"setfunc\"|'setfunc'|setfunc)\b[^>]*\bvalue\s*=\s*(?:\"{re.escape(setfunc_value)}\"|'{re.escape(setfunc_value)}'|{re.escape(setfunc_value)})", form, re.I | re.S):
            return form
    return None


def _extract_form_action(form_html: str) -> str:
    match = re.search(r"\baction\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", form_html, re.I)
    if not match:
        return "/"
    value = next(group for group in match.groups() if group is not None)
    if not value.startswith("/"):
        value = "/" + value
    return value


def _extract_form_inputs(form_html: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for match in re.finditer(r"<input\b[^>]*>", form_html, re.I | re.S):
        tag = match.group(0)
        name_match = re.search(r"\bname\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))", tag, re.I)
        if not name_match:
            continue
        name = next(group for group in name_match.groups() if group is not None)
        value = _extract_input_value(tag, name) or ""
        fields[name] = html.unescape(value)
    return fields


def _is_failure_record_page(text: str) -> bool:
    return "clearWebLogAction" in text and "Clear failure record and continue" in text


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _encode_user(username: str, challenge: str) -> str:
    # Mirrors the NPort login page JavaScript:
    #   encodePassword(theform.Username.value, SHA256(theform.FakeChallenge.value))
    # The visible Username field is disabled before submit, so the transformed
    # username must be sent through EncUser.
    key = _sha256_hex(challenge)
    ascii_table = (
        "01234567890123456789012345678901"
        " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"
    )
    result = [int(key[index:index + 2], 16) for index in range(0, len(key), 2)]
    for index, character in enumerate(username):
        character_value = ascii_table.rfind(character)
        if character_value < 0:
            character_value = ord(character)
        result[index] ^= character_value
    return "".join(f"{value:02x}" for value in result)


def _build_login_body(username: str, password: str, challenge: str) -> bytes:
    enc_passwd = _sha256_hex(username + password + challenge)
    enc_user = _encode_user(username, challenge)
    # The visible Username/Password fields are disabled by the page's JS before submit.
    # Send only the hidden values that the NPort login handler expects.
    return (
        f"EncPasswd={enc_passwd}&"
        f"EncUser={enc_user}&"
        f"FakeChallenge={challenge}"
    ).encode("ascii")


def _extract_links_and_actions(base_path: str, text: str) -> List[str]:
    found: List[str] = []
    patterns = (
        r"\bhref\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        r"\bsrc\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        r"\baction\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        r"location\.href\s*=\s*(?:\"([^\"]+)\"|'([^']+)')",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = next((group for group in match.groups() if group), None)
            if not value:
                continue
            value = html.unescape(value.strip())
            if not value or value.startswith("#") or value.lower().startswith("javascript:"):
                continue
            parsed = urlparse(value)
            if parsed.scheme in ("http", "https"):
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
            else:
                path = urljoin(base_path, value)
                parsed2 = urlparse(path)
                path = parsed2.path or "/"
                if parsed2.query:
                    path += "?" + parsed2.query
            found.append(path)
    result: List[str] = []
    seen = set()
    for path in found:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _response_summary(name: str, response: HttpResponse) -> str:
    text = response.text
    lines = [
        f"name={name}",
        f"path={response.path}",
        f"status={response.status}",
        f"reason={response.reason}",
        f"body_bytes={len(response.body)}",
        f"title={_title(text)}",
        f"contains_login_form={_contains_login_form(text)}",
        f"contains_session_expired={'Session Expired' in text}",
        f"location={response.headers.get('Location', '')}",
        "",
        "headers:",
    ]
    for key, value in sorted(response.headers.items()):
        lines.append(f"  {key}: {value}")
    links = _extract_links_and_actions(response.path, text)
    lines.extend(["", "links/actions/srcs:"])
    for link in links[:100]:
        lines.append(f"  {link}")
    lines.extend(["", "forms:"])
    for idx, form_match in enumerate(re.finditer(r"<form\b.*?</form>", text, re.I | re.S), start=1):
        form = re.sub(r"\s+", " ", form_match.group(0)).strip()
        lines.append(f"  FORM {idx}: {form[:2000]}")
    return "\n".join(lines) + "\n"


def _tcp_port_open(ip_address: str, port: int, timeout_s: float = 1.0) -> Tuple[bool, Optional[str]]:
    try:
        with socket.create_connection((ip_address, port), timeout=timeout_s):
            return True, None
    except OSError as exc:
        return False, str(exc)


def inspect_one(label: str, ip_address: str, run_dir: Path) -> None:
    prefix = f"{_safe_name(label)}_{ip_address.replace('.', '_')}"
    cookie_jar: Dict[str, str] = {}

    summary_lines = [
        f"inspect_version={INSPECT_VERSION}",
        f"label={label}",
        f"ip_address={ip_address}",
    ]

    for port in (80, 443, 4001, 950, 966, 23):
        ok, error = _tcp_port_open(ip_address, port)
        summary_lines.append(f"tcp_port_{port}={'open' if ok else 'closed'} error={error}")

    login_page = _request(ip_address, "GET", "/", cookie_jar=cookie_jar)
    _write(run_dir / f"{prefix}_login_page.html", login_page.body)
    _write(run_dir / f"{prefix}_login_page_summary.txt", _response_summary("login_page", login_page))
    challenge = _extract_fake_challenge(login_page.text)

    summary_lines.append(f"login_page_status={login_page.status}")
    summary_lines.append(f"login_page_title={_title(login_page.text)}")
    summary_lines.append(f"challenge={challenge or ''}")
    summary_lines.append(f"challenge_length={len(challenge) if challenge else 0}")

    if not challenge:
        summary_lines.append("web_login_ok=False")
        summary_lines.append("web_login_message=FakeChallenge not found in login page.")
        _write(run_dir / f"{prefix}_run_summary.txt", "\n".join(summary_lines) + "\n")
        return

    body = _build_login_body(USERNAME, PASSWORD, challenge)
    debug = [
        f"username={USERNAME}",
        f"password=<redacted length={len(PASSWORD)}>",
        f"challenge={challenge}",
        f"challenge_length={len(challenge)}",
        f"EncPasswd={_sha256_hex(USERNAME + PASSWORD + challenge)}",
        f"EncUser={_encode_user(USERNAME, challenge)}",
        f"FakeChallenge={challenge}",
    ]
    _write(run_dir / f"{prefix}_login_payload_debug.txt", "\n".join(debug) + "\n")

    post = _request(
        ip_address,
        "POST",
        "/",
        body=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
            "Referer": f"http://{ip_address}/",
        },
        cookie_jar=cookie_jar,
    )
    _write(run_dir / f"{prefix}_post_login_response.html", post.body)
    _write(run_dir / f"{prefix}_post_login_summary.txt", _response_summary("post_login", post))

    summary_lines.append(f"post_login_status={post.status}")
    summary_lines.append(f"post_login_location={post.headers.get('Location', '')}")
    summary_lines.append(f"post_login_set_cookie={'Set-Cookie' in post.headers}")
    summary_lines.append(f"cookie_jar={'; '.join(cookie_jar.keys())}")

    auth_pages: List[HttpResponse] = []
    redirect_location = post.headers.get("Location", "")
    if redirect_location:
        parsed = urlparse(redirect_location)
        redirect_path = parsed.path or "/"
        if parsed.query:
            redirect_path += "?" + parsed.query
        try:
            redirect_resp = _request(ip_address, "GET", redirect_path, cookie_jar=cookie_jar)
            auth_pages.append(redirect_resp)
            safe = _safe_name(redirect_path.strip("/") or "root")
            _write(run_dir / f"{prefix}_redirect_{safe}.html", redirect_resp.body)
            _write(run_dir / f"{prefix}_redirect_{safe}_summary.txt", _response_summary(f"redirect_{redirect_path}", redirect_resp))

            if _is_failure_record_page(redirect_resp.text):
                form = _extract_first_form(redirect_resp.text, setfunc_value="clearWebLogAction")
                if form:
                    action_path = _extract_form_action(form)
                    fields = _extract_form_inputs(form)
                    # Use the non-destructive Continue button, not clearLog.
                    fields.pop("clearLog", None)
                    fields["continue"] = fields.get("continue", "Continue") or "Continue"
                    continue_body = urlencode(fields).encode("ascii", errors="ignore")
                    continue_resp = _request(
                        ip_address,
                        "POST",
                        action_path,
                        body=continue_body,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Content-Length": str(len(continue_body)),
                            "Referer": f"http://{ip_address}{redirect_path}",
                        },
                        cookie_jar=cookie_jar,
                    )
                    auth_pages.append(continue_resp)
                    continue_safe = _safe_name("continue_" + action_path.strip("/") or "continue_root")
                    _write(run_dir / f"{prefix}_{continue_safe}.html", continue_resp.body)
                    _write(run_dir / f"{prefix}_{continue_safe}_summary.txt", _response_summary(f"continue_{action_path}", continue_resp))
                    summary_lines.append(f"failure_record_continue_status={continue_resp.status}")
                    summary_lines.append(f"failure_record_continue_location={continue_resp.headers.get('Location', '')}")

                    continue_location = continue_resp.headers.get("Location", "")
                    if continue_location:
                        parsed_continue = urlparse(continue_location)
                        continue_redirect_path = parsed_continue.path or "/"
                        if parsed_continue.query:
                            continue_redirect_path += "?" + parsed_continue.query
                        final_resp = _request(ip_address, "GET", continue_redirect_path, cookie_jar=cookie_jar)
                        auth_pages.append(final_resp)
                        final_safe = _safe_name("continue_redirect_" + continue_redirect_path.strip("/") or "continue_redirect_root")
                        _write(run_dir / f"{prefix}_{final_safe}.html", final_resp.body)
                        _write(run_dir / f"{prefix}_{final_safe}_summary.txt", _response_summary(f"continue_redirect_{continue_redirect_path}", final_resp))
                else:
                    summary_lines.append("failure_record_continue_error=form_not_found")
        except Exception as exc:
            summary_lines.append(f"redirect_get_error={exc}")

    # If LoginOK returns a frameset/menu, discover links. Also try common candidate pages.
    queue: List[str] = list(CANDIDATE_AUTH_PAGES)
    for resp in auth_pages:
        queue.extend(_extract_links_and_actions(resp.path, resp.text))
    seen = set()
    fetched = 0
    for path in queue:
        if fetched >= MAX_DISCOVERED_GETS:
            break
        if not path or path in seen:
            continue
        seen.add(path)
        # Avoid fetching static images/styles unless they may contain HTML navigation.
        lowered = path.lower()
        if lowered.endswith((".gif", ".jpg", ".jpeg", ".png", ".css", ".ico")):
            continue
        try:
            resp = _request(ip_address, "GET", path, cookie_jar=cookie_jar)
        except Exception as exc:
            _write(run_dir / f"{prefix}_get_{_safe_name(path)}_error.txt", str(exc) + "\n")
            continue
        fetched += 1
        safe = _safe_name(path.strip("/") or "root")
        _write(run_dir / f"{prefix}_get_{safe}.html", resp.body)
        _write(run_dir / f"{prefix}_get_{safe}_summary.txt", _response_summary(f"get_{path}", resp))
        # Discover one more layer, bounded by MAX_DISCOVERED_GETS.
        for link in _extract_links_and_actions(path, resp.text):
            if link not in seen and len(queue) < MAX_DISCOVERED_GETS * 3:
                queue.append(link)

    logged_in = False
    reasons: List[str] = []
    for resp in auth_pages:
        text = resp.text
        if resp.status == 200 and not _contains_login_form(text) and "Session Expired" not in text:
            logged_in = True
            reasons.append(f"redirect page {resp.path} looked authenticated")
    summary_lines.append(f"auth_get_count={fetched}")
    summary_lines.append(f"web_login_ok={logged_in}")
    summary_lines.append(f"web_login_message={'; '.join(reasons) if reasons else 'Login redirect was followed, inspect saved pages.'}")

    _write(run_dir / f"{prefix}_run_summary.txt", "\n".join(summary_lines) + "\n")


def main() -> int:
    run_dir = Path("nport_web_login_logs") / f"run_{_timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("NPort web login inspect / v8")
    print("--------------------------")
    print(f"inspect_version: {INSPECT_VERSION}")
    print(f"output_dir: {run_dir}")
    print("nports:")
    for label, ip_address in NPORTS:
        print(f"  - {label}: {ip_address}")

    for label, ip_address in NPORTS:
        print()
        print(f"{label} at {ip_address}")
        print("-" * (len(label) + len(ip_address) + 4))
        try:
            inspect_one(label, ip_address, run_dir)
            print("done")
        except Exception as exc:
            print(f"error: {exc}")
            _write(run_dir / f"{_safe_name(label)}_{ip_address.replace('.', '_')}_fatal_error.txt", repr(exc) + "\n")

    print()
    print(f"Logs: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

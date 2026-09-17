import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"
CHAT_TIMEOUT_SECONDS = 300
ENV_FILE = Path(__file__).resolve().parents[1] / "backend" / ".env"


def resolve_token(cli_token):
    if cli_token:
        return cli_token
    env_token = os.environ.get("AUTH_TOKEN")
    if env_token:
        return env_token
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AUTH_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def http_json(url, payload=None, timeout=60, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is None:
        req = urllib.request.Request(url, method="GET", headers=headers)
    else:
        headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=headers,
        )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(base_url, message, conversation_id, token):
    return http_json(
        f"{base_url}/chat",
        {"message": message, "conversation_id": conversation_id},
        timeout=CHAT_TIMEOUT_SECONDS,
        token=token,
    )


def health(base_url, token):
    return http_json(f"{base_url}/health", timeout=10, token=token)


def send(base_url, message, conversation_id, token):
    try:
        result = chat(base_url, message, conversation_id, token)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
        return
    except urllib.error.URLError as exc:
        print(f"Bağlantı hatası: {exc.reason}")
        return
    except TimeoutError:
        print(
            f"Sunucu yanıtı {CHAT_TIMEOUT_SECONDS} saniye içinde alınamadı. "
            "İstek sunucuda çalışmaya devam ediyor olabilir; kısa süre sonra "
            "sonucu sorabilirsin."
        )
        return
    print(result["reply"])
    if result.get("status") == "confirmation_required":
        for tool_call in result.get("tool_calls") or []:
            args = json.dumps(tool_call.get("args", {}), ensure_ascii=False)
            print(f"[onay bekleniyor] {tool_call['name']}({args})")


def handle_command(base_url, message, token):
    if message in ("/exit", "/quit"):
        return "exit"
    if message == "/health":
        try:
            print(health(base_url, token))
        except urllib.error.URLError as exc:
            print(f"Bağlantı hatası: {exc.reason}")
        return "health"
    if message == "/new":
        return "new"
    return None


def run_interactive(base_url, token):
    conversation_id = str(uuid.uuid4())
    print(f"Sunucu: {base_url}")
    try:
        print(f"Durum: {health(base_url, token)}")
    except urllib.error.URLError as exc:
        print(f"Sunucuya bağlanılamadı: {exc.reason}")
        sys.exit(1)
    print(f"Sohbet: {conversation_id}")
    print("Çıkmak için /exit, sunucu durumu için /health, yeni sohbet için /new")
    while True:
        try:
            message = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not message:
            continue
        command = handle_command(base_url, message, token)
        if command == "exit":
            return
        if command == "new":
            conversation_id = str(uuid.uuid4())
            print(f"Yeni sohbet: {conversation_id}")
            continue
        if command is None:
            send(base_url, message, conversation_id, token)


def main():
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Rona sunucusu için basit CLI istemci")
    parser.add_argument(
        "message", nargs="*", help="verilirse tek seferlik mesaj gönderilir"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="sunucu adresi")
    parser.add_argument(
        "--token",
        default=None,
        help="bearer token (yoksa AUTH_TOKEN env / .env okunur)",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")
    token = resolve_token(args.token)
    if not token:
        print(
            "AUTH_TOKEN bulunamadı. --token argümanı, AUTH_TOKEN ortam değişkeni "
            "veya kök .env dosyası ile sağla."
        )
        sys.exit(1)

    if args.message:
        message = " ".join(args.message)
        if handle_command(base_url, message, token) is None:
            send(base_url, message, str(uuid.uuid4()), token)
    else:
        run_interactive(base_url, token)


if __name__ == "__main__":
    main()

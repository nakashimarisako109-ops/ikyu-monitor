import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://www.ikyu.com/00002997/"
LAST_NOTIFIED_FILE = Path("last_notified.txt")
NOTIFY_INTERVAL_HOURS = 12

SALE_PATTERNS = [
    r"タイムセール",
    r"timesale",
    r"time[\s_-]?sale",
    r"TIME[\s_-]?SALE",
    r"期間限定",
    r"特別価格",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}


def fetch_page(url: str) -> str:
    session = requests.Session()
    session.headers.update(HEADERS)
    # トップページを先に訪問してCookieを取得
    try:
        session.get("https://www.ikyu.com/", timeout=15)
    except Exception:
        pass
    resp = session.get(url, timeout=30)
    if resp.status_code == 403:
        print(f"403 Forbidden: サイトがアクセスをブロックしました。スキップします。")
        sys.exit(0)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def detect_sale(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    # class属性にセール関連文字列を含む要素を探す
    sale_class_pattern = re.compile(r"timesale|time.?sale|sale", re.IGNORECASE)
    class_matches = []
    for tag in soup.find_all(class_=sale_class_pattern):
        text = tag.get_text(strip=True)
        if text:
            class_matches.append(f"[class:{tag.get('class')}] {text[:80]}")

    # テキストノードからパターン検索
    full_text = soup.get_text(" ", strip=True)
    text_matches = []
    for pattern in SALE_PATTERNS:
        for m in re.finditer(pattern, full_text, re.IGNORECASE):
            start = max(0, m.start() - 20)
            end = min(len(full_text), m.end() + 40)
            snippet = full_text[start:end].strip()
            text_matches.append(snippet)

    return list(dict.fromkeys(class_matches + text_matches))  # 重複除去・順序維持


def should_notify() -> bool:
    if not LAST_NOTIFIED_FILE.exists():
        return True
    raw = LAST_NOTIFIED_FILE.read_text(encoding="utf-8").strip()
    try:
        last_time = datetime.fromisoformat(raw)
        return datetime.now() - last_time > timedelta(hours=NOTIFY_INTERVAL_HOURS)
    except ValueError:
        return True


def record_notified():
    LAST_NOTIFIED_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")


def send_gmail(detected: list[str]):
    gmail_address = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    notify_email = os.environ.get("NOTIFY_EMAIL", gmail_address)

    detected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snippets = "\n".join(f"  ・{s}" for s in detected[:10])

    body = f"""\
タイムセールを検知しました。

検知時刻　: {detected_at}
ページURL　: {TARGET_URL}

【検知テキスト（抜粋）】
{snippets}

すぐに確認してください。
"""

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "【タイムセール開始】五島リトリート ray by 温故知新"
    msg["From"] = gmail_address
    msg["To"] = notify_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_address, app_password)
        smtp.send_message(msg)

    print(f"[{detected_at}] メール送信完了 → {notify_email}")


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 監視開始: {TARGET_URL}")

    try:
        html = fetch_page(TARGET_URL)
    except requests.RequestException as e:
        print(f"ページ取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    detected = detect_sale(html)

    if not detected:
        print("タイムセールは検知されませんでした。")
        return

    print(f"タイムセール検知: {len(detected)} 件のマッチ")
    for s in detected[:5]:
        print(f"  {s}")

    if not should_notify():
        print(f"前回通知から {NOTIFY_INTERVAL_HOURS} 時間未満のため通知をスキップします。")
        return

    try:
        send_gmail(detected)
        record_notified()
    except Exception as e:
        print(f"メール送信失敗: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

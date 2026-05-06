from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "channels.json"
DATA_PATH = ROOT / "data" / "processed_videos.json"
REPORTS_DIR = ROOT / "reports"
INDEX_PATH = ROOT / "index.html"
USER_AGENT = "youtube-ai-report/1.0"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def today_jst() -> dt.date:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()


def resolve_feed_url(channel: dict[str, str]) -> str:
    if channel.get("feed_url"):
        return channel["feed_url"]
    if channel.get("channel_id"):
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel['channel_id']}"
    handle = channel.get("handle")
    if not handle:
        raise ValueError(f"Channel entry requires feed_url, channel_id, or handle: {channel}")
    handle = handle if handle.startswith("@") else f"@{handle}"
    encoded_handle = urllib.parse.quote(handle, safe="@")
    page_url = f"https://www.youtube.com/{encoded_handle}/videos"
    body = http_get(page_url)
    match = re.search(r'"channelId":"(UC[^"]+)"', body)
    if not match:
        match = re.search(r'<meta itemprop="channelId" content="(UC[^"]+)">', body)
    if not match:
        raise RuntimeError(f"Could not resolve channel id for {handle}")
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={match.group(1)}"


def http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_videos(channels: list[dict[str, str]]) -> list[dict[str, str]]:
    videos: list[dict[str, str]] = []
    for channel in channels:
        feed_url = resolve_feed_url(channel)
        root = ET.fromstring(http_get(feed_url))
        feed_title = root.findtext("atom:title", default="Unknown Channel", namespaces=ATOM_NS)
        channel_name = channel.get("name") or feed_title
        for entry in root.findall("atom:entry", ATOM_NS):
            video_id = entry.findtext("yt:videoId", default="", namespaces=ATOM_NS)
            title = entry.findtext("atom:title", default="", namespaces=ATOM_NS)
            published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)
            summary = entry.findtext("atom:summary", default="", namespaces=ATOM_NS)
            link_node = entry.find("atom:link", ATOM_NS)
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            videos.append(
                {
                    "id": video_id,
                    "title": title.strip(),
                    "url": link,
                    "channel": channel_name,
                    "published": published,
                    "summary": strip_html(summary).strip(),
                }
            )
    return sorted(videos, key=lambda item: item.get("published", ""), reverse=True)


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def build_ai_summary(videos: list[dict[str, str]], skip_openai: bool) -> str:
    if not videos:
        return "本日の新着動画はありませんでした。"
    if skip_openai or not os.environ.get("OPENAI_API_KEY"):
        titles = "\n".join(f"- {v['channel']}: {v['title']}" for v in videos[:10])
        return f"OpenAI APIキー未設定のため、取得した新着動画の一覧を表示します。\n{titles}"

    from openai import OpenAI

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI()
    source = json.dumps(videos[:20], ensure_ascii=False, indent=2)
    prompt = (
        "以下はYouTubeの新着動画一覧です。日本語で、忙しい読者向けに要点を整理してください。\n"
        "出力は次の形式にしてください。\n"
        "1. 全体傾向\n"
        "2. 注目動画3件\n"
        "3. 今日見るならこの順番\n\n"
        f"{source}"
    )
    response = client.responses.create(
        model=model,
        input=prompt,
    )
    return response.output_text.strip()


def render_report(report_date: dt.date, videos: list[dict[str, str]], ai_summary: str) -> str:
    video_items = "\n".join(render_video_card(video) for video in videos)
    if not video_items:
        video_items = '<p class="empty">新着動画はありません。</p>'
    title = f"YouTube AI Report - {report_date.isoformat()}"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="../styles.css">
</head>
<body>
  <main class="page">
    <header class="header">
      <p class="eyebrow">Daily YouTube Report</p>
      <h1>{html.escape(report_date.isoformat())}</h1>
      <a class="back" href="../index.html">レポート一覧へ戻る</a>
    </header>

    <section class="summary">
      <h2>AI要約</h2>
      {render_markdownish(ai_summary)}
    </section>

    <section class="videos">
      <h2>取得動画</h2>
      <div class="video-grid">
        {video_items}
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_markdownish(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    parts: list[str] = []
    list_open = False
    for line in lines:
        if not line:
            if list_open:
                parts.append("</ul>")
                list_open = False
            continue
        if line.startswith("- "):
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{html.escape(line[2:])}</li>")
        else:
            if list_open:
                parts.append("</ul>")
                list_open = False
            parts.append(f"<p>{html.escape(line)}</p>")
    if list_open:
        parts.append("</ul>")
    return "\n".join(parts)


def render_video_card(video: dict[str, str]) -> str:
    return f"""<article class="video-card">
  <p class="channel">{html.escape(video.get("channel", ""))}</p>
  <h3><a href="{html.escape(video.get("url", ""))}">{html.escape(video.get("title", ""))}</a></h3>
  <p class="published">{html.escape(video.get("published", ""))}</p>
  <p>{html.escape(video.get("summary", ""))}</p>
</article>"""


def update_index() -> None:
    reports = sorted(REPORTS_DIR.glob("*.html"), reverse=True)
    links = "\n".join(
        f'<li><a href="reports/{html.escape(path.name)}">{html.escape(path.stem)}</a></li>'
        for path in reports
    )
    if not links:
        links = '<li class="empty">まだレポートはありません。</li>'
    INDEX_PATH.write_text(
        f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YouTube AI Report</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="page">
    <header class="header">
      <p class="eyebrow">YouTube AI Report</p>
      <h1>日次レポート</h1>
    </header>
    <section class="reports">
      <h2>Reports</h2>
      <ul class="report-list">
        {links}
      </ul>
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-openai", action="store_true")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format")
    args = parser.parse_args()

    channels = load_json(CONFIG_PATH, [])
    if not channels:
        raise RuntimeError("No channels configured in config/channels.json")

    report_date = dt.date.fromisoformat(args.date) if args.date else today_jst()
    state = load_json(DATA_PATH, {"processed": {}})
    processed: dict[str, Any] = state.setdefault("processed", {})

    videos = fetch_videos(channels)
    new_videos = [video for video in videos if video["id"] and video["id"] not in processed]
    ai_summary = build_ai_summary(new_videos, args.skip_openai)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{report_date.isoformat()}.html"
    report_path.write_text(render_report(report_date, new_videos, ai_summary), encoding="utf-8")

    for video in new_videos:
        processed[video["id"]] = {
            "title": video["title"],
            "channel": video["channel"],
            "url": video["url"],
            "published": video["published"],
            "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    write_json(DATA_PATH, state)
    update_index()
    print(f"Generated {report_path.relative_to(ROOT)} with {len(new_videos)} new videos.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

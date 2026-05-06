# YouTube AI Report

YouTubeチャンネルの新着動画を集め、OpenAI APIで要点を整理したHTMLレポートを生成する小さな自動化プロジェクトです。生成されたレポートはGitHub Pagesで公開できます。

## できること

- `config/channels.json` に登録したYouTubeチャンネルのRSSを取得
- 未処理の新着動画を `data/processed_videos.json` で管理
- `reports/YYYY-MM-DD.html` に日次レポートを生成
- `index.html` を最新レポート一覧として更新
- GitHub Actionsで毎日自動実行

## ローカルでの実行

このリポジトリ直下で実行します。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

OpenAI APIキーを使う場合:

```powershell
$env:OPENAI_API_KEY = "sk-..."
py scripts\generate_report.py
```

APIキーなしでHTML生成だけ確認する場合:

```powershell
py scripts\generate_report.py --skip-openai
```

## チャンネル設定

`config/channels.json` を編集します。

```json
[
  {
    "name": "AI仙人ch",
    "channel_id": "UCRxPq02pjQS_ax60gcTSDHQ"
  }
]
```

使える指定方法:

- `handle`: `@example` のようなYouTubeハンドル
- `channel_id`: `UC...` で始まるチャンネルID
- `feed_url`: YouTube RSSのURLを直接指定

## GitHub Pages設定

GitHubのリポジトリ画面で以下を設定します。

```text
Settings > Pages
```

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/ (root)`

## GitHub Actions設定

```text
Settings > Secrets and variables > Actions
```

Repository secret:

```text
OPENAI_API_KEY
```

任意のRepository variable:

```text
OPENAI_MODEL
```

未設定の場合は `gpt-4.1-mini` を使います。

## 手動実行

GitHub上で以下を開きます。

```text
Actions > Daily YouTube Report > Run workflow
```

成功すると次のファイルが更新されます。

- `reports/YYYY-MM-DD.html`
- `index.html`
- `data/processed_videos.json`

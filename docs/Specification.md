# Flow Launcher プラグイン仕様書：App Manager

## 1. ドキュメント情報

| 項目 | 内容 |
|---|---|
| プロジェクト名 | App Manager |
| ドキュメント種別 | 機能仕様書（Specification） |
| 対応要件定義書 | [Requirements.md](./Requirements.md) |
| 参照ドキュメント | [Flow Launcher 公式ドキュメント](https://www.flowlauncher.com/docs/#/) |
| 作成日 | 2026-03-10 |
| ステータス | Draft |

---

## 2. システム概要

### 2.1 アーキテクチャ概要

App Manager は **Flow Launcher プラグインフレームワーク** 上で動作する **Python プラグイン** である。Flow Launcher 本体と **JSON-RPC プロトコル** を介して通信する。

```
┌──────────────────────────────────────────────────────┐
│              Flow Launcher 本体                       │
│  ┌────────────────────────────────────────────────┐  │
│  │     Plugin Host (JSON-RPC over stdin/stdout)   │  │
│  │  ┌──────────────────────────────────────────┐  │  │
│  │  │   App Manager Plugin (Python / main.py)  │  │  │
│  │  │   class AppManager(FlowLauncher)         │  │  │
│  │  │  ┌────────────┐  ┌─────────────────┐    │  │  │
│  │  │  │  Search     │  │  App Registry   │    │  │  │
│  │  │  │  Handler    │  │  Manager        │    │  │  │
│  │  │  └────────────┘  └─────────────────┘    │  │  │
│  │  │  ┌────────────┐  ┌─────────────────┐    │  │  │
│  │  │  │ Settings   │  │  Cache / Data   │    │  │  │
│  │  │  │ Manager    │  │  Store          │    │  │  │
│  │  │  └────────────┘  └─────────────────┘    │  │  │
│  │  └──────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │       Windows Shell API / Registry / COM       │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 2.2 JSON-RPC プロセスモデル

Flow Launcher の Python プラグインは **リクエストごとに新しい Python プロセス** が起動される。

```
[ユーザー入力] → Flow Launcher 本体
  → Python プロセス起動 (main.py)
    → sys.argv[1] から JSON-RPC リクエストを受信
    → 該当メソッド（query / context_menu / アクション）を実行
    → query / context_menu の場合: 結果を stdout に JSON 出力
    → アクションの場合: 処理実行（stdout 出力は任意）
  → プロセス終了
```

**通信例:**
```
→ Plugin: {"method": "query", "parameters": [""]}
← Plugin: {"result": [{"Title":"...", "SubTitle":"...", "IcoPath":"..."}], "debugMessage":""}
```

> **重要**: このプロセスモデルにより、プラグイン内でのメモリ上キャッシュは **リクエストをまたいで保持されない**。永続化が必要なデータはすべてファイルに書き出す必要がある。

### 2.3 モジュール構成

| モジュール | 責務 | 対応要件 |
|---|---|---|
| `main.py` | エントリーポイント。`FlowLauncher` クラスを継承し、`query`, `context_menu` 等を実装する。 | — |
| `app_registry.py` | アプリ一覧取得・キャッシュ管理・データ永続化。 | 3.1.2, 3.1.5, 4.1.2, 4.2.1 |
| `search_handler.py` | クエリ解析・検索結果構築・ランキング。 | 3.1.1, 3.1.3, 3.1.4, 3.2 |
| `execution_handler.py` | アプリ起動・履歴更新。 | 3.3 |
| `settings_manager.py` | ユーザー設定の読み書き・エクスポート/インポート。 | 3.4 |
| `models.py` | データモデル定義。 | — |

### 2.4 使用ライブラリ

| ライブラリ | 種別 | 用途 |
|---|---|---|
| `flowlauncher` | 公式（PyPI） | `FlowLauncher` 基底クラス + `FlowLauncherAPI` ユーティリティ |
| `comtypes` | サードパーティ | Shell API (`shell:AppsFolder`) COM 経由のアプリ列挙 |

**`flowlauncher` モジュールの構成（ソースコード確認済み）:**

| クラス | 役割 |
|---|---|
| `FlowLauncher` | プラグイン基底クラス。`__init__` で `sys.argv[1]` から JSON-RPC を受け取り、対応メソッドを呼び出す。`query` / `context_menu` の戻り値のみ stdout に出力する。 |
| `FlowLauncherAPI` | Flow Launcher 本体 API のラッパー。全メソッドが `@classmethod` であり、stdout に JSON-RPC コマンドを直接 print する。 |

> **注意**: `FlowLauncher` と `FlowLauncherAPI` は **別クラス** である。`FlowLauncher` 基底クラスには API 呼び出しメソッドはない。

### 2.5 `main.py` の基本構造

```python
import sys
from pathlib import Path

plugindir = Path.absolute(Path(__file__).parent)
paths = (".", "lib", "plugin")
sys.path = [str(plugindir / p) for p in paths] + sys.path

from flowlauncher import FlowLauncher, FlowLauncherAPI
import os
import subprocess


class AppManager(FlowLauncher):

    def query(self, query: str = '') -> list:
        """検索結果を返却。戻り値は自動的に stdout へ出力される。"""
        registry = AppRegistry.load()  # ファイルから毎回読み込み
        results = SearchHandler.search(registry, query)
        return results

    def context_menu(self, data) -> list:
        """右クリックメニュー。戻り値は自動的に stdout へ出力される。"""
        app_id = data[0]
        return ContextMenuBuilder.build(app_id)

    def execute(self, app_id: str):
        """アプリ起動。戻り値は stdout に出力されない。"""
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        # Python から直接起動（FlowLauncherAPI.shell_run ではない）
        if entry.exec_path:
            os.startfile(entry.exec_path)
        elif entry.aumid:
            subprocess.Popen(
                f'explorer.exe shell:AppsFolder\\{entry.aumid}'
            )
        entry.last_used = datetime.utcnow()
        registry.save()

    def open_location(self, app_id: str):
        """ファイルの場所をエクスプローラーで開く。"""
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        if entry.exec_path:
            folder = str(Path(entry.exec_path).parent)
            subprocess.Popen(f'explorer.exe "{folder}"')

    def toggle_pin(self, app_id: str):
        """ピン留め状態をトグル。"""
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        entry.is_pinned = not entry.is_pinned
        registry.save()

    def add_to_blacklist(self, app_id: str):
        """ブラックリストに追加。"""
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        entry.is_blacklisted = True
        registry.save()


if __name__ == "__main__":
    AppManager()
```

> **アプリ起動方式**: `FlowLauncherAPI.shell_run()` ではなく、Python 標準の `os.startfile()` / `subprocess.Popen()` を使用する。これは公式サンプル（HelloWorldPython: `webbrowser.open()`）や Steam Search プラグインと同じパターンであり、起動処理と履歴更新を同一メソッド内で確実に実行できる。

---

## 3. データモデル

### 3.1 `AppEntry`（アプリケーションエントリ）

| フィールド | 型 | 説明 | 必須 |
|---|---|---|---|
| `id` | `str` | 一意識別子。Win32 は正規化済みパス、UWP は AUMID。 | ✅ |
| `name` | `str` | OS から取得したアプリケーション表示名。 | ✅ |
| `source` | `enum(shell, registry, custom)` | 取得元。 | ✅ |
| `exec_path` | `str \| None` | Win32 アプリの実行パス。UWP は `None`。 | — |
| `aumid` | `str \| None` | UWP アプリの AppUserModelId。Win32 は `None`。 | — |
| `logo_path` | `str \| None` | UWP アプリのロゴ画像パス（パッケージマニフェストから取得）。Win32 は `None`（`exec_path` から自動抽出）。 | — |
| `last_used` | `str \| None` | 最終使用日時（ISO 8601 UTC）。未使用は `None`。 | — |
| `is_pinned` | `bool` | ピン留め状態。デフォルト `False`。 | ✅ |
| `aliases` | `list[str]` | ユーザー定義エイリアスのリスト。 | ✅ |
| `is_blacklisted` | `bool` | ブラックリスト状態。デフォルト `False`。 | ✅ |
| `last_detected` | `str` | 最後にスキャンで検出された日時（ISO 8601 UTC）。 | ✅ |

### 3.2 永続化フォーマット

#### 3.2.1 プラグイン内部データ: `app_cache.json`

```json
{
  "schema_version": 1,
  "last_scan_time": "2026-03-10T03:00:00Z",
  "entries": [
    {
      "id": "C:\\Program Files\\Example\\app.exe",
      "name": "Example App",
      "source": "shell",
      "exec_path": "C:\\Program Files\\Example\\app.exe",
      "aumid": null,
      "logo_path": null,
      "last_used": "2026-03-09T10:30:00Z",
      "is_pinned": false,
      "aliases": ["ex"],
      "is_blacklisted": false,
      "last_detected": "2026-03-10T03:00:00Z"
    }
  ]
}
```

* `schema_version` によりアップデート時に新規フィールドをデフォルト値で自動補完する（要件 4.2.3）。

> **プロセスモデルとの整合性**: §2.2 のとおりリクエストごとにプロセスが起動されるため、`app_cache.json` は毎回ファイルから読み込む。書き込み時は排他制御（ファイルロック）を考慮する。

#### 3.2.2 ユーザー設定: `SettingsTemplate.yaml` + Flow Launcher Settings

Flow Launcher は `SettingsTemplate.yaml` で定義された設定値を以下のパスに保存する:

```
{FlowLauncherUserData}/Settings/Plugins/{PluginName}/Settings.json
```

プラグインからはこのファイルを直接読み込むことでアクセスする。

#### 3.2.3 バックアップファイル

エクスポート時は `app_cache.json` の履歴・エイリアス・ピン留め情報と Settings の値を統合した単一 JSON を生成する。インポート時は同形式のファイルを読み込み、既存データとマージする。

---

## 4. 機能仕様

### 4.1 アプリケーション取得（App Registry）

#### 4.1.1 取得ソースと手順

| ソース | 取得方法 | 取得対象 |
|---|---|---|
| **Shell API** | `shell:AppsFolder` を COM 経由で列挙。 | スタートメニューアプリ全般（Win32 + UWP）。 |
| **レジストリ** | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` + `HKCU` を走査。 | Shell API で漏れる Win32 アプリの補完。 |
| **カスタムパス** | ユーザー指定ディレクトリを再帰走査し `.exe` / `.lnk` / `.appref-ms` を収集。 | ユーザー指定アプリ。 |

#### 4.1.2 識別子（ID）の生成ルール

| アプリ種別 | ID 生成ルール | 例 |
|---|---|---|
| Win32 | `os.path.normcase()` で正規化 | `c:\program files\example\app.exe` |
| UWP | AUMID をそのまま使用 | `Microsoft.WindowsCalculator_8wekyb3d8bbwe!App` |
| カスタムパス | 正規化したパス | `d:\tools\mytool.exe` |

> **重複の扱い（要件 3.1.2）**: パスが異なれば別エントリ。パスが同一の場合は `source` 優先度（`shell` > `registry` > `custom`）で採用し統合。

#### 4.1.3 自動スキャン

スキャンは完全に自動化される。ユーザーによる手動操作は不要。

* **トリガー**: `query()` 呼び出し時に `last_scan_time` をチェックし、`scan_interval`（設定画面で変更可、デフォルト60分）を超過していれば `scanner.py` を別プロセスで起動。
* **初回**: `app_cache.json` が存在しない場合は同期スキャンを実行してからクエリに応答。
* **応答への影響なし**: バックグラウンドスキャン中は既存キャッシュで即座に応答。スキャン結果は次回のクエリから反映。
* **排他制御**: `scanner.py` は一時ファイルに書き出してからリネームすることで、読み取り中のクエリと競合しない。

### 4.2 検索・結果構築（Search Handler）

#### 4.2.1 起動条件

* アクションキーワード: `ap`（`plugin.json` の `ActionKeyword` で定義）
* Flow Launcher がユーザー入力 `ap ` を検知すると `query` メソッドが呼び出される。

#### 4.2.2 検索フロー

`ap <text>` の入力は**常にアプリ検索**として処理する。特殊コマンドは存在しない。

```
query(query) が呼び出される
  │
  ├─ app_cache.json をファイルから読み込み
  │
  ├─ 自動スキャン判定（§4.1.3）
  │
  ├─ 設定画面のエクスポート/インポートをチェック（§4.4.5）
  │
  ├─ query が空文字？
  │   ├─ YES → 履歴順表示モード（§4.2.3）
  │   └─ NO  → アプリ検索モード（§4.2.4）
  │
  └─ 結果リスト（list[dict]）を return
```

#### 4.2.3 履歴順表示モード（クエリ未入力時）

1. ピン留め済みアプリを登録順で最上位に配置（`Score` を高い値に設定）。
2. 残りを `last_used` 降順。
3. `last_used` が `None` は末尾にアプリ名昇順。
4. ブラックリスト除外。

#### 4.2.4 アプリ検索モード（クエリ入力時）

1. 全 `AppEntry` から `name` と `aliases` を候補文字列として生成。
2. **エイリアス完全一致**: `Score` を最大値（100）に設定（要件 3.2.3）。
3. **Flow Launcher 標準マッチング**: `Title` に候補文字列を設定して返却し、本体のファジーサーチに委譲（要件 3.1.3）。
4. ピン留め済みは `Score` に加算ボーナス。
5. ブラックリスト除外。

> **`Score` について（公式ドキュメント）**: 0〜100 の範囲。アクションキーワード使用プラグインのベースは 0。値が高いほど検索結果で上位に表示。

#### 4.2.5 結果アイテムの構築

各検索結果は **PascalCase キーの辞書** で返却する（公式 `flowlauncher` モジュール準拠）:

```python
# Win32 アプリの場合: exec_path をそのまま IcoPath に指定
{
    "Title": "Example App",
    "SubTitle": "C:\\Program Files\\Example\\app.exe",
    "IcoPath": "C:\\Program Files\\Example\\app.exe",
    "Score": 0,
    "ContextData": ["app_id_here"],
    "JsonRPCAction": {
        "method": "execute",
        "parameters": ["app_id_here"],
        "dontHideAfterAction": False
    }
}

# UWP アプリの場合: パッケージマニフェストのロゴパスを使用
{
    "Title": "Calculator",
    "SubTitle": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "IcoPath": "C:\\Program Files\\WindowsApps\\...\\Calculator.png",
    "Score": 0,
    ...
}
```

| プロパティ | 値 | 備考 |
|---|---|---|
| `Title` | エイリアスがあればそれを使用、なければアプリ名。 | 要件 3.5.1 |
| `SubTitle` | `exec_path` または AUMID 情報。 | 要件 3.5.1 |
| `IcoPath` | Win32: `exec_path` をそのまま指定（Flow Launcher が自動抽出）。UWP: `logo_path`。取得不可時: `Images/app.png`。 | 要件 3.5.1, §4.5 |
| `Score` | エイリアス一致時 100、ピン留め時加算、他 0。 | 要件 3.2 |
| `ContextData` | `[app_id]`。`context_menu` の `data` 引数に渡される。 | — |
| `JsonRPCAction` | 選択時に呼び出されるメソッド名とパラメータ。 | — |

**`JsonRPCAction` の追加プロパティ:**

| プロパティ | 型 | 説明 |
|---|---|---|
| `dontHideAfterAction` | `bool` | `True` の場合、アクション実行後も Flow Launcher を非表示にしない。エイリアス設定操作等で使用。 |

### 4.3 実行処理（Execution Handler）

#### 4.3.1 実行フロー

```
execute(app_id) が呼び出される
  │
  ├─ app_cache.json から AppEntry を取得
  │
  ├─ アプリ種別の判定
  │   ├─ Win32 (exec_path != None)
  │   │   └─ os.startfile(exec_path)
  │   └─ UWP (aumid != None)
  │       └─ subprocess.Popen(
  │            f'explorer.exe shell:AppsFolder\{aumid}')
  │
  ├─ 履歴更新: last_used を現在日時(UTC)に更新
  │
  └─ app_cache.json に書き出し
```

> **`os.startfile()` を使用する理由**: 公式サンプル（HelloWorldPython: `webbrowser.open()`、Steam Search: `webbrowser.open()`）と同様に、Python から直接起動する。これにより起動と履歴更新を同一メソッド内で確実に実行でき、`FlowLauncherAPI.shell_run()` の stdout 競合問題を回避できる。

#### 4.3.2 コンテキストメニュー

`context_menu(self, data)` メソッドで実装。`data` には `ContextData` の値がリストとして渡される。

```python
def context_menu(self, data) -> list:
    app_id = data[0]
    registry = AppRegistry.load()
    entry = registry.get(app_id)
    pin_title = "ピン解除" if entry.is_pinned else "ピン留め"
    return [
        {
            "Title": "ファイルの場所を開く",
            "SubTitle": "エクスプローラーで開きます",
            "IcoPath": "Images/open_folder.png",
            "JsonRPCAction": {
                "method": "open_location",
                "parameters": [app_id]
            }
        },
        {
            "Title": pin_title,
            "SubTitle": "検索結果の最上位に固定します",
            "IcoPath": "Images/pin.png",
            "JsonRPCAction": {
                "method": "toggle_pin",
                "parameters": [app_id]
            }
        },
        {
            "Title": "ブラックリストに追加",
            "SubTitle": "検索結果から非表示にします",
            "IcoPath": "Images/block.png",
            "JsonRPCAction": {
                "method": "add_to_blacklist",
                "parameters": [app_id]
            }
        }
    ]
```

| メニュー項目 | 動作 |
|---|---|
| ファイルの場所を開く | `subprocess.Popen` でエクスプローラーを起動。 |
| ピン留め / ピン解除 | `is_pinned` トグル → `app_cache.json` 保存。 |
| ブラックリストに追加 | `is_blacklisted = True` → `app_cache.json` 保存。 |

> **管理者実行**: Flow Launcher 本体が標準提供する機能であり、プラグイン側での実装は不要（要件 3.3.3）。
>
> **エイリアス管理**: 設定画面の「エイリアス設定」欄で編集する（§4.4.1）。

### 4.4 設定管理（Settings Manager）

プラグインの全設定は **Flow Launcher のプラグイン設定画面（GUI）** で管理する。

```
Flow Launcher 設定 → プラグイン → App Manager → ⚙️設定ボタン
```

この画面は `SettingsTemplate.yaml` で宣言的に定義される。ユーザーから見ると通常の GUI フォーム（テキストボックス、チェックボックス等）として表示される。

#### 4.4.1 設定画面の構成（`SettingsTemplate.yaml`）

```yaml
body:
  - type: textBlock
    attributes:
      description: >
        App Manager はインストール済みアプリケーションを高速に検索・起動するプラグインです。

  - type: textarea
    attributes:
      name: alias_map
      label: エイリアス設定
      description: >
        アプリに別名（エイリアス）を設定します。1行に1つ、「アプリ名=エイリアス」の形式で入力してください。
        複数のエイリアスはカンマ区切りで指定できます。
        例: Calculator=c,calc

  - type: textarea
    attributes:
      name: custom_paths
      label: カスタムスキャンパス
      description: >
        追加でスキャンするディレクトリパスを1行に1つずつ入力してください。

  - type: input
    attributes:
      name: stale_threshold_days
      label: データクレンジング猶予日数
      description: >
        外部ドライブのアプリが検出されなくなってから自動削除するまでの猶予日数です。
      defaultValue: "30"

  - type: input
    attributes:
      name: scan_interval_minutes
      label: 自動スキャン間隔（分）
      description: >
        アプリ一覧を自動で再スキャンする間隔です。0にすると毎回スキャンします。
      defaultValue: "60"

  - type: checkbox
    attributes:
      name: scan_registry
      label: レジストリからもアプリを取得する
      description: >
        Shell API で取得できないアプリをレジストリから補完します。
      defaultValue: true

  - type: inputWithFolderBtn
    attributes:
      name: export_folder
      label: エクスポート先フォルダ
      description: >
        フォルダを選択すると、次回のプラグイン使用時に設定と履歴を JSON ファイルとしてエクスポートします。
        エクスポート完了後、この欄は自動的にクリアされます。

  - type: inputWithFileBtn
    attributes:
      name: import_file
      label: インポートファイル
      description: >
        JSON ファイルを選択すると、次回のプラグイン使用時にデータをインポートします。
        インポート完了後、この欄は自動的にクリアされます。
```

#### 4.4.2 設定値へのアクセス

`flowlauncher` 公式モジュールには設定値アクセス機能がないため、Flow Launcher が保存する設定ファイルを直接読み込む:

```python
import json
from pathlib import Path

def load_settings(plugin_name: str) -> dict:
    """Flow Launcher の設定ファイルを読み込む。"""
    plugin_dir = Path(__file__).parent
    user_data = plugin_dir.parent.parent
    settings_path = (
        user_data / "Settings" / "Plugins" / plugin_name / "Settings.json"
    )
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_settings(plugin_name: str, settings: dict):
    """Flow Launcher の設定ファイルに書き込む（値のクリア用）。"""
    plugin_dir = Path(__file__).parent
    user_data = plugin_dir.parent.parent
    settings_path = (
        user_data / "Settings" / "Plugins" / plugin_name / "Settings.json"
    )
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
```

#### 4.4.3 GUI で管理する設定項目の一覧

| GUI コントロール | 設定項目 | 操作 |
|---|---|---|
| `textarea` | エイリアス設定 | アプリ名=エイリアスを1行ずつ入力 |
| `textarea` | カスタムスキャンパス | ディレクトリパスを1行ずつ入力 |
| `input` | データクレンジング猶予日数 | 数値を入力 |
| `input` | 自動スキャン間隔（分） | 数値を入力 |
| `checkbox` | レジストリスキャン ON/OFF | チェックで切り替え |
| `inputWithFolderBtn` | エクスポート先 | フォルダを選択 → 次回使用時に自動実行 |
| `inputWithFileBtn` | インポートファイル | ファイルを選択 → 次回使用時に自動実行 |

**GUI の制約**: アクションボタン（押して即実行）は `SettingsTemplate.yaml` に存在しない。そのためエクスポート/インポートはファイル選択をトリガーとして使う（§4.4.5）。ピン留め・ブラックリストはコンテキストメニュー（§4.3.2）で操作する。

#### 4.4.4 スキーマのマイグレーション

`app_cache.json` の `schema_version` により、不足フィールドをデフォルト値で自動補完する（要件 4.2.3）。

#### 4.4.5 エクスポート/インポート

設定画面でフォルダ/ファイルを選択すると、次回 `query()` 実行時に自動処理される。

* **エクスポート**: `export_folder` に値あり → `{export_folder}/app_manager_backup_{timestamp}.json` を出力 → 欄をクリア → 結果アイテムで完了通知。
* **インポート**: `import_file` に値あり → JSON を読み込み `app_cache.json` にマージ → 欄をクリア → 結果アイテムで完了通知。

### 4.5 アイコン管理

**Flow Launcher の `IcoPath` に `.exe` / `.lnk` ファイルのパスを直接指定すると、Flow Launcher 本体がアイコンを自動抽出して表示する。** これにより、プラグイン側でのアイコンキャッシュ管理は不要。

| アプリ種別 | `IcoPath` に指定する値 |
|---|---|
| Win32 (`.exe`) | `exec_path` をそのまま指定。Flow Launcher が `.exe` からアイコンを自動抽出。 |
| Win32 (`.lnk`) | `.lnk` ファイルパスを指定。Flow Launcher がショートカットのアイコンを表示。 |
| UWP | パッケージマニフェストの `Square44x44Logo` から取得したロゴ画像の絶対パスを `logo_path` に保存し使用。 |
| 取得不可 | プラグイン同梱のデフォルトアイコン `Images/app.png` を使用。 |

> **これにより以下が不要になる**: `icon_provider.py` モジュール、`Pillow` ライブラリ、`icons/` キャッシュディレクトリ。アーキテクチャが大幅に簡素化される。

### 4.6 データクレンジング

```
各 AppEntry について:
  │
  ├─ 今回のスキャンで検出？
  │   ├─ YES → last_detected を更新
  │   └─ NO  → 未検出処理
  │            ├─ source="custom" かつ 外部ドライブ？
  │            │   ├─ YES → (現在 - last_detected) > stale_threshold_days？
  │            │   │   ├─ YES → 削除（アイコンも）
  │            │   │   └─ NO  → 保持（猶予）
  │            │   └─ NO → 削除（アイコンも）
```

外部ドライブ判定: `ctypes` 経由で `GetDriveType` API を使用。

---

## 5. プラグインマニフェスト（`plugin.json`）

```json
{
    "$schema": "https://www.flowlauncher.com/schemas/plugin.schema.json",
    "ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "ActionKeyword": "ap",
    "Name": "App Manager",
    "Description": "インストール済みアプリケーションを高速に検索・起動するプラグイン",
    "Author": "（開発者名）",
    "Version": "1.0.0",
    "Language": "python",
    "Website": "https://github.com/（リポジトリURL）",
    "IcoPath": "Images\\app.png",
    "ExecuteFileName": "main.py"
}
```

| フィールド | 説明 |
|---|---|
| `ID` | 32ビット UUID。プラグインの一意識別子。 |
| `ActionKeyword` | `ap` を使用。 |
| `Language` | `python` を指定。Flow Launcher が自動的にランタイムをセットアップ。 |
| `IcoPath` | プラグインフォルダからの相対パス。区切りは `\\`。 |
| `ExecuteFileName` | エントリーポイント。`.py` ファイルを指定。 |

---

## 6. Flow Launcher API リファレンス

`FlowLauncherAPI` クラスのメソッド（全て `@classmethod`、stdout に JSON-RPC を直接出力）:

```python
from flowlauncher import FlowLauncherAPI

# 使用例
FlowLauncherAPI.change_query("ap calc", requery=False)
FlowLauncherAPI.show_msg("エラー", "アプリが見つかりません", "Images/app.png")
```

| メソッド | 対応 API | パラメータ | 用途 |
|---|---|---|---|
| `change_query()` | `Flow.Launcher.ChangeQuery` | `query: str, requery: bool` | クエリ変更 |
| `shell_run()` | `Flow.Launcher.ShellRun` | `cmd: str` | シェルコマンド実行 |
| `show_msg()` | `Flow.Launcher.ShowMsg` | `title, sub_title, ico_path` | メッセージ表示 |
| `close_app()` | `Flow.Launcher.CloseApp` | — | Flow Launcher 終了 |
| `hide_app()` | `Flow.Launcher.HideApp` | — | ウィンドウ非表示 |
| `show_app()` | `Flow.Launcher.ShowApp` | — | ウィンドウ表示 |
| `open_setting_dialog()` | `Flow.Launcher.OpenSettingDialog` | — | 設定画面を開く |
| `start_loadingbar()` | `Flow.Launcher.StartLoadingBar` | — | ローディング表示 |
| `stop_loadingbar()` | `Flow.Launcher.StopLoadingBar` | — | ローディング停止 |
| `reload_plugins()` | `Flow.Launcher.ReloadPlugins` | — | プラグインリロード |

> **stdout 競合に注意**: `FlowLauncherAPI` のメソッドは stdout に JSON を出力する。`query` / `context_menu` メソッド内で呼ぶとレスポンスと混在する可能性があるため、**アクションメソッド内でのみ使用** すること。

---

## 7. パフォーマンス仕様

| 操作 | 目標時間 | 実現方針 |
|---|---|---|
| クエリ → 結果表示 | **≤ 100ms** | `app_cache.json` をファイルから読み込み、メモリで検索。 |
| プラグイン初期化 → 検索可能 | **≤ 500ms** | キャッシュファイルの読み込みのみ。 |
| フルスキャン完了 | **≤ 10s**（目安） | Shell API + レジストリ + カスタムパスの並列実行。 |

* アプリ 1,000 件以下を想定。
* `app_cache.json` のサイズが応答速度に直結するため、エントリ数が多い場合は最適化を検討。

---

## 8. エラーハンドリング

| エラー種別 | 対応 |
|---|---|
| **アクセス拒否** | スキップしてログ記録。プラグイン動作は継続。 |
| **ファイル破損** | `.bak` から復旧。不可ならデフォルト値で再作成。 |
| **起動失敗** | `FlowLauncherAPI.show_msg()` でエラー通知。 |
| **スキャンタイムアウト** | 取得済み結果でキャッシュ更新、次回再試行。 |

---

## 9. ファイル・ディレクトリ構成

```
Flow.Launcher.Plugin.AppManager/
├── plugin.json                # プラグインメタデータ（§5）
├── SettingsTemplate.yaml      # 設定画面定義（§4.4.1）
├── main.py                    # エントリーポイント（§2.5）
├── app_registry.py            # アプリ取得・キャッシュ管理
├── search_handler.py          # 検索ロジック・コマンド解析（§4.2）
├── execution_handler.py       # 実行・履歴更新
├── settings_manager.py        # 設定管理・エクスポート/インポート（§4.4）
├── models.py                  # データモデル定義
├── scanner.py                 # バックグラウンドスキャン用スクリプト
├── requirements.txt           # Python 依存パッケージ
├── lib/                       # 依存ライブラリ（pip -t で出力）
│   └── flowlauncher/          #   flowlauncher モジュール
├── plugin/                    # 内部モジュール（オプション）
├── Images/
│   ├── app.png                # プラグインアイコン（デフォルト/フォールバック用）
│   ├── open_folder.png        # コンテキストメニュー用アイコン
│   ├── pin.png                # 同上
│   └── block.png              # 同上
├── data/
│   └── app_cache.json         # アプリキャッシュ・履歴（実行時生成）
├── .github/
│   └── workflows/
│       └── Publish Release.yml
├── docs/
│   ├── Requirements.md
│   └── Specification.md
└── tests/
    ├── test_app_registry.py
    ├── test_search_handler.py
    └── test_settings_manager.py
```

---

## 10. ビルド・デプロイ

### 10.1 GitHub Actions ワークフロー

```yaml
env:
  python_ver: 3.11

steps:
  - name: Install dependencies
    run: |
      python -m pip install --upgrade pip
      pip install -r ./requirements.txt -t ./lib
      zip -r Flow.Launcher.Plugin.AppManager.zip . -x '*.git*'

  - name: Publish
    uses: softprops/action-gh-release@v1
    with:
      files: 'Flow.Launcher.Plugin.AppManager.zip'
      tag_name: "v${{steps.version.outputs.prop}}"
```

### 10.2 Plugin Store 公開

[Flow Launcher PluginsManifest](https://github.com/Flow-Launcher/Flow.Launcher.PluginsManifest) に PR を作成。

---

## 11. 制約事項・前提条件

### 11.1 動作環境

| 項目 | 条件 |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.11（Flow Launcher 同梱 Embedded Python） |
| ホストアプリ | Flow Launcher 1.x 系 |
| 通信 | JSON-RPC（`sys.argv[1]` → stdout） |
| 依存モジュール | `flowlauncher`（公式）、`comtypes` |

### 11.2 技術的制約

* **プロセスモデル**: リクエストごとにプロセスが起動されるため、メモリ上キャッシュは保持されない。`app_cache.json` の I/O が応答速度のボトルネックとなる可能性がある。
* **応答速度リスク**: Python プロセスの起動に 100〜300ms を要するため、要件 4.1.1 の「100ms 以内」はプラグイン内処理時間を指す目標値として扱う。エンドツーエンドの応答速度は Flow Launcher 本体のプロセス管理に依存する。
* **Embedded Python**: `lib/` フォルダに全依存を同梱する必要がある。コンパイル済み C 拡張を含むライブラリ（`comtypes` 等）の互換性を事前検証する。
* **`FlowLauncherAPI` の制約**: stdout 経由の通信のため、`query` / `context_menu` 内からは呼び出し不可。アクションメソッド内でのみ使用。
* **設定アクセス**: 公式 `flowlauncher` モジュールに設定読み込み機能がないため、Settings.json ファイルを直接読み込む（§4.4.2）。
* **設定画面**: `SettingsTemplate.yaml` にはボタンコントロールがない。エクスポート/インポートはファイル/フォルダ選択欄を擬似トリガーとして代用する（§4.4.5）。
* **Shell API 依存**: `shell:AppsFolder` の結果は Windows バージョンにより異なる。レジストリで補完。
* **UWP アイコン**: パッケージマニフェストのロゴパスが取得できない場合はデフォルトアイコンを使用。
* **日本語検索**: Flow Launcher のファジーサーチが日本語非対応の場合、エイリアス運用を推奨。

---

## 12. 要件トレーサビリティ

| 要件 ID | 要件概要 | 実現箇所（本仕様） |
|---|---|---|
| 3.1.1 | `ap ` 入力で起動 | §4.2.1, §5 |
| 3.1.2 | OS管理リスト + カスタムパスから取得 | §4.1.1, §4.1.2 |
| 3.1.3 | Flow Launcher 標準検索の利用 | §4.2.4 |
| 3.1.4 | 日本語・特殊文字対応 | §4.2.4, §11.2 |
| 3.1.5 | キャッシュ更新戦略 | §4.1.3 |
| 3.2.1 | 履歴優先表示 | §4.2.3 |
| 3.2.2 | ピン留め | §4.2.3, §4.2.4 |
| 3.2.3 | エイリアス優先 | §4.2.4 |
| 3.3.1 | 実行の委譲・識別 | §4.3.1 |
| 3.3.2 | 履歴の更新 | §4.3.1 |
| 3.3.3 | 標準操作の継承 | §4.3.2 |
| 3.4.1 | GUIカスタマイズ | §4.4.1, §4.4.3 |
| 3.4.2 | 設定バックアップ | §3.2.3 |
| 3.5.1 | UIレイアウト | §4.2.5 |
| 4.1.1 | 応答速度 100ms 以内 | §7 |
| 4.1.2 | 不要なディスクスキャン排除 | §4.1.3, §7 |
| 4.2.1 | データ永続化 | §3.2 |
| 4.2.2 | データクレンジング | §4.6 |
| 4.2.3 | アップデート対応 | §4.4.4 |
| 5 (制約) | Windows 10/11, Flow Launcher API 準拠 | §11 |

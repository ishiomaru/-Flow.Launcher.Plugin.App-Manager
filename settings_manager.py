"""App Manager - 設定管理

Flow Launcher の設定ファイルの読み書きとエクスポート/インポート。
仕様書 §4.4 準拠。
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# プラグイン名（Settings.json パスの構築に使用）
PLUGIN_NAME = "App Manager"


def _get_settings_path() -> Path:
    """Flow Launcher の設定ファイルパスを取得する。

    プラグインディレクトリ構造:
      {UserData}/Plugins/{PluginName}/{plugin files}
    設定ファイル:
      {UserData}/Settings/Plugins/{PluginName}/Settings.json
    """
    plugin_dir = Path(__file__).parent
    user_data = plugin_dir.parent.parent
    return user_data / "Settings" / "Plugins" / PLUGIN_NAME / "Settings.json"


def load_settings() -> dict:
    """Flow Launcher の設定ファイルを読み込む。"""
    settings_path = _get_settings_path()
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(settings: dict):
    """Flow Launcher の設定ファイルに書き込む（値のクリア用）。"""
    settings_path = _get_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def parse_alias_map(alias_text: str) -> dict:
    """エイリアス設定テキストをパースする。

    形式: 1行に1つ「アプリ名=エイリアス1,エイリアス2」

    Args:
        alias_text: textarea から取得した生テキスト。

    Returns:
        {app_name_lower: [alias1, alias2, ...]} の辞書。
    """
    result = {}
    if not alias_text:
        return result

    for line in alias_text.strip().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        app_name, _, aliases_str = line.partition("=")
        app_name = app_name.strip()
        if not app_name:
            continue
        aliases = [a.strip() for a in aliases_str.split(",") if a.strip()]
        if aliases:
            result[app_name.lower()] = aliases
    return result


def get_custom_paths(settings: dict) -> list:
    """カスタムスキャンパスのリストを取得する。"""
    custom_text = settings.get("custom_paths", "")
    if not custom_text:
        return []
    paths = []
    for line in custom_text.strip().splitlines():
        line = line.strip()
        if line and os.path.isabs(line):
            paths.append(line)
    return paths


def get_scan_interval(settings: dict) -> int:
    """自動スキャン間隔（分）を取得する。デフォルト 60。"""
    try:
        return max(0, int(settings.get("scan_interval_minutes", "60")))
    except (ValueError, TypeError):
        return 60


def get_stale_threshold_days(settings: dict) -> int:
    """データクレンジング猶予日数を取得する。デフォルト 30。"""
    try:
        return max(1, int(settings.get("stale_threshold_days", "30")))
    except (ValueError, TypeError):
        return 30


def is_registry_scan_enabled(settings: dict) -> bool:
    """レジストリスキャンが有効かどうかを判定する。"""
    val = settings.get("scan_registry", True)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return True


def get_export_folder(settings: dict) -> Optional[str]:
    """エクスポート先フォルダを取得する。未設定なら None。"""
    folder = settings.get("export_folder", "")
    return folder if folder and os.path.isabs(folder) else None


def get_import_file(settings: dict) -> Optional[str]:
    """インポートファイルパスを取得する。未設定なら None。"""
    filepath = settings.get("import_file", "")
    return filepath if filepath and os.path.isabs(filepath) else None


def do_export(cache_data: dict, settings: dict, export_folder: str) -> str:
    """設定と履歴をエクスポートする。

    Args:
        cache_data: app_cache.json の全データ。
        settings: 現在の設定。
        export_folder: 出力先フォルダ。

    Returns:
        出力ファイルのパス。
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"app_manager_backup_{timestamp}.json"
    filepath = os.path.join(export_folder, filename)

    backup_data = {
        "type": "app_manager_backup",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": {
            "alias_map": settings.get("alias_map", ""),
            "custom_paths": settings.get("custom_paths", ""),
            "stale_threshold_days": settings.get("stale_threshold_days", "30"),
            "scan_interval_minutes": settings.get("scan_interval_minutes", "60"),
            "scan_registry": settings.get("scan_registry", True),
        },
        "entries": [],
    }

    # 履歴・エイリアス・ピン留め情報のみ抽出
    for entry in cache_data.get("entries", []):
        if entry.get("last_used") or entry.get("is_pinned") or entry.get("aliases"):
            backup_data["entries"].append({
                "id": entry["id"],
                "name": entry.get("name", ""),
                "last_used": entry.get("last_used"),
                "is_pinned": entry.get("is_pinned", False),
                "aliases": entry.get("aliases", []),
                "is_blacklisted": entry.get("is_blacklisted", False),
            })

    os.makedirs(export_folder, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)

    # 設定の export_folder をクリア
    settings["export_folder"] = ""
    save_settings(settings)

    return filepath


def do_import(import_file: str, cache_data: dict, settings: dict) -> int:
    """バックアップ JSON をインポートする。

    Args:
        import_file: インポートファイルのパス。
        cache_data: 現在の app_cache.json データ。
        settings: 現在の設定。

    Returns:
        マージされたエントリ数。
    """
    with open(import_file, "r", encoding="utf-8") as f:
        backup = json.load(f)

    # 設定の復元
    if "settings" in backup:
        for key, value in backup["settings"].items():
            settings[key] = value

    # エントリのマージ
    existing = {e["id"]: e for e in cache_data.get("entries", [])}
    merged_count = 0

    for entry in backup.get("entries", []):
        entry_id = entry.get("id", "")
        if not entry_id:
            continue
        if entry_id in existing:
            # 既存エントリに履歴・設定をマージ
            existing_entry = existing[entry_id]
            if entry.get("last_used"):
                existing_entry["last_used"] = entry["last_used"]
            if entry.get("is_pinned"):
                existing_entry["is_pinned"] = True
            if entry.get("aliases"):
                existing_entry["aliases"] = entry["aliases"]
            if entry.get("is_blacklisted"):
                existing_entry["is_blacklisted"] = True
            merged_count += 1

    # 設定の import_file をクリア
    settings["import_file"] = ""
    save_settings(settings)

    return merged_count

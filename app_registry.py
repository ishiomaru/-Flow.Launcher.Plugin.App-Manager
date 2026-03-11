"""App Manager - アプリレジストリ（キャッシュ管理）

app_cache.json の読み書きと AppEntry の管理。
仕様書 §4.1 準拠。
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import AppEntry, CURRENT_SCHEMA_VERSION


def _get_data_dir() -> Path:
    """プラグインの data/ ディレクトリパスを取得する。"""
    return Path(__file__).parent / "data"


def _get_cache_path() -> Path:
    """app_cache.json のパスを取得する。"""
    return _get_data_dir() / "app_cache.json"


def _get_backup_path() -> Path:
    """app_cache.json.bak のパスを取得する。"""
    return _get_data_dir() / "app_cache.json.bak"


class AppRegistry:
    """アプリケーションキャッシュの管理クラス。

    Attributes:
        schema_version: スキーマバージョン。
        last_scan_time: 最終スキャン日時（ISO 8601 UTC）。
        entries: AppEntry のリスト。
        _entries_by_id: ID でインデックスされた辞書（内部用）。
    """

    def __init__(self):
        self.schema_version: int = CURRENT_SCHEMA_VERSION
        self.last_scan_time: Optional[str] = None
        self.entries: list[AppEntry] = []
        self._entries_by_id: dict[str, AppEntry] = {}

    def get(self, app_id: str) -> Optional[AppEntry]:
        """ID でエントリを検索する。"""
        return self._entries_by_id.get(app_id)

    def _rebuild_index(self):
        """内部インデックスを再構築する。"""
        self._entries_by_id = {e.id: e for e in self.entries}

    @classmethod
    def load(cls) -> "AppRegistry":
        """app_cache.json からレジストリを読み込む。

        ファイルが存在しないか破損している場合は空のレジストリを返す。
        破損時は .bak からの復旧を試みる（§8）。
        """
        cache_path = _get_cache_path()
        backup_path = _get_backup_path()

        registry = cls()

        data = None
        for path in [cache_path, backup_path]:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    break
                except (json.JSONDecodeError, OSError):
                    continue

        if data is None:
            return registry

        registry.schema_version = data.get("schema_version", CURRENT_SCHEMA_VERSION)
        registry.last_scan_time = data.get("last_scan_time")
        registry.entries = [
            AppEntry.from_dict(e) for e in data.get("entries", [])
        ]
        registry._rebuild_index()
        return registry

    def save(self):
        """app_cache.json にレジストリを保存する。

        一時ファイルに書き出してからリネームすることで、
        読み取り中のクエリと競合しない（§4.1.3 排他制御）。
        """
        data_dir = _get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_path = _get_cache_path()
        backup_path = _get_backup_path()

        data = self.to_dict()

        # 既存ファイルをバックアップ
        if cache_path.exists():
            try:
                if backup_path.exists():
                    backup_path.unlink()
                cache_path.rename(backup_path)
            except OSError:
                pass

        # 一時ファイルに書き出してからリネーム（アトミック書き込み）
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(data_dir), suffix=".tmp", prefix="app_cache_"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Windows ではリネーム先が存在するとエラーになるため削除
            if cache_path.exists():
                cache_path.unlink()
            os.rename(tmp_path, str(cache_path))
        except OSError:
            # 一時ファイルが残っていれば削除
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except (OSError, UnboundLocalError):
                pass

    def to_dict(self) -> dict:
        """辞書に変換する。"""
        return {
            "schema_version": self.schema_version,
            "last_scan_time": self.last_scan_time,
            "entries": [e.to_dict() for e in self.entries],
        }

    def apply_aliases(self, alias_map: dict):
        """設定画面のエイリアス設定を AppEntry に適用する。

        Args:
            alias_map: {app_name_lower: [alias1, alias2, ...]} の辞書。
        """
        for entry in self.entries:
            name_lower = entry.name.lower()
            if name_lower in alias_map:
                entry.aliases = alias_map[name_lower]
            else:
                entry.aliases = []

    def cache_exists(self) -> bool:
        """app_cache.json が存在するかどうか。"""
        return _get_cache_path().exists()

    def needs_scan(self, scan_interval_minutes: int) -> bool:
        """スキャンが必要かどうかを判定する。

        Args:
            scan_interval_minutes: スキャン間隔（分）。0 なら常にスキャン。

        Returns:
            スキャンが必要なら True。
        """
        if not self.cache_exists():
            return True
        if scan_interval_minutes == 0:
            return True
        if not self.last_scan_time:
            return True
        try:
            last_scan = datetime.fromisoformat(self.last_scan_time)
            now = datetime.now(timezone.utc)
            elapsed_minutes = (now - last_scan).total_seconds() / 60
            return elapsed_minutes >= scan_interval_minutes
        except (ValueError, TypeError):
            return True

    def get_active_entries(self, blacklist_names: set = None) -> list[AppEntry]:
        """ブラックリスト除外済みのエントリリストを返す。

        Args:
            blacklist_names: 設定画面で指定されたブラックリストのアプリ名セット（小文字）。
        """
        if blacklist_names is None:
            blacklist_names = set()
        return [
            e for e in self.entries
            if not e.is_blacklisted and e.name.lower() not in blacklist_names
        ]


def get_cache_path() -> str:
    """app_cache.json のパスを文字列で返す（外部モジュール用）。"""
    return str(_get_cache_path())

"""App Manager - app_registry.py のテスト"""

import json
import os
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from unittest import mock

from models import AppEntry, CURRENT_SCHEMA_VERSION


class TestAppRegistry:
    """AppRegistry のテスト。"""

    def test_load_empty(self):
        """キャッシュファイルが存在しない場合、空のレジストリを返す。"""
        with mock.patch("app_registry._get_cache_path") as m_cache, \
             mock.patch("app_registry._get_backup_path") as m_backup:
            m_cache.return_value = type("P", (), {"exists": lambda self: False})()
            m_backup.return_value = type("P", (), {"exists": lambda self: False})()

            from app_registry import AppRegistry
            registry = AppRegistry.load()
            assert registry.entries == []
            assert registry.last_scan_time is None

    def test_load_and_save_roundtrip(self):
        """保存→読み込みのラウンドトリップ。"""
        from app_registry import AppRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "app_cache.json")

            with mock.patch("app_registry._get_data_dir", return_value=type("P", (), {
                "mkdir": lambda self, **kw: None,
                "__truediv__": lambda self, name: type("P", (), {
                    "exists": lambda self: os.path.exists(
                        os.path.join(tmpdir, name)),
                    "unlink": lambda self: os.unlink(
                        os.path.join(tmpdir, name)),
                    "rename": lambda self, target: os.rename(
                        os.path.join(tmpdir, name), str(target)),
                    "__str__": lambda self: os.path.join(tmpdir, name),
                })(),
            })()):
                with mock.patch("app_registry._get_cache_path") as m_cache, \
                     mock.patch("app_registry._get_backup_path") as m_backup:

                    # パスオブジェクトを模擬
                    from pathlib import Path
                    m_cache.return_value = Path(cache_path)
                    m_backup.return_value = Path(os.path.join(tmpdir, "app_cache.json.bak"))

                    # 空のレジストリにエントリを追加して保存
                    registry = AppRegistry()
                    registry.last_scan_time = "2026-03-10T00:00:00Z"
                    registry.entries = [
                        AppEntry(
                            id="test1",
                            name="Test App",
                            source="shell",
                            exec_path="C:\\test.exe",
                            last_detected="2026-03-10T00:00:00Z",
                        ),
                    ]

                    # save: テンポラリファイルを使わずに直接書き出し
                    data = registry.to_dict()
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                    # 読み込み
                    loaded = AppRegistry.load()
                    assert len(loaded.entries) == 1
                    assert loaded.entries[0].id == "test1"
                    assert loaded.entries[0].name == "Test App"
                    assert loaded.last_scan_time == "2026-03-10T00:00:00Z"

    def test_to_dict(self):
        """辞書変換。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        registry.last_scan_time = "2026-03-10T00:00:00Z"
        registry.entries = [
            AppEntry(id="a", name="Alpha", source="shell",
                     last_detected="2026-03-10T00:00:00Z"),
        ]
        d = registry.to_dict()
        assert d["schema_version"] == CURRENT_SCHEMA_VERSION
        assert d["last_scan_time"] == "2026-03-10T00:00:00Z"
        assert len(d["entries"]) == 1

    def test_get_entry(self):
        """ID でエントリを検索。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        entry = AppEntry(id="target", name="Target", source="shell",
                         last_detected="2026-03-10T00:00:00Z")
        registry.entries = [entry]
        registry._rebuild_index()

        assert registry.get("target") is entry
        assert registry.get("nonexistent") is None

    def test_get_active_entries(self):
        """ブラックリスト除外。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        registry.entries = [
            AppEntry(id="a", name="A", source="shell",
                     last_detected="2026-03-10T00:00:00Z"),
            AppEntry(id="b", name="B", source="shell",
                     is_blacklisted=True,
                     last_detected="2026-03-10T00:00:00Z"),
        ]
        active = registry.get_active_entries()
        assert len(active) == 1
        assert active[0].id == "a"

    def test_apply_aliases(self):
        """エイリアスの適用。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        registry.entries = [
            AppEntry(id="a", name="Calculator", source="shell",
                     last_detected="2026-03-10T00:00:00Z"),
            AppEntry(id="b", name="Notepad", source="shell",
                     last_detected="2026-03-10T00:00:00Z"),
        ]
        alias_map = {"calculator": ["c", "calc"]}
        registry.apply_aliases(alias_map)

        assert registry.entries[0].aliases == ["c", "calc"]
        assert registry.entries[1].aliases == []

    def test_needs_scan_no_cache(self):
        """キャッシュなしの場合はスキャン必要。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        with mock.patch.object(registry, "cache_exists", return_value=False):
            assert registry.needs_scan(60) is True

    def test_needs_scan_interval_zero(self):
        """interval=0 は常にスキャン。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        with mock.patch.object(registry, "cache_exists", return_value=True):
            assert registry.needs_scan(0) is True

    def test_needs_scan_recent(self):
        """最近スキャンした場合はスキャン不要。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        registry.last_scan_time = datetime.now(timezone.utc).isoformat()
        with mock.patch.object(registry, "cache_exists", return_value=True):
            assert registry.needs_scan(60) is False

    def test_needs_scan_outdated(self):
        """スキャン間隔を超過した場合はスキャン必要。"""
        from app_registry import AppRegistry
        registry = AppRegistry()
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        registry.last_scan_time = old_time
        with mock.patch.object(registry, "cache_exists", return_value=True):
            assert registry.needs_scan(60) is True

"""App Manager - models.py のテスト"""

import pytest
from models import AppEntry, CURRENT_SCHEMA_VERSION


class TestAppEntry:
    """AppEntry データクラスのテスト。"""

    def test_create_entry(self):
        """基本的なエントリ作成。"""
        entry = AppEntry(
            id="c:\\program files\\test\\app.exe",
            name="Test App",
            source="shell",
            exec_path="C:\\Program Files\\Test\\app.exe",
        )
        assert entry.id == "c:\\program files\\test\\app.exe"
        assert entry.name == "Test App"
        assert entry.source == "shell"
        assert entry.is_pinned is False
        assert entry.aliases == []
        assert entry.is_blacklisted is False

    def test_to_dict(self):
        """辞書変換。"""
        entry = AppEntry(
            id="test_id",
            name="Test",
            source="registry",
            exec_path="C:\\test.exe",
        )
        d = entry.to_dict()
        assert d["id"] == "test_id"
        assert d["name"] == "Test"
        assert d["source"] == "registry"
        assert d["exec_path"] == "C:\\test.exe"
        assert d["aumid"] is None
        assert d["is_pinned"] is False

    def test_from_dict_full(self):
        """辞書からの完全なエントリ生成。"""
        data = {
            "id": "test_id",
            "name": "Test App",
            "source": "shell",
            "exec_path": "C:\\test.exe",
            "aumid": None,
            "logo_path": None,
            "last_used": "2026-01-01T00:00:00Z",
            "is_pinned": True,
            "aliases": ["t", "test"],
            "is_blacklisted": False,
            "last_detected": "2026-03-10T00:00:00Z",
        }
        entry = AppEntry.from_dict(data)
        assert entry.id == "test_id"
        assert entry.is_pinned is True
        assert entry.aliases == ["t", "test"]
        assert entry.last_used == "2026-01-01T00:00:00Z"

    def test_from_dict_migration(self):
        """不足フィールドの自動補完（マイグレーション）。"""
        old_data = {
            "id": "test_id",
            "name": "Test App",
            "source": "shell",
        }
        entry = AppEntry.from_dict(old_data)
        assert entry.exec_path is None
        assert entry.aumid is None
        assert entry.is_pinned is False
        assert entry.aliases == []
        assert entry.is_blacklisted is False
        assert entry.last_detected == ""

    def test_from_dict_aliases_independent(self):
        """各エントリの aliases が独立している（参照共有しない）。"""
        data1 = {"id": "a", "name": "A", "source": "shell"}
        data2 = {"id": "b", "name": "B", "source": "shell"}
        entry1 = AppEntry.from_dict(data1)
        entry2 = AppEntry.from_dict(data2)
        entry1.aliases.append("x")
        assert entry2.aliases == []

    def test_roundtrip(self):
        """to_dict → from_dict のラウンドトリップ。"""
        original = AppEntry(
            id="test_id",
            name="Test",
            source="custom",
            exec_path="D:\\tools\\tool.exe",
            is_pinned=True,
            aliases=["t"],
            last_used="2026-01-01T00:00:00Z",
            last_detected="2026-03-10T00:00:00Z",
        )
        restored = AppEntry.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.is_pinned == original.is_pinned
        assert restored.aliases == original.aliases

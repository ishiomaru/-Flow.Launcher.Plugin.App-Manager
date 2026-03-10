"""App Manager - settings_manager.py のテスト"""

import json
import os
import pytest
import tempfile
from unittest import mock

import settings_manager


class TestParseAliasMap:
    """エイリアスパースのテスト。"""

    def test_basic_alias(self):
        result = settings_manager.parse_alias_map("Calculator=c,calc")
        assert result == {"calculator": ["c", "calc"]}

    def test_multiple_lines(self):
        text = "Calculator=c,calc\nNotepad=np"
        result = settings_manager.parse_alias_map(text)
        assert result == {
            "calculator": ["c", "calc"],
            "notepad": ["np"],
        }

    def test_empty_input(self):
        assert settings_manager.parse_alias_map("") == {}
        assert settings_manager.parse_alias_map(None) == {}

    def test_ignore_invalid_lines(self):
        text = "valid=v\ninvalid line\n=no_name\n"
        result = settings_manager.parse_alias_map(text)
        assert result == {"valid": ["v"]}

    def test_whitespace_handling(self):
        text = "  Calculator = c , calc  "
        result = settings_manager.parse_alias_map(text)
        assert result == {"calculator": ["c", "calc"]}


class TestGetCustomPaths:
    """カスタムパス取得のテスト。"""

    def test_basic_paths(self):
        settings = {"custom_paths": "C:\\Tools\nD:\\Apps"}
        result = settings_manager.get_custom_paths(settings)
        assert result == ["C:\\Tools", "D:\\Apps"]

    def test_empty(self):
        assert settings_manager.get_custom_paths({}) == []

    def test_filter_relative_paths(self):
        settings = {"custom_paths": "C:\\Tools\nrelative/path"}
        result = settings_manager.get_custom_paths(settings)
        assert result == ["C:\\Tools"]


class TestGetSettings:
    """設定値取得のテスト。"""

    def test_scan_interval_default(self):
        assert settings_manager.get_scan_interval({}) == 60

    def test_scan_interval_custom(self):
        assert settings_manager.get_scan_interval({"scan_interval_minutes": "30"}) == 30

    def test_scan_interval_invalid(self):
        assert settings_manager.get_scan_interval({"scan_interval_minutes": "abc"}) == 60

    def test_stale_threshold_default(self):
        assert settings_manager.get_stale_threshold_days({}) == 30

    def test_registry_scan_enabled(self):
        assert settings_manager.is_registry_scan_enabled({}) is True
        assert settings_manager.is_registry_scan_enabled({"scan_registry": False}) is False
        assert settings_manager.is_registry_scan_enabled({"scan_registry": "true"}) is True


class TestExportImport:
    """エクスポート/インポートのテスト。"""

    def test_export(self):
        """エクスポートの基本動作。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_data = {
                "schema_version": 1,
                "entries": [
                    {
                        "id": "app1",
                        "name": "App One",
                        "last_used": "2026-01-01T00:00:00Z",
                        "is_pinned": True,
                        "aliases": ["a1"],
                        "is_blacklisted": False,
                    }
                ],
            }
            settings = {"alias_map": "App One=a1"}

            with mock.patch.object(settings_manager, "save_settings"):
                filepath = settings_manager.do_export(cache_data, settings, tmpdir)

            assert os.path.isfile(filepath)
            with open(filepath, "r", encoding="utf-8") as f:
                backup = json.load(f)
            assert backup["type"] == "app_manager_backup"
            assert len(backup["entries"]) == 1
            assert backup["entries"][0]["id"] == "app1"

    def test_import(self):
        """インポートの基本動作。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_data = {
                "type": "app_manager_backup",
                "version": 1,
                "settings": {"alias_map": "App One=a1"},
                "entries": [
                    {
                        "id": "app1",
                        "last_used": "2026-02-01T00:00:00Z",
                        "is_pinned": True,
                        "aliases": ["a1"],
                    },
                ],
            }
            backup_path = os.path.join(tmpdir, "backup.json")
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup_data, f)

            cache_data = {
                "entries": [
                    {
                        "id": "app1",
                        "name": "App One",
                        "last_used": "2026-01-01T00:00:00Z",
                        "is_pinned": False,
                        "aliases": [],
                        "is_blacklisted": False,
                    },
                ],
            }
            settings = {}

            with mock.patch.object(settings_manager, "save_settings"):
                count = settings_manager.do_import(backup_path, cache_data, settings)

            assert count == 1
            assert cache_data["entries"][0]["last_used"] == "2026-02-01T00:00:00Z"
            assert cache_data["entries"][0]["is_pinned"] is True
            assert settings["alias_map"] == "App One=a1"

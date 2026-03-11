"""App Manager - search_handler.py のテスト"""

import pytest
from models import AppEntry
from search_handler import SearchHandler


def make_entry(
    id="app1", name="App One", source="shell",
    exec_path="C:\\app1.exe", is_pinned=False,
    aliases=None, is_blacklisted=False,
    last_used=None, aumid=None, logo_path=None,
):
    return AppEntry(
        id=id, name=name, source=source,
        exec_path=exec_path, is_pinned=is_pinned,
        aliases=aliases or [], is_blacklisted=is_blacklisted,
        last_used=last_used, aumid=aumid, logo_path=logo_path,
        last_detected="2026-03-10T00:00:00Z",
    )


class TestHistoryMode:
    """履歴順表示モードのテスト（§4.2.3）。"""

    def test_empty_entries(self):
        """空のエントリリスト。"""
        results = SearchHandler.search([], "")
        assert results == []

    def test_pinned_first(self):
        """ピン留めが最上位。"""
        entries = [
            make_entry(id="a", name="Alpha", last_used="2026-01-01T00:00:00Z"),
            make_entry(id="b", name="Beta", is_pinned=True),
        ]
        results = SearchHandler.search(entries, "")
        assert results[0]["Title"] == "Beta"
        assert results[0]["Score"] == 100

    def test_history_order(self):
        """last_used 降順。"""
        entries = [
            make_entry(id="a", name="Alpha", last_used="2026-01-01T00:00:00Z"),
            make_entry(id="b", name="Beta", last_used="2026-03-01T00:00:00Z"),
        ]
        results = SearchHandler.search(entries, "")
        assert results[0]["Title"] == "Beta"
        assert results[1]["Title"] == "Alpha"

    def test_no_history_alphabetical(self):
        """last_used なしは名前昇順。"""
        entries = [
            make_entry(id="c", name="Charlie"),
            make_entry(id="a", name="Alpha"),
        ]
        results = SearchHandler.search(entries, "")
        assert results[0]["Title"] == "Alpha"
        assert results[1]["Title"] == "Charlie"

    def test_mixed_order(self):
        """ピン留め → 履歴あり → 履歴なしの順。"""
        entries = [
            make_entry(id="c", name="Charlie"),
            make_entry(id="a", name="Alpha", last_used="2026-01-01T00:00:00Z"),
            make_entry(id="b", name="Beta", is_pinned=True),
        ]
        results = SearchHandler.search(entries, "")
        titles = [r["Title"] for r in results]
        assert titles == ["Beta", "Alpha", "Charlie"]


class TestSearchMode:
    """アプリ検索モードのテスト（§4.2.4）。"""

    def test_alias_exact_match_score_100(self):
        """エイリアス完全一致で Score 100。"""
        entries = [make_entry(id="calc", name="Calculator")]
        alias_map = {"calculator": ["c", "calc"]}
        results = SearchHandler.search(entries, "c", alias_map)

        # エイリアス完全一致のアイテムがある
        exact_matches = [r for r in results if r["Score"] == 100]
        assert len(exact_matches) == 1
        assert exact_matches[0]["Title"] == "c"

    def test_pinned_bonus(self):
        """ピン留めアプリのボーナススコア。"""
        entries = [
            make_entry(id="a", name="Alpha", is_pinned=True),
            make_entry(id="b", name="Beta"),
        ]
        results = SearchHandler.search(entries, "a")
        alpha_results = [r for r in results if r["ContextData"] == ["a"]]
        beta_results = [r for r in results if r["ContextData"] == ["b"]]
        assert alpha_results[0]["Score"] > beta_results[0]["Score"]

    def test_all_entries_returned_for_fuzzy_search(self):
        """全エントリが結果に含まれる（Flow Launcher のファジーサーチに委譲）。"""
        entries = [
            make_entry(id="a", name="Alpha"),
            make_entry(id="b", name="Beta"),
        ]
        results = SearchHandler.search(entries, "xyz")
        # 少なくとも元のエントリ分は返される
        assert len(results) >= 2


class TestResultBuilding:
    """結果アイテム構築のテスト（§4.2.5）。"""

    def test_win32_icon_path(self):
        """Win32 アプリは exec_path を IcoPath に使用。"""
        entries = [make_entry(exec_path="C:\\app.exe")]
        results = SearchHandler.search(entries, "")
        assert results[0]["IcoPath"] == "C:\\app.exe"

    def test_uwp_icon_path(self):
        """UWP アプリは logo_path を IcoPath に使用。"""
        entries = [make_entry(
            exec_path=None, aumid="pkg!App",
            logo_path="C:\\logos\\app.png"
        )]
        results = SearchHandler.search(entries, "")
        assert results[0]["IcoPath"] == "C:\\logos\\app.png"

    def test_default_icon_fallback(self):
        """パスなしの場合はデフォルトアイコン。"""
        entries = [make_entry(exec_path=None, aumid=None, logo_path=None)]
        results = SearchHandler.search(entries, "")
        assert results[0]["IcoPath"] == "Images/app.png"

    def test_context_data(self):
        """ContextData に app_id が含まれる。"""
        entries = [make_entry(id="my_app")]
        results = SearchHandler.search(entries, "")
        assert results[0]["ContextData"] == ["my_app"]

    def test_json_rpc_action(self):
        """JsonRPCAction が正しく構築される。"""
        entries = [make_entry(id="my_app")]
        results = SearchHandler.search(entries, "")
        action = results[0]["JsonRPCAction"]
        assert action["method"] == "execute"
        assert action["parameters"] == ["my_app"]
        assert action["dontHideAfterAction"] is False

    def test_auto_complete_text(self):
        """AutoCompleteText が正しく設定される。"""
        entries = [make_entry(id="my_app", name="My App")]
        results = SearchHandler.search(entries, "")
        assert results[0]["AutoCompleteText"] == "ap My App"

    def test_auto_complete_text_with_alias(self):
        """エイリアスタイトルの場合も AutoCompleteText が正しく設定される。"""
        entries = [make_entry(id="calc", name="Calculator")]
        alias_map = {"calculator": ["c"]}
        results = SearchHandler.search(entries, "c", alias_map)
        # エイリアス完全一致の結果
        exact = [r for r in results if r["Score"] == 100]
        assert len(exact) == 1
        assert exact[0]["AutoCompleteText"] == "ap c"

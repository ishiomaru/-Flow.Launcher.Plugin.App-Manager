"""App Manager - エントリーポイント

FlowLauncher クラスを継承し、JSON-RPC メソッドを実装する。
仕様書 §2.5 準拠。
"""

import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# プラグインディレクトリのパスを設定
plugindir = Path.absolute(Path(__file__).parent)
paths = (".", "lib", "plugin")
sys.path = [str(plugindir / p) for p in paths] + sys.path

from flowlauncher import FlowLauncher, FlowLauncherAPI

from app_registry import AppRegistry, get_cache_path
from search_handler import SearchHandler
from execution_handler import ExecutionHandler
import settings_manager


class AppManager(FlowLauncher):
    """App Manager プラグインのメインクラス。"""

    def query(self, query: str = '') -> list:
        """検索結果を返却する。

        戻り値は自動的に stdout へ出力される。
        """
        # 設定の読み込み
        settings = settings_manager.load_settings()

        # レジストリを読み込み
        registry = AppRegistry.load()

        # --- エクスポート/インポートのチェック（§4.4.5）---
        notification = self._check_export_import(registry, settings)
        if notification:
            return notification

        # --- 自動スキャン判定（§4.1.3）---
        scan_interval = settings_manager.get_scan_interval(settings)
        if not registry.cache_exists():
            # 初回: 同期スキャンを実行してから応答
            self._run_scan_sync(settings)
            registry = AppRegistry.load()
        elif registry.needs_scan(scan_interval):
            # バックグラウンドスキャンを起動
            self._run_scan_async(settings)

        # --- エイリアスの適用 ---
        alias_text = settings.get("alias_map", "")
        alias_map = settings_manager.parse_alias_map(alias_text)
        registry.apply_aliases(alias_map)

        # --- 検索実行 ---
        active_entries = registry.get_active_entries()
        results = SearchHandler.search(active_entries, query, alias_map)

        return results

    def context_menu(self, data) -> list:
        """右クリックメニュー（§4.3.2）。

        戻り値は自動的に stdout へ出力される。
        """
        app_id = data[0]
        registry = AppRegistry.load()
        entry = registry.get(app_id)

        if entry is None:
            return []

        pin_title = "ピン解除" if entry.is_pinned else "ピン留め"

        menu = [
            {
                "Title": pin_title,
                "SubTitle": "検索結果の最上位に固定します",
                "IcoPath": "Images/pin.png",
                "JsonRPCAction": {
                    "method": "toggle_pin",
                    "parameters": [app_id],
                },
            },
            {
                "Title": "ブラックリストに追加",
                "SubTitle": "検索結果から非表示にします",
                "IcoPath": "Images/block.png",
                "JsonRPCAction": {
                    "method": "add_to_blacklist",
                    "parameters": [app_id],
                },
            },
        ]

        # ファイルの場所を開く（exec_path がある場合のみ）
        if entry.exec_path:
            menu.insert(0, {
                "Title": "ファイルの場所を開く",
                "SubTitle": "エクスプローラーで開きます",
                "IcoPath": "Images/open_folder.png",
                "JsonRPCAction": {
                    "method": "open_location",
                    "parameters": [app_id],
                },
            })

        return menu

    def execute(self, app_id: str):
        """アプリ起動（§4.3.1）。"""
        try:
            ExecutionHandler.execute(app_id)
        except Exception as e:
            FlowLauncherAPI.show_msg(
                "起動エラー",
                str(e),
                "Images/app.png",
            )

    def open_location(self, app_id: str):
        """ファイルの場所をエクスプローラーで開く。"""
        ExecutionHandler.open_location(app_id)

    def toggle_pin(self, app_id: str):
        """ピン留め状態をトグル。"""
        ExecutionHandler.toggle_pin(app_id)

    def add_to_blacklist(self, app_id: str):
        """ブラックリストに追加。"""
        ExecutionHandler.add_to_blacklist(app_id)

    def _check_export_import(self, registry: AppRegistry, settings: dict) -> list | None:
        """エクスポート/インポートの自動処理をチェックする。

        Returns:
            通知結果リスト、または None（処理なし）。
        """
        # エクスポート
        export_folder = settings_manager.get_export_folder(settings)
        if export_folder:
            try:
                filepath = settings_manager.do_export(
                    registry.to_dict(), settings, export_folder
                )
                return [SearchHandler.build_notification(
                    "✅ エクスポート完了",
                    f"保存先: {filepath}",
                )]
            except Exception as e:
                return [SearchHandler.build_notification(
                    "❌ エクスポートエラー",
                    str(e),
                )]

        # インポート
        import_file = settings_manager.get_import_file(settings)
        if import_file:
            try:
                cache_data = registry.to_dict()
                count = settings_manager.do_import(import_file, cache_data, settings)
                # マージ結果を保存
                registry.entries = [
                    __import__("models").AppEntry.from_dict(e)
                    for e in cache_data.get("entries", [])
                ]
                registry.save()
                return [SearchHandler.build_notification(
                    "✅ インポート完了",
                    f"{count} 件の設定をマージしました",
                )]
            except Exception as e:
                return [SearchHandler.build_notification(
                    "❌ インポートエラー",
                    str(e),
                )]

        return None

    def _run_scan_sync(self, settings: dict):
        """同期スキャンを実行する（初回用）。"""
        self._do_scan(settings, wait=True)

    def _run_scan_async(self, settings: dict):
        """バックグラウンドスキャンを起動する。"""
        self._do_scan(settings, wait=False)

    def _do_scan(self, settings: dict, wait: bool = False):
        """scanner.py をサブプロセスで実行する。

        Args:
            settings: 現在の設定。
            wait: True なら同期実行（完了を待つ）。
        """
        scanner_path = str(plugindir / "scanner.py")
        cache_path = get_cache_path()
        custom_paths = settings_manager.get_custom_paths(settings)
        scan_registry_flag = settings_manager.is_registry_scan_enabled(settings)
        stale_days = settings_manager.get_stale_threshold_days(settings)

        cmd = [
            sys.executable, scanner_path,
            "--cache-path", cache_path,
            "--stale-threshold-days", str(stale_days),
        ]

        if custom_paths:
            cmd.extend(["--custom-paths", ";".join(custom_paths)])

        if scan_registry_flag:
            cmd.append("--scan-registry")

        try:
            if wait:
                subprocess.run(
                    cmd,
                    timeout=30,
                    capture_output=True,
                )
            else:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass


if __name__ == "__main__":
    AppManager()

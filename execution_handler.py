"""App Manager - 実行ハンドラ

アプリ起動と履歴更新。
仕様書 §4.3 準拠。
"""

import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app_registry import AppRegistry


class ExecutionHandler:
    """アプリの起動と履歴更新を担当するハンドラ。"""

    @staticmethod
    def execute(app_id: str):
        """アプリを起動し履歴を更新する（§4.3.1）。

        Args:
            app_id: アプリケーションの一意識別子。

        Raises:
            ValueError: app_id に対応するエントリが見つからない場合。
            OSError: アプリの起動に失敗した場合。
        """
        registry = AppRegistry.load()
        entry = registry.get(app_id)

        if entry is None:
            raise ValueError(f"アプリが見つかりません: {app_id}")

        # アプリの起動
        if entry.exec_path:
            # Win32: os.startfile() で起動
            os.startfile(entry.exec_path)
        elif entry.aumid:
            # UWP: explorer.exe 経由で起動
            subprocess.Popen(
                f'explorer.exe shell:AppsFolder\\{entry.aumid}',
                shell=False,
            )
        else:
            raise ValueError(f"起動方法が不明です: {app_id}")

        # 履歴更新
        entry.last_used = datetime.now(timezone.utc).isoformat()
        registry.save()

    @staticmethod
    def open_location(app_id: str):
        """アプリのファイルの場所をエクスプローラーで開く。

        Args:
            app_id: アプリケーションの一意識別子。
        """
        registry = AppRegistry.load()
        entry = registry.get(app_id)

        if entry is None or not entry.exec_path:
            return

        folder = str(Path(entry.exec_path).parent)
        subprocess.Popen(f'explorer.exe "{folder}"')

    @staticmethod
    def toggle_pin(app_id: str):
        """ピン留め状態をトグルする。

        Args:
            app_id: アプリケーションの一意識別子。
        """
        print(f"[AppManager] toggle_pin called: {app_id}", file=sys.stderr)
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        if entry is not None:
            entry.is_pinned = not entry.is_pinned
            registry.save()
            print(f"[AppManager] toggle_pin done: is_pinned={entry.is_pinned}", file=sys.stderr)
        else:
            print(f"[AppManager] toggle_pin: entry not found for {app_id}", file=sys.stderr)

    @staticmethod
    def add_to_blacklist(app_id: str):
        """アプリをブラックリストに追加する。

        Args:
            app_id: アプリケーションの一意識別子。
        """
        print(f"[AppManager] add_to_blacklist called: {app_id}", file=sys.stderr)
        registry = AppRegistry.load()
        entry = registry.get(app_id)
        if entry is not None:
            entry.is_blacklisted = True
            registry.save()
            print(f"[AppManager] add_to_blacklist done: {entry.name}", file=sys.stderr)
        else:
            print(f"[AppManager] add_to_blacklist: entry not found for {app_id}", file=sys.stderr)

"""App Manager - データモデル定義

AppEntry データクラスと関連ユーティリティ。
仕様書 §3.1 準拠。
"""

from dataclasses import dataclass, field, asdict
from typing import Optional

# 現在のスキーマバージョン
CURRENT_SCHEMA_VERSION = 1

# AppEntry のデフォルト値（マイグレーション補完用）
_ENTRY_DEFAULTS = {
    "id": "",
    "name": "",
    "source": "shell",
    "exec_path": None,
    "aumid": None,
    "logo_path": None,
    "last_used": None,
    "is_pinned": False,
    "aliases": [],
    "is_blacklisted": False,
    "last_detected": "",
}


@dataclass
class AppEntry:
    """アプリケーションエントリ（§3.1）。

    Attributes:
        id: 一意識別子。Win32 は正規化済みパス、UWP は AUMID。
        name: OS から取得したアプリケーション表示名。
        source: 取得元（"shell", "registry", "custom"）。
        exec_path: Win32 アプリの実行パス。UWP は None。
        aumid: UWP アプリの AppUserModelId。Win32 は None。
        logo_path: UWP アプリのロゴ画像パス。Win32 は None。
        last_used: 最終使用日時（ISO 8601 UTC）。未使用は None。
        is_pinned: ピン留め状態。
        aliases: ユーザー定義エイリアスのリスト。
        is_blacklisted: ブラックリスト状態。
        last_detected: 最後にスキャンで検出された日時（ISO 8601 UTC）。
    """

    id: str
    name: str
    source: str = "shell"
    exec_path: Optional[str] = None
    aumid: Optional[str] = None
    logo_path: Optional[str] = None
    last_used: Optional[str] = None
    is_pinned: bool = False
    aliases: list = field(default_factory=list)
    is_blacklisted: bool = False
    last_detected: str = ""

    def to_dict(self) -> dict:
        """辞書に変換する。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppEntry":
        """辞書から AppEntry を生成する。

        不足フィールドはデフォルト値で補完する（§4.4.4 マイグレーション対応）。
        """
        merged = {}
        for key, default_val in _ENTRY_DEFAULTS.items():
            if key in data:
                merged[key] = data[key]
            else:
                # リストのデフォルト値はコピーして参照共有を防ぐ
                merged[key] = list(default_val) if isinstance(default_val, list) else default_val
        return cls(**merged)

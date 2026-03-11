"""App Manager - 検索ハンドラ

クエリ解析・検索結果構築・ランキング。
仕様書 §4.2 準拠。
"""

from models import AppEntry

# デフォルトアイコンパス
DEFAULT_ICON = "Images/app.png"

# ピン留めボーナススコア
PIN_BONUS = 50


class SearchHandler:
    """検索結果を構築するハンドラ。"""

    @staticmethod
    def search(
        entries: list[AppEntry],
        query: str,
        alias_map: dict = None,
    ) -> list[dict]:
        """検索クエリに基づいて結果リストを返す。

        Args:
            entries: ブラックリスト除外済みの AppEntry リスト。
            query: ユーザー入力のクエリ文字列。
            alias_map: {app_name_lower: [alias1, ...]} の辞書。

        Returns:
            PascalCase キーの結果辞書リスト。
        """
        if alias_map is None:
            alias_map = {}

        if not query.strip():
            return SearchHandler._history_mode(entries)
        else:
            return SearchHandler._search_mode(entries, query.strip(), alias_map)

    @staticmethod
    def _history_mode(entries: list[AppEntry]) -> list[dict]:
        """履歴順表示モード（§4.2.3）。

        1. ピン留め済みを最上位に配置（Score を高く設定）
        2. 残りを last_used 降順
        3. last_used が None のものは末尾にアプリ名昇順
        """
        pinned = []
        with_history = []
        no_history = []

        for entry in entries:
            if entry.is_pinned:
                pinned.append(entry)
            elif entry.last_used:
                with_history.append(entry)
            else:
                no_history.append(entry)

        # ピン留め: 登録順（Score で最上位に配置）
        # last_used あり: 降順
        with_history.sort(key=lambda e: e.last_used or "", reverse=True)
        # last_used なし: 名前昇順
        no_history.sort(key=lambda e: e.name.lower())

        results = []
        # ピン留めアイテム: 高い Score で最上位に配置
        for i, entry in enumerate(pinned):
            score = 100 - i  # 登録順で少しずつスコアを下げる
            results.append(SearchHandler._build_result(entry, score=score))

        # 履歴あり: ピン留めの次に表示
        for entry in with_history:
            results.append(SearchHandler._build_result(entry, score=0))

        # 履歴なし: 末尾
        for entry in no_history:
            results.append(SearchHandler._build_result(entry, score=0))

        return results

    @staticmethod
    def _search_mode(
        entries: list[AppEntry],
        query: str,
        alias_map: dict,
    ) -> list[dict]:
        """アプリ検索モード（§4.2.4）。

        1. エイリアスとアプリ名を候補文字列として結果を生成
        2. エイリアス完全一致: Score 100
        3. ピン留め: Score にボーナス加算
        4. Flow Launcher 本体のファジーサーチに委譲  
        """
        results = []
        query_lower = query.lower()

        for entry in entries:
            # エイリアスの取得（設定画面の alias_map を優先）
            aliases = alias_map.get(entry.name.lower(), entry.aliases)

            # エイリアス完全一致チェック
            alias_exact_match = None
            for alias in aliases:
                if alias.lower() == query_lower:
                    alias_exact_match = alias
                    break

            if alias_exact_match:
                # エイリアス完全一致: Score 100
                score = 100
                result = SearchHandler._build_result(
                    entry, score=score, title=alias_exact_match
                )
                results.append(result)
            else:
                # 各候補文字列で結果を生成し、Flow Launcher のファジーサーチに委譲
                score = PIN_BONUS if entry.is_pinned else 0

                # アプリ名で結果を生成
                results.append(SearchHandler._build_result(entry, score=score))

                # エイリアスでも結果を生成（Title をエイリアスに設定）
                for alias in aliases:
                    results.append(
                        SearchHandler._build_result(
                            entry, score=score, title=alias
                        )
                    )

        return results

    @staticmethod
    def _build_result(
        entry: AppEntry,
        score: int = 0,
        title: str = None,
    ) -> dict:
        """結果アイテムを構築する（§4.2.5）。

        Args:
            entry: AppEntry オブジェクト。
            score: スコア値（0-100）。
            title: 表示タイトル。None の場合はアプリ名を使用。

        Returns:
            PascalCase キーの辞書。
        """
        display_title = title or entry.name
        subtitle = entry.exec_path or entry.aumid or ""

        # IcoPath の決定
        if entry.exec_path:
            # Win32: exec_path をそのまま指定（Flow Launcher が自動抽出）
            ico_path = entry.exec_path
        elif entry.logo_path:
            # UWP: logo_path を使用
            ico_path = entry.logo_path
        else:
            # デフォルトアイコン
            ico_path = DEFAULT_ICON

        return {
            "Title": display_title,
            "SubTitle": subtitle,
            "IcoPath": ico_path,
            "Score": score,
            "AutoCompleteText": f"ap {display_title}",
            "ContextData": [entry.id],
            "JsonRPCAction": {
                "method": "execute",
                "parameters": [entry.id],
                "dontHideAfterAction": False,
            },
        }

    @staticmethod
    def build_notification(title: str, subtitle: str, icon: str = DEFAULT_ICON) -> dict:
        """通知用の結果アイテムを構築する。

        エクスポート/インポート完了通知等に使用。

        Args:
            title: 通知タイトル。
            subtitle: 通知サブタイトル。
            icon: アイコンパス。

        Returns:
            PascalCase キーの辞書。
        """
        return {
            "Title": title,
            "SubTitle": subtitle,
            "IcoPath": icon,
            "Score": 100,
        }

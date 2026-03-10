"""App Manager - バックグラウンドスキャナー

アプリケーション一覧を取得し app_cache.json に保存する独立スクリプト。
main.py から subprocess で起動される。
仕様書 §4.1 準拠。

使用方法:
    python scanner.py [--cache-path PATH] [--custom-paths PATH1;PATH2]
                      [--scan-registry] [--stale-threshold-days N]
"""

import argparse
import ctypes
import json
import logging
import os
import sys
import tempfile
import winreg
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Shell API の定数
SIGDN_FILESYSPATH = 0x80058000  # SIGDN_FILESYSPATH
SIGDN_NORMALDISPLAY = 0x00000000  # SIGDN_NORMALDISPLAY

# GetDriveType の定数
DRIVE_REMOVABLE = 2
DRIVE_REMOTE = 4


def is_external_drive(path: str) -> bool:
    """パスが外部ドライブ（リムーバブル/ネットワーク）上にあるかを判定する。"""
    try:
        drive = os.path.splitdrive(path)[0]
        if not drive:
            return False
        drive_root = drive + "\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_root)
        return drive_type in (DRIVE_REMOVABLE, DRIVE_REMOTE)
    except Exception:
        return False


def scan_shell_apps() -> list:
    """Shell API (shell:AppsFolder) 経由でアプリを列挙する。

    comtypes を使って IShellFolder2 COM インターフェースにアクセスする。

    Returns:
        AppEntry 相当の辞書のリスト。
    """
    entries = []
    try:
        import comtypes
        from comtypes import GUID
        import comtypes.client

        # CLSID_ShellDesktop と IID_IShellFolder
        CLSID_ShellDesktop = GUID("{00021400-0000-0000-C000-000000000046}")

        # shell:AppsFolder の GUID
        FOLDERID_AppsFolder = GUID("{1e87508d-89c2-42f0-8a7e-645a0f50ca58}")

        # SHGetKnownFolderIDList を使用
        shell32 = ctypes.windll.shell32
        pidl = ctypes.c_void_p()
        hr = shell32.SHGetKnownFolderIDList(
            ctypes.byref(FOLDERID_AppsFolder), 0, None, ctypes.byref(pidl)
        )
        if hr != 0:
            logger.warning("SHGetKnownFolderIDList failed: 0x%08x", hr)
            return entries

        # IShellFolder を取得
        desktop_folder = ctypes.POINTER(ctypes.c_void_p)()
        hr = shell32.SHGetDesktopFolder(ctypes.byref(desktop_folder))
        if hr != 0:
            logger.warning("SHGetDesktopFolder failed")
            return entries

        # shell:AppsFolder を explorer 経由で列挙する代替手法
        # comtypes の高レベル API を使用
        try:
            shell = comtypes.client.CreateObject(
                "Shell.Application", interface=None
            )
            folder = shell.NameSpace("shell:AppsFolder")
            if folder is None:
                logger.warning("shell:AppsFolder を開けませんでした")
                return entries

            items = folder.Items()
            for i in range(items.Count):
                try:
                    item = items.Item(i)
                    name = item.Name
                    path = item.Path  # AUMID or path

                    if not name:
                        continue

                    entry = {
                        "name": name,
                        "source": "shell",
                        "exec_path": None,
                        "aumid": None,
                        "logo_path": None,
                    }

                    # パスが .exe / .lnk ならWin32、それ以外はUWP (AUMID)
                    if path and (path.lower().endswith(".exe") or
                                path.lower().endswith(".lnk") or
                                path.lower().endswith(".appref-ms")):
                        normalized = os.path.normcase(path)
                        entry["id"] = normalized
                        entry["exec_path"] = path
                    elif path and "!" in path:
                        # AUMID 形式 (PackageFamilyName!AppId)
                        entry["id"] = path
                        entry["aumid"] = path
                        entry["logo_path"] = _get_uwp_logo(path)
                    else:
                        # 不明な形式はスキップ
                        if path:
                            entry["id"] = path
                        else:
                            continue

                    entries.append(entry)
                except Exception as e:
                    logger.debug("Shell item enumeration error: %s", e)
                    continue

        except Exception as e:
            logger.warning("Shell.Application COM error: %s", e)

    except ImportError:
        logger.warning("comtypes が見つかりません。Shell API スキャンをスキップします。")
    except Exception as e:
        logger.error("Shell API scan error: %s", e)

    logger.info("Shell API: %d 件取得", len(entries))
    return entries


def _get_uwp_logo(aumid: str) -> str | None:
    """UWP アプリのロゴパスをパッケージマニフェストから取得する。

    Args:
        aumid: AppUserModelId (PackageFamilyName!AppId)

    Returns:
        ロゴ画像の絶対パス、または None。
    """
    try:
        package_family = aumid.split("!")[0]
        packages_dir = Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "WindowsApps"

        # パッケージフォルダを検索
        if not packages_dir.exists():
            return None

        matching_dirs = []
        try:
            for d in packages_dir.iterdir():
                if d.is_dir() and d.name.startswith(package_family.split("_")[0]):
                    matching_dirs.append(d)
        except PermissionError:
            return None

        for pkg_dir in matching_dirs:
            manifest_path = pkg_dir / "AppxManifest.xml"
            if manifest_path.exists():
                try:
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(str(manifest_path))
                    root = tree.getroot()

                    # 名前空間を処理
                    ns = {"default": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}
                    # Square44x44Logo を検索
                    for logo_elem in root.iter():
                        if "Square44x44Logo" in logo_elem.tag:
                            logo_rel = logo_elem.get("Logo") or logo_elem.text
                            if logo_rel:
                                logo_path = pkg_dir / logo_rel
                                # .scale-* バリアントを検索
                                logo_stem = logo_path.stem
                                logo_parent = logo_path.parent
                                if logo_parent.exists():
                                    for f in logo_parent.iterdir():
                                        if f.stem.startswith(logo_stem) and f.suffix in (".png", ".jpg"):
                                            return str(f)
                                if logo_path.exists():
                                    return str(logo_path)

                    # Application の VisualElements を検索
                    for app_elem in root.iter():
                        tag = app_elem.tag.split("}")[-1] if "}" in app_elem.tag else app_elem.tag
                        if tag == "VisualElements" or tag == "DefaultTile":
                            logo = app_elem.get("Square44x44Logo")
                            if logo:
                                logo_path = pkg_dir / logo
                                logo_stem = logo_path.stem
                                logo_parent = logo_path.parent
                                if logo_parent.exists():
                                    for f in logo_parent.iterdir():
                                        if f.stem.startswith(logo_stem) and f.suffix in (".png", ".jpg"):
                                            return str(f)
                                if logo_path.exists():
                                    return str(logo_path)
                except Exception:
                    continue

    except Exception:
        pass
    return None


def scan_registry() -> list:
    """レジストリからアプリ情報を取得する。

    HKLM/HKCU の Uninstall キーを走査。

    Returns:
        AppEntry 相当の辞書のリスト。
    """
    entries = []
    uninstall_paths = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hkey, path in uninstall_paths:
        try:
            with winreg.OpenKey(hkey, path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            name = _reg_value(subkey, "DisplayName")
                            if not name:
                                continue

                            # システムコンポーネントはスキップ
                            sys_component = _reg_value(subkey, "SystemComponent")
                            if sys_component == 1:
                                continue

                            # 表示アイコンからパスを推定
                            display_icon = _reg_value(subkey, "DisplayIcon")
                            install_location = _reg_value(subkey, "InstallLocation")

                            exec_path = None
                            if display_icon:
                                # "path,0" 形式のアイコンパスから実行パスを取得
                                icon_path = display_icon.split(",")[0].strip().strip('"')
                                if icon_path.lower().endswith(".exe") and os.path.isfile(icon_path):
                                    exec_path = icon_path
                            if not exec_path and install_location:
                                # InstallLocation 内の .exe を検索
                                if os.path.isdir(install_location):
                                    for f in os.listdir(install_location):
                                        if f.lower().endswith(".exe"):
                                            candidate = os.path.join(install_location, f)
                                            if os.path.isfile(candidate):
                                                exec_path = candidate
                                                break

                            if exec_path:
                                normalized = os.path.normcase(exec_path)
                                entries.append({
                                    "id": normalized,
                                    "name": name,
                                    "source": "registry",
                                    "exec_path": exec_path,
                                    "aumid": None,
                                    "logo_path": None,
                                })
                    except OSError:
                        continue
        except OSError:
            continue

    logger.info("レジストリ: %d 件取得", len(entries))
    return entries


def _reg_value(key, name: str):
    """レジストリ値を安全に取得する。"""
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return value
    except OSError:
        return None


def scan_custom_paths(paths: list) -> list:
    """カスタムパスからアプリを取得する。

    指定ディレクトリを再帰走査し .exe / .lnk / .appref-ms を収集。

    Args:
        paths: スキャン対象ディレクトリのリスト。

    Returns:
        AppEntry 相当の辞書のリスト。
    """
    entries = []
    target_extensions = {".exe", ".lnk", ".appref-ms"}

    for base_path in paths:
        if not os.path.isdir(base_path):
            logger.warning("カスタムパスが見つかりません: %s", base_path)
            continue
        try:
            for root, _, files in os.walk(base_path):
                for filename in files:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in target_extensions:
                        filepath = os.path.join(root, filename)
                        normalized = os.path.normcase(filepath)
                        name = os.path.splitext(filename)[0]
                        entries.append({
                            "id": normalized,
                            "name": name,
                            "source": "custom",
                            "exec_path": filepath,
                            "aumid": None,
                            "logo_path": None,
                        })
        except PermissionError:
            logger.warning("アクセス拒否: %s", base_path)
        except Exception as e:
            logger.error("カスタムパス走査エラー: %s - %s", base_path, e)

    logger.info("カスタムパス: %d 件取得", len(entries))
    return entries


def merge_entries(
    existing_data: dict,
    new_entries: list,
    stale_threshold_days: int
) -> dict:
    """新しいスキャン結果を既存データにマージする。

    Args:
        existing_data: 既存の app_cache.json データ。
        new_entries: スキャンで取得した新しいエントリのリスト。
        stale_threshold_days: データクレンジング猶予日数。

    Returns:
        マージ後の app_cache.json データ。
    """
    now = datetime.now(timezone.utc).isoformat()
    existing_by_id = {}
    for e in existing_data.get("entries", []):
        existing_by_id[e["id"]] = e

    # ソース優先度
    source_priority = {"shell": 3, "registry": 2, "custom": 1}

    # 新しいエントリを処理
    new_ids = set()
    for entry in new_entries:
        entry_id = entry["id"]
        new_ids.add(entry_id)
        entry["last_detected"] = now

        if entry_id in existing_by_id:
            # 既存エントリとマージ: ユーザーデータを保持
            existing = existing_by_id[entry_id]
            new_source_pri = source_priority.get(entry.get("source", ""), 0)
            existing_source_pri = source_priority.get(existing.get("source", ""), 0)

            if new_source_pri >= existing_source_pri:
                # 新しいソースが優先 → name, source, exec_path 等を更新
                existing["name"] = entry["name"]
                existing["source"] = entry["source"]
                existing["exec_path"] = entry.get("exec_path")
                existing["aumid"] = entry.get("aumid")
                existing["logo_path"] = entry.get("logo_path")

            existing["last_detected"] = now
        else:
            # 新規エントリ
            entry.setdefault("last_used", None)
            entry.setdefault("is_pinned", False)
            entry.setdefault("aliases", [])
            entry.setdefault("is_blacklisted", False)
            existing_by_id[entry_id] = entry

    # データクレンジング（§4.6）
    entries_to_keep = []
    for entry_id, entry in existing_by_id.items():
        if entry_id in new_ids:
            entries_to_keep.append(entry)
        else:
            # 未検出のエントリ
            source = entry.get("source", "")
            if source == "custom" and entry.get("exec_path") and is_external_drive(entry["exec_path"]):
                # 外部ドライブのカスタムパスアプリ → 猶予期間チェック
                last_detected = entry.get("last_detected", "")
                if last_detected:
                    try:
                        detected_time = datetime.fromisoformat(last_detected)
                        days_elapsed = (datetime.now(timezone.utc) - detected_time).days
                        if days_elapsed <= stale_threshold_days:
                            entries_to_keep.append(entry)
                            continue
                    except (ValueError, TypeError):
                        pass
                # 猶予期間超過 → 削除
                logger.info("古いエントリを削除: %s", entry.get("name", entry_id))
            else:
                # 外部ドライブ以外 → 即削除
                logger.info("未検出エントリを削除: %s", entry.get("name", entry_id))

    return {
        "schema_version": existing_data.get("schema_version", 1),
        "last_scan_time": now,
        "entries": entries_to_keep,
    }


def run_scan(
    cache_path: str,
    custom_paths: list,
    scan_registry_flag: bool = True,
    stale_threshold_days: int = 30,
):
    """フルスキャンを実行して app_cache.json を更新する。

    Args:
        cache_path: app_cache.json のパス。
        custom_paths: カスタムスキャンパスのリスト。
        scan_registry_flag: レジストリスキャンを行うか。
        stale_threshold_days: データクレンジング猶予日数。
    """
    logger.info("スキャン開始")

    # 既存データの読み込み
    existing_data = {"schema_version": 1, "last_scan_time": None, "entries": []}
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("既存キャッシュの読み込みに失敗。新規作成します。")

    # 各ソースからアプリを取得
    all_entries = []

    # Shell API
    shell_entries = scan_shell_apps()
    all_entries.extend(shell_entries)

    # レジストリ
    if scan_registry_flag:
        reg_entries = scan_registry()
        all_entries.extend(reg_entries)

    # カスタムパス
    if custom_paths:
        custom_entries = scan_custom_paths(custom_paths)
        all_entries.extend(custom_entries)

    # マージ
    merged_data = merge_entries(existing_data, all_entries, stale_threshold_days)

    # 一時ファイルに書き出してからリネーム
    cache_dir = os.path.dirname(cache_path)
    os.makedirs(cache_dir, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=cache_dir, suffix=".tmp", prefix="scan_"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)

        # Windows ではリネーム先が存在するとエラーになるため削除
        if os.path.exists(cache_path):
            os.unlink(cache_path)
        os.rename(tmp_path, cache_path)
        logger.info("スキャン完了: %d 件", len(merged_data["entries"]))
    except OSError as e:
        logger.error("キャッシュ書き込みエラー: %s", e)
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass


def main():
    """コマンドライン引数を処理してスキャンを実行する。"""
    parser = argparse.ArgumentParser(description="App Manager スキャナー")
    parser.add_argument(
        "--cache-path", required=True,
        help="app_cache.json のパス"
    )
    parser.add_argument(
        "--custom-paths", default="",
        help="カスタムスキャンパス（セミコロン区切り）"
    )
    parser.add_argument(
        "--scan-registry", action="store_true", default=False,
        help="レジストリスキャンを実行する"
    )
    parser.add_argument(
        "--stale-threshold-days", type=int, default=30,
        help="データクレンジング猶予日数"
    )

    args = parser.parse_args()
    custom_paths = [p.strip() for p in args.custom_paths.split(";") if p.strip()]

    run_scan(
        cache_path=args.cache_path,
        custom_paths=custom_paths,
        scan_registry_flag=args.scan_registry,
        stale_threshold_days=args.stale_threshold_days,
    )


if __name__ == "__main__":
    main()

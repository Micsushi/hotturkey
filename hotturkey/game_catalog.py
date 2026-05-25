import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameInstall:
    source: str
    name: str
    install_root: str
    launch_exes: frozenset[str]
    app_id: str = ""


def _norm_path(path: str | os.PathLike) -> str:
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))


def _match_path(path: str | os.PathLike) -> str:
    return os.path.normcase(_norm_path(path))


def _basename_lower(path: str) -> str:
    return os.path.basename(path.replace("/", os.sep)).lower()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_vdf_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for key, value in re.findall(r'"([^"]+)"\s+"([^"]*)"', text):
        pairs[key] = value.replace("\\\\", "\\")
    return pairs


def _parse_vdf_values(text: str, wanted_key: str) -> list[str]:
    values: list[str] = []
    for key, value in re.findall(r'"([^"]+)"\s+"([^"]*)"', text):
        if key == wanted_key:
            values.append(value.replace("\\\\", "\\"))
    return values


def scan_steam_library(library_root: str | os.PathLike) -> list[GameInstall]:
    root = Path(library_root)
    steamapps = root / "steamapps"
    if not steamapps.exists():
        return []

    games: list[GameInstall] = []
    for manifest in steamapps.glob("appmanifest_*.acf"):
        try:
            values = _parse_vdf_pairs(_read_text(manifest))
        except OSError:
            continue

        name = values.get("name") or values.get("appid") or manifest.stem
        installdir = values.get("installdir")
        if not installdir:
            continue

        games.append(
            GameInstall(
                source="Steam",
                name=name,
                install_root=_norm_path(steamapps / "common" / installdir),
                launch_exes=frozenset(),
                app_id=values.get("appid", ""),
            )
        )
    return games


def _steam_roots_from_libraryfolders(steam_root: Path) -> list[Path]:
    roots = [steam_root]
    libraryfolders = steam_root / "steamapps" / "libraryfolders.vdf"
    if not libraryfolders.exists():
        return roots

    try:
        text = _read_text(libraryfolders)
    except OSError:
        return roots

    for value in _parse_vdf_values(text, "path"):
        if value:
            roots.append(Path(value))

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = _match_path(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _default_steam_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / "Steam")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "Steam")
    return roots


def scan_steam_games(
    steam_roots: list[str | os.PathLike] | None = None,
) -> list[GameInstall]:
    candidates = (
        [Path(p) for p in steam_roots] if steam_roots else _default_steam_roots()
    )
    roots: list[Path] = []
    for candidate in candidates:
        roots.extend(_steam_roots_from_libraryfolders(candidate))

    games: list[GameInstall] = []
    seen: set[tuple[str, str]] = set()
    for root in roots:
        for game in scan_steam_library(root):
            key = (game.source, _match_path(game.install_root))
            if key not in seen:
                seen.add(key)
                games.append(game)
    return games


def scan_epic_manifests(manifests_dir: str | os.PathLike) -> list[GameInstall]:
    root = Path(manifests_dir)
    if not root.exists():
        return []

    games: list[GameInstall] = []
    for manifest in root.glob("*.item"):
        try:
            data = json.loads(_read_text(manifest))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        install_root = data.get("InstallLocation")
        if not isinstance(install_root, str) or not install_root.strip():
            continue

        launch_exe = data.get("LaunchExecutable")
        launch_exes = frozenset(
            {_basename_lower(launch_exe)}
            if isinstance(launch_exe, str) and launch_exe
            else set()
        )
        name = data.get("DisplayName") or data.get("AppName") or manifest.stem
        app_id = data.get("CatalogItemId") or data.get("AppName") or ""
        games.append(
            GameInstall(
                source="Epic",
                name=str(name),
                install_root=_norm_path(install_root),
                launch_exes=launch_exes,
                app_id=str(app_id),
            )
        )
    return games


def _default_epic_manifest_dirs() -> list[Path]:
    program_data = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return [Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"]


def scan_epic_games(
    manifest_dirs: list[str | os.PathLike] | None = None,
) -> list[GameInstall]:
    dirs = (
        [Path(p) for p in manifest_dirs]
        if manifest_dirs
        else _default_epic_manifest_dirs()
    )
    games: list[GameInstall] = []
    for manifests_dir in dirs:
        games.extend(scan_epic_manifests(manifests_dir))
    return games


def scan_legendary_installed(installed_json: str | os.PathLike) -> list[GameInstall]:
    path = Path(installed_json)
    if not path.exists():
        return []

    try:
        data = json.loads(_read_text(path))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    games: list[GameInstall] = []
    for app_name, row in data.items():
        if not isinstance(row, dict):
            continue
        install_root = row.get("install_path") or row.get("install_dir")
        if not isinstance(install_root, str) or not install_root.strip():
            continue
        exe = row.get("executable") or row.get("launch_executable")
        launch_exes = frozenset(
            {_basename_lower(exe)} if isinstance(exe, str) and exe else set()
        )
        title = (
            row.get("title") or row.get("app_title") or row.get("app_name") or app_name
        )
        games.append(
            GameInstall(
                source="Legendary",
                name=str(title),
                install_root=_norm_path(install_root),
                launch_exes=launch_exes,
                app_id=str(row.get("app_name") or app_name),
            )
        )
    return games


def _default_legendary_installed_paths() -> list[Path]:
    home = Path.home()
    appdata = os.environ.get("APPDATA")
    paths = [
        home / ".config" / "legendary" / "installed.json",
    ]
    if appdata:
        paths.append(Path(appdata) / "legendary" / "installed.json")
    return paths


def scan_legendary_games(
    installed_paths: list[str | os.PathLike] | None = None,
) -> list[GameInstall]:
    paths = (
        [Path(p) for p in installed_paths]
        if installed_paths
        else _default_legendary_installed_paths()
    )
    games: list[GameInstall] = []
    for path in paths:
        games.extend(scan_legendary_installed(path))
    return games


def scan_installed_games() -> list[GameInstall]:
    games: list[GameInstall] = []
    games.extend(scan_steam_games())
    games.extend(scan_epic_games())
    games.extend(scan_legendary_games())
    return games


def find_game_for_exe_path(
    exe_path: str, games: list[GameInstall]
) -> GameInstall | None:
    if not exe_path:
        return None

    exe_name = _basename_lower(exe_path)
    normalized = _match_path(exe_path) if os.path.dirname(exe_path) else ""

    best: GameInstall | None = None
    best_len = -1
    for game in games:
        root = _match_path(game.install_root)
        if normalized:
            try:
                if (
                    os.path.commonpath([normalized, root]) == root
                    and len(root) > best_len
                ):
                    best = game
                    best_len = len(root)
            except ValueError:
                pass
        elif exe_name in game.launch_exes:
            return game

    if best is not None:
        return best

    for game in games:
        if exe_name in game.launch_exes:
            return game

    return None

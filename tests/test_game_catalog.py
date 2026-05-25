import json
from pathlib import Path

from hotturkey.game_catalog import (
    GameInstall,
    find_game_for_exe_path,
    scan_epic_manifests,
    scan_legendary_installed,
    scan_steam_games,
    scan_steam_library,
)


def test_scan_steam_library_reads_appmanifest_install_root(tmp_path):
    steam_root = tmp_path / "SteamLibrary"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_1808500.acf").write_text(
        """
"AppState"
{
    "appid"        "1808500"
    "name"        "ARC Raiders"
    "installdir"  "ARC Raiders"
    "StateFlags"  "4"
}
""",
        encoding="utf-8",
    )

    games = scan_steam_library(steam_root)

    assert games == [
        GameInstall(
            source="Steam",
            name="ARC Raiders",
            install_root=str(steamapps / "common" / "ARC Raiders"),
            launch_exes=frozenset(),
            app_id="1808500",
        )
    ]


def test_scan_steam_games_reads_multiple_libraryfolders_paths(tmp_path):
    steam_root = tmp_path / "Steam"
    steamapps = steam_root / "steamapps"
    steamapps.mkdir(parents=True)
    lib_a = tmp_path / "LibraryA"
    lib_b = tmp_path / "LibraryB"
    (steamapps / "libraryfolders.vdf").write_text(
        f'''
"libraryfolders"
{{
    "0"
    {{
        "path" "{str(lib_a).replace("\\", "\\\\")}"
    }}
    "1"
    {{
        "path" "{str(lib_b).replace("\\", "\\\\")}"
    }}
}}
''',
        encoding="utf-8",
    )
    for idx, library in enumerate((lib_a, lib_b), start=1):
        app_dir = library / "steamapps"
        app_dir.mkdir(parents=True)
        (app_dir / f"appmanifest_{idx}.acf").write_text(
            f"""
"AppState"
{{
    "appid" "{idx}"
    "name" "Game {idx}"
    "installdir" "Game {idx}"
}}
""",
            encoding="utf-8",
        )

    games = scan_steam_games([steam_root])

    assert {game.name for game in games} == {"Game 1", "Game 2"}


def test_scan_epic_manifests_reads_install_location_and_launch_exe(tmp_path):
    manifests = tmp_path / "Manifests"
    manifests.mkdir()
    (manifests / "arc.item").write_text(
        json.dumps(
            {
                "AppName": "Pioneer",
                "DisplayName": "ARC Raiders",
                "InstallLocation": str(tmp_path / "Epic" / "ARC Raiders"),
                "LaunchExecutable": "Pioneer/Binaries/Win64/PioneerGame.exe",
                "CatalogItemId": "catalog-arc",
            }
        ),
        encoding="utf-8",
    )

    games = scan_epic_manifests(manifests)

    assert games == [
        GameInstall(
            source="Epic",
            name="ARC Raiders",
            install_root=str(tmp_path / "Epic" / "ARC Raiders"),
            launch_exes=frozenset({"pioneergame.exe"}),
            app_id="catalog-arc",
        )
    ]


def test_scan_legendary_installed_reads_imported_epic_games(tmp_path):
    installed = tmp_path / "installed.json"
    installed.write_text(
        json.dumps(
            {
                "Pioneer": {
                    "title": "ARC Raiders",
                    "install_path": str(tmp_path / "Legendary" / "ARC Raiders"),
                    "executable": "Pioneer/Binaries/Win64/PioneerGame.exe",
                    "app_name": "Pioneer",
                }
            }
        ),
        encoding="utf-8",
    )

    games = scan_legendary_installed(installed)

    assert games == [
        GameInstall(
            source="Legendary",
            name="ARC Raiders",
            install_root=str(tmp_path / "Legendary" / "ARC Raiders"),
            launch_exes=frozenset({"pioneergame.exe"}),
            app_id="Pioneer",
        )
    ]


def test_find_game_for_exe_path_matches_path_under_install_root(tmp_path):
    game_root = tmp_path / "SteamLibrary" / "steamapps" / "common" / "ARC Raiders"
    exe_path = game_root / "Pioneer" / "Binaries" / "Win64" / "PioneerGame.exe"
    games = [
        GameInstall(
            source="Steam",
            name="ARC Raiders",
            install_root=str(game_root),
            launch_exes=frozenset(),
            app_id="1808500",
        )
    ]

    assert find_game_for_exe_path(str(exe_path), games) == games[0]


def test_find_game_for_exe_path_avoids_sibling_prefix_false_positive(tmp_path):
    game_root = tmp_path / "Games" / "Arc"
    sibling_exe = tmp_path / "Games" / "ArcadeEditor" / "editor.exe"
    games = [
        GameInstall(
            source="Steam",
            name="Arc",
            install_root=str(game_root),
            launch_exes=frozenset(),
            app_id="1",
        )
    ]

    assert find_game_for_exe_path(str(sibling_exe), games) is None


def test_find_game_for_exe_path_can_match_known_launch_exe_without_path(tmp_path):
    game_root = tmp_path / "Epic" / "ARC Raiders"
    games = [
        GameInstall(
            source="Epic",
            name="ARC Raiders",
            install_root=str(game_root),
            launch_exes=frozenset({"pioneergame.exe"}),
            app_id="catalog-arc",
        )
    ]

    assert find_game_for_exe_path("PioneerGame.exe", games) == games[0]

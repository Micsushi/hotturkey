import json
import os
import tempfile
import unittest

import hotturkey.config as config
import hotturkey.tracked_targets as tracked_targets


class TrackedTargetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_state_dir = config.STATE_DIR
        self.orig_targets_file = config.TRACKED_TARGETS_FILE
        config.STATE_DIR = self.tmp.name
        tracked_targets.refresh_tracked_targets_cache()

    def tearDown(self):
        config.STATE_DIR = self.orig_state_dir
        config.TRACKED_TARGETS_FILE = self.orig_targets_file
        tracked_targets.refresh_tracked_targets_cache()
        self.tmp.cleanup()

    def _write_targets(self, name, tracked_sites):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"tracked_sites": tracked_sites}, handle)
        os.utime(path, (1000, 1000))
        return path

    def test_cache_invalidates_when_target_path_changes_even_with_same_mtime(self):
        first = self._write_targets("first.json", ["one"])
        second = self._write_targets("second.json", ["two"])

        config.TRACKED_TARGETS_FILE = first
        self.assertEqual(
            tracked_targets.get_tracked_targets()["tracked_sites"], ["one"]
        )

        config.TRACKED_TARGETS_FILE = second

        self.assertEqual(
            tracked_targets.get_tracked_targets()["tracked_sites"], ["two"]
        )

    def test_user_file_missing_keys_inherit_packaged_defaults(self):
        path = self._write_targets("partial.json", ["custom-video"])
        config.TRACKED_TARGETS_FILE = path

        targets = tracked_targets.get_tracked_targets()

        self.assertEqual(targets["tracked_sites"], ["custom-video"])
        self.assertIn("brave", targets["browsers"])
        self.assertIn("pioneergame.exe", targets["known_game_executables"])


if __name__ == "__main__":
    unittest.main()

"""Only the existing exact Events promotion title gains a patch release signal."""

from pathlib import Path
import tomllib
import unittest

from semantic_release.commit_parser.conventional import (
    ConventionalCommitParser, ConventionalCommitParserOptions,
)
from semantic_release.enums import LevelBump


ROOT = Path(__file__).resolve().parents[1]


class EventsReleaseSignalTests(unittest.TestCase):
    def setUp(self):
        config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.parser = ConventionalCommitParser(ConventionalCommitParserOptions(
            **config['tool']['semantic_release']['commit_parser_options']))

    def bump(self, message):
        parsed = self.parser.parse_message(message)
        return parsed.bump if parsed else LevelBump.NO_RELEASE

    def test_exact_promoter_title_releases_with_or_without_squash_body(self):
        for message in (
                'chore(deps): update events-service to v0.7.0',
                'chore(deps): update events-service to v0.7.0\n',
                'chore(deps): update events-service to v0.7.0\n\nVerified artifact promotion.'):
            with self.subTest(message=message):
                self.assertEqual(self.bump(message), LevelBump.PATCH)

    def test_unrelated_chores_and_malformed_promotion_titles_do_not_release(self):
        for message in (
                'chore(deps): update another-service to v0.7.0',
                'chore(ci): update events-service to v0.7.0',
                'chore(deps): update events-service to latest',
                'chore(deps): update events-service to v0.7.0 and another change',
                'chore: maintenance', 'chore(release): v0.33.20'):
            with self.subTest(message=message):
                self.assertEqual(self.bump(message), LevelBump.NO_RELEASE)

    def test_existing_feature_fix_and_nonrelease_signals_are_preserved(self):
        for message, expected in (
                ('feat(events): add transport', LevelBump.MINOR),
                ('fix(events): correct transport', LevelBump.PATCH),
                ('docs(events): explain transport', LevelBump.NO_RELEASE)):
            self.assertEqual(self.bump(message), expected)


if __name__ == '__main__':
    unittest.main()

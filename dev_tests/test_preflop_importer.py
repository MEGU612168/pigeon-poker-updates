import tempfile
import unittest
from pathlib import Path

from pigeon_poker.preflop_importer import (
    import_folder, lookup_frequencies, parse_frequency_csv, parse_gto_wizard_html,
)


class ImporterTests(unittest.TestCase):
    def test_cumulative_css_widths(self):
        source = '''<div class="rtc rtc_strategy_range_normalized ra_table_cell" style="background-image: linear-gradient(to right, rgb(233, 150, 122), rgb(233, 150, 122)), linear-gradient(to right, rgb(143, 188, 139), rgb(143, 188, 139)), linear-gradient(to right, rgb(109, 162, 192), rgb(109, 162, 192)); background-size: 20% 100%, 60% 100%, 100% 100%;"><div class="rtc_title">AKs <!----></div></div>'''
        row = parse_gto_wizard_html(source).hands["AKs"]
        self.assertAlmostEqual(row.raise_pct, 20)
        self.assertAlmostEqual(row.call_pct, 40)
        self.assertAlmostEqual(row.fold_pct, 40)

    def test_csv(self):
        result = parse_frequency_csv("Hand,Raise,Call,Fold\nAKs,45,35,20\nAA,100,0,0\n")
        self.assertEqual(result.hands["AKs"].raise_pct, 45)

    def test_import_deduplicates_and_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "exports"
            root.mkdir()
            path = root / "6max_100bb_BTN_RFI.csv"
            path.write_text("Hand,Raise,Call,Fold\nAKs,80,20,0\n", encoding="utf-8")
            db = Path(tmp) / "pigeon.sqlite3"
            first = import_folder(root, db)
            again = import_folder(root, db)
            self.assertEqual(first.imported, 1)
            self.assertEqual(again.skipped, 1)
            rows = lookup_frequencies(db, position="BTN", node="RFI", hand="AKs", stack_bb=100, players=6)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["raise_pct"], 80)


if __name__ == "__main__":
    unittest.main()

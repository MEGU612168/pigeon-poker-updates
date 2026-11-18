# Pigeon Poker preflop range importer

Converts locally saved/exported GTO Wizard preflop range files into a searchable SQLite database. It does not log in to GTO Wizard, scrape the website, or send automated requests.

## Import a folder

```powershell
python -m pigeon_poker.preflop_importer .\GTOWizardExports --db .\pigeon_preflop.sqlite3
```

Supported inputs:
- .html / .htm / .txt: saved GTO Wizard range-table HTML
- .csv: Hand,Raise,Call,Fold frequency table

The importer scans folders recursively, parses mixed frequencies, stores spots and hand rows in SQLite, skips duplicate file+spot combinations, and warns if fewer than 169 hand classes were found.

## Spot metadata

Filename tokens such as `6max_100bb_BTN_RFI.html` populate simple fields automatically. For more complete context, put a JSON sidecar beside the export using the same basename:

```json
{
  "game": "cash",
  "format": "6max",
  "players": 6,
  "stack_bb": 100,
  "ante_bb": 0,
  "position": "BTN",
  "node": "RFI",
  "tree": "100bb_6max_cash"
}
```

Without sufficient metadata, a file is stored under its filename as an unmapped spot. The CPU must not use an unmapped spot as an exact strategy match.

## Integration status

This is the import/data layer. It is not yet connected to the installed Pigeon Poker Settings screen or CPU decision loop. The connected GitHub repository contains the update channel, not the current app entry point, so the live UI integration cannot be safely completed from this repository alone.

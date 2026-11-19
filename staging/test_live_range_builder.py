import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_range_builder import build_live_hu_solver_setup


def chart():
    rows=[]
    for node in ("01_UTG_OPEN","04_BTN_OPEN","10_BB_VS_UTG","18_SB_VS_BTN"):
        rows.extend([
            {"node":node,"hand":"AA","p":{"raise":1.0,"call":1.0,"fold":0.0}},
            {"node":node,"hand":"AKs","p":{"raise":0.5,"call":0.4,"fold":0.1}},
            {"node":node,"hand":"72o","p":{"raise":0.0,"call":0.0,"fold":1.0}},
        ])
    return {"rows":rows}


def hand(events, active, dealer=0, current_pot=500, dealt_count=6):
    players=[SimpleNamespace(player_id=f"p{i}",eligible=f"p{i}" in active,
                             hole_cards=(["As","Ah"] if i < dealt_count else []),
                             stack=9000 if f"p{i}" in active else 0) for i in range(6)]
    return SimpleNamespace(players=players,dealer_index=dealer,big_blind=1000,
                           events=events,street="flop",board=["As","Kd","7c"],pot=current_pot)


class LiveAutoSolveRangeTests(unittest.TestCase):
    def setUp(self):
        self.chart=chart()

    def test_btn_open_sb_call_ip_oop_ranges(self):
        events=[
            {"type":"action","street":"preflop","player":"p5","action":"fold"},
            {"type":"action","street":"preflop","player":"p4","action":"fold"},
            {"type":"action","street":"preflop","player":"p3","action":"fold"},
            {"type":"action","street":"preflop","player":"p0","action":"raise","target":2500},
            {"type":"action","street":"preflop","player":"p1","action":"call"},
            {"type":"action","street":"preflop","player":"p2","action":"fold"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
        ]
        r=build_live_hu_solver_setup(hand(events,{"p0","p1"}),self.chart,rake_pct=5)
        self.assertTrue(r["supported"],r)
        self.assertEqual(r["root"]["ip_player_id"],"p0")
        self.assertEqual(r["root"]["oop_player_id"],"p1")
        self.assertEqual(r["root"]["ip_range"],"AA:1.0000,AKs:0.5000")
        self.assertEqual(r["root"]["oop_range"],"AA:1.0000,AKs:0.4000")

    def test_utg_open_bb_call_button_folded_ip_oop(self):
        events=[
            {"type":"action","street":"preflop","player":"p3","action":"raise","target":2500},
            {"type":"action","street":"preflop","player":"p4","action":"fold"},
            {"type":"action","street":"preflop","player":"p5","action":"fold"},
            {"type":"action","street":"preflop","player":"p0","action":"fold"},
            {"type":"action","street":"preflop","player":"p1","action":"fold"},
            {"type":"action","street":"preflop","player":"p2","action":"call"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
        ]
        r=build_live_hu_solver_setup(hand(events,{"p2","p3"}),self.chart,rake_pct=5)
        self.assertTrue(r["supported"],r)
        self.assertEqual((r["root"]["oop_player_id"],r["root"]["ip_player_id"]),("p2","p3"))

    def test_short_handed_table_is_rejected_not_mapped_to_six_max_positions(self):
        events=[
            {"type":"action","street":"preflop","player":"p0","action":"raise","target":2500},
            {"type":"action","street":"preflop","player":"p1","action":"call"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
        ]
        r=build_live_hu_solver_setup(
            hand(events,{"p0","p1"},dealt_count=2),self.chart,rake_pct=5)
        self.assertFalse(r["supported"])
        self.assertIn("six dealt players",r["reason"])

    def test_three_bet_is_explicitly_rejected(self):
        events=[
            {"type":"action","street":"preflop","player":"p3","action":"raise","target":2500},
            {"type":"action","street":"preflop","player":"p0","action":"raise","target":8000},
            {"type":"action","street":"preflop","player":"p3","action":"call"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
        ]
        r=build_live_hu_solver_setup(hand(events,{"p0","p3"}),self.chart,rake_pct=5)
        self.assertFalse(r["supported"])
        self.assertIn("exactly one",r["reason"])

    def test_nonstandard_open_size_is_rejected(self):
        events=[
            {"type":"action","street":"preflop","player":"p5","action":"fold"},
            {"type":"action","street":"preflop","player":"p4","action":"fold"},
            {"type":"action","street":"preflop","player":"p3","action":"fold"},
            {"type":"action","street":"preflop","player":"p0","action":"raise","target":4000},
            {"type":"action","street":"preflop","player":"p1","action":"call"},
            {"type":"action","street":"preflop","player":"p2","action":"fold"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
        ]
        r=build_live_hu_solver_setup(hand(events,{"p0","p1"}),self.chart,rake_pct=5)
        self.assertFalse(r["supported"])
        self.assertIn("differs",r["reason"])

    def test_flop_root_pot_stack_and_line_reconstruction(self):
        events=[
            {"type":"action","street":"preflop","player":"p5","action":"fold"},
            {"type":"action","street":"preflop","player":"p4","action":"fold"},
            {"type":"action","street":"preflop","player":"p3","action":"fold"},
            {"type":"action","street":"preflop","player":"p0","action":"raise","target":2500},
            {"type":"action","street":"preflop","player":"p1","action":"call"},
            {"type":"action","street":"preflop","player":"p2","action":"fold"},
            {"type":"street","street":"flop","board":["As","Kd","7c"]},
            {"type":"action","street":"flop","player":"p1","action":"check","pot_before":5000,"street_contribution_before":0,"to_call_before":0},
            {"type":"action","street":"flop","player":"p0","action":"bet","target":2500,"street_contribution_before":0,"to_call_before":0,"pot_before":5000},
        ]
        r=build_live_hu_solver_setup(hand(events,{"p0","p1"},current_pot=7500),self.chart,rake_pct=5)
        self.assertTrue(r["supported"],r)
        self.assertEqual(r["root"]["pot_bb"],5.0)
        self.assertEqual(r["root"]["effective_stack_bb"],9.0)
        self.assertEqual(len(r["postflop_line"]),2)


if __name__=="__main__":
    unittest.main(verbosity=2)

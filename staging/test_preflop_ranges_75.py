import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('preflop_screenshot_ranges_75.py')
spec = importlib.util.spec_from_file_location('preflop75', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

class FixedRandom:
    def __init__(self, *values):
        self.values = list(values)
    def random(self):
        if self.values:
            return self.values.pop(0)
        return 0.5

class FakePlayer:
    def __init__(self, player_id, hole_cards=('As','Kd')):
        self.player_id = player_id
        self.name = player_id
        self.hole_cards = hole_cards
        self.street_contribution = 0
        self.total_contribution = 0
        self.stack = 10000
        self.eligible = True

class FakeHand:
    def __init__(self, node, combo='AKo'):
        self.street='preflop'
        self.big_blind=100
        self.dealer_index=0
        self.players=[FakePlayer(f'p{i}') for i in range(6)]
        self.seat_by_id={f'p{i}':i for i in range(6)}
        self.events=[]
        pos_to_id={position:f'p{offset}' for offset,position in module.POSITIONS_BY_CLOCKWISE_DISTANCE.items()}
        history_positions={item['pos'] for item in node['history']}
        for item in node['history']:
            player_id=pos_to_id[item['pos']]
            target=int(round(item['amount_bb']*self.big_blind))
            player=self.player(player_id)
            player.stack=max(0,10000-target)
            player.total_contribution=target
            self.events.append({
                'type':'action','street':'preflop','player_id':player_id,
                'action':'allin' if item['action']=='allin' else 'raise',
                'target':target,
            })
        # A folded player is no longer part of the hand's effective stack.
        if node['history'] and 'BTN' not in history_positions and node['actor_position'] != 'BTN':
            self.players[0].eligible=False
            self.events.insert(0, {'type':'action','street':'preflop','player_id':'p0','action':'fold'})
        self.actor_id=pos_to_id[node['actor_position']]
        self.players[int(self.actor_id[1:])].hole_cards=self._cards(combo)
        self._pos_to_id=pos_to_id
    @staticmethod
    def _cards(combo):
        suit_names={'s':('♠','♠'),'o':('♠','♥')}
        if len(combo)==2:
            return (combo[0]+'♠', combo[1]+'♥')
        s1,s2=suit_names[combo[-1]]
        return (combo[0]+s1, combo[1]+s2)
    def player(self, player_id):
        return self.players[int(str(player_id)[1:])]
    def legal_actions(self, player_id):
        return {'actions':['fold','call','raise','all-in','check'], 'min_target':200, 'max_target':10000}

class FakeTable:
    dealer_index=0

class FakeCPU:
    def __init__(self, random_value=.5, level=5):
        self.level=level
        self.rng=FixedRandom(random_value)

def choose_rng_for_action(node, combo, target_action, legal=None):
    actions=node['hands'][combo]
    if legal is None:
        legal={'actions':['fold','call','raise','all-in','check'], 'min_target':200, 'max_target':10000}
    kept=[]
    for item in actions:
        action=item['action']
        if action=='raise' and 'raise' not in legal['actions']: continue
        if action=='allin' and not any(x in legal['actions'] for x in ('all-in','allin','all_in','jam','shove')): continue
        if action in ('call','fold') and action not in legal['actions']: continue
        if item['frequency']>0: kept.append(item)
    total=sum(x['frequency'] for x in kept)
    before=0.0
    for item in kept:
        if item['action']==target_action:
            return (before+item['frequency']/2)/total
        before+=item['frequency']
    raise AssertionError(f'{node["id"]}/{combo}: action {target_action} not selectable')


def test_all_75_histories_match():
    data=module._data()
    assert len(data['nodes'])==75
    for node in data['nodes']:
        hand=FakeHand(node)
        got=module._node_for_actor(FakeTable(), hand, hand.actor_id)
        assert got==node['id'], (node['id'],got,node['history'])


def test_wrong_size_is_rejected():
    data=module._data()
    node=data['nodes'][20]
    hand=FakeHand(node)
    hand.events[-1]['target'] += 100
    assert module._node_for_actor(FakeTable(),hand,hand.actor_id) is None


def test_unexpected_nonfold_history_is_rejected():
    node=module._data()['nodes'][20]
    hand=FakeHand(node)
    hand.events.append({'type':'action','street':'preflop','player_id':'p5','action':'call'})
    assert module._node_for_actor(FakeTable(),hand,hand.actor_id) is None


def test_raise_sizes_for_every_raise_node():
    checked=0
    for node in module._data()['nodes']:
        for combo, actions in node['hands'].items():
            raises=[a for a in actions if a['action']=='raise' and a['frequency']>0]
            if not raises: continue
            sizes={a['amount_bb'] for a in raises}
            assert len(sizes)==1, (node['id'],combo,sizes)
            hand=FakeHand(node,combo)
            value=choose_rng_for_action(node,combo,'raise')
            cpu=FakeCPU(value)
            decision=module.choose_preflop_action(FakeTable(),hand,hand.actor_id,cpu)
            expected=int(round(next(iter(sizes))*hand.big_blind))
            assert decision is not None and decision.node_id==node['id']
            assert decision.action=='raise' and decision.amount==expected, (node['id'],combo,expected,decision)
            checked+=1
            break
    assert checked==50, checked


def test_allin_actions_for_every_allin_node():
    checked=0
    for node in module._data()['nodes']:
        for combo, actions in node['hands'].items():
            if not any(a['action']=='allin' and a['frequency']>0 for a in actions): continue
            hand=FakeHand(node,combo)
            value=choose_rng_for_action(node,combo,'allin')
            decision=module.choose_preflop_action(FakeTable(),hand,hand.actor_id,FakeCPU(value))
            assert decision is not None and decision.action=='all-in' and decision.amount is None, (node['id'],combo,decision)
            checked+=1
            break
    assert checked==20, checked


def test_decisions_and_zero_rows():
    data=module._data()
    node=data['nodes'][20]
    hand=FakeHand(node, '72o')
    assert module.choose_preflop_action(FakeTable(),hand,hand.actor_id,FakeCPU(.5)) is None
    fallback=object()
    node2=data['nodes'][0]
    hand2=FakeHand(node2,'AA')
    assert module.choose_preflop_action(FakeTable(),hand2,hand2.actor_id,FakeCPU(.1,level=1),fallback) is fallback


def test_legal_action_filtering_reweights_surviving_choices():
    node=module._data()['nodes'][20]
    combo=next(c for c,a in node['hands'].items() if any(x['action']=='call' and x['frequency']>0 for x in a) and any(x['action']=='fold' and x['frequency']>0 for x in a))
    hand=FakeHand(node,combo)
    hand.legal_actions=lambda _pid:{'actions':['fold','call']}
    actions=[a for a in node['hands'][combo] if a['action'] in ('call','fold') and a['frequency']>0]
    for item in actions:
        total=sum(x['frequency'] for x in actions)
        before=sum(x['frequency'] for x in actions if actions.index(x)<actions.index(item))
        value=(before+item['frequency']/2)/total
        decision=module.choose_preflop_action(FakeTable(),hand,hand.actor_id,FakeCPU(value))
        assert decision.action==item['action']



def test_all_12675_rows_and_every_positive_action_choice():
    data=module._data()
    row_count=0
    active_rows=0
    tested_choices=0
    for node in data['nodes']:
        for combo, raw_actions in node['hands'].items():
            row_count += 1
            hand=FakeHand(node,combo)
            legal=hand.legal_actions(hand.actor_id)
            choices=module._decision_choices(node,combo,hand,hand.actor_id,legal)
            positive=sum(float(a.get('frequency',0.0))>0 for a in raw_actions)
            if not positive:
                assert choices==[], (node['id'],combo,choices)
                assert module.choose_preflop_action(FakeTable(),hand,hand.actor_id,FakeCPU(.5)) is None
                continue
            active_rows += 1
            assert choices, (node['id'],combo,raw_actions)
            total=sum(weight for _,_,weight in choices)
            before=0.0
            for expected_action, expected_amount, weight in choices:
                value=(before+weight/2)/total
                decision=module.choose_preflop_action(
                    FakeTable(),hand,hand.actor_id,FakeCPU(value)
                )
                assert decision is not None, (node['id'],combo,expected_action)
                assert decision.action==expected_action, (node['id'],combo,expected_action,decision)
                assert decision.amount==expected_amount, (node['id'],combo,expected_amount,decision)
                before += weight
                tested_choices += 1
    assert row_count==12675, row_count
    assert active_rows>0 and tested_choices>active_rows


def test_100bb_stack_gate_and_folded_short_stack():
    node=module._data()['nodes'][0]
    hand=FakeHand(node,'AA')
    assert module._supports_100bb_effective_stack(hand)
    # A participating 60 BB stack invalidates the 100 BB chart and uses legacy CPU.
    hand.players[4].stack=6000
    assert not module._supports_100bb_effective_stack(hand)
    assert module._node_for_actor(FakeTable(),hand,hand.actor_id) is None
    # A folded short stack still influenced the line; it must invalidate the 100BB chart.
    hand=FakeHand(node,'AA')
    hand.players[1].eligible=False
    hand.players[1].stack=0
    hand.players[1].total_contribution=2000
    assert not module._supports_100bb_effective_stack(hand)
    assert module._node_for_actor(FakeTable(),hand,hand.actor_id) is None

def test_opponent_ranges_follow_the_observed_action_line():
    node=module._data()['nodes_by_id']['21_UTG_VS_HJ_3BET']
    hand=FakeHand(node,'AA')
    # UTG's 4-bet is the final observed decision at node 21.
    hand.events.append({'type':'action','street':'preflop','player_id':'p3','action':'raise','target':2000})
    hand.players[3].stack=8000
    hand.players[3].total_contribution=2000
    estimate=module.estimate_preflop_opponent_ranges(FakeTable(),hand,exclude_player_id='hero')
    assert estimate['supported'] is True
    utg=estimate['players']['p3']
    hj=estimate['players']['p4']
    assert utg['supported'] and utg['node_id']=='21_UTG_VS_HJ_3BET' and utg['action']=='raise'
    assert hj['supported'] and hj['node_id']=='06_HJ_VS_UTG' and hj['action']=='raise'
    assert abs(sum(utg['hand_class_probabilities'].values())-1.0)<1e-9
    assert abs(sum(hj['hand_class_probabilities'].values())-1.0)<1e-9
    # The mass in each posterior must be proportional to physical combos in that class.
    raw=node['hands']
    weighted={}
    total=0.0
    for combo,actions in raw.items():
        f=sum(a['frequency'] for a in actions if a['action']=='raise' and abs(float(a['amount_bb'])-20.0)<0.01)
        if f>0:
            multiplicity=6 if len(combo)==2 else (4 if combo.endswith('s') else 12)
            weighted[combo]=f*multiplicity
            total += f*multiplicity
    expected={combo:value/total for combo,value in weighted.items()}
    assert set(expected)==set(utg['hand_class_probabilities'])
    for combo in expected:
        assert abs(expected[combo]-utg['hand_class_probabilities'][combo])<1e-9


def test_opponent_ranges_fail_closed_after_unsupported_call_branch():
    node=module._data()['nodes_by_id']['06_HJ_VS_UTG']
    hand=FakeHand(node,'AA')
    # HJ calls UTG's open; a later CO decision after this call is not in the screenshots.
    hand.events.append({'type':'action','street':'preflop','player_id':'p4','action':'call'})
    hand.events.append({'type':'action','street':'preflop','player_id':'p5','action':'raise','target':800})
    hand.players[5].stack=9200
    hand.players[5].total_contribution=800
    estimate=module.estimate_preflop_opponent_ranges(FakeTable(),hand)
    assert estimate['players']['p4']['supported'] is True
    assert estimate['players']['p4']['node_id']=='06_HJ_VS_UTG'
    assert estimate['players']['p5']['supported'] is False
    assert estimate['players']['p5']['reason']=='unsupported_preflop_history'


def test_action_weights_reproduce_all_75_screenshot_totals():
    data=module._data()
    combo_count=lambda combo: 6 if len(combo)==2 else (4 if combo.endswith('s') else 12)
    assert len(data['nodes'])==75
    for node in data['nodes']:
        observed={}
        for combo,actions in node['hands'].items():
            for item in actions:
                label=item['label']
                observed[label]=observed.get(label,0.0)+float(item['frequency'])*combo_count(combo)
        total=sum(observed.values())
        targets=node['target_action_frequencies_pct']
        assert abs(sum(targets.values())-100.0)<=0.11, (node['id'],sum(targets.values()))
        for label,target_pct in targets.items():
            actual_pct=(observed.get(label,0.0)/total*100.0) if total else 0.0
            assert abs(actual_pct-float(target_pct))<=0.15, (node['id'],label,target_pct,actual_pct)


def test_hand_class_parsing():
    assert module.hand_class_from_cards(('A♠','A♥'))=='AA'
    assert module.hand_class_from_cards(('A♠','K♠'))=='AKs'
    assert module.hand_class_from_cards(('K♦','A♠'))=='AKo'

if __name__=='__main__':
    tests=[v for k,v in globals().items() if k.startswith('test_') and callable(v)]
    for test in tests:
        test(); print('PASS',test.__name__)
    print('ALL PASS',len(tests),module.coverage_summary())
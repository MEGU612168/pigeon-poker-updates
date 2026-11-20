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

class FakeHand:
    def __init__(self, node, combo='AKo'):
        self.street='preflop'
        self.big_blind=100
        self.dealer_index=0
        self.players=[FakePlayer(f'p{i}') for i in range(6)]
        self.seat_by_id={f'p{i}':i for i in range(6)}
        self.events=[]
        pos_to_id={position:f'p{offset}' for offset,position in module.POSITIONS_BY_CLOCKWISE_DISTANCE.items()}
        for item in node['history']:
            self.events.append({
                'type':'action','street':'preflop','player_id':pos_to_id[item['pos']],
                'action':'allin' if item['action']=='allin' else 'raise',
                'target':int(round(item['amount_bb']*self.big_blind)),
            })
        # Add realistic folds around the voluntary sequence. They must not alter node matching.
        if node['history']:
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


def test_hand_class_parsing():
    assert module.hand_class_from_cards(('A♠','A♥'))=='AA'
    assert module.hand_class_from_cards(('A♠','K♠'))=='AKs'
    assert module.hand_class_from_cards(('K♦','A♠'))=='AKo'

if __name__=='__main__':
    tests=[v for k,v in globals().items() if k.startswith('test_') and callable(v)]
    for test in tests:
        test(); print('PASS',test.__name__)
    print('ALL PASS',len(tests),module.coverage_summary())
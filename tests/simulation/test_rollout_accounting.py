import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.simulation.sequential_postflop import rollout
from tools.simulation.model_b_runtime import rake_net

class Oracle:
    def __init__(self, label, cost=None):
        self.label, self.cost = label, cost
    async def decide(self, raw):
        return {'bestLabel': self.label, 'alternatives': [
            {'label': self.label, 'costBB': self.cost, 'evBB': 1}]}

class Environment:
    def __init__(self, action, size=.01):
        self.action, self.size = action, size
    def sample_action(self, **kwargs):
        return self.action
    def sample_sizing(self, **kwargs):
        return self.size

def scenario(hero_stack=100, opponent_stack=100, first='H'):
    return dict(hero='H', opponent='V', profile=0, hero_cards=['As','Ah'],
                opponent_cards=['Ks','Kh'], flop=['2c','3d','7h'], runout=['8s','9c'],
                postflop_order=[first, 'V' if first=='H' else 'H'],
                stacks_bb={'H':hero_stack,'V':opponent_stack},
                preflop_contributions_bb={'H':3,'V':3}, flop_pot_bb=6,
                big_blind_chips=200, raw_hand='PokerStars Hand #123:',
                scenario_id='test', environment_seed=1, pot_type='SRP',
                preflop_roles={'H':'PFR','V':'CALLER'})

class AccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkdown(self):
        row=await rollout(scenario(), 'current', Oracle('CHECK'), Environment('CHECK'))
        self.assertEqual(row['utility_bb'], rake_net(6))
        self.assertEqual(row['terminal'], 'showdown')

    async def test_uncalled_bet_is_refunded_on_fold(self):
        row=await rollout(scenario(), 'current', Oracle('BET', 20), Environment('FOLD'))
        self.assertEqual(row['uncalled_return_bb'], 20)
        self.assertEqual(row['utility_bb'], rake_net(6))

    async def test_short_allin_call_refunds_excess(self):
        row=await rollout(scenario(opponent_stack=8), 'current', Oracle('JAM', 97), Environment('CALL'))
        self.assertEqual(row['terminal'], 'allin_showdown')
        self.assertEqual(row['utility_bb'], rake_net(16)-5)

    async def test_hero_short_allin_call(self):
        row=await rollout(scenario(hero_stack=8, first='V'), 'current', Oracle('CALL'), Environment('BET', 10))
        self.assertEqual(row['terminal'], 'allin_showdown')
        self.assertEqual(row['utility_bb'], rake_net(16)-5)

    async def test_minimum_opening_bet(self):
        row=await rollout(scenario(), 'current', Oracle('BET', .01), Environment('FOLD'))
        self.assertEqual(row['hero_actions'][0]['executed_cost_bb'], 1)
        self.assertEqual(row['uncalled_return_bb'], 1)

    async def test_short_opening_allin(self):
        row=await rollout(scenario(hero_stack=3.5), 'current', Oracle('BET', .5), Environment('CALL'))
        self.assertEqual(row['utility_bb'], rake_net(7)-.5)

    async def test_raise_against_allin_becomes_call(self):
        row=await rollout(scenario(opponent_stack=8, first='V'), 'current', Oracle('RAISE', 50), Environment('BET', 10))
        self.assertEqual(row['hero_actions'][0]['executed_kind'], 'CALL')
        self.assertEqual(row['hero_actions'][0]['executed_cost_bb'], 5)
        self.assertEqual(row['utility_bb'], rake_net(16)-5)

    async def test_check_facing_bet_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'illegal check'):
            await rollout(scenario(first='V'), 'current', Oracle('CHECK'), Environment('BET'))

if __name__=='__main__': unittest.main()

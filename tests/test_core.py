import copy
import json
import unittest

from controller_swap.core import (MODES, baseline, evidence_view, fixture_pack, metrics,
                                  new_run, record_step, supported_modes, validate_prediction, verify_chain)
from controller_swap.tasks import expected_action, public_task, validate_action


class TaskAndTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = fixture_pack()

    def test_full_crossed_fixture_matrix_is_balanced(self):
        self.assertEqual(len(self.pack), 72)
        cells = {(r['task'], r['mode'], r['worker'], r['repetition']) for r in self.pack}
        self.assertEqual(len(cells), 72)
        self.assertTrue(all(r['scope'] == 'synthetic_fixture' and not r['research_eligible'] for r in self.pack))
        self.assertEqual(sum(r['split'] == 'evaluation' for r in self.pack), 48)

    def test_mock_rules_cover_edge_cases(self):
        self.assertEqual(expected_action('files', 'F1')['value'], 'restricted')
        self.assertEqual(expected_action('routing', 'R3')['value'], 'review')
        self.assertEqual(expected_action('meetings', 'M4')['value'], 'review')
        self.assertEqual(expected_action('configuration', 'C2')['value'], 'unchanged')
        self.assertEqual(expected_action('ordering', 'T1')['value'], '2')
        self.assertNotIn('answers', public_task('issues'))

    def test_allowlisted_action_boundary(self):
        for action in ({'record': 'I1', 'value': 'delete'}, {'record': '../real', 'value': 'ready'}, {'record': 'I1', 'value': 'ready', 'path': 'C:\\'}):
            with self.assertRaises(ValueError):
                validate_action('issues', action)

    def test_invalid_step_has_no_partial_events(self):
        run = new_run('issues', 'human_steps', 'worker_a')
        before = copy.deepcopy(run)
        with self.assertRaises(ValueError):
            record_step(run, {'record': 'I1', 'value': 'ready'}, worker_action={})
        self.assertEqual(run, before)

    def test_human_mode_cannot_advance_without_input(self):
        run = new_run('issues', 'human_steps', 'worker_a')
        with self.assertRaises(ValueError):
            record_step(run)
        with self.assertRaises(ValueError):
            record_step(run, {'record': 'I1', 'value': 'ready'}, automation=True)

    def test_duplicate_action_is_rejected_without_partial_mutation(self):
        run = new_run('issues', 'human_steps', 'worker_a')
        record_step(run, {'record': 'I1', 'value': 'ready'})
        before = copy.deepcopy(run)
        with self.assertRaises(ValueError):
            record_step(run, {'record': 'I1', 'value': 'ready'})
        self.assertEqual(run, before)

    def test_adherence_and_task_correctness_are_different(self):
        run = new_run('issues', 'human_steps', 'worker_a')
        record_step(run, {'record': 'I1', 'value': 'hold'})
        self.assertEqual(run['events'][-1]['data']['adherence'], 'consistent')
        self.assertNotEqual(run['state']['I1'], expected_action('issues', 'I1')['value'])

    def test_all_fixture_hashes_verify(self):
        self.assertTrue(all(verify_chain(r) for r in self.pack))

    def test_edited_deleted_reordered_and_state_tampering_detected(self):
        for mutation in ('edit', 'delete', 'reorder', 'state', 'truncate'):
            run = copy.deepcopy(self.pack[0])
            if mutation == 'edit':
                run['events'][2]['data']['text'] = 'changed'
            elif mutation == 'delete':
                del run['events'][2]
            elif mutation == 'reorder':
                run['events'][2], run['events'][3] = run['events'][3], run['events'][2]
            elif mutation == 'state':
                run['state']['I1'] = 'wrong'
            else:
                run['events'].pop()
            self.assertFalse(verify_chain(run), mutation)

    def test_public_views_exclude_private_metadata_and_origins(self):
        for view in ('actions', 'messages'):
            for run in self.pack:
                result = evidence_view(run, view)
                text = json.dumps(result)
                for secret in ('arrangement', 'controller_origin', 'worker_alias', 'worker_a', 'worker_b', 'protocol_hash', 'fixture_simulation', run['id']):
                    self.assertNotIn(json.dumps(secret), text)
                self.assertEqual([e['record_ref'] for e in result['events']], [f'v{i}' for i in range(len(result['events']))])
                self.assertTrue(all('source' not in e for e in result['events']))
                self.assertEqual(supported_modes(result)[0], list(MODES))
                if view == 'actions':
                    self.assertFalse(any(e['kind'] == 'controller_decision' for e in result['events']))

    def test_complete_fixture_view_is_explicit_oracle_only(self):
        run = self.pack[0]
        prediction = baseline(run, 'complete', 'evidence_checklist')
        self.assertEqual(prediction['label'], run['mode'])
        self.assertIn('Software diagnostic only', prediction['reason'])

    def test_browser_steps_are_not_authenticated_human(self):
        run = new_run('issues', 'human_steps', 'worker_a')
        for record in public_task('issues')['records']:
            record_step(run, expected_action('issues', record['id']))
        p = baseline(run, 'complete', 'evidence_checklist')
        self.assertEqual(p['label'], 'unresolved')
        self.assertFalse(run['research_eligible'])

    def test_model_run_has_no_fabricated_worker_narrative(self):
        run = new_run('issues', 'standing_instruction', 'worker_b', backend='model')
        record_step(run, worker_action={'record': 'I1', 'value': 'ready'})
        event = next(e for e in run['events'] if e['kind'] == 'worker_action')
        self.assertNotIn('text', event['data'])

    def test_prediction_refs_checked_against_selected_view(self):
        run = self.pack[0]
        with self.assertRaises(ValueError):
            validate_prediction({'label': 'human_steps', 'view': 'actions', 'evidence': ['v999']}, run)
        with self.assertRaises(ValueError):
            validate_prediction({'label': 'human_steps', 'view': 'actions', 'compatible': list(MODES)}, run)


class MetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = fixture_pack()

    def test_abstention_denominators_and_missing_error(self):
        predictions = [baseline(r, 'actions', 'always_abstain') for r in self.pack]
        s = metrics(self.pack, predictions)['summaries'][0]
        self.assertEqual(s['n'], 48)
        self.assertEqual(s['coverage'], 0)
        self.assertIsNone(s['answered_error'])
        self.assertEqual(s['assigned_mode_accuracy'], 0)
        self.assertEqual(s['evidence_set_correct'], 48)
        self.assertEqual(s['worker_pairs'], 24)
        self.assertEqual(s['controller_pairs'], 48)

    def test_import_duplicates_do_not_inflate_count(self):
        p = [baseline(r, 'complete', 'evidence_checklist') for r in self.pack]
        s = metrics(self.pack, p + p)['summaries'][0]
        self.assertEqual(s['n'], 48)
        self.assertEqual(s['worker_pair_both_correct'], 24)
        self.assertEqual(s['controller_pair_both_correct'], 48)
        self.assertEqual(s['family_count'], 4)

    def test_wrong_constant_predictor_is_not_successful_consistency(self):
        p = [baseline(r, 'actions', 'surface_heuristic') for r in self.pack]
        s = metrics(self.pack, p)['summaries'][0]
        self.assertEqual(s['worker_pair_disagreement'], 0)
        self.assertEqual(s['worker_pair_both_correct'], 8)
        self.assertEqual(s['unsupported_definitive'], 48)
        self.assertAlmostEqual(s['macro_recall'], 1 / 3)


if __name__ == '__main__':
    unittest.main()

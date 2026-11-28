"""Batch review preserves decisions and requires a current, explicit preview."""
import unittest
from copy import deepcopy
import test_b2_web as fixtures


class BatchReviewTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebReviewTests(methodName='test_pending_handoff_blocked')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.session.save(self.f.accepted())
        state=self.f.session.state()
        self.f.session.start_simplification(self.request(state))

    def request(self,state=None,**extra):
        state=state or self.f.session.state()
        return dict(revision=state['revision'],simplification_revision=state['simplification_revision'],**extra)

    def test_preview_is_readonly_then_apply_resolves_all_pending_without_finalizing(self):
        session=self.f.session
        original=session.simplification_path.read_bytes()
        review=self.f.review.read_bytes()
        result=session.batch_simplification(self.request())
        self.assertEqual(session.simplification_path.read_bytes(),original)
        self.assertEqual(result['plan']['pending_after'],0)
        state=session.batch_simplification(self.request(proposal_revision=result['proposal_revision']),apply=True)
        record=state['simplification']
        self.assertFalse(record['confirmed'])
        self.assertTrue(all(r['decision']!='pending' for r in record['proposals']))
        self.assertEqual(self.f.review.read_bytes(),review)
        self.assertTrue(list(self.f.bundle.glob('*.before-batch-*.json')))
        for group in record['sets']:
            if group['decision']!='keep':
                self.assertFalse(any(ref in record['protected_faces'] for ref in group['faces']))

    def test_saved_omit_is_preserved_and_part_scope_does_not_decide_others(self):
        session=self.f.session
        state=session.state()
        row=next(r for r in state['simplification']['proposals'] if r['face'][0]=='1/1')
        state=session.save_simplification(self.request(state,item={'id':row['id'],'decision':'omit'},notes='saved user choice'))
        preview=session.batch_simplification(self.request(state,part_id='1/1'))
        state=session.batch_simplification(self.request(state,part_id='1/1',proposal_revision=preview['proposal_revision']),apply=True)
        actual=next(r for r in state['simplification']['proposals'] if r['id']==row['id'])
        self.assertEqual(actual['decision'],'omit')
        self.assertTrue(any(r['decision']=='pending' for r in state['simplification']['proposals'] if r['face'][0]!='1/1'))
        self.assertEqual(state['simplification']['notes'],'saved user choice')

    def test_missing_or_stale_preview_cannot_write(self):
        session=self.f.session
        original=session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):session.batch_simplification(self.request(),apply=True)
        with self.assertRaises(ValueError):session.batch_simplification(self.request(proposal_revision='stale'),apply=True)
        self.assertEqual(session.simplification_path.read_bytes(),original)


if __name__=='__main__':unittest.main()

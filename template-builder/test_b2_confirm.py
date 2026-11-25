"""Combined per-part approval is explicit, current and separate from B3."""
from pathlib import Path
import unittest
import test_b2_web as fixtures
from b2_confirm import confirmation_state, approve_part, confirmation_path


class CombinedConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebReviewTests(methodName='test_pending_handoff_blocked')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def approve(self,pid):
        state=confirmation_state(self.f.session,pid)
        return approve_part(self.f.session,dict(part_id=pid,proposal_revision=state['proposal_revision']))

    def test_preview_does_not_approve_and_one_click_binds_both_stages(self):
        state=confirmation_state(self.f.session,'1/1')
        self.assertFalse(state['approved'])
        self.assertFalse(confirmation_path(self.f.session).exists())
        self.assertTrue(state['plan']['contacts'])
        self.assertEqual(len(state['plan']['faces']),6)
        result=self.approve('1/1')
        self.assertTrue(result['approved'])
        self.assertEqual(result['approved_parts'],['1/1'])
        self.assertFalse(self.f.review.exists())
        self.assertFalse(list(self.f.bundle.glob('confirmed-b2-*')))

    def test_stale_display_rejected_and_contact_change_requires_reconfirmation(self):
        self.f.session.save(self.f.accepted())
        state=confirmation_state(self.f.session,'1/1')
        self.approve('1/1')
        request=self.f.accepted()
        request['item']['condition']['tolerance_mm']=.02
        self.f.session.save(request)
        self.assertFalse(confirmation_state(self.f.session,'1/1')['approved'])
        with self.assertRaises(ValueError):
            approve_part(self.f.session,dict(part_id='1/1',proposal_revision=state['proposal_revision']))

    def test_all_placements_materialize_guarded_handoff_in_new_directory(self):
        self.approve('1/1')
        self.approve('1/2')
        result=self.approve('1/3')
        output=Path(result['confirmed_output'])
        self.assertTrue((output/'b3-input.json').exists())
        self.assertTrue((output/'review.simplification.json').exists())
        self.assertEqual(len(result['approved_parts']),3)
        self.assertFalse(self.f.review.exists())


if __name__=='__main__':unittest.main()

"""Contact edits retain old judgments and invalidate simplification safely."""
import unittest
import test_b2_web as fixtures


class ContactReentryTests(unittest.TestCase):
    def test_contact_change_archives_both_and_marks_simplification_stale(self):
        f=fixtures.WebReviewTests(methodName='test_pending_handoff_blocked')
        f.setUp()
        self.addCleanup(f.doCleanups)
        state=f.session.save(f.accepted())
        state=f.session.start_simplification(dict(revision=state['revision'],simplification_revision=state['simplification_revision']))
        original_contact=f.review.read_bytes()
        original_simplification=f.session.simplification_path.read_bytes()
        state=f.session.save(f.accepted(f.corrected_pair))
        self.assertEqual(state['simplification_status'],'stale')
        self.assertIsNone(state['simplification'])
        contacts=list(f.bundle.glob('review.before-contact-*.json'))
        simplifications=list(f.bundle.glob('review.simplification.before-contact-*.json'))
        self.assertTrue(any(p.read_bytes()==original_contact for p in contacts))
        self.assertTrue(any(p.read_bytes()==original_simplification for p in simplifications))
        self.assertEqual(f.session.simplification_path.read_bytes(),original_simplification)
        self.assertEqual(state['draft']['reviews'][0]['faces'],f.corrected_pair)


if __name__=='__main__':unittest.main()

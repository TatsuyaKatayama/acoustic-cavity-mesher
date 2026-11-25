"""Part proposals remain advisory and preserve all source review decisions."""
from hashlib import sha256
import unittest
from b2_propose_part import propose_part
import test_b2_web as fixtures

class PartProposalTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebReviewTests(methodName='test_pending_handoff_blocked');self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.session.save(self.f.accepted())

    def test_readonly_exhaustive_part_proposal(self):
        paths=[self.f.bundle/'assembly.json',self.f.candidates,self.f.review]
        before=[sha256(p.read_bytes()).hexdigest() for p in paths]
        result=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1')
        self.assertFalse(result['approved'])
        self.assertEqual(len(result['faces']),6)
        self.assertEqual(len({tuple(f['face']) for f in result['faces']}),6)
        self.assertTrue(all(r['face'][0]=='1/1' for r in result['faces']))
        self.assertEqual(before,[sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_contact_faces_reserved_not_omitted(self):
        result=propose_part(self.f.bundle,self.f.candidates,self.f.review,'1/1')
        faces={tuple(f['face']):f['suggestion'] for f in result['faces']}
        for contact in result['contacts']:
            for ref in contact['faces']:
                if ref[0]=='1/1':self.assertEqual(faces[tuple(ref)],'keep')
        self.assertFalse(self.f.session.simplification_path.exists())

    def test_unknown_part_rejected(self):
        with self.assertRaises(ValueError):propose_part(self.f.bundle,self.f.candidates,self.f.review,'missing')

if __name__=='__main__':unittest.main()

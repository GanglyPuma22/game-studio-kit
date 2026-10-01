"""Source-basis and trajectory invariants, independent of optional ML/Blender."""
import math
import unittest
from studio_tools.adapters import unimate_motion as motion
from studio_tools.common import StudioError


def yaw(angle, position=(0, 0, 0)):
    c, s = math.cos(angle), math.sin(angle)
    return motion.rigid([[c,0,s],[0,1,0],[-s,0,c]], position)


class BakeMathTests(unittest.TestCase):
    def assertMatrix(self, actual, expected):
        self.assertLess(max(abs(actual[i][j]-expected[i][j]) for i in range(4) for j in range(4)), 1e-9)

    def fixture(self):
        # Nonunit scale, rotated source axes and nonzero canonical origin.
        C = [[0,0,2.5,3],[0,2.5,0,-2],[-2.5,0,0,1],[0,0,0,1]]
        parents = {"Helper": "Tip", "Tip": "Root", "Root": None}
        D0 = motion.joint_globals({"Root": motion.rigid(position=(0,1,0)),
                                   "Tip": motion.rigid(position=(1,0,0)),
                                   "Helper": motion.rigid(position=(0.5,0,0))}, parents)
        converted = motion.to_source(D0,C)
        # Deliberate source bone rolls differ from decoder's identity axes.
        B0 = {name: motion.multiply(converted[name], yaw(angle))
              for name,angle in (("Tip",0.7),("Root",-0.3))}
        return C, parents, D0, B0

    def test_identity_rest_recovers_original_basis_in_shuffled_storage_order(self):
        C, parents, D0, B0 = self.fixture()
        calibration = motion.source_calibration(D0,B0,C)
        recovered = motion.calibrated_source(dict(reversed(list(D0.items()))),C,calibration)
        self.assertEqual(set(recovered), {"Root","Tip"})
        for name in B0:
            self.assertMatrix(recovered[name],B0[name])

    def test_full_helper_recovery_precedes_name_projection(self):
        C, parents, D0, B0 = self.fixture()
        delta = yaw(0.4,(0.2,0.3,-0.1))
        frame = {name: motion.multiply(delta,rest) for name,rest in D0.items()}
        result = motion.calibrated_source(frame,C,motion.source_calibration(D0,B0,C))
        self.assertNotIn("Helper",result)
        self.assertEqual(set(result),set(B0))
        locals_ = motion.source_locals(result,{"Tip":"Root","Root":None})
        rebuilt = motion.joint_globals(locals_,{"Tip":"Root","Root":None})
        for name in result:
            self.assertMatrix(rebuilt[name],result[name])

    def test_raw_translated_rotated_trajectory_scales_once_and_preserves_articulation(self):
        C, parents, D0, B0 = self.fixture()
        alignment = motion.source_calibration(D0,B0,C)
        root = yaw(0.6,(1.2,1.4,-0.7))
        local_tip = yaw(-0.2,(1,0,0))
        frame = motion.joint_globals({"Root":root,"Tip":local_tip,
                                      "Helper":motion.rigid(position=(0.5,0,0))},parents)
        result = motion.calibrated_source(frame,C,alignment)
        uncalibrated = {name:motion.multiply(result[name],motion.inverse_rigid(alignment[name])) for name in result}
        # Independent inverse of C: source axes (x,y,z)=(-cz,cy,cx)/2.5.
        for name, source in uncalibrated.items():
            p = frame[name]
            self.assertMatrix(source,motion.rigid(
                [[-p[2][j] for j in range(3)], [p[1][j] for j in range(3)], [p[0][j] for j in range(3)]],
                ((1-p[2][3])/2.5,(p[1][3]+2)/2.5,(p[0][3]-3)/2.5)))
        self.assertNotEqual(result["Root"],B0["Root"])

    def test_distinct_per_bone_basis_does_not_change_source_joint_heads(self):
        C, parents, D0, B0 = self.fixture()
        trajectory = yaw(1.0,(0.4,0.2,0.7))
        frames = {name:motion.multiply(trajectory,pose) for name,pose in D0.items()}
        result = motion.calibrated_source(frames,C,motion.source_calibration(D0,B0,C))
        direct = motion.to_source(frames,C)
        for name in result:
            for axis in range(3):
                self.assertAlmostEqual(result[name][axis][3],direct[name][axis][3],places=10)

    def test_missing_joint_cycle_or_invalid_source_frame_refuses(self):
        C,parents,D0,B0 = self.fixture()
        with self.assertRaises(StudioError):
            motion.calibrated_source({"Root":D0["Root"]},C,motion.source_calibration(D0,B0,C))
        with self.assertRaises(StudioError):
            motion.joint_globals({"a":motion.rigid(),"b":motion.rigid()},{"a":"b","b":"a"})
        with self.assertRaises(StudioError):
            motion.source_calibration(D0,{"Extra":motion.rigid()},C)
        invalid = motion.rigid(); invalid[0][0] = 2
        with self.assertRaises(StudioError):
            motion.source_calibration(D0,{"Root":invalid},C)

    def test_quaternion_frame_unit_validation_and_overflow_refusal(self):
        result = motion.quaternion_frame([math.cos(.2),0,math.sin(.2),0],(1,2,3))
        self.assertMatrix(result,yaw(.4,(1,2,3)))
        for q in ([0,0,0,0],[1e308,1e308,0,0],[float("nan"),0,0,0],[2,0,0,0]):
            with self.assertRaises(StudioError):
                motion.quaternion_frame(q,(0,0,0))

    def test_float32_source_basis_is_preserved_without_weakening_canonical_frames(self):
        C,parents,D0,B0 = self.fixture()
        # Actual Blender captures can depart from orthogonality by just over
        # 1e-6. Rest calibration must retain these bytes, not normalize the rig.
        B0["Tip"][0][0] += 2e-6
        original = [row[:] for row in B0["Tip"]]
        result = motion.calibrated_source(D0,C,motion.source_calibration(D0,B0,C))
        self.assertMatrix(result["Tip"],original)
        self.assertEqual(B0["Tip"],original)
        with self.assertRaises(StudioError):
            motion.inverse_rigid(B0["Tip"])
        B0["Tip"][0][0] += 1e-3
        with self.assertRaises(StudioError):
            motion.source_calibration(D0,B0,C)

    def test_wrong_scale_or_source_rest_position_cannot_be_hidden_in_alignment(self):
        C,parents,D0,B0 = self.fixture()
        changed = [row[:] for row in C]
        for i in range(3):
            for j in range(3):
                changed[i][j] *= 2
        with self.assertRaises(StudioError):
            motion.source_calibration(D0,B0,changed)
        B0["Tip"][0][3] += .001
        with self.assertRaises(StudioError):
            motion.source_calibration(D0,B0,C)


if __name__ == "__main__":
    unittest.main()

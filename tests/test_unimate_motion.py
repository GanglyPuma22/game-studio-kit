"""Synthetic rigid-trajectory invariants; no creature/Blender quality claims."""

import math
import unittest
from studio_tools.adapters.unimate_motion import multiply, rigid, inverse_rigid, remove_trajectory, to_source, source_locals
from studio_tools.common import StudioError


def yaw(angle, position=(0, 0, 0)):
    c, s = math.cos(angle), math.sin(angle)
    return rigid([[c,0,s],[0,1,0],[-s,0,c]], position)


def pitch(angle, position=(0, 0, 0)):
    c, s = math.cos(angle), math.sin(angle)
    return rigid([[1,0,0],[0,c,-s],[0,s,c]], position)


class TrajectoryTests(unittest.TestCase):
    def assertFrame(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        for name in expected:
            for i in range(4):
                for j in range(4):
                    self.assertAlmostEqual(actual[name][i][j], expected[name][i][j], places=8)

    def test_mite_translated_rotated_trajectory_preserves_bob_and_articulation(self):
        anchor = yaw(-0.4, (7, 2, -5))
        relative = {"Root": pitch(0.1, (0, 0.12, 0)),
                    "Foot": multiply(pitch(0.1, (0, 0.12, 0)), pitch(0.2, (0.3, -0.4, 0.1)))}
        expected = {name: multiply(anchor, matrix) for name, matrix in relative.items()}
        for angle, x, z in ((0,0,0), (0.9,4,-3), (-2.5,-9,8)):
            trajectory = yaw(angle, (x, 1.25, z))
            moving = {name: multiply(trajectory, pose) for name, pose in relative.items()}
            output, removed = remove_trajectory(moving, anchor, kind="mite", reference_height=1.25)
            self.assertFrame(output, expected)
            recovered = {name: multiply(multiply(removed, inverse_rigid(anchor)), pose) for name, pose in output.items()}
            self.assertFrame(recovered, moving)
            # Zeroing Root alone cannot fix Foot, which is still in the moving frame.
            self.assertGreater(abs(moving["Foot"][0][3] - expected["Foot"][0][3]), 1)

    def test_kite_removes_full_root_motion_including_altitude_and_bank(self):
        anchor = yaw(0.3, (-2, 8, 4))
        relative = {"Root": rigid(), "Wing": pitch(-0.35, (1, 0.3, 0))}
        expected = {name: multiply(anchor, pose) for name, pose in relative.items()}
        for trajectory in (yaw(0.7, (10,20,30)), multiply(yaw(-0.8, (3,12,-9)), pitch(0.5))):
            moving = {name: multiply(trajectory, pose) for name, pose in relative.items()}
            output, removed = remove_trajectory(moving, anchor, kind="kite", reference_height=0)
            self.assertFrame(output, expected)
            self.assertFrame({name: multiply(multiply(removed, inverse_rigid(anchor)), pose) for name, pose in output.items()}, moving)

    def test_nonunit_similarity_and_source_parent_solve_reconstruct_original_frames(self):
        source = {"Root": yaw(0.2, (1,2,3)), "Foot": multiply(yaw(0.2, (1,2,3)), pitch(0.3, (0.4,-0.7,0.2)))}
        transform = yaw(1.1, (6,-3,7))
        scale = 2.4
        similarity = [row[:] for row in transform]
        for i in range(3):
            for j in range(3):similarity[i][j] *= scale
        # Construct the expected canonical frames independently: scale positions,
        # rotate the rigid orientations, then add the canonical translation.
        canonical = {}
        for name, matrix in source.items():
            rotation = [[sum(transform[i][k]*matrix[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
            position = [scale*sum(transform[i][k]*matrix[k][3] for k in range(3))+transform[i][3] for i in range(3)]
            canonical[name] = rigid(rotation, position)
        recovered = to_source(canonical, similarity)
        self.assertFrame(recovered, source)
        local = source_locals(recovered, {"Foot":"Root", "Root":None})
        self.assertFrame({"Root":local["Root"], "Foot":multiply(local["Root"],local["Foot"])}, source)
        self.assertFrame({"Foot":local["Foot"]}, {"Foot":pitch(0.3,(0.4,-0.7,0.2))})

    def test_invalid_matrices_reflection_cycles_and_vertical_heading_refuse(self):
        for matrix in ([[1,0,0,0],[0,2,0,0],[0,0,1,0],[0,0,0,1]],
                       [[-1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                       [[1,0,0,float('nan')],[0,1,0,0],[0,0,1,0],[0,0,0,1]]):
            with self.assertRaises(StudioError):to_source({"Root":rigid()}, matrix)
        with self.assertRaises(StudioError):
            source_locals({"Root":rigid(),"Foot":rigid()}, {"Root":"Foot","Foot":"Root"})
        with self.assertRaises(StudioError):
            remove_trajectory({"Root":pitch(math.pi/2)}, rigid(), kind="mite", reference_height=0)


if __name__ == "__main__":
    unittest.main()

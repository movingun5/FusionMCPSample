import copy
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.profile_geometry import (
    ProfileValidation,
    all_profile_parameter_names,
    evaluate_profile_request,
    generated_profile_parameter_names,
    validate_profile_request,
)
from tests.fakes import FakeDesign, FakeComponent


class ProfileGeometryTests(unittest.TestCase):
    def setUp(self):
        self.design = FakeDesign([FakeComponent("Root", "root")])

    @staticmethod
    def l_vertices():
        return [
            {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
            {"key": "p2", "x_expression": "50 mm", "y_expression": "-30 mm"},
            {"key": "p3", "x_expression": "50 mm", "y_expression": "30 mm"},
            {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
            {"key": "p5", "x_expression": "10 mm", "y_expression": "0 mm"},
            {"key": "p6", "x_expression": "-50 mm", "y_expression": "0 mm"},
        ]

    def normalize(self, vertices=None, depth="8 mm"):
        return validate_profile_request(
            "LProfile",
            "l_profile",
            self.l_vertices() if vertices is None else vertices,
            depth,
        )

    def code_for(self, vertices=None, depth="8 mm"):
        try:
            normalized = self.normalize(vertices=vertices, depth=depth)
            evaluate_profile_request(normalized, self.design.unitsManager)
        except ProfileValidation as error:
            return error.code
        self.fail("Expected ProfileValidation")

    def test_normalizes_without_mutating_nested_vertices_and_generates_names(self):
        vertices = self.l_vertices()
        original = copy.deepcopy(vertices)

        normalized = self.normalize(vertices)
        names = generated_profile_parameter_names(normalized)

        self.assertEqual(original, vertices)
        self.assertIsNot(vertices, normalized["vertices"])
        self.assertIsNot(vertices[0], normalized["vertices"][0])
        self.assertEqual("l_profile_depth", names["depth"])
        self.assertEqual(
            {"x": "l_profile_p1_x", "y": "l_profile_p1_y"},
            names["vertices"]["p1"],
        )

    def test_rejects_invalid_identifiers_counts_and_strict_vertex_fields(self):
        invalid_requests = [
            ("bad prefix", self.l_vertices()),
            ("l_profile", self.l_vertices()[:2]),
            (
                "l_profile",
                self.l_vertices()
                + [
                    {
                        "key": f"extra_{index}",
                        "x_expression": f"{index + 60} mm",
                        "y_expression": "0 mm",
                    }
                    for index in range(27)
                ],
            ),
        ]
        for prefix, vertices in invalid_requests:
            with self.subTest(prefix=prefix, count=len(vertices)):
                with self.assertRaises(ProfileValidation) as caught:
                    validate_profile_request(
                        "LProfile", prefix, vertices, "8 mm"
                    )
                self.assertEqual("INVALID_REQUEST", caught.exception.code)

        vertices = self.l_vertices()
        vertices[0]["unexpected"] = True
        with self.assertRaises(ProfileValidation) as caught:
            self.normalize(vertices)
        self.assertEqual("INVALID_REQUEST", caught.exception.code)

        vertices = self.l_vertices()
        vertices[1]["key"] = vertices[0]["key"]
        with self.assertRaises(ProfileValidation) as caught:
            self.normalize(vertices)
        self.assertEqual("INVALID_REQUEST", caught.exception.code)

    def test_evaluates_l_profile_and_flattens_parameter_order(self):
        evaluated = evaluate_profile_request(
            self.normalize(),
            self.design.unitsManager,
        )

        self.assertEqual(8.0, evaluated["depth_mm"])
        self.assertEqual([-50.0, -30.0], evaluated["vertices"][0]["point_mm"])
        self.assertEqual([-50.0, 0.0], evaluated["vertices"][-1]["point_mm"])
        self.assertEqual(4200.0, evaluated["area_mm2"])
        self.assertEqual(
            ["l_profile_depth"]
            + [
                f"l_profile_p{index}_{axis}"
                for index in range(1, 7)
                for axis in ("x", "y")
            ],
            all_profile_parameter_names(evaluated),
        )

    def test_accepts_clockwise_simple_polygon(self):
        evaluated = evaluate_profile_request(
            self.normalize(list(reversed(self.l_vertices()))),
            self.design.unitsManager,
        )

        self.assertEqual(4200.0, evaluated["area_mm2"])
        self.assertEqual(6, len(evaluated["vertices"]))

    def test_rejects_invalid_expression_and_nonpositive_depth(self):
        vertices = self.l_vertices()
        vertices[0]["x_expression"] = "not-a-length"
        self.assertEqual("PROFILE_EXPRESSION_INVALID", self.code_for(vertices))
        self.assertEqual("PROFILE_DEPTH_INVALID", self.code_for(depth="0 mm"))
        self.assertEqual("PROFILE_DEPTH_INVALID", self.code_for(depth="-2 mm"))

    def test_rejects_duplicate_adjacent_and_closing_vertices(self):
        adjacent = self.l_vertices()
        adjacent[1]["x_expression"] = adjacent[0]["x_expression"]
        adjacent[1]["y_expression"] = adjacent[0]["y_expression"]
        self.assertEqual("PROFILE_VERTEX_DUPLICATE", self.code_for(adjacent))

        closing = self.l_vertices()
        closing[-1]["x_expression"] = closing[0]["x_expression"]
        closing[-1]["y_expression"] = closing[0]["y_expression"]
        self.assertEqual("PROFILE_VERTEX_DUPLICATE", self.code_for(closing))

    def test_rejects_self_intersection_and_nonadjacent_touching(self):
        bow_tie = [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "40 mm", "y_expression": "40 mm"},
            {"key": "c", "x_expression": "0 mm", "y_expression": "40 mm"},
            {"key": "d", "x_expression": "40 mm", "y_expression": "0 mm"},
        ]
        self.assertEqual("PROFILE_SELF_INTERSECTION", self.code_for(bow_tie))

        touching = [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "40 mm", "y_expression": "0 mm"},
            {"key": "c", "x_expression": "20 mm", "y_expression": "20 mm"},
            {"key": "d", "x_expression": "40 mm", "y_expression": "40 mm"},
            {"key": "e", "x_expression": "0 mm", "y_expression": "40 mm"},
            {"key": "f", "x_expression": "20 mm", "y_expression": "20 mm"},
        ]
        self.assertEqual("PROFILE_SELF_INTERSECTION", self.code_for(touching))

    def test_rejects_zero_area_collinear_profile(self):
        collinear = [
            {"key": "a", "x_expression": "0 mm", "y_expression": "0 mm"},
            {"key": "b", "x_expression": "20 mm", "y_expression": "0 mm"},
            {"key": "c", "x_expression": "40 mm", "y_expression": "0 mm"},
        ]
        self.assertEqual("PROFILE_AREA_INVALID", self.code_for(collinear))


if __name__ == "__main__":
    unittest.main()

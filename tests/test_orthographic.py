import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.orthographic import (
    OrthographicValidation,
    compare_shared_dimensions,
    validate_orthographic_request,
)


class OrthographicValidationTests(unittest.TestCase):
    def view(self, plane):
        return {
            "image_path": rf"C:\drawings\{plane}.png",
            "plane": plane,
            "width_expression": "100 mm",
        }

    def assert_invalid_request(self, name="Views", views=None, tolerance=0.25):
        if views is None:
            views = [self.view("xy"), self.view("xz")]
        with self.assertRaises(OrthographicValidation) as caught:
            validate_orthographic_request(name, views, tolerance)
        self.assertEqual("INVALID_REQUEST", caught.exception.code)

    def test_accepts_two_or_three_unique_principal_views_and_sets_defaults(self):
        for planes in (("xy", "xz"), ("xy", "xz", "yz")):
            with self.subTest(planes=planes):
                name, views, tolerance = validate_orthographic_request(
                    "  Gearbox Views  ",
                    [self.view(plane) for plane in planes],
                    0.25,
                )

                self.assertEqual("Gearbox Views", name)
                self.assertEqual(list(planes), [view["plane"] for view in views])
                self.assertEqual("0 mm", views[0]["center_x_expression"])
                self.assertEqual("0 mm", views[0]["center_y_expression"])
                self.assertEqual(50, views[0]["opacity"])
                self.assertIs(False, views[0]["flip_horizontal"])
                self.assertIs(False, views[0]["flip_vertical"])
                self.assertEqual(0.25, tolerance)

    def test_rejects_wrong_count_duplicate_planes_and_unknown_fields(self):
        for views in (
            [self.view("xy")],
            [self.view("xy"), self.view("xy")],
            [self.view("xy"), self.view("xz"), self.view("yz"), self.view("xy")],
            [{**self.view("xy"), "rotation": 90}, self.view("xz")],
        ):
            with self.subTest(views=views):
                self.assert_invalid_request(views=views)

    def test_rejects_blank_name_non_list_and_invalid_view_fields(self):
        self.assert_invalid_request(name="  ")
        self.assert_invalid_request(views=(self.view("xy"), self.view("xz")))
        self.assert_invalid_request(views=[self.view("front"), self.view("xz")])
        for missing in ("image_path", "plane", "width_expression"):
            view = self.view("xy")
            del view[missing]
            with self.subTest(missing=missing):
                self.assert_invalid_request(views=[view, self.view("xz")])
        for field in (
            "image_path",
            "plane",
            "width_expression",
            "center_x_expression",
            "center_y_expression",
        ):
            view = self.view("xy")
            view[field] = " "
            with self.subTest(field=field):
                self.assert_invalid_request(views=[view, self.view("xz")])

    def test_rejects_invalid_opacity_flip_and_tolerance_types(self):
        for field, value in (
            ("opacity", -1),
            ("opacity", 101),
            ("opacity", True),
            ("opacity", 50.0),
            ("flip_horizontal", 1),
            ("flip_vertical", "yes"),
        ):
            view = self.view("xy")
            view[field] = value
            with self.subTest(field=field, value=value):
                self.assert_invalid_request(views=[view, self.view("xz")])
        for tolerance in (True, "0.25", 0, 0.0009, 10.001):
            with self.subTest(tolerance=tolerance):
                self.assert_invalid_request(tolerance=tolerance)

    def test_normalization_does_not_mutate_input_views(self):
        original = [self.view("xy"), self.view("xz")]
        _, normalized, _ = validate_orthographic_request("Views", original, 0.25)

        self.assertNotIn("opacity", original[0])
        self.assertIsNot(original[0], normalized[0])

    def test_compares_x_y_and_z_shared_dimensions(self):
        axes, checks = compare_shared_dimensions(
            [
                {"plane": "xy", "width_mm": 100.0, "height_mm": 60.0},
                {"plane": "xz", "width_mm": 100.2, "height_mm": 40.0},
                {"plane": "yz", "width_mm": 60.1, "height_mm": 40.1},
            ],
            0.25,
        )

        self.assertEqual({"x": 100.1, "y": 60.05, "z": 40.05}, axes)
        self.assertEqual(["x", "y", "z"], [item["axis"] for item in checks])
        self.assertTrue(all(item["matched"] for item in checks))
        self.assertEqual(["xy", "xz"], checks[0]["planes"])
        self.assertEqual([100.0, 100.2], checks[0]["values_mm"])
        self.assertEqual(0.2, checks[0]["difference_mm"])
        self.assertEqual(0.25, checks[0]["tolerance_mm"])

    def test_accepts_difference_exactly_at_tolerance(self):
        axes, checks = compare_shared_dimensions(
            [
                {"plane": "xy", "width_mm": 100.0, "height_mm": 60.0},
                {"plane": "xz", "width_mm": 100.25, "height_mm": 40.0},
            ],
            0.25,
        )

        self.assertEqual({"x": 100.125, "y": 60.0, "z": 40.0}, axes)
        self.assertEqual(0.25, checks[0]["difference_mm"])
        self.assertTrue(checks[0]["matched"])

    def test_rejects_shared_dimension_above_tolerance(self):
        with self.assertRaises(OrthographicValidation) as caught:
            compare_shared_dimensions(
                [
                    {"plane": "xy", "width_mm": 100.0, "height_mm": 60.0},
                    {"plane": "xz", "width_mm": 100.251, "height_mm": 40.0},
                ],
                0.25,
            )

        self.assertEqual("ORTHOGRAPHIC_DIMENSION_MISMATCH", caught.exception.code)
        self.assertEqual("x", caught.exception.details["axis"])
        self.assertEqual(0.251, caught.exception.details["difference_mm"])
        self.assertEqual(["xy", "xz"], caught.exception.details["planes"])


if __name__ == "__main__":
    unittest.main()

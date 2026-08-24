import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.plate_geometry import (
    PlateValidation,
    all_parameter_names,
    evaluate_plate_request,
    generated_parameter_names,
    validate_plate_request,
)
from tests.fakes import FakeUnitsManager


class PlateGeometryTests(unittest.TestCase):
    def request(self, **changes):
        request = {
            "name": "MountingPlate",
            "parameter_prefix": "plate",
            "width_expression": "100 mm",
            "height_expression": "60 mm",
            "thickness_expression": "5 mm",
            "holes": [
                {
                    "key": "lower_left",
                    "x_expression": "-40 mm",
                    "y_expression": "-20 mm",
                    "diameter_expression": "6 mm",
                },
                {
                    "key": "upper_left",
                    "x_expression": "-40 mm",
                    "y_expression": "20 mm",
                    "diameter_expression": "6 mm",
                },
                {
                    "key": "lower_right",
                    "x_expression": "40 mm",
                    "y_expression": "-20 mm",
                    "diameter_expression": "6 mm",
                },
                {
                    "key": "upper_right",
                    "x_expression": "40 mm",
                    "y_expression": "20 mm",
                    "diameter_expression": "6 mm",
                },
            ],
            "edge_finish": {"type": "fillet", "size_expression": "3 mm"},
        }
        request.update(changes)
        return request

    def evaluated(self, **changes):
        normalized = validate_plate_request(**self.request(**changes))
        return evaluate_plate_request(normalized, FakeUnitsManager())

    def validation_code(self, **changes):
        with self.assertRaises(PlateValidation) as caught:
            self.evaluated(**changes)
        return caught.exception.code

    def test_normalizes_request_and_generates_every_parameter_name(self):
        normalized = validate_plate_request(**self.request())
        names = generated_parameter_names(normalized)

        self.assertEqual("MountingPlate", normalized["name"])
        self.assertEqual("plate_width", names["width"])
        self.assertEqual("plate_height", names["height"])
        self.assertEqual("plate_thickness", names["thickness"])
        self.assertEqual("plate_upper_left_x", names["holes"]["upper_left"]["x"])
        self.assertEqual(
            "plate_upper_left_diameter",
            names["holes"]["upper_left"]["diameter"],
        )
        self.assertEqual("plate_edge_size", names["edge_size"])

    def test_defaults_are_fresh_and_do_not_mutate_inputs(self):
        holes = [{
            "key": "center",
            "x_expression": "0 mm",
            "y_expression": "0 mm",
            "diameter_expression": "6 mm",
        }]
        edge = {"type": "chamfer", "size_expression": "2 mm"}
        normalized = validate_plate_request(
            **self.request(holes=holes, edge_finish=edge)
        )
        normalized["holes"][0]["key"] = "changed"
        normalized["edge_finish"]["type"] = "fillet"

        self.assertEqual("center", holes[0]["key"])
        self.assertEqual("chamfer", edge["type"])
        defaults = validate_plate_request(
            **self.request(holes=None, edge_finish=None)
        )
        self.assertEqual([], defaults["holes"])
        self.assertEqual({"type": "none"}, defaults["edge_finish"])

    def test_evaluates_internal_cm_and_reports_literal_mm(self):
        evaluated = self.evaluated()

        self.assertEqual(10.0, evaluated["values_cm"]["width"])
        self.assertEqual(100.0, evaluated["values_mm"]["width"])
        self.assertEqual(5.0, evaluated["values_mm"]["thickness"])
        self.assertEqual(-40.0, evaluated["holes"][0]["x_mm"])
        self.assertEqual(6.0, evaluated["holes"][0]["diameter_mm"])
        self.assertEqual(3.0, evaluated["edge_finish"]["size_mm"])

    def test_flattens_parameter_names_in_creation_order(self):
        names = all_parameter_names(self.evaluated())

        self.assertEqual(
            [
                "plate_width",
                "plate_height",
                "plate_thickness",
                "plate_lower_left_x",
                "plate_lower_left_y",
                "plate_lower_left_diameter",
                "plate_upper_left_x",
                "plate_upper_left_y",
                "plate_upper_left_diameter",
                "plate_lower_right_x",
                "plate_lower_right_y",
                "plate_lower_right_diameter",
                "plate_upper_right_x",
                "plate_upper_right_y",
                "plate_upper_right_diameter",
                "plate_edge_size",
            ],
            names,
        )

    def test_rejects_hole_that_touches_plate_boundary(self):
        holes = [{
            "key": "edge",
            "x_expression": "47 mm",
            "y_expression": "0 mm",
            "diameter_expression": "6 mm",
        }]
        self.assertEqual(
            "PLATE_HOLE_OUT_OF_BOUNDS",
            self.validation_code(holes=holes),
        )

    def test_rejects_touching_holes(self):
        holes = [
            {
                "key": "a",
                "x_expression": "0 mm",
                "y_expression": "0 mm",
                "diameter_expression": "6 mm",
            },
            {
                "key": "b",
                "x_expression": "6 mm",
                "y_expression": "0 mm",
                "diameter_expression": "6 mm",
            },
        ]
        self.assertEqual("PLATE_HOLES_OVERLAP", self.validation_code(holes=holes))

    def test_accepts_thirty_two_non_overlapping_holes(self):
        holes = []
        for row, y_value in enumerate((-18, -6, 6, 18)):
            for column in range(8):
                holes.append({
                    "key": f"h_{row}_{column}",
                    "x_expression": f"{-42 + (column * 12)} mm",
                    "y_expression": f"{y_value} mm",
                    "diameter_expression": "2 mm",
                })

        self.assertEqual(32, len(self.evaluated(holes=holes)["holes"]))
        holes.append({
            "key": "too_many",
            "x_expression": "0 mm",
            "y_expression": "0 mm",
            "diameter_expression": "1 mm",
        })
        self.assertEqual("INVALID_REQUEST", self.validation_code(holes=holes))

    def test_rejects_invalid_identifiers_and_duplicate_hole_keys(self):
        self.assertEqual(
            "INVALID_REQUEST",
            self.validation_code(parameter_prefix="plate-width"),
        )
        invalid_key = [dict(self.request()["holes"][0], key="upper-left")]
        self.assertEqual("INVALID_REQUEST", self.validation_code(holes=invalid_key))
        duplicate = [self.request()["holes"][0], self.request()["holes"][0].copy()]
        self.assertEqual("INVALID_REQUEST", self.validation_code(holes=duplicate))

    def test_rejects_unknown_nested_fields_and_invalid_edge_shapes(self):
        unknown_hole = [dict(self.request()["holes"][0], depth_expression="5 mm")]
        self.assertEqual("INVALID_REQUEST", self.validation_code(holes=unknown_hole))
        self.assertEqual(
            "INVALID_REQUEST",
            self.validation_code(edge_finish={"type": "none", "size_expression": "2 mm"}),
        )
        self.assertEqual(
            "INVALID_REQUEST",
            self.validation_code(edge_finish={"type": "round", "size_expression": "2 mm"}),
        )

    def test_rejects_control_characters_and_empty_expressions(self):
        self.assertEqual("INVALID_REQUEST", self.validation_code(name="Bad\nName"))
        self.assertEqual(
            "INVALID_REQUEST",
            self.validation_code(width_expression=" "),
        )

    def test_rejects_invalid_or_non_length_expressions(self):
        self.assertEqual(
            "PLATE_EXPRESSION_INVALID",
            self.validation_code(width_expression="not-a-length"),
        )
        self.assertEqual(
            "PLATE_EXPRESSION_INVALID",
            self.validation_code(width_expression="90 deg"),
        )

    def test_rejects_non_positive_dimensions(self):
        for field in (
            "width_expression",
            "height_expression",
            "thickness_expression",
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    "PLATE_DIMENSION_INVALID",
                    self.validation_code(**{field: "0 mm"}),
                )
        hole = [dict(self.request()["holes"][0], diameter_expression="0 mm")]
        self.assertEqual("PLATE_DIMENSION_INVALID", self.validation_code(holes=hole))

    def test_rejects_impossible_edge_finish_size(self):
        self.assertEqual(
            "PLATE_DIMENSION_INVALID",
            self.validation_code(
                edge_finish={"type": "fillet", "size_expression": "30 mm"}
            ),
        )
        self.assertEqual(
            "PLATE_DIMENSION_INVALID",
            self.validation_code(
                edge_finish={"type": "chamfer", "size_expression": "0 mm"}
            ),
        )


if __name__ == "__main__":
    unittest.main()

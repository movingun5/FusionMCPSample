import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.profile_builder import (
    FusionProfileBuilder,
    ProfileBuildFailure,
)
from fusion_mcp_addin.fusion.profile_geometry import (
    evaluate_profile_request,
    validate_profile_request,
)
from tests.fakes import (
    FakeBody,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeOccurrences,
    FakePoint,
)


class _ExtrudeFeature(FakeFeature):
    def __init__(self, profile, distance, operation, body):
        super().__init__("Extrude", "profile-extrude-1")
        self.profile = profile
        self.distance = distance
        self.operation = operation
        self.bodies = FakeCollection([body])
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Extrudes(FakeCollection):
    def __init__(self, component, fail_add=False):
        super().__init__()
        self.component = component
        self.fail_add = fail_add

    def addSimple(self, profile, distance, operation):
        if self.fail_add:
            return None
        body = FakeBody(
            "Body1",
            "profile-body-1",
            volume=33.6,
            minimum=(-5.0, -3.0, 0.0),
            maximum=(5.0, 3.0, 0.8),
        )
        self.component.bRepBodies._items.append(body)
        feature = _ExtrudeFeature(profile, distance, operation, body)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self, component, fail_extrusion=False):
        super().__init__()
        self.extrudeFeatures = _Extrudes(component, fail_add=fail_extrusion)

    def __iter__(self):
        return iter(self.extrudeFeatures)


def _component_factory(fail_extrusion=False):
    component = FakeComponent("Component", "component-1")
    component.features = _Features(component, fail_extrusion=fail_extrusion)
    return component


class ProfileBuilderTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeComponent("Root", "root")
        self.root.occurrences = FakeOccurrences(component_factory=_component_factory)
        self.design = FakeDesign([self.root])

    @staticmethod
    def vertices():
        return [
            {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
            {"key": "p2", "x_expression": "50 mm", "y_expression": "-30 mm"},
            {"key": "p3", "x_expression": "50 mm", "y_expression": "30 mm"},
            {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
            {"key": "p5", "x_expression": "10 mm", "y_expression": "0 mm"},
            {"key": "p6", "x_expression": "-50 mm", "y_expression": "0 mm"},
        ]

    def evaluated(self):
        normalized = validate_profile_request(
            "LProfile", "l_profile", self.vertices(), "8 mm"
        )
        return evaluate_profile_request(normalized, self.design.unitsManager)

    def builder(self, *, part_design_intent="PartDesignIntentType"):
        return FusionProfileBuilder(
            self.design,
            self.root,
            point_factory=FakePoint,
            matrix_factory=lambda: object(),
            value_input_factory=lambda expression: expression,
            dimension_orientations={"horizontal": "horizontal", "vertical": "vertical"},
            new_body_operation="new-body",
            part_design_intent=part_design_intent,
        )

    def test_builds_hybrid_component_with_parameter_driven_closed_profile(self):
        result = self.builder().build("LProfile", self.evaluated())

        self.assertEqual("child_component", result["container_mode"])
        self.assertEqual("LProfile", result["component"].name)
        self.assertEqual("LProfile", result["body"].name)
        self.assertEqual("LProfile_Profile", result["profile_sketch"].name)
        self.assertEqual(6, len(result["profile_points"]))
        self.assertEqual(6, len(result["profile_lines"]))
        self.assertEqual(1, result["profile_sketch"].profiles.count)
        self.assertEqual("l_profile_depth", result["extrusion"].distance)
        self.assertEqual(13, self.design.userParameters.count)
        self.assertEqual(
            ["create_parametric_profile_extrusion:LProfile"] * 13,
            [parameter.comment for parameter in self.design.userParameters],
        )

    def test_builds_part_design_in_root_without_renaming_root(self):
        self.design.designIntent = "PartDesignIntentType"
        self.root.features = _Features(self.root)

        result = self.builder().build("LProfile", self.evaluated())

        self.assertIsNone(result["occurrence"])
        self.assertIs(self.root, result["component"])
        self.assertEqual("root_part", result["container_mode"])
        self.assertEqual("Root", self.root.name)
        self.assertEqual(0, self.root.occurrences.count)

    def test_dimensions_reference_generated_signed_coordinate_parameters(self):
        result = self.builder().build("LProfile", self.evaluated())
        expressions = [
            dimension.parameter.expression
            for dimension in result["profile_sketch"].sketchDimensions
        ]

        self.assertIn("-(l_profile_p1_x)", expressions)
        self.assertIn("-(l_profile_p1_y)", expressions)
        self.assertIn("l_profile_p3_x", expressions)
        self.assertIn("l_profile_p3_y", expressions)
        self.assertEqual(10, len(expressions))
        self.assertEqual(2, len(result["profile_sketch"].geometricConstraints._items))

    def test_rolls_back_hybrid_occurrence_and_parameters_after_extrusion_failure(self):
        self.root.occurrences = FakeOccurrences(
            component_factory=lambda: _component_factory(fail_extrusion=True)
        )
        builder = self.builder()

        with self.assertRaises(ProfileBuildFailure) as caught:
            builder.build("LProfile", self.evaluated())
        rollback = builder.rollback()

        self.assertEqual("extrusion", caught.exception.stage)
        self.assertEqual("PROFILE_EXTRUSION_FAILED", caught.exception.code)
        self.assertTrue(rollback["clean"])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)

    def test_rolls_back_exact_root_entities_and_parameters_without_transaction(self):
        self.design.designIntent = "PartDesignIntentType"
        self.root.features = _Features(self.root, fail_extrusion=True)
        builder = self.builder()

        with self.assertRaises(ProfileBuildFailure):
            builder.build("LProfile", self.evaluated())
        rollback = builder.rollback()

        self.assertTrue(rollback["clean"])
        self.assertEqual(0, self.root.sketches.count)
        self.assertEqual(0, self.design.userParameters.count)


if __name__ == "__main__":
    unittest.main()

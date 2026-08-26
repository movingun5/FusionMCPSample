import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.plate_builder import (
    FusionPlateBuilder,
    PlateBuildFailure,
)
from fusion_mcp_addin.fusion.plate_geometry import (
    evaluate_plate_request,
    validate_plate_request,
)
from tests.fakes import (
    FakeBody,
    FakeBoundingBox,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
    FakeOccurrence,
    FakeOccurrences,
    FakePoint,
)


class _ObjectCollection(FakeCollection):
    def add(self, item):
        self._items.append(item)
        return True


class _FaceEvaluator:
    def getNormalAtPoint(self, _point):
        return True, FakePoint(0.0, 0.0, 1.0)


class _PlaneGeometry:
    objectType = "Plane"


class _TopFace:
    def __init__(self, z_value):
        self.geometry = _PlaneGeometry()
        self.pointOnFace = FakePoint(0.0, 0.0, z_value)
        self.evaluator = _FaceEvaluator()


class _Edge:
    def __init__(self, minimum, maximum):
        self.boundingBox = FakeBoundingBox(minimum, maximum)


def _box_edges():
    x_min, x_max = -5.0, 5.0
    y_min, y_max = -3.0, 3.0
    z_min, z_max = 0.0, 0.5
    return [
        _Edge((x_min, y_min, z_min), (x_max, y_min, z_min)),
        _Edge((x_max, y_min, z_min), (x_max, y_max, z_min)),
        _Edge((x_min, y_max, z_min), (x_max, y_max, z_min)),
        _Edge((x_min, y_min, z_min), (x_min, y_max, z_min)),
        _Edge((x_min, y_min, z_max), (x_max, y_min, z_max)),
        _Edge((x_max, y_min, z_max), (x_max, y_max, z_max)),
        _Edge((x_min, y_max, z_max), (x_max, y_max, z_max)),
        _Edge((x_min, y_min, z_max), (x_min, y_max, z_max)),
        _Edge((x_min, y_min, z_min), (x_min, y_min, z_max)),
        _Edge((x_max, y_min, z_min), (x_max, y_min, z_max)),
        _Edge((x_max, y_max, z_min), (x_max, y_max, z_max)),
        _Edge((x_min, y_max, z_min), (x_min, y_max, z_max)),
    ]


class _ExtrudeFeature(FakeFeature):
    def __init__(self, profile, distance, operation, body):
        super().__init__("Extrude", "extrude-1")
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
            "body-1",
            volume=29.0,
            minimum=(-5.0, -3.0, 0.0),
            maximum=(5.0, 3.0, 0.5),
        )
        body.faces = FakeCollection([_TopFace(0.5)])
        body.edges = FakeCollection(_box_edges())
        self.component.bRepBodies._items.append(body)
        feature = _ExtrudeFeature(profile, distance, operation, body)
        self._items.append(feature)
        return feature


class _HoleInput:
    def __init__(self, diameter):
        self.diameter = diameter
        self.point = None
        self.distance = None
        self.participantBodies = []

    def setPositionBySketchPoint(self, point):
        self.point = point
        return True

    def setDistanceExtent(self, distance):
        self.distance = distance
        return True


class _HoleFeature(FakeFeature):
    def __init__(self, hole_input, index):
        super().__init__("Hole", f"hole-{index}")
        self.input = hole_input
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Holes(FakeCollection):
    def __init__(self, fail_add_at=None):
        super().__init__()
        self.fail_add_at = fail_add_at
        self.add_attempts = 0

    def createSimpleInput(self, diameter):
        return _HoleInput(diameter)

    def add(self, hole_input):
        self.add_attempts += 1
        if self.add_attempts == self.fail_add_at:
            return None
        feature = _HoleFeature(hole_input, self.add_attempts)
        self._items.append(feature)
        return feature


class _FilletEdgeSets:
    def __init__(self):
        self.collection = None
        self.radius = None
        self.tangent_chain = None

    def addConstantRadiusEdgeSet(self, collection, radius, tangent_chain):
        self.collection = collection
        self.radius = radius
        self.tangent_chain = tangent_chain
        return self


class _FilletInput:
    def __init__(self):
        self.edgeSetInputs = _FilletEdgeSets()


class _FilletFeature(FakeFeature):
    def __init__(self, fillet_input):
        super().__init__("Fillet", "fillet-1")
        self.input = fillet_input


class _Fillets(FakeCollection):
    def createInput(self):
        return _FilletInput()

    def add(self, fillet_input):
        feature = _FilletFeature(fillet_input)
        self._items.append(feature)
        return feature


class _ChamferEdgeSets:
    def __init__(self):
        self.collection = None
        self.distance = None
        self.tangent_chain = None

    def addEqualDistanceChamferEdgeSet(self, collection, distance, tangent_chain):
        self.collection = collection
        self.distance = distance
        self.tangent_chain = tangent_chain
        return True


class _ChamferInput:
    def __init__(self):
        self.chamferEdgeSets = _ChamferEdgeSets()


class _ChamferFeature(FakeFeature):
    def __init__(self, chamfer_input):
        super().__init__("Chamfer", "chamfer-1")
        self.input = chamfer_input


class _Chamfers(FakeCollection):
    def createInput2(self):
        return _ChamferInput()

    def add(self, chamfer_input):
        feature = _ChamferFeature(chamfer_input)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self, component, fail_hole_at=None, fail_extrusion=False):
        super().__init__()
        self.extrudeFeatures = _Extrudes(component, fail_add=fail_extrusion)
        self.holeFeatures = _Holes(fail_add_at=fail_hole_at)
        self.filletFeatures = _Fillets()
        self.chamferFeatures = _Chamfers()

    def __iter__(self):
        return iter(
            list(self.extrudeFeatures)
            + list(self.holeFeatures)
            + list(self.filletFeatures)
            + list(self.chamferFeatures)
        )


def _component_factory(fail_hole_at=None, fail_extrusion=False):
    component = FakeComponent("Component", "component-1")
    component.features = _Features(
        component,
        fail_hole_at=fail_hole_at,
        fail_extrusion=fail_extrusion,
    )
    return component


class PlateBuilderTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeComponent("Root", "root")
        self.root.occurrences = FakeOccurrences(
            component_factory=lambda: _component_factory()
        )
        self.design = FakeDesign([self.root])

    def evaluated(self, edge_finish=None, holes=None):
        request = validate_plate_request(
            "MountingPlate",
            "plate",
            "100 mm",
            "60 mm",
            "5 mm",
            holes=holes if holes is not None else [
                {"key": "lower_left", "x_expression": "-40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_left", "x_expression": "-40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
                {"key": "lower_right", "x_expression": "40 mm", "y_expression": "-20 mm", "diameter_expression": "6 mm"},
                {"key": "upper_right", "x_expression": "40 mm", "y_expression": "20 mm", "diameter_expression": "6 mm"},
            ],
            edge_finish=edge_finish or {"type": "fillet", "size_expression": "3 mm"},
        )
        return evaluate_plate_request(request, self.design.unitsManager)

    def builder(self, *, part_design_intent="PartDesignIntentType"):
        return FusionPlateBuilder(
            self.design,
            self.root,
            point_factory=FakePoint,
            matrix_factory=lambda: object(),
            value_input_factory=lambda expression: expression,
            dimension_orientations={"horizontal": "horizontal", "vertical": "vertical"},
            new_body_operation="new-body",
            object_collection_factory=_ObjectCollection,
            part_design_intent=part_design_intent,
        )

    def test_builds_part_design_in_root_without_creating_occurrence(self):
        self.design.designIntent = "PartDesignIntentType"
        self.root.features = _Features(self.root)

        result = self.builder(
            part_design_intent="PartDesignIntentType"
        ).build("MountingPlate", self.evaluated())

        self.assertIsNone(result["occurrence"])
        self.assertIs(self.root, result["component"])
        self.assertEqual("root_part", result["container_mode"])
        self.assertEqual("Root", self.root.name)
        self.assertEqual("MountingPlate", result["body"].name)
        self.assertEqual(0, self.root.occurrences.count)

    def test_builds_named_parameter_driven_four_hole_fillet_plate(self):
        result = self.builder().build("MountingPlate", self.evaluated())

        self.assertEqual("MountingPlate", result["component"].name)
        self.assertEqual("MountingPlate", result["body"].name)
        self.assertEqual("MountingPlate_Profile", result["profile_sketch"].name)
        self.assertEqual(4, len(result["hole_sketches"]))
        self.assertEqual(
            "plate_width",
            result["profile_dimensions"]["width"].parameter.expression,
        )
        self.assertEqual(
            "plate_height",
            result["profile_dimensions"]["height"].parameter.expression,
        )
        self.assertEqual("plate_thickness", result["extrusion"].distance)
        self.assertEqual(4, len(result["hole_features"]))
        self.assertEqual(
            "plate_upper_left_diameter",
            result["hole_inputs"]["upper_left"].diameter,
        )
        self.assertEqual(
            "plate_thickness",
            result["hole_inputs"]["upper_left"].distance,
        )
        self.assertEqual("MountingPlate_Fillet", result["edge_feature"].name)
        self.assertEqual("plate_edge_size", result["edge_size_input"])
        self.assertEqual(
            4,
            result["edge_feature"].input.edgeSetInputs.collection.count,
        )
        self.assertEqual(16, self.design.userParameters.count)

    def test_isolates_each_hole_in_its_own_placement_sketch(self):
        result = self.builder().build("MountingPlate", self.evaluated())

        self.assertEqual(4, len(result["hole_sketches"]))
        self.assertEqual(
            [
                "MountingPlate_lower_left_HolePlacement",
                "MountingPlate_upper_left_HolePlacement",
                "MountingPlate_lower_right_HolePlacement",
                "MountingPlate_upper_right_HolePlacement",
            ],
            [sketch.name for sketch in result["hole_sketches"]],
        )

    def test_builds_no_hole_plate_without_hidden_sketch_or_edge_feature(self):
        evaluated = self.evaluated(holes=[], edge_finish={"type": "none"})
        result = self.builder().build("MountingPlate", evaluated)

        self.assertEqual([], result["hole_sketches"])
        self.assertEqual([], result["hole_features"])
        self.assertIsNone(result["edge_feature"])
        self.assertEqual(3, self.design.userParameters.count)

    def test_constrains_profile_center_to_origin_for_later_dimension_updates(self):
        evaluated = self.evaluated(holes=[], edge_finish={"type": "none"})
        result = self.builder().build("MountingPlate", evaluated)
        sketch = result["profile_sketch"]
        construction_lines = [
            line
            for line in sketch.sketchCurves.sketchLines
            if line.isConstruction
        ]
        midpoint_constraints = [
            constraint
            for constraint in sketch.geometricConstraints
            if constraint[0] == "midpoint"
        ]

        self.assertEqual(1, len(construction_lines))
        self.assertEqual(
            [("midpoint", sketch.originPoint, construction_lines[0])],
            midpoint_constraints,
        )

    def test_builds_chamfer_on_only_vertical_outer_edges(self):
        evaluated = self.evaluated(
            holes=[],
            edge_finish={"type": "chamfer", "size_expression": "2 mm"},
        )
        result = self.builder().build("MountingPlate", evaluated)

        self.assertEqual("MountingPlate_Chamfer", result["edge_feature"].name)
        edge_set = result["edge_feature"].input.chamferEdgeSets
        self.assertEqual(4, edge_set.collection.count)
        self.assertEqual("plate_edge_size", edge_set.distance)

    def test_negative_and_zero_hole_coordinates_use_driving_constraints(self):
        holes = [
            {"key": "negative", "x_expression": "-10 mm", "y_expression": "-5 mm", "diameter_expression": "4 mm"},
            {"key": "x_zero", "x_expression": "0 mm", "y_expression": "10 mm", "diameter_expression": "4 mm"},
        ]
        result = self.builder().build("MountingPlate", self.evaluated(holes=holes))
        expressions = [
            dimension.parameter.expression
            for sketch in result["hole_sketches"]
            for dimension in sketch.sketchDimensions
        ]

        self.assertIn("-(plate_negative_x)", expressions)
        self.assertIn("-(plate_negative_y)", expressions)
        self.assertEqual(
            1,
            sum(
                len(sketch.geometricConstraints._items)
                for sketch in result["hole_sketches"]
            ),
        )

    def test_rolls_back_occurrence_and_parameters_after_hole_failure(self):
        self.root.occurrences = FakeOccurrences(
            component_factory=lambda: _component_factory(fail_hole_at=2)
        )
        builder = self.builder()

        with self.assertRaises(PlateBuildFailure) as caught:
            builder.build("MountingPlate", self.evaluated())
        rollback = builder.rollback()

        self.assertEqual("holes", caught.exception.stage)
        self.assertEqual("PLATE_HOLE_FAILED", caught.exception.code)
        self.assertTrue(rollback["clean"])
        self.assertEqual(0, self.root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)

    def test_rolls_back_parameters_when_component_creation_fails(self):
        self.root.occurrences = FakeOccurrences(fail_add=True)
        builder = self.builder()

        with self.assertRaises(PlateBuildFailure) as caught:
            builder.build("MountingPlate", self.evaluated(holes=[]))
        rollback = builder.rollback()

        self.assertEqual("component", caught.exception.stage)
        self.assertTrue(rollback["clean"])
        self.assertEqual(0, self.design.userParameters.count)


if __name__ == "__main__":
    unittest.main()

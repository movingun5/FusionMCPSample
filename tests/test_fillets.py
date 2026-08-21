from pathlib import Path
import tempfile
import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.core.audit import AuditLogger
from fusion_mcp_addin.fusion.checkpoints import clear_last_checkpoint, get_last_checkpoint
from fusion_mcp_addin.fusion.fillets import create_fillet
from tests.fakes import (
    FakeApp,
    FakeBody,
    FakeBoundingBox,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeFeature,
)


class _Edge:
    def __init__(self, minimum, maximum):
        self.boundingBox = FakeBoundingBox(minimum, maximum)


class _ObjectCollection(FakeCollection):
    def add(self, item):
        self._items.append(item)
        return True


class _EdgeSetInputs:
    def __init__(self):
        self.collection = None
        self.radius = None
        self.tangent_chain = None

    def addConstantRadiusEdgeSet(self, collection, radius, tangent_chain):
        self.collection = collection
        self.radius = radius
        self.tangent_chain = tangent_chain
        return object()


class _FilletInput:
    def __init__(self):
        self.edgeSetInputs = _EdgeSetInputs()


class _FilletFeature(FakeFeature):
    def __init__(self, fillet_input):
        super().__init__("Fillet", "fillet-1")
        self.input = fillet_input
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Fillets(FakeCollection):
    def itemByName(self, name):
        return next(
            (item for item in self._items if item.name == name and not item.deleted),
            None,
        )

    def createInput(self):
        return _FilletInput()

    def add(self, fillet_input):
        feature = _FilletFeature(fillet_input)
        self._items.append(feature)
        return feature


class _Features(FakeCollection):
    def __init__(self):
        super().__init__()
        self.filletFeatures = _Fillets(self._items)


def _box_edges():
    x_min, x_max = -2.0, 2.0
    y_min, y_max = -1.5, 1.5
    z_min, z_max = 0.0, 1.2
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


class FilletTests(unittest.TestCase):
    def setUp(self):
        clear_last_checkpoint()
        self.body = FakeBody(
            "Base Body",
            "body-1",
            volume=14.4,
            minimum=(-2.0, -1.5, 0.0),
            maximum=(2.0, 1.5, 1.2),
        )
        self.body.edges = FakeCollection(_box_edges())
        self.root = FakeComponent("Root", "root", bodies=[self.body])
        self.root.features = _Features()
        self.design = FakeDesign([self.root])
        self.app = FakeApp(self.design)
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.audit = AuditLogger(Path(self.temp_directory.name) / "audit.jsonl")

    def tearDown(self):
        clear_last_checkpoint()

    def create(self, **kwargs):
        arguments = {
            "app": self.app,
            "name": "Edge Fillet",
            "body_name": "Base Body",
            "radius_expression": "2 mm",
            "edge_selector": "all",
            "tangent_chain": True,
            "value_input_factory": lambda expression: expression,
            "object_collection_factory": _ObjectCollection,
            "audit_logger": self.audit,
        }
        arguments.update(kwargs)
        return create_fillet(**arguments)

    def test_creates_constant_radius_fillet_on_all_edges(self):
        result = self.create()

        feature = self.root.features.filletFeatures.itemByName("Edge Fillet")
        edge_set = feature.input.edgeSetInputs
        self.assertFalse(result["isError"])
        self.assertEqual(12, edge_set.collection.count)
        self.assertEqual("2 mm", edge_set.radius)
        self.assertTrue(edge_set.tangent_chain)
        self.assertEqual(2.0, result["structuredContent"]["evaluated_radius_mm"])
        self.assertEqual("create_fillet", get_last_checkpoint()["mutation"])

    def test_selects_top_bottom_and_vertical_edges(self):
        for selector in ("top", "bottom", "vertical"):
            with self.subTest(selector=selector):
                name = f"{selector} Fillet"
                result = self.create(name=name, edge_selector=selector)
                feature = self.root.features.filletFeatures.itemByName(name)
                self.assertFalse(result["isError"])
                self.assertEqual(4, feature.input.edgeSetInputs.collection.count)

    def test_missing_body_is_rejected_before_transaction(self):
        result = self.create(body_name="Missing")

        self.assertEqual("BODY_NOT_FOUND", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_non_positive_radius_is_rejected_before_transaction(self):
        result = self.create(radius_expression="0 mm")

        self.assertEqual("FILLET_RADIUS_INVALID", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_no_matching_edges_is_rejected(self):
        self.body.edges = FakeCollection(_box_edges()[:8])

        result = self.create(edge_selector="vertical")

        self.assertEqual("FILLET_EDGES_NOT_FOUND", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_duplicate_feature_name_is_rejected(self):
        self.create()
        self.app.commands.clear()

        result = self.create()

        self.assertEqual("FEATURE_NAME_CONFLICT", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_recompute_failure_aborts_transaction(self):
        self.design.compute_result = False

        result = self.create()

        self.assertEqual("RECOMPUTE_FAILED", result["error"]["code"])
        self.assertEqual("PTransaction.Abort", self.app.commands[-1])
        self.assertIn("local_traceback", self.audit.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

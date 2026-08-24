import unittest

import tests  # noqa: F401 - installs the Fusion package test bootstrap
from fusion_mcp_addin.fusion.undo import undo_with
from tests.fakes import (
    FakeApp,
    FakeCanvasInput,
    FakeCollection,
    FakeComponent,
    FakeDesign,
    FakeOccurrences,
)


class UndoTests(unittest.TestCase):
    def setUp(self):
        self.design = FakeDesign([FakeComponent("Root", "root")])
        self.app = FakeApp(self.design)

    def test_undo_without_checkpoint_is_structured_error(self):
        result = undo_with(self.app, None)

        self.assertEqual("NO_EXECUTION_CHECKPOINT", result["error"]["code"])

    def test_undo_rejects_checkpoint_from_different_document(self):
        result = undo_with(self.app, {"document_id": "another-document"})

        self.assertEqual("CHECKPOINT_DOCUMENT_MISMATCH", result["error"]["code"])
        self.assertEqual([], self.app.commands)

    def test_undo_runs_fusion_command_and_recomputes(self):
        checkpoint = {"document_id": self.design.parentDocument.id, "request_id": "request-1"}

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual("Commands.Start UndoCommand", self.app.commands[-1])
        self.assertEqual("request-1", result["undone_request_id"])

    def test_undo_reference_canvas_deletes_the_exact_checkpoint_canvas(self):
        root = self.design.rootComponent
        canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\plate.png", root.xYConstructionPlane)
        )
        canvas.name = "Reference Canvas"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas",
            "mutation": "create_reference_canvas",
            "canvas_name": "Reference Canvas",
            "canvas_entity_token": canvas.entityToken,
        }

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual(0, root.canvases.count)
        self.assertEqual("canvas_deleted", result["undo_mode"])
        self.assertNotIn("Commands.Start UndoCommand", self.app.commands)

    def test_undo_canvas_set_deletes_every_checkpoint_canvas(self):
        root = self.design.rootComponent
        xy_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\top.png", root.xYConstructionPlane)
        )
        xy_canvas.name = "Assembly_XY"
        xz_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\front.png", root.xZConstructionPlane)
        )
        xz_canvas.name = "Assembly_XZ"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas-set",
            "mutation": "create_orthographic_canvas_set",
            "component_entity_token": root.entityToken,
            "starting_canvas_count": 0,
            "canvases": [
                {"name": xy_canvas.name, "entity_token": xy_canvas.entityToken},
                {"name": xz_canvas.name, "entity_token": xz_canvas.entityToken},
            ],
        }

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual(0, root.canvases.count)
        self.assertEqual(0, result["canvas_count"])
        self.assertEqual("canvas_set_deleted", result["undo_mode"])
        self.assertEqual(
            'PTransaction.Start "Codex Undo Orthographic Canvas Set"',
            self.app.commands[0],
        )
        self.assertEqual("PTransaction.Commit", self.app.commands[-1])
        self.assertNotIn("Commands.Start UndoCommand", self.app.commands)

    def test_undo_canvas_set_refuses_partial_target_match(self):
        root = self.design.rootComponent
        xy_canvas = root.canvases.add(
            FakeCanvasInput(r"C:\reference\top.png", root.xYConstructionPlane)
        )
        xy_canvas.name = "Assembly_XY"
        unrelated = root.canvases.add(
            FakeCanvasInput(r"C:\reference\other.png", root.xZConstructionPlane)
        )
        unrelated.name = "Other"
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-canvas-set",
            "mutation": "create_orthographic_canvas_set",
            "component_entity_token": root.entityToken,
            "starting_canvas_count": 0,
            "canvases": [
                {"name": xy_canvas.name, "entity_token": xy_canvas.entityToken},
                {"name": "Assembly_XZ", "entity_token": "missing-token"},
            ],
        }

        result = undo_with(self.app, checkpoint)

        self.assertEqual("CHECKPOINT_ENTITY_NOT_FOUND", result["error"]["code"])
        self.assertEqual(2, root.canvases.count)
        self.assertFalse(xy_canvas.deleted)
        self.assertFalse(unrelated.deleted)
        self.assertEqual([], self.app.commands)

    def _plate_checkpoint(self, occurrence, parameter_names):
        return {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-plate",
            "mutation": "create_parametric_plate",
            "occurrence_entity_token": occurrence.entityToken,
            "component_entity_token": occurrence.component.entityToken,
            "parameter_names": parameter_names,
            "starting_counts": {
                "components": 1,
                "bodies": 0,
                "sketches": 0,
                "features": 0,
                "user_parameters": 0,
            },
        }

    def test_undo_parametric_plate_deletes_exact_occurrence_then_parameters(self):
        root = self.design.rootComponent
        root.occurrences = FakeOccurrences(
            component_factory=lambda: FakeComponent("MountingPlate", "component-plate")
        )
        occurrence = root.occurrences.addNewComponent(object())
        width = self.design.userParameters.add("plate_width", "100 mm", "mm", "plate")
        height = self.design.userParameters.add("plate_height", "60 mm", "mm", "plate")
        checkpoint = self._plate_checkpoint(
            occurrence,
            [width.name, height.name],
        )

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual("parametric_plate_deleted", result["undo_mode"])
        self.assertEqual(0, root.occurrences.count)
        self.assertEqual(0, self.design.userParameters.count)
        self.assertEqual(
            ['PTransaction.Start "Codex Undo Parametric Plate"', "PTransaction.Commit"],
            self.app.commands,
        )

    def test_undo_parametric_plate_refuses_missing_parameter_before_mutation(self):
        root = self.design.rootComponent
        root.occurrences = FakeOccurrences(
            component_factory=lambda: FakeComponent("MountingPlate", "component-plate")
        )
        occurrence = root.occurrences.addNewComponent(object())
        width = self.design.userParameters.add("plate_width", "100 mm", "mm", "plate")
        checkpoint = self._plate_checkpoint(
            occurrence,
            [width.name, "plate_missing"],
        )

        result = undo_with(self.app, checkpoint)

        self.assertEqual("CHECKPOINT_ENTITY_NOT_FOUND", result["error"]["code"])
        self.assertEqual(1, root.occurrences.count)
        self.assertEqual(1, self.design.userParameters.count)
        self.assertEqual([], self.app.commands)

    def test_undo_parametric_plate_refuses_component_token_mismatch(self):
        root = self.design.rootComponent
        root.occurrences = FakeOccurrences(
            component_factory=lambda: FakeComponent("MountingPlate", "component-plate")
        )
        occurrence = root.occurrences.addNewComponent(object())
        width = self.design.userParameters.add("plate_width", "100 mm", "mm", "plate")
        checkpoint = self._plate_checkpoint(occurrence, [width.name])
        checkpoint["component_entity_token"] = "wrong-component"

        result = undo_with(self.app, checkpoint)

        self.assertEqual("CHECKPOINT_ENTITY_NOT_FOUND", result["error"]["code"])
        self.assertEqual(1, root.occurrences.count)
        self.assertEqual([], self.app.commands)

    def test_undo_root_part_plate_deletes_exact_features_sketches_and_parameters(self):
        class ActiveCollection(FakeCollection):
            @property
            def count(self):
                return len([item for item in self._items if not item.deleted])

            def item(self, index):
                return [item for item in self._items if not item.deleted][index]

            def __iter__(self):
                return iter([item for item in self._items if not item.deleted])

        class Entity:
            def __init__(self, name, token, on_delete=None):
                self.name = name
                self.entityToken = token
                self.deleted = False
                self.healthState = "HealthyFeatureHealthState"
                self.errorOrWarningMessage = ""
                self.on_delete = on_delete

            def deleteMe(self):
                self.deleted = True
                if self.on_delete is not None:
                    self.on_delete()
                return True

        root = self.design.rootComponent
        body = Entity("MountingPlate", "body-part")
        profile = Entity("MountingPlate_Profile", "sketch-profile")
        holes = Entity("MountingPlate_Holes", "sketch-holes")
        extrusion = Entity(
            "MountingPlate_Extrusion",
            "feature-extrusion",
            on_delete=body.deleteMe,
        )
        hole = Entity("MountingPlate_lower_left_Hole", "feature-hole")
        fillet = Entity("MountingPlate_Fillet", "feature-fillet")
        root.bRepBodies = ActiveCollection([body])
        root.sketches = ActiveCollection([profile, holes])
        root.features = ActiveCollection([extrusion, hole, fillet])
        width = self.design.userParameters.add("plate_width", "100 mm", "mm", "plate")
        entities = {
            entity.entityToken: entity
            for entity in (body, profile, holes, extrusion, hole, fillet)
        }
        self.design.findEntityByToken = lambda token: (
            [entities[token]] if token in entities and not entities[token].deleted else []
        )
        checkpoint = {
            "document_id": self.design.parentDocument.id,
            "request_id": "request-root-part",
            "mutation": "create_parametric_plate",
            "container_mode": "root_part",
            "component_entity_token": root.entityToken,
            "occurrence_entity_token": None,
            "body_entity_token": body.entityToken,
            "feature_entity_tokens": [extrusion.entityToken, hole.entityToken, fillet.entityToken],
            "sketch_entity_tokens": [profile.entityToken, holes.entityToken],
            "parameter_names": [width.name],
            "starting_counts": {
                "components": 1,
                "bodies": 0,
                "sketches": 0,
                "features": 0,
                "user_parameters": 0,
            },
        }

        result = undo_with(self.app, checkpoint)

        self.assertFalse(result["isError"])
        self.assertEqual("parametric_root_part_deleted", result["undo_mode"])
        self.assertEqual(0, root.bRepBodies.count)
        self.assertEqual(0, root.sketches.count)
        self.assertEqual(0, root.features.count)
        self.assertEqual(0, self.design.userParameters.count)


if __name__ == "__main__":
    unittest.main()

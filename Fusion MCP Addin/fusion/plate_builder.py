"""Low-level Fusion entity builder for one parametric plate component."""

from .extrusions import _largest_profile
from .fillets import _select_edges
from .holes import _add_position_dimensions, _top_planar_face
from .sketches import _dimension_lines
from .snapshot import safe_value


class PlateBuildFailure(RuntimeError):
    """Failure tied to one stable plate build stage and error code."""

    def __init__(self, stage, code, message):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message


class FusionPlateBuilder:
    """Build Fusion entities without owning transaction or checkpoint policy."""

    def __init__(
        self,
        design,
        root,
        *,
        point_factory=None,
        matrix_factory=None,
        value_input_factory=None,
        dimension_orientations=None,
        new_body_operation=None,
        object_collection_factory=None,
    ):
        self.design = design
        self.root = root
        self.point_factory = point_factory
        self.matrix_factory = matrix_factory
        self.value_input_factory = value_input_factory
        self.dimension_orientations = dimension_orientations
        self.new_body_operation = new_body_operation
        self.object_collection_factory = object_collection_factory
        self.occurrence = None
        self.component = None
        self.parameters = []
        self._rolled_back = False

    def _resolve_factories(self):
        if (
            self.point_factory is not None
            and self.matrix_factory is not None
            and self.value_input_factory is not None
            and self.dimension_orientations is not None
            and self.new_body_operation is not None
            and self.object_collection_factory is not None
        ):
            return

        import adsk.core
        import adsk.fusion

        self.point_factory = self.point_factory or adsk.core.Point3D.create
        self.matrix_factory = self.matrix_factory or adsk.core.Matrix3D.create
        self.value_input_factory = (
            self.value_input_factory or adsk.core.ValueInput.createByString
        )
        self.dimension_orientations = self.dimension_orientations or {
            "horizontal": adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            "vertical": adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
        }
        self.new_body_operation = (
            self.new_body_operation
            if self.new_body_operation is not None
            else adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        self.object_collection_factory = (
            self.object_collection_factory or adsk.core.ObjectCollection.create
        )

    @staticmethod
    def _failure(stage, code, message):
        raise PlateBuildFailure(stage, code, message)

    def _create_component(self, name):
        occurrences = safe_value(self.root, "occurrences")
        add_new = safe_value(occurrences, "addNewComponent")
        if not callable(add_new):
            self._failure(
                "component",
                "PLATE_COMPONENT_WRITE_FAILED",
                "The root component does not expose component occurrences.",
            )
        try:
            occurrence = add_new(self.matrix_factory())
        except Exception as error:
            raise PlateBuildFailure(
                "component",
                "PLATE_COMPONENT_WRITE_FAILED",
                "Fusion could not create the plate component occurrence.",
            ) from error
        component = safe_value(occurrence, "component")
        if occurrence is None or component is None:
            self._failure(
                "component",
                "PLATE_COMPONENT_WRITE_FAILED",
                "Fusion did not return a new plate component occurrence.",
            )
        self.occurrence = occurrence
        self.component = component
        component.name = name
        return occurrence, component

    def _parameter_specs(self, name, evaluated):
        names = evaluated["parameter_names"]
        specs = [
            (names["width"], evaluated["width_expression"]),
            (names["height"], evaluated["height_expression"]),
            (names["thickness"], evaluated["thickness_expression"]),
        ]
        for hole in evaluated["holes"]:
            hole_names = names["holes"][hole["key"]]
            specs.extend(
                [
                    (hole_names["x"], hole["x_expression"]),
                    (hole_names["y"], hole["y_expression"]),
                    (hole_names["diameter"], hole["diameter_expression"]),
                ]
            )
        if "edge_size" in names:
            specs.append((names["edge_size"], evaluated["edge_finish"]["size_expression"]))
        return [(parameter_name, expression, f"create_parametric_plate:{name}") for parameter_name, expression in specs]

    def _create_parameters(self, name, evaluated):
        collection = safe_value(self.design, "userParameters")
        if collection is None:
            self._failure(
                "parameters",
                "PLATE_PARAMETER_WRITE_FAILED",
                "The active design does not expose user parameters.",
            )
        try:
            for parameter_name, expression, comment in self._parameter_specs(name, evaluated):
                parameter = collection.add(
                    parameter_name,
                    self.value_input_factory(expression),
                    "mm",
                    comment,
                )
                if parameter is None:
                    self._failure(
                        "parameters",
                        "PLATE_PARAMETER_WRITE_FAILED",
                        f"Fusion did not create user parameter {parameter_name!r}.",
                    )
                self.parameters.append(parameter)
        except PlateBuildFailure:
            raise
        except Exception as error:
            raise PlateBuildFailure(
                "parameters",
                "PLATE_PARAMETER_WRITE_FAILED",
                "Fusion could not create the plate user parameters.",
            ) from error
        return list(self.parameters)

    def _create_profile(self, name, evaluated):
        component = self.component
        sketches = safe_value(component, "sketches")
        plane = safe_value(component, "xYConstructionPlane")
        if sketches is None or plane is None:
            self._failure(
                "sketch",
                "PLATE_SKETCH_FAILED",
                "The new component does not expose an XY sketch plane.",
            )
        try:
            sketch = sketches.add(plane)
            if sketch is None:
                raise RuntimeError("Fusion did not create the profile sketch.")
            sketch.name = f"{name}_Profile"
            sketch.isComputeDeferred = True
            width = evaluated["values_cm"]["width"]
            height = evaluated["values_cm"]["height"]
            lines = sketch.sketchCurves.sketchLines.addCenterPointRectangle(
                self.point_factory(0.0, 0.0, 0.0),
                self.point_factory(width / 2.0, height / 2.0, 0.0),
            )
            if lines is None or safe_value(lines, "count", 0) != 4:
                raise RuntimeError("Fusion did not create four profile lines.")
            horizontal, vertical = _dimension_lines(lines)
            offset = max(width, height) * 0.15
            width_dimension = sketch.sketchDimensions.addDistanceDimension(
                horizontal.startSketchPoint,
                horizontal.endSketchPoint,
                self.dimension_orientations["horizontal"],
                self.point_factory(0.0, -(height / 2.0) - offset, 0.0),
            )
            height_dimension = sketch.sketchDimensions.addDistanceDimension(
                vertical.startSketchPoint,
                vertical.endSketchPoint,
                self.dimension_orientations["vertical"],
                self.point_factory((width / 2.0) + offset, 0.0, 0.0),
            )
            if width_dimension is None or height_dimension is None:
                raise RuntimeError("Fusion did not create profile dimensions.")
            width_dimension.parameter.expression = evaluated["parameter_names"]["width"]
            height_dimension.parameter.expression = evaluated["parameter_names"]["height"]
            sketch.isComputeDeferred = False
            return sketch, {"width": width_dimension, "height": height_dimension}
        except Exception as error:
            try:
                sketch.isComputeDeferred = False
            except Exception:
                pass
            raise PlateBuildFailure(
                "sketch",
                "PLATE_SKETCH_FAILED",
                "Fusion could not create the parameter-driven plate profile.",
            ) from error

    def _create_extrusion(self, name, evaluated, profile_sketch):
        features = safe_value(self.component, "features")
        extrudes = safe_value(features, "extrudeFeatures")
        if extrudes is None:
            self._failure(
                "extrusion",
                "PLATE_EXTRUSION_FAILED",
                "The new component does not expose extrusion features.",
            )
        profile, _index = _largest_profile(safe_value(profile_sketch, "profiles"))
        if profile is None:
            self._failure(
                "extrusion",
                "PLATE_EXTRUSION_FAILED",
                "The plate profile sketch has no closed profile.",
            )
        try:
            feature = extrudes.addSimple(
                profile,
                self.value_input_factory(evaluated["parameter_names"]["thickness"]),
                self.new_body_operation,
            )
            if feature is None:
                raise RuntimeError("Fusion did not create the plate extrusion.")
            feature.name = f"{name}_Extrusion"
            bodies = safe_value(feature, "bodies")
            body = bodies.item(0) if safe_value(bodies, "count", 0) else None
            if body is None or not bool(safe_value(body, "isSolid", False)):
                raise RuntimeError("The plate extrusion did not create a solid body.")
            body.name = name
            return feature, body
        except Exception as error:
            raise PlateBuildFailure(
                "extrusion",
                "PLATE_EXTRUSION_FAILED",
                "Fusion could not create the plate extrusion.",
            ) from error

    def _create_holes(self, name, evaluated, body):
        if not evaluated["holes"]:
            return None, [], {}
        sketches = safe_value(self.component, "sketches")
        features = safe_value(self.component, "features")
        holes = safe_value(features, "holeFeatures")
        top_face = _top_planar_face(body)
        if sketches is None or holes is None or top_face is None:
            self._failure(
                "holes",
                "PLATE_HOLE_FAILED",
                "The plate does not expose a planar +Z face and hole features.",
            )
        try:
            sketch = sketches.add(top_face)
            if sketch is None:
                raise RuntimeError("Fusion did not create the hole placement sketch.")
            sketch.name = f"{name}_Holes"
            sketch.isComputeDeferred = True
            points = {}
            for hole in evaluated["holes"]:
                if abs(hole["x_cm"]) <= 1e-9 and abs(hole["y_cm"]) <= 1e-9:
                    point = sketch.originPoint
                else:
                    point = sketch.sketchPoints.add(
                        self.point_factory(hole["x_cm"], hole["y_cm"], 0.0)
                    )
                    if point is None:
                        raise RuntimeError("Fusion did not create a hole placement point.")
                    hole_names = evaluated["parameter_names"]["holes"][hole["key"]]
                    _add_position_dimensions(
                        sketch,
                        point,
                        hole_names["x"],
                        hole_names["y"],
                        hole["x_cm"],
                        hole["y_cm"],
                        self.point_factory,
                        self.dimension_orientations,
                    )
                points[hole["key"]] = point
            sketch.isComputeDeferred = False

            created_features = []
            inputs = {}
            for hole in evaluated["holes"]:
                key = hole["key"]
                hole_names = evaluated["parameter_names"]["holes"][key]
                hole_input = holes.createSimpleInput(
                    self.value_input_factory(hole_names["diameter"])
                )
                if hole_input is None:
                    raise RuntimeError("Fusion did not create a simple-hole input.")
                if hole_input.setPositionBySketchPoint(points[key]) is False:
                    raise RuntimeError("Fusion rejected a hole placement point.")
                if hole_input.setDistanceExtent(
                    self.value_input_factory(evaluated["parameter_names"]["thickness"])
                ) is False:
                    raise RuntimeError("Fusion rejected the hole distance extent.")
                hole_input.participantBodies = [body]
                feature = holes.add(hole_input)
                if feature is None:
                    raise RuntimeError(f"Fusion did not create hole feature {key!r}.")
                feature.name = f"{name}_{key}_Hole"
                created_features.append(feature)
                inputs[key] = hole_input
            sketch.isVisible = False
            return sketch, created_features, inputs
        except Exception as error:
            try:
                sketch.isComputeDeferred = False
            except Exception:
                pass
            raise PlateBuildFailure(
                "holes",
                "PLATE_HOLE_FAILED",
                "Fusion could not create every parameter-driven through-hole.",
            ) from error

    def _edge_collection(self, body):
        selected = _select_edges(body, "vertical")
        if not selected:
            self._failure(
                "edge_finish",
                "PLATE_EDGE_FINISH_FAILED",
                "The plate has no stable vertical outer edges.",
            )
        collection = self.object_collection_factory()
        for edge in selected:
            if collection.add(edge) is False:
                self._failure(
                    "edge_finish",
                    "PLATE_EDGE_FINISH_FAILED",
                    "Fusion rejected a vertical edge selection.",
                )
        return collection

    def _create_edge_finish(self, name, evaluated, body):
        edge = evaluated["edge_finish"]
        if edge["type"] == "none":
            return None, None
        features = safe_value(self.component, "features")
        edge_size = evaluated["parameter_names"]["edge_size"]
        collection = self._edge_collection(body)
        try:
            if edge["type"] == "fillet":
                fillets = safe_value(features, "filletFeatures")
                fillet_input = fillets.createInput() if fillets is not None else None
                if fillet_input is None:
                    raise RuntimeError("Fusion did not create a fillet input.")
                edge_set = fillet_input.edgeSetInputs.addConstantRadiusEdgeSet(
                    collection,
                    self.value_input_factory(edge_size),
                    True,
                )
                if edge_set is None:
                    raise RuntimeError("Fusion rejected the plate fillet edge set.")
                feature = fillets.add(fillet_input)
                feature_name = f"{name}_Fillet"
            else:
                chamfers = safe_value(features, "chamferFeatures")
                chamfer_input = chamfers.createInput2() if chamfers is not None else None
                if chamfer_input is None:
                    raise RuntimeError("Fusion did not create a chamfer input.")
                added = chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                    collection,
                    self.value_input_factory(edge_size),
                    True,
                )
                if added is False:
                    raise RuntimeError("Fusion rejected the plate chamfer edge set.")
                feature = chamfers.add(chamfer_input)
                feature_name = f"{name}_Chamfer"
            if feature is None:
                raise RuntimeError("Fusion did not create the plate edge feature.")
            feature.name = feature_name
            return feature, edge_size
        except Exception as error:
            raise PlateBuildFailure(
                "edge_finish",
                "PLATE_EDGE_FINISH_FAILED",
                "Fusion could not create the requested vertical-edge finish.",
            ) from error

    def build(self, name, evaluated):
        """Create all entities in dependency order without committing them."""

        self._resolve_factories()
        occurrence, component = self._create_component(name)
        parameters = self._create_parameters(name, evaluated)
        profile, profile_dimensions = self._create_profile(name, evaluated)
        extrusion, body = self._create_extrusion(name, evaluated, profile)
        hole_sketch, hole_features, hole_inputs = self._create_holes(
            name,
            evaluated,
            body,
        )
        edge_feature, edge_size_input = self._create_edge_finish(name, evaluated, body)
        return {
            "occurrence": occurrence,
            "component": component,
            "body": body,
            "profile_sketch": profile,
            "profile_dimensions": profile_dimensions,
            "hole_sketch": hole_sketch,
            "extrusion": extrusion,
            "hole_features": hole_features,
            "hole_inputs": hole_inputs,
            "edge_feature": edge_feature,
            "edge_size_input": edge_size_input,
            "parameters": parameters,
        }

    def rollback(self):
        """Delete the created occurrence, then its now-unreferenced parameters."""

        errors = []
        deleted_occurrence = False
        deleted_parameters = []
        if not self._rolled_back:
            if self.occurrence is not None:
                try:
                    deleted_occurrence = self.occurrence.deleteMe() is not False
                    if not deleted_occurrence:
                        errors.append("occurrence deletion was rejected")
                except Exception as error:
                    errors.append(f"occurrence deletion failed: {type(error).__name__}")
            for parameter in reversed(self.parameters):
                try:
                    if parameter.deleteMe() is False:
                        errors.append(f"parameter deletion was rejected: {safe_value(parameter, 'name', '')}")
                    else:
                        deleted_parameters.append(safe_value(parameter, "name", ""))
                except Exception as error:
                    errors.append(
                        f"parameter deletion failed: {safe_value(parameter, 'name', '')}:{type(error).__name__}"
                    )
            self._rolled_back = True

        occurrence_clean = self.occurrence is None or bool(
            safe_value(self.occurrence, "deleted", False)
        )
        parameters_clean = all(
            bool(safe_value(parameter, "deleted", False))
            for parameter in self.parameters
        )
        return {
            "clean": occurrence_clean and parameters_clean and not errors,
            "deleted_occurrence": deleted_occurrence,
            "deleted_parameters": deleted_parameters,
            "errors": errors,
        }

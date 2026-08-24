"""Low-level Fusion entity builder for one parametric profile extrusion."""

from .extrusions import _largest_profile
from .holes import _add_position_dimensions
from .snapshot import safe_value


class ProfileBuildFailure(RuntimeError):
    """Failure tied to one stable profile build stage and error code."""

    def __init__(self, stage, code, message):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message


def _remove_inferred_point_constraints(point):
    """Remove constraints Fusion inferred before explicit coordinate dimensions."""

    constraints = safe_value(point, "geometricConstraints")
    count = int(safe_value(constraints, "count", 0))
    attached = [constraints.item(index) for index in range(count)]
    for constraint in reversed(attached):
        if safe_value(constraint, "isDeletable", True) is False:
            raise RuntimeError("Fusion inferred a non-deletable point constraint.")
        delete = safe_value(constraint, "deleteMe")
        if not callable(delete) or delete() is False:
            raise RuntimeError("Fusion could not remove an inferred point constraint.")


class FusionProfileBuilder:
    """Build profile entities without owning transaction or checkpoint policy."""

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
        part_design_intent=None,
    ):
        self.design = design
        self.root = root
        self.point_factory = point_factory
        self.matrix_factory = matrix_factory
        self.value_input_factory = value_input_factory
        self.dimension_orientations = dimension_orientations
        self.new_body_operation = new_body_operation
        self.part_design_intent = part_design_intent
        self.occurrence = None
        self.component = None
        self.container_mode = None
        self.parameters = []
        self.created_sketches = []
        self.created_features = []
        self._rolled_back = False

    def _resolve_factories(self):
        if all(
            value is not None
            for value in (
                self.point_factory,
                self.matrix_factory,
                self.value_input_factory,
                self.dimension_orientations,
                self.new_body_operation,
                self.part_design_intent,
            )
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
        self.part_design_intent = (
            self.part_design_intent
            if self.part_design_intent is not None
            else adsk.fusion.DesignIntentTypes.PartDesignIntentType
        )

    @staticmethod
    def _failure(stage, code, message):
        raise ProfileBuildFailure(stage, code, message)

    def _create_component(self, name):
        if safe_value(self.design, "designIntent") == self.part_design_intent:
            self.component = self.root
            self.container_mode = "root_part"
            return None, self.root

        occurrences = safe_value(self.root, "occurrences")
        add_new = safe_value(occurrences, "addNewComponent")
        if not callable(add_new):
            self._failure(
                "component",
                "PROFILE_COMPONENT_WRITE_FAILED",
                "The root component does not expose component occurrences.",
            )
        try:
            occurrence = add_new(self.matrix_factory())
        except Exception as error:
            raise ProfileBuildFailure(
                "component",
                "PROFILE_COMPONENT_WRITE_FAILED",
                "Fusion could not create the profile component occurrence.",
            ) from error
        component = safe_value(occurrence, "component")
        if occurrence is None or component is None:
            self._failure(
                "component",
                "PROFILE_COMPONENT_WRITE_FAILED",
                "Fusion did not return a new profile component occurrence.",
            )
        self.occurrence = occurrence
        self.component = component
        self.container_mode = "child_component"
        component.name = name
        return occurrence, component

    @staticmethod
    def _parameter_specs(name, evaluated):
        names = evaluated["parameter_names"]
        specs = [(names["depth"], evaluated["depth_expression"])]
        for vertex in evaluated["vertices"]:
            vertex_names = names["vertices"][vertex["key"]]
            specs.extend(
                [
                    (vertex_names["x"], vertex["x_expression"]),
                    (vertex_names["y"], vertex["y_expression"]),
                ]
            )
        comment = f"create_parametric_profile_extrusion:{name}"
        return [(parameter_name, expression, comment) for parameter_name, expression in specs]

    def _create_parameters(self, name, evaluated):
        collection = safe_value(self.design, "userParameters")
        if collection is None:
            self._failure(
                "parameters",
                "PROFILE_PARAMETER_WRITE_FAILED",
                "The active design does not expose user parameters.",
            )
        try:
            for parameter_name, expression, comment in self._parameter_specs(
                name, evaluated
            ):
                parameter = collection.add(
                    parameter_name,
                    self.value_input_factory(expression),
                    "mm",
                    comment,
                )
                if parameter is None:
                    raise RuntimeError(
                        f"Fusion did not create user parameter {parameter_name!r}."
                    )
                self.parameters.append(parameter)
        except Exception as error:
            raise ProfileBuildFailure(
                "parameters",
                "PROFILE_PARAMETER_WRITE_FAILED",
                "Fusion could not create the profile user parameters.",
            ) from error
        return list(self.parameters)

    def _create_profile(self, name, evaluated):
        sketches = safe_value(self.component, "sketches")
        plane = safe_value(self.component, "xYConstructionPlane")
        if sketches is None or plane is None:
            self._failure(
                "sketch",
                "PROFILE_SKETCH_FAILED",
                "The profile component does not expose an XY sketch plane.",
            )
        sketch = None
        try:
            sketch = sketches.add(plane)
            if sketch is None:
                raise RuntimeError("Fusion did not create the profile sketch.")
            self.created_sketches.append(sketch)
            sketch.name = f"{name}_Profile"
            sketch.isComputeDeferred = True
            profile_points = []
            names = evaluated["parameter_names"]["vertices"]
            for vertex in evaluated["vertices"]:
                if abs(vertex["x_cm"]) <= 1e-9 and abs(vertex["y_cm"]) <= 1e-9:
                    point = sketch.originPoint
                else:
                    point = sketch.sketchPoints.add(
                        self.point_factory(vertex["x_cm"], vertex["y_cm"], 0.0)
                    )
                    if point is None:
                        raise RuntimeError("Fusion did not create a profile sketch point.")
                    _remove_inferred_point_constraints(point)
                    vertex_names = names[vertex["key"]]
                    _add_position_dimensions(
                        sketch,
                        point,
                        vertex_names["x"],
                        vertex_names["y"],
                        vertex["x_cm"],
                        vertex["y_cm"],
                        self.point_factory,
                        self.dimension_orientations,
                    )
                profile_points.append(point)

            sketch_lines = safe_value(safe_value(sketch, "sketchCurves"), "sketchLines")
            add_line = safe_value(sketch_lines, "addByTwoPoints")
            if not callable(add_line):
                raise RuntimeError("Fusion does not expose straight profile-line creation.")
            profile_lines = []
            for index, point in enumerate(profile_points):
                line = add_line(point, profile_points[(index + 1) % len(profile_points)])
                if line is None:
                    raise RuntimeError("Fusion did not create every profile line.")
                profile_lines.append(line)

            sketch.isComputeDeferred = False
            if safe_value(safe_value(sketch, "profiles"), "count", 0) != 1:
                raise RuntimeError("The sketch did not produce exactly one closed profile.")
            return sketch, profile_points, profile_lines
        except Exception as error:
            if sketch is not None:
                try:
                    sketch.isComputeDeferred = False
                except Exception:
                    pass
            raise ProfileBuildFailure(
                "sketch",
                "PROFILE_SKETCH_FAILED",
                "Fusion could not create the parameter-driven closed profile.",
            ) from error

    def _create_extrusion(self, name, evaluated, profile_sketch):
        features = safe_value(self.component, "features")
        extrudes = safe_value(features, "extrudeFeatures")
        if extrudes is None:
            self._failure(
                "extrusion",
                "PROFILE_EXTRUSION_FAILED",
                "The profile component does not expose extrusion features.",
            )
        profile, _index = _largest_profile(safe_value(profile_sketch, "profiles"))
        if profile is None:
            self._failure(
                "extrusion",
                "PROFILE_EXTRUSION_FAILED",
                "The profile sketch has no closed profile.",
            )
        try:
            feature = extrudes.addSimple(
                profile,
                self.value_input_factory(evaluated["parameter_names"]["depth"]),
                self.new_body_operation,
            )
            if feature is None:
                raise RuntimeError("Fusion did not create the profile extrusion.")
            feature.name = f"{name}_Extrusion"
            self.created_features.append(feature)
            bodies = safe_value(feature, "bodies")
            body = bodies.item(0) if safe_value(bodies, "count", 0) else None
            if body is None or not bool(safe_value(body, "isSolid", False)):
                raise RuntimeError("The profile extrusion did not create a solid body.")
            body.name = name
            return feature, body
        except Exception as error:
            raise ProfileBuildFailure(
                "extrusion",
                "PROFILE_EXTRUSION_FAILED",
                "Fusion could not create the profile extrusion.",
            ) from error

    def build(self, name, evaluated):
        """Create all entities in dependency order without committing them."""

        self._resolve_factories()
        occurrence, component = self._create_component(name)
        parameters = self._create_parameters(name, evaluated)
        sketch, points, lines = self._create_profile(name, evaluated)
        extrusion, body = self._create_extrusion(name, evaluated, sketch)
        return {
            "occurrence": occurrence,
            "component": component,
            "container_mode": self.container_mode,
            "parameters": parameters,
            "profile_sketch": sketch,
            "profile_points": points,
            "profile_lines": lines,
            "extrusion": extrusion,
            "body": body,
        }

    def rollback(self):
        """Delete the exact created container/entities, then generated parameters."""

        errors = []
        deleted_occurrence = False
        deleted_features = []
        deleted_sketches = []
        deleted_parameters = []
        if not self._rolled_back:
            if self.occurrence is not None:
                try:
                    deleted_occurrence = self.occurrence.deleteMe() is not False
                    if not deleted_occurrence:
                        errors.append("occurrence deletion was rejected")
                except Exception as error:
                    errors.append(f"occurrence deletion failed: {type(error).__name__}")
            else:
                for feature in reversed(self.created_features):
                    try:
                        if feature.deleteMe() is False:
                            errors.append("feature deletion was rejected")
                        else:
                            deleted_features.append(safe_value(feature, "name", ""))
                    except Exception as error:
                        errors.append(f"feature deletion failed: {type(error).__name__}")
                for sketch in reversed(self.created_sketches):
                    try:
                        if sketch.deleteMe() is False:
                            errors.append("sketch deletion was rejected")
                        else:
                            deleted_sketches.append(safe_value(sketch, "name", ""))
                    except Exception as error:
                        errors.append(f"sketch deletion failed: {type(error).__name__}")
            for parameter in reversed(self.parameters):
                try:
                    if parameter.deleteMe() is False:
                        errors.append(
                            f"parameter deletion was rejected: {safe_value(parameter, 'name', '')}"
                        )
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
        root_entities_clean = self.occurrence is not None or (
            all(bool(safe_value(feature, "deleted", False)) for feature in self.created_features)
            and all(bool(safe_value(sketch, "deleted", False)) for sketch in self.created_sketches)
        )
        parameters_clean = all(
            bool(safe_value(parameter, "deleted", False)) for parameter in self.parameters
        )
        return {
            "clean": occurrence_clean and root_entities_clean and parameters_clean and not errors,
            "deleted_occurrence": deleted_occurrence,
            "deleted_features": deleted_features,
            "deleted_sketches": deleted_sketches,
            "deleted_parameters": deleted_parameters,
            "errors": errors,
        }

class FakeCollection:
    def __init__(self, items=()):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def __iter__(self):
        return iter(self._items)


class FakePoint:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class FakeBoundingBox:
    def __init__(self, minimum, maximum):
        self.minPoint = FakePoint(*minimum)
        self.maxPoint = FakePoint(*maximum)


class FakeBody:
    def __init__(self, name, token, volume=0.0, minimum=(0, 0, 0), maximum=(0, 0, 0)):
        self.name = name
        self.entityToken = token
        self.volume = volume
        self.boundingBox = FakeBoundingBox(minimum, maximum)
        self.isSolid = True


class FakeSketch:
    def __init__(self, name, token, profile_count=0):
        self.name = name
        self.entityToken = token
        self.profiles = FakeCollection([object()] * profile_count)
        self.isComputeDeferred = False


class FakeSketchPoint:
    def __init__(self, point):
        self.geometry = point


class FakeSketchLine:
    def __init__(self, start, end):
        self.startSketchPoint = (
            start if isinstance(start, FakeSketchPoint) else FakeSketchPoint(start)
        )
        self.endSketchPoint = (
            end if isinstance(end, FakeSketchPoint) else FakeSketchPoint(end)
        )


class FakeSketchLines(FakeCollection):
    def __init__(self, sketch):
        super().__init__()
        self.sketch = sketch
        self.last_center = None
        self.last_corner = None

    def addCenterPointRectangle(self, center, corner):
        self.last_center = center
        self.last_corner = corner
        opposite_x = (2.0 * center.x) - corner.x
        opposite_y = (2.0 * center.y) - corner.y
        lower_left = FakePoint(opposite_x, opposite_y, 0.0)
        lower_right = FakePoint(corner.x, opposite_y, 0.0)
        upper_right = FakePoint(corner.x, corner.y, 0.0)
        upper_left = FakePoint(opposite_x, corner.y, 0.0)
        self._items = [
            FakeSketchLine(lower_left, lower_right),
            FakeSketchLine(lower_right, upper_right),
            FakeSketchLine(upper_right, upper_left),
            FakeSketchLine(upper_left, lower_left),
        ]
        self.sketch.profiles = FakeCollection([object()])
        return self

    def addByTwoPoints(self, start, end):
        line = FakeSketchLine(start, end)
        self._items.append(line)
        if (
            len(self._items) >= 3
            and self._items[-1].endSketchPoint is self._items[0].startSketchPoint
        ):
            self.sketch.profiles = FakeCollection([object()])
        return line


class FakeSketchCurves:
    def __init__(self, sketch):
        self.sketchLines = FakeSketchLines(sketch)


class FakeDimensionParameter:
    def __init__(self):
        self.expression = ""


class FakeSketchDimension:
    def __init__(self, orientation):
        self.orientation = orientation
        self.parameter = FakeDimensionParameter()


class FakeSketchDimensions(FakeCollection):
    def addDistanceDimension(self, point_one, point_two, orientation, text_point):
        dimension = FakeSketchDimension(orientation)
        self._items.append(dimension)
        return dimension


class FakeSketchPoints(FakeCollection):
    def add(self, point):
        sketch_point = FakeSketchPoint(point)
        self._items.append(sketch_point)
        return sketch_point


class FakeGeometricConstraints(FakeCollection):
    def addVerticalPoints(self, point_one, point_two):
        constraint = ("vertical-points", point_one, point_two)
        self._items.append(constraint)
        return constraint

    def addHorizontalPoints(self, point_one, point_two):
        constraint = ("horizontal-points", point_one, point_two)
        self._items.append(constraint)
        return constraint


class FakeCreatedSketch(FakeSketch):
    def __init__(self, plane, token):
        super().__init__("Sketch", token)
        self.plane = plane
        self.deleted = False
        self.sketchCurves = FakeSketchCurves(self)
        self.sketchDimensions = FakeSketchDimensions()
        self.originPoint = FakeSketchPoint(FakePoint(0.0, 0.0, 0.0))
        self.sketchPoints = FakeSketchPoints()
        self.geometricConstraints = FakeGeometricConstraints()
        self.isVisible = True

    def deleteMe(self):
        self.deleted = True
        return True


class FakeSketches(FakeCollection):
    @property
    def count(self):
        return len([item for item in self._items if not getattr(item, "deleted", False)])

    def item(self, index):
        return [
            item for item in self._items if not getattr(item, "deleted", False)
        ][index]

    def __iter__(self):
        return iter([
            item for item in self._items if not getattr(item, "deleted", False)
        ])

    def itemByName(self, name):
        return next(
            (
                item
                for item in self._items
                if item.name == name and not getattr(item, "deleted", False)
            ),
            None,
        )

    def add(self, plane):
        sketch = FakeCreatedSketch(plane, f"sketch-{len(self._items) + 1}")
        self._items.append(sketch)
        return sketch


class FakeFeature:
    def __init__(self, name, token, health="HealthyFeatureHealthState"):
        self.name = name
        self.entityToken = token
        self.healthState = health
        self.errorOrWarningMessage = "" if "Healthy" in health else "failed"


class FakePoint2D:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y


class FakeVector2D:
    def __init__(self, x=0.0, y=0.0):
        self.x = x
        self.y = y

    @property
    def length(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5


class FakeMatrix2D:
    def __init__(self):
        self.origin = FakePoint2D()
        self.x_axis = FakeVector2D(2.0, 0.0)
        self.y_axis = FakeVector2D(0.0, 1.0)

    def getAsCoordinateSystem(self):
        return self.origin, self.x_axis, self.y_axis

    def setWithCoordinateSystem(self, origin, x_axis, y_axis):
        self.origin = origin
        self.x_axis = x_axis
        self.y_axis = y_axis
        return True


class FakeCanvasInput:
    def __init__(self, image_filename, plane):
        self.imageFilename = image_filename
        self.planarEntity = plane
        self.transform = FakeMatrix2D()
        self.opacity = 50
        self.isSelectable = False
        self.isDisplayedThrough = True
        self.isRenderable = False


class FakeCanvas:
    def __init__(self, canvas_input, token, collection=None):
        self.name = "Canvas"
        self.entityToken = token
        self.imageFilename = canvas_input.imageFilename
        self.planarEntity = canvas_input.planarEntity
        self.transform = canvas_input.transform
        self.opacity = canvas_input.opacity
        self.isSelectable = canvas_input.isSelectable
        self.isDisplayedThrough = canvas_input.isDisplayedThrough
        self.isRenderable = canvas_input.isRenderable
        self.deleted = False
        self.collection = collection

    def deleteMe(self):
        self.deleted = True
        if self.collection is not None:
            self.collection.deleted_tokens.append(self.entityToken)
        return True


class FakeCanvases(FakeCollection):
    def __init__(self, items=(), fail_input=False, fail_add=False, fail_add_at=None):
        super().__init__(items)
        self.fail_input = fail_input
        self.fail_add = fail_add
        self.fail_add_at = fail_add_at
        self.add_attempts = 0
        self.deleted_tokens = []
        self.aspect_ratio = 2.0

    @property
    def count(self):
        return len([item for item in self._items if not item.deleted])

    def item(self, index):
        return [item for item in self._items if not item.deleted][index]

    def __iter__(self):
        return iter([item for item in self._items if not item.deleted])

    def itemByName(self, name):
        return next(
            (item for item in self._items if item.name == name and not item.deleted),
            None,
        )

    def createInput(self, image_filename, plane):
        if self.fail_input:
            return None
        canvas_input = FakeCanvasInput(image_filename, plane)
        canvas_input.transform.x_axis = FakeVector2D(self.aspect_ratio, 0.0)
        return canvas_input

    def add(self, canvas_input):
        self.add_attempts += 1
        if self.fail_add or self.add_attempts == self.fail_add_at:
            return None
        canvas = FakeCanvas(
            canvas_input,
            f"canvas-{len(self._items) + 1}",
            collection=self,
        )
        self._items.append(canvas)
        return canvas


class FakeOccurrence:
    def __init__(self, component, token, collection):
        self.component = component
        self.entityToken = token
        self._collection = collection
        self.deleted = False
        self.fail_delete = False

    def deleteMe(self):
        if self.fail_delete:
            return False
        self.deleted = True
        return True


class FakeOccurrences(FakeCollection):
    def __init__(self, items=(), component_factory=None, fail_add=False):
        super().__init__(items)
        self.component_factory = component_factory
        self.fail_add = fail_add

    @property
    def count(self):
        return len([item for item in self._items if not item.deleted])

    def item(self, index):
        return [item for item in self._items if not item.deleted][index]

    def __iter__(self):
        return iter([item for item in self._items if not item.deleted])

    def addNewComponent(self, _matrix):
        if self.fail_add:
            return None
        index = len(self._items) + 1
        factory = self.component_factory or (
            lambda: FakeComponent("Component", f"component-{index}")
        )
        component = factory()
        occurrence = FakeOccurrence(component, f"occurrence-{index}", self)
        self._items.append(occurrence)
        return occurrence


class FakeComponent:
    def __init__(
        self,
        name,
        token,
        bodies=(),
        sketches=(),
        features=(),
        model_parameters=(),
        canvases=(),
        occurrences=None,
    ):
        self.name = name
        self.entityToken = token
        self.bRepBodies = FakeCollection(bodies)
        self.sketches = FakeSketches(sketches)
        self.features = FakeCollection(features)
        self.modelParameters = FakeCollection(model_parameters)
        self.canvases = FakeCanvases(canvases)
        self.occurrences = occurrences or FakeOccurrences()
        self.xYConstructionPlane = object()
        self.xZConstructionPlane = object()
        self.yZConstructionPlane = object()


class FakeParameter:
    def __init__(self, name, expression, unit="mm", value=0.0, comment=""):
        self.name = name
        self.expression = expression
        self.unit = unit
        self.value = value
        self.comment = comment
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class FakeModelParameter(FakeParameter):
    def __init__(
        self,
        name,
        expression,
        role,
        created_by,
        component=None,
        unit="mm",
        value=0.0,
    ):
        super().__init__(name, expression, unit=unit, value=value)
        self.role = role
        self.createdBy = created_by
        self.component = component
        self.entityToken = f"parameter-{name}"


class FakeUserParameters(FakeCollection):
    @property
    def count(self):
        return len([item for item in self._items if not item.deleted])

    def item(self, index):
        return [item for item in self._items if not item.deleted][index]

    def __iter__(self):
        return iter([item for item in self._items if not item.deleted])

    def itemByName(self, name):
        return next(
            (item for item in self._items if item.name == name and not item.deleted),
            None,
        )

    def add(self, name, value_input, unit, comment):
        parameter = FakeParameter(
            name,
            value_input,
            unit,
            value=0.0,
            comment=comment,
        )
        self._items.append(parameter)
        return parameter


class FakeTimeline:
    def __init__(self, marker_position=0, count=0):
        self.markerPosition = marker_position
        self.count = count


class FakeUnitsManager:
    defaultLengthUnits = "mm"

    def evaluateExpression(self, expression, unit):
        parts = expression.split()
        number = float(parts[0])
        source = parts[1] if len(parts) > 1 else unit
        factors_to_cm = {"mm": 0.1, "cm": 1.0, "in": 2.54}
        if source not in factors_to_cm or unit not in factors_to_cm:
            raise ValueError("unsupported or incompatible unit")
        return number * factors_to_cm[source]


class FakeDocument:
    def __init__(self, name="Design", document_id="doc-1", saved=True):
        self.name = name
        self.id = document_id
        self.isSaved = saved


class FakeAllComponents:
    def __init__(self, components):
        self._roots = list(components)

    def _current(self):
        result = []
        seen = set()

        def add_component(component):
            if component is None or id(component) in seen:
                return
            seen.add(id(component))
            result.append(component)
            for occurrence in getattr(component, "occurrences", ()):
                add_component(getattr(occurrence, "component", None))

        for component in self._roots:
            add_component(component)
        return result

    @property
    def count(self):
        return len(self._current())

    def item(self, index):
        return self._current()[index]

    def __iter__(self):
        return iter(self._current())


class FakeDesign:
    def __init__(self, components=(), parameters=(), document=None):
        components = list(components)
        self.rootComponent = components[0] if components else FakeComponent("Root", "root")
        self.activeComponent = self.rootComponent
        self.allComponents = FakeAllComponents(components or [self.rootComponent])
        self.userParameters = FakeUserParameters(parameters)
        self.timeline = FakeTimeline(marker_position=2, count=2)
        self.unitsManager = FakeUnitsManager()
        self.designType = "ParametricDesignType"
        self.parentDocument = document or FakeDocument()
        self.compute_result = True

    def computeAll(self):
        return self.compute_result


class FakeViewport:
    pass


class FakeApp:
    def __init__(self, design=None, document=None):
        self.activeProduct = design
        self.activeDocument = document or (design.parentDocument if design else None)
        self.activeViewport = FakeViewport()
        self.logs = []
        self.commands = []

    def getVersion(self):
        return "2.0-test"

    def log(self, message):
        self.logs.append(message)

    def executeTextCommand(self, command):
        self.commands.append(command)
        return ""


class FakeUI:
    def __init__(self, approval=True):
        self.approval = approval
        self.messages = []

    def messageBox(self, message, *args):
        self.messages.append(message)
        return "DialogYes" if self.approval else "DialogNo"


class FakeExportManager:
    def __init__(self):
        self.executed = []

    def createSTEPExportOptions(self, path, entity):
        return {"format": "step", "path": path, "entity": entity}

    def createSTLExportOptions(self, entity, path):
        return {"format": "stl", "path": path, "entity": entity}

    def execute(self, options):
        from pathlib import Path

        self.executed.append(options)
        Path(options["path"]).write_bytes(b"fusion-export")
        return True

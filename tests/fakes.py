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


class FakeFeature:
    def __init__(self, name, token, health="HealthyFeatureHealthState"):
        self.name = name
        self.entityToken = token
        self.healthState = health
        self.errorOrWarningMessage = "" if "Healthy" in health else "failed"


class FakeComponent:
    def __init__(self, name, token, bodies=(), sketches=(), features=()):
        self.name = name
        self.entityToken = token
        self.bRepBodies = FakeCollection(bodies)
        self.sketches = FakeCollection(sketches)
        self.features = FakeCollection(features)


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


class FakeDesign:
    def __init__(self, components=(), parameters=(), document=None):
        components = list(components)
        self.rootComponent = components[0] if components else FakeComponent("Root", "root")
        self.activeComponent = self.rootComponent
        self.allComponents = FakeCollection(components or [self.rootComponent])
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

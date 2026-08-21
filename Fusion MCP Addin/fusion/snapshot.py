"""Serializable Fusion design snapshots and expected-change comparison."""


def iter_collection(collection):
    """Yield items from Fusion collections or ordinary Python iterables."""

    if collection is None:
        return
    count = getattr(collection, "count", None)
    item_method = getattr(collection, "item", None)
    if isinstance(count, int) and callable(item_method):
        for index in range(count):
            yield item_method(index)
        return
    for item in collection:
        yield item


def safe_value(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def entity_token(entity):
    return safe_value(entity, "entityToken") or safe_value(entity, "tempId")


def _point_mm(point):
    if point is None:
        return None
    return [round(float(safe_value(point, axis, 0.0)) * 10.0, 6) for axis in ("x", "y", "z")]


def body_summary(body):
    bounds = safe_value(body, "boundingBox")
    minimum = _point_mm(safe_value(bounds, "minPoint")) if bounds else None
    maximum = _point_mm(safe_value(bounds, "maxPoint")) if bounds else None
    size = None
    if minimum is not None and maximum is not None:
        size = [round(maximum[index] - minimum[index], 6) for index in range(3)]
    return {
        "name": safe_value(body, "name", ""),
        "entity_token": entity_token(body),
        "is_solid": bool(safe_value(body, "isSolid", False)),
        "volume_cm3": safe_value(body, "volume"),
        "bounding_box_mm": {"min": minimum, "max": maximum},
        "size_mm": size,
    }


def _feature_summary(feature):
    health = str(safe_value(feature, "healthState", "unknown"))
    return {
        "name": safe_value(feature, "name", ""),
        "entity_token": entity_token(feature),
        "health": health,
        "message": safe_value(feature, "errorOrWarningMessage", ""),
    }


def _is_healthy_feature(feature):
    health = feature["health"]
    return health == "0" or "healthy" in health.lower()


def capture_snapshot(design):
    """Capture JSON-serializable design state from the current request."""

    if design is None or safe_value(design, "rootComponent") is None:
        raise ValueError("NO_ACTIVE_DESIGN")

    components = list(iter_collection(safe_value(design, "allComponents")))
    if not components:
        components = [design.rootComponent]

    bodies = []
    sketches = []
    features = []
    for component in components:
        bodies.extend(body_summary(body) for body in iter_collection(safe_value(component, "bRepBodies")))
        sketches.extend(
            {
                "name": safe_value(sketch, "name", ""),
                "entity_token": entity_token(sketch),
                "profile_count": safe_value(safe_value(sketch, "profiles"), "count", 0),
                "compute_deferred": bool(safe_value(sketch, "isComputeDeferred", False)),
            }
            for sketch in iter_collection(safe_value(component, "sketches"))
        )
        features.extend(
            _feature_summary(feature)
            for feature in iter_collection(safe_value(component, "features"))
        )

    failed_features = [feature for feature in features if not _is_healthy_feature(feature)]
    parameters = [
        {
            "name": safe_value(parameter, "name", ""),
            "expression": safe_value(parameter, "expression", ""),
            "unit": safe_value(parameter, "unit", ""),
        }
        for parameter in iter_collection(safe_value(design, "userParameters"))
    ]
    timeline = safe_value(design, "timeline")
    document = safe_value(design, "parentDocument")

    return {
        "document": {
            "id": safe_value(document, "id"),
            "name": safe_value(document, "name"),
            "saved": bool(safe_value(document, "isSaved", False)),
        },
        "design_type": str(safe_value(design, "designType", "unknown")),
        "active_component": safe_value(safe_value(design, "activeComponent"), "name"),
        "timeline": {
            "marker_position": safe_value(timeline, "markerPosition"),
            "count": safe_value(timeline, "count"),
        },
        "counts": {
            "components": len(components),
            "bodies": len(bodies),
            "sketches": len(sketches),
            "features": len(features),
        },
        "parameters": parameters,
        "bodies": bodies,
        "sketches": sketches,
        "features": features,
        "failed_features": failed_features,
    }


def compare_snapshots(before, after, expected=None):
    """Compare count deltas and check explicit ``*_created`` expectations."""

    expected = expected or {}
    before_counts = before.get("counts", {})
    after_counts = after.get("counts", {})
    names = sorted(set(before_counts) | set(after_counts))
    delta = {
        name: int(after_counts.get(name, 0)) - int(before_counts.get(name, 0))
        for name in names
    }
    mismatches = []
    checked = {}
    for collection_name in ("components", "bodies", "sketches", "features"):
        key = f"{collection_name}_created"
        if key not in expected:
            continue
        wanted = int(expected[key])
        actual = delta.get(collection_name, 0)
        checked[key] = {"expected": wanted, "actual": actual}
        if wanted != actual:
            mismatches.append(f"{key}: expected {wanted}, actual {actual}")

    failed_features = after.get("failed_features", [])
    if failed_features:
        mismatches.append(f"failed_features: {len(failed_features)}")

    return {
        "delta": delta,
        "checked_expectations": checked,
        "expectations_met": not mismatches,
        "mismatches": mismatches,
        "failed_features": failed_features,
    }

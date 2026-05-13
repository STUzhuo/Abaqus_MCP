from __future__ import print_function

import json
import os
import sys
import traceback

from abaqusConstants import MISES
from odbAccess import openOdb


def _safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _label(value, name):
    item = _safe_attr(value, name, None)
    if item is None:
        return None
    try:
        return int(item)
    except Exception:
        return item


def _instance_name(value):
    instance = _safe_attr(value, "instance", None)
    if instance is None:
        return None
    return _safe_attr(instance, "name", None)


def _magnitude(data):
    try:
        return float(sum(float(x) * float(x) for x in data) ** 0.5)
    except TypeError:
        return abs(float(data))


def _max_vector(field):
    best = None
    for value in field.values:
        mag = _safe_attr(value, "magnitude", None)
        if mag is None:
            mag = _magnitude(value.data)
        mag = float(mag)
        if best is None or mag > best["magnitude"]:
            best = {
                "magnitude": mag,
                "node_label": _label(value, "nodeLabel"),
                "element_label": _label(value, "elementLabel"),
                "instance": _instance_name(value),
                "data": list(value.data) if hasattr(value.data, "__iter__") else value.data,
            }
    return best


def _max_scalar(field):
    best = None
    for value in field.values:
        data = float(value.data)
        if best is None or data > best["value"]:
            best = {
                "value": data,
                "node_label": _label(value, "nodeLabel"),
                "element_label": _label(value, "elementLabel"),
                "instance": _instance_name(value),
            }
    return best


def summarize_odb(odb_path, step_name=None):
    odb = openOdb(path=odb_path, readOnly=True)
    try:
        step_names = list(odb.steps.keys())
        if not step_names:
            raise RuntimeError("ODB contains no steps")
        selected_step_name = step_name or step_names[-1]
        if selected_step_name not in odb.steps:
            raise RuntimeError("Step not found: %s" % selected_step_name)

        # Keep the summary deliberately small.  Pulling full field data through
        # MCP would be slow and usually unnecessary for first-pass diagnostics.
        instances = []
        for name, instance in odb.rootAssembly.instances.items():
            instances.append(
                {
                    "name": name,
                    "nodes": len(instance.nodes),
                    "elements": len(instance.elements),
                }
            )

        steps = []
        for name, step in odb.steps.items():
            steps.append(
                {
                    "name": name,
                    "frames": len(step.frames),
                    "description": _safe_attr(step, "description", ""),
                    "domain": str(_safe_attr(step, "domain", "")),
                }
            )

        step = odb.steps[selected_step_name]
        if len(step.frames) == 0:
            raise RuntimeError("Selected step has no frames: %s" % selected_step_name)
        frame = step.frames[-1]
        field_names = list(frame.fieldOutputs.keys())

        measurements = {}
        if "U" in frame.fieldOutputs:
            measurements["max_displacement"] = _max_vector(frame.fieldOutputs["U"])
        if "RF" in frame.fieldOutputs:
            measurements["max_reaction_force"] = _max_vector(frame.fieldOutputs["RF"])
        if "S" in frame.fieldOutputs:
            # Abaqus stores stress as tensors; the MCP tool reports a scalar
            # Mises maximum because it is the fastest useful health check.
            mises = frame.fieldOutputs["S"].getScalarField(invariant=MISES)
            measurements["max_mises"] = _max_scalar(mises)
        if "PEEQ" in frame.fieldOutputs:
            measurements["max_peeq"] = _max_scalar(frame.fieldOutputs["PEEQ"])

        return {
            "odb_path": os.path.abspath(odb_path),
            "selected_step": selected_step_name,
            "selected_frame": {
                "index": len(step.frames) - 1,
                "frame_value": _safe_attr(frame, "frameValue", None),
                "description": _safe_attr(frame, "description", ""),
            },
            "steps": steps,
            "instances": instances,
            "field_outputs": field_names,
            "measurements": measurements,
        }
    finally:
        odb.close()


def main(argv):
    if len(argv) < 3:
        raise SystemExit("Usage: odb_extract.py <odb_path> <output_json> [step_name]")
    odb_path = argv[1]
    output_json = argv[2]
    step_name = argv[3] if len(argv) > 3 else None
    try:
        summary = summarize_odb(odb_path, step_name=step_name)
        payload = {"ok": True, "summary": summary}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        raise
    finally:
        with open(output_json, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv)

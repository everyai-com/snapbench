"""Result validation.

A small JSON Schema validator covering exactly the keywords the result schema
uses, so the runner works on a bare Python (Termux, Windows) with no pip
installs. tests/test_schema.py cross-checks it against the `jsonschema`
package when that is installed.
"""

import json
import os
import re

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schema", "result-v1.schema.json")

SUPPORTED = {"$schema", "$id", "title", "description", "type", "const", "enum", "required",
             "properties", "additionalProperties", "propertyNames", "items", "pattern",
             "minimum", "maxLength", "$ref", "$defs"}

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def load_schema(path=SCHEMA_PATH):
    with open(path) as f:
        return json.load(f)


def validate(doc, schema=None):
    """Return a list of 'path: problem' strings; empty means valid."""
    schema = schema or load_schema()
    errors = []
    _check(doc, schema, schema, "$", errors)
    return errors


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError("only local $ref supported: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(v, s, root, path, errors):
    unknown = set(s) - SUPPORTED
    if unknown:
        raise ValueError("schema keyword(s) not supported by snapbench validator: %s" % sorted(unknown))
    if "$ref" in s:
        _check(v, _resolve(root, s["$ref"]), root, path, errors)
    if "type" in s:
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_TYPES[t](v) for t in types):
            errors.append("%s: expected %s, got %s" % (path, "/".join(types), type(v).__name__))
            return
    if "const" in s and v != s["const"]:
        errors.append("%s: must be %r" % (path, s["const"]))
    if "enum" in s and v not in s["enum"]:
        errors.append("%s: %r not one of %s" % (path, v, s["enum"]))
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errors.append("%s: %r does not match %s" % (path, v, s["pattern"]))
        if "maxLength" in s and len(v) > s["maxLength"]:
            errors.append("%s: longer than %d characters" % (path, s["maxLength"]))
    if _TYPES["number"](v) and "minimum" in s and v < s["minimum"]:
        errors.append("%s: %r is below %r" % (path, v, s["minimum"]))
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errors.append("%s: missing required field %r" % (path, k))
        props = s.get("properties", {})
        extra = s.get("additionalProperties", True)
        names = s.get("propertyNames")
        for k, sub in v.items():
            p = "%s.%s" % (path, k)
            if names is not None:
                _check(k, names, root, p + " (name)", errors)
            if k in props:
                _check(sub, props[k], root, p, errors)
            elif extra is False:
                errors.append("%s: unexpected field" % p)
            elif isinstance(extra, dict):
                _check(sub, extra, root, p, errors)
    if isinstance(v, list) and "items" in s:
        for i, item in enumerate(v):
            _check(item, s["items"], root, "%s[%d]" % (path, i), errors)


def acceptance_errors(doc):
    """Extra rules for files in results/: real runs on Snapdragon hardware only."""
    errs = []
    if doc.get("provenance") != "measured":
        errs.append("provenance is %r; only 'measured' runs belong in results/" % doc.get("provenance"))
    if not doc.get("soc", {}).get("is_snapdragon"):
        errs.append("device is not detected as Snapdragon")
    if not any(r.get("status") in ("ok", "partial") for r in doc.get("runs", [])):
        errs.append("no successful runs")
    return errs


def validate_file(path, accept=False):
    with open(path) as f:
        try:
            doc = json.load(f)
        except ValueError as e:
            return ["$: not valid JSON: %s" % e]
    errs = validate(doc)
    if accept and not errs:
        errs = acceptance_errors(doc)
    return errs

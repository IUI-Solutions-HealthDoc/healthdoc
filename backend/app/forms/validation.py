"""Validate data against the stored form version; never infer clinical ranges."""
import math
import re
from datetime import date

from app.forms.schemas import FormFieldDef


def validate_submission(fields: list[FormFieldDef], data: dict) -> None:
    if set(data) - {field.id for field in fields}:
        raise ValueError("Response contains fields not defined by this form version")
    for field in fields:
        value = data.get(field.id)
        empty = value is None or (isinstance(value, str) and not value.strip())
        if empty:
            if field.required:
                raise ValueError(f"Missing required field: {field.label}")
            continue
        valid = False
        if field.type == "number":
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
        elif field.type == "checkbox":
            valid = isinstance(value, bool)
        elif field.type in ("text", "textarea"):
            valid = isinstance(value, str) and len(value) <= 10000
        elif field.type == "select":
            valid = isinstance(value, str) and value in {option.value for option in field.options or []}
        elif field.type == "date":
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    date.fromisoformat(value)
                    valid = True
                except ValueError:
                    pass
        if not valid:
            # Never echo the submitted clinical value into logs/error toasts.
            raise ValueError(f"Invalid {field.type} response for field: {field.label}")

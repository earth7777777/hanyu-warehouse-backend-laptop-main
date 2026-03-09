"""Minimal RM Inbound field mapping for Stage S4 / Step 2.

Do NOT add business logic here. Keep mapping only.
"""

RM_INBOUND_FIELD_MAP = {
    "pallet_id": "f17",
}


def get_rm_inbound_field(field_key: str) -> str:
    """Resolve logical field name to actual RM Inbound fieldname."""
    return RM_INBOUND_FIELD_MAP.get(field_key, field_key)


def get_rm_inbound_value(doc, field_key: str):
    """Read value by logical field name from a RM Inbound doc."""
    return doc.get(get_rm_inbound_field(field_key))


def set_rm_inbound_value(doc, field_key: str, value):
    """Write value by logical field name to a RM Inbound doc."""
    doc.set(get_rm_inbound_field(field_key), value)

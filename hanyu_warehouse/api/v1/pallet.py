import json

import frappe
from frappe.utils import now_datetime


CONTRACT_VERSION = "v1"


def _resp(ok: bool, **kwargs):
    payload = {"contract_version": CONTRACT_VERSION, "ok": ok}
    payload.update(kwargs)
    return payload


def _to_str(value) -> str:
    return str(value or "").strip()


def _serialize_pallet(doc):
    contents = []
    for row in (doc.get("contents") or []):
        contents.append(
            {
                "material_code": row.get("material_code"),
                "material_name": row.get("material_name"),
                "batch_no": row.get("batch_no"),
                "qty": row.get("qty"),
                "uom": row.get("uom"),
            }
        )

    return {
        "name": doc.name,
        "pallet_code": doc.get("pallet_code"),
        "rm_inbound": doc.get("rm_inbound"),
        "supplier": doc.get("supplier"),
        "posting_date": doc.get("posting_date"),
        "item_code": doc.get("item_code"),
        "item_name": doc.get("item_name"),
        "batch_no": doc.get("batch_no"),
        "qty": doc.get("qty"),
        "uom": doc.get("uom"),
        "warehouse": doc.get("warehouse"),
        "contents": contents,
    }


def _get_pallet_by_code_doc(pallet_code: str):
    pallet_name = frappe.db.get_value("Pallet", {"pallet_code": pallet_code}, "name")
    if not pallet_name:
        return None
    return frappe.get_doc("Pallet", pallet_name)


@frappe.whitelist(methods=["POST"])
def create_or_get(pallet_code=None, rm_inbound=None):
    try:
        code = _to_str(pallet_code)
        inbound_name = _to_str(rm_inbound)

        if not code:
            return _resp(False, error="pallet_code is required")

        doc = _get_pallet_by_code_doc(code)
        if doc:
            return _resp(True, action="get", pallet=_serialize_pallet(doc))

        if not inbound_name:
            return _resp(False, error="rm_inbound is required when creating pallet")
        if not frappe.db.exists("RM Inbound", inbound_name):
            return _resp(False, error=f"RM Inbound not found: {inbound_name}")

        doc = frappe.get_doc(
            {
                "doctype": "Pallet",
                "pallet_code": code,
                "rm_inbound": inbound_name,
            }
        )
        doc.insert(ignore_permissions=True)
        return _resp(True, action="create", pallet=_serialize_pallet(doc))
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "pallet.create_or_get")
        return _resp(False, error=str(ex))


@frappe.whitelist(methods=["GET"])
def get_by_code(pallet_code=None):
    try:
        code = _to_str(pallet_code)
        if not code:
            return _resp(False, error="pallet_code is required")

        doc = _get_pallet_by_code_doc(code)
        if not doc:
            return _resp(False, error=f"Pallet not found by code: {code}")

        return _resp(True, pallet=_serialize_pallet(doc))
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "pallet.get_by_code")
        return _resp(False, error=str(ex))


@frappe.whitelist(methods=["GET"])
def generate_label_payload(pallet_code=None):
    try:
        code = _to_str(pallet_code)
        if not code:
            return _resp(False, error="pallet_code is required")

        doc = _get_pallet_by_code_doc(code)
        if not doc:
            return _resp(False, error=f"Pallet not found by code: {code}")

        label_data = {
            "contract_version": CONTRACT_VERSION,
            "pallet_id": doc.name,
            "pallet_code": doc.get("pallet_code"),
            "rm_inbound": doc.get("rm_inbound"),
            "supplier": doc.get("supplier"),
            "item_code": doc.get("item_code"),
            "item_name": doc.get("item_name"),
            "batch_no": doc.get("batch_no"),
            "qty": doc.get("qty"),
            "uom": doc.get("uom"),
            "warehouse": doc.get("warehouse"),
            "generated_at": now_datetime().isoformat(),
        }
        qr_payload = json.dumps(label_data, ensure_ascii=False)

        return _resp(True, label=label_data, qr_payload=qr_payload)
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "pallet.generate_label_payload")
        return _resp(False, error=str(ex))

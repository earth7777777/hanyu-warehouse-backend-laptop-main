import json

import frappe


CONTRACT_VERSION = "v1"


def _resp(ok: bool, **kwargs):
    payload = {"contract_version": CONTRACT_VERSION, "ok": ok}
    payload.update(kwargs)
    return payload


def _to_str(value) -> str:
    return str(value or "").strip()


def _parse_dict(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _collect_payload(payload, kwargs):
    data = _parse_dict(payload)
    for key, value in (kwargs or {}).items():
        if key in {"payload", "cmd"}:
            continue
        if value is not None:
            data[key] = value
    return data


def _check_contract_version(contract_version):
    if _to_str(contract_version) != CONTRACT_VERSION:
        return _resp(
            False,
            error="contract_version must be v1",
            error_code="INVALID_CONTRACT_VERSION",
        )
    return None


def _check_permission(doctype, ptype):
    if frappe.has_permission(doctype, ptype=ptype):
        return None
    return _resp(
        False,
        error=f"permission denied: {doctype} {ptype}",
        error_code="PERMISSION_DENIED",
    )


def _serialize_scrap(doc):
    process_trace = []
    raw_json = doc.get("process_event_trace_json")
    if raw_json:
        try:
            process_trace = json.loads(raw_json)
        except Exception:
            process_trace = []

    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "recycle_batch_id": doc.get("recycle_batch_id"),
        "reason": doc.get("reason"),
        "loss_amount": doc.get("loss_amount"),
        "closed_at": doc.get("closed_at"),
        "is_close_applied": doc.get("is_close_applied"),
        "process_event_trace": process_trace,
    }


def _serialize_batch(batch_doc):
    return {
        "name": batch_doc.name,
        "process_status": batch_doc.get("process_status"),
        "total_cost_accumulated": batch_doc.get("total_cost_accumulated"),
        "is_closed": batch_doc.get("is_closed"),
        "closed_by_scrap": batch_doc.get("closed_by_scrap"),
        "closed_at": batch_doc.get("closed_at"),
    }


@frappe.whitelist(methods=["POST"])
def submit_and_close(
    contract_version=None,
    recycle_scrap=None,
    recycle_batch_id=None,
    reason=None,
    payload=None,
    **kwargs,
):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("Recycle Scrap", "submit")
        if permission_error and not frappe.has_permission("Recycle Scrap", ptype="create"):
            return permission_error

        scrap_name = _to_str(recycle_scrap) or _to_str(data.get("recycle_scrap"))
        submit_done = False

        if scrap_name:
            if not frappe.db.exists("Recycle Scrap", scrap_name):
                return _resp(
                    False,
                    error=f"Recycle Scrap not found: {scrap_name}",
                    error_code="RECYCLE_SCRAP_NOT_FOUND",
                )
            doc = frappe.get_doc("Recycle Scrap", scrap_name)
        else:
            batch_id = _to_str(recycle_batch_id) or _to_str(data.get("recycle_batch_id"))
            reason_value = _to_str(reason) or _to_str(data.get("reason"))

            if not batch_id:
                return _resp(
                    False,
                    error="recycle_batch_id is required",
                    error_code="RECYCLE_BATCH_ID_REQUIRED",
                )
            if not reason_value:
                return _resp(
                    False,
                    error="reason is required",
                    error_code="SCRAP_REASON_REQUIRED",
                )

            doc = frappe.get_doc(
                {
                    "doctype": "Recycle Scrap",
                    "recycle_batch_id": batch_id,
                    "reason": reason_value,
                }
            )
            doc.insert(ignore_permissions=True)

        if doc.docstatus == 0:
            doc.submit()
            submit_done = True

        if hasattr(doc, "close_batch_if_needed"):
            doc.close_batch_if_needed()
            doc.reload()

        batch_doc = frappe.get_doc("Recycle Batch", doc.get("recycle_batch_id"))

        return _resp(
            True,
            submit_done=submit_done,
            recycle_scrap=_serialize_scrap(doc),
            recycle_batch=_serialize_batch(batch_doc),
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "recycle_scrap.submit_and_close")
        error_code = "PERMISSION_DENIED" if isinstance(ex, frappe.PermissionError) else "UNKNOWN_ERROR"
        text = _to_str(ex)
        if "RECYCLE_BATCH_ID_REQUIRED" in text:
            error_code = "RECYCLE_BATCH_ID_REQUIRED"
        if "RECYCLE_BATCH_NOT_FOUND" in text:
            error_code = "RECYCLE_BATCH_NOT_FOUND"
        if "RECYCLE_BATCH_ALREADY_CLOSED" in text:
            error_code = "RECYCLE_BATCH_ALREADY_CLOSED"
        if "LOSS_AMOUNT_MISMATCH" in text:
            error_code = "LOSS_AMOUNT_MISMATCH"
        if "SCRAP_CLOSE_ONLY_VIA_RECYCLE_SCRAP" in text:
            error_code = "SCRAP_CLOSE_ONLY_VIA_RECYCLE_SCRAP"
        return _resp(False, error=str(ex), error_code=error_code)

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


def _parse_list(raw):
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    return []


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


def _serialize_process(doc):
    cost_rows = []
    for row in doc.get("cost_breakdown") or []:
        cost_rows.append(
            {
                "cost_item": row.get("cost_item"),
                "amount": row.get("amount"),
                "note": row.get("note"),
            }
        )

    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "recycle_batch_id": doc.get("recycle_batch_id"),
        "process_type": doc.get("process_type"),
        "total_cost": doc.get("total_cost"),
        "cost_breakdown": cost_rows,
        "is_applied": doc.get("is_applied"),
        "applied_at": doc.get("applied_at"),
        "batch_total_before_apply": doc.get("batch_total_before_apply"),
        "batch_total_after_apply": doc.get("batch_total_after_apply"),
        "remarks": doc.get("remarks"),
    }


def _serialize_batch(batch_doc):
    return {
        "name": batch_doc.name,
        "process_status": batch_doc.get("process_status"),
        "total_cost_accumulated": batch_doc.get("total_cost_accumulated"),
        "is_closed": batch_doc.get("is_closed"),
    }


@frappe.whitelist(methods=["POST"])
def create_draft(contract_version=None, payload=None, cost_breakdown=None, **kwargs):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("Recycle Process", "create")
        if permission_error:
            return permission_error

        doc = frappe.get_doc(
            {
                "doctype": "Recycle Process",
                "recycle_batch_id": data.get("recycle_batch_id"),
                "process_type": data.get("process_type"),
                "total_cost": data.get("total_cost"),
                "remarks": data.get("remarks"),
                "cost_breakdown": [],
            }
        )

        rows = _parse_list(cost_breakdown)
        if not rows:
            rows = _parse_list(data.get("cost_breakdown"))

        for row in rows:
            if not isinstance(row, dict):
                continue
            doc.append(
                "cost_breakdown",
                {
                    "cost_item": row.get("cost_item"),
                    "amount": row.get("amount"),
                    "note": row.get("note"),
                },
            )

        doc.insert(ignore_permissions=True)

        return _resp(True, recycle_process=_serialize_process(doc))
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "recycle_process.create_draft")
        error_code = "PERMISSION_DENIED" if isinstance(ex, frappe.PermissionError) else "UNKNOWN_ERROR"
        if "RECYCLE_BATCH_ID_REQUIRED" in _to_str(ex):
            error_code = "RECYCLE_BATCH_ID_REQUIRED"
        if "RECYCLE_BATCH_NOT_FOUND" in _to_str(ex):
            error_code = "RECYCLE_BATCH_NOT_FOUND"
        if "TOTAL_COST_REQUIRED" in _to_str(ex):
            error_code = "TOTAL_COST_REQUIRED"
        return _resp(False, error=str(ex), error_code=error_code)


@frappe.whitelist(methods=["POST"])
def submit_and_apply(
    contract_version=None,
    recycle_process=None,
    payload=None,
    **kwargs,
):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("Recycle Process", "submit")
        if permission_error and not frappe.has_permission("Recycle Process", ptype="write"):
            return permission_error

        process_name = _to_str(recycle_process) or _to_str(data.get("recycle_process"))
        if not process_name:
            return _resp(
                False,
                error="recycle_process is required",
                error_code="RECYCLE_PROCESS_ID_REQUIRED",
            )

        if not frappe.db.exists("Recycle Process", process_name):
            return _resp(
                False,
                error=f"Recycle Process not found: {process_name}",
                error_code="RECYCLE_PROCESS_NOT_FOUND",
            )

        doc = frappe.get_doc("Recycle Process", process_name)

        submit_done = False
        if doc.docstatus == 0:
            doc.submit()
            submit_done = True

        if hasattr(doc, "apply_to_batch_if_needed"):
            doc.apply_to_batch_if_needed()
            doc.reload()

        batch_doc = frappe.get_doc("Recycle Batch", doc.get("recycle_batch_id"))

        return _resp(
            True,
            submit_done=submit_done,
            recycle_process=_serialize_process(doc),
            recycle_batch=_serialize_batch(batch_doc),
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "recycle_process.submit_and_apply")
        error_code = "PERMISSION_DENIED" if isinstance(ex, frappe.PermissionError) else "UNKNOWN_ERROR"
        if "RECYCLE_BATCH_CLOSED" in _to_str(ex):
            error_code = "RECYCLE_BATCH_CLOSED"
        if "TOTAL_COST_REQUIRED" in _to_str(ex):
            error_code = "TOTAL_COST_REQUIRED"
        if "RECYCLE_BATCH_NOT_FOUND" in _to_str(ex):
            error_code = "RECYCLE_BATCH_NOT_FOUND"
        return _resp(False, error=str(ex), error_code=error_code)

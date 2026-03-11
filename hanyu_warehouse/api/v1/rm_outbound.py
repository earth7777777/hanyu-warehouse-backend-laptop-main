import json

import frappe
from frappe.utils import cint, get_datetime, now_datetime


CONTRACT_VERSION = "v1"
ERROR_CODE_CANDIDATES = (
    "INVALID_CONTRACT_VERSION",
    "PERMISSION_DENIED",
    "OUTBOUND_ID_REQUIRED",
    "OUTBOUND_NOT_FOUND",
    "OUTBOUND_NOT_SUBMITTED",
    "OUTBOUND_CANCELLED",
    "REROUTE_REASON_REQUIRED",
    "REROUTE_NO_CHANGE",
    "INSUFFICIENT_STOCK",
    "SOURCE_LOCATION_REQUIRED",
    "ITEM_CODE_REQUIRED",
    "BATCH_NO_REQUIRED",
    "MACHINE_REQUIRED",
    "STOCK_VALIDATION_UNAVAILABLE",
)


def _resp(ok: bool, **kwargs):
    payload = {"contract_version": CONTRACT_VERSION, "ok": ok}
    payload.update(kwargs)
    return payload


def _to_str(value) -> str:
    return str(value or "").strip()


def _parse_json_object(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _collect_payload(payload, kwargs):
    data = _parse_json_object(payload)
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


def _extract_error_code(ex):
    if isinstance(ex, frappe.PermissionError):
        return "PERMISSION_DENIED"

    message = _to_str(ex)
    for code in ERROR_CODE_CANDIDATES:
        if code in message:
            return code
    return "UNKNOWN_ERROR"


def _serialize_outbound(doc):
    posting = (
        doc.get_posting_snapshot()
        if hasattr(doc, "get_posting_snapshot")
        else {
            "is_posted": cint(doc.get("is_posted")),
            "posted_at": doc.get("posted_at"),
            "available_qty_before_post": doc.get("available_qty_before_post"),
            "available_qty_after_post": doc.get("available_qty_after_post"),
        }
    )

    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "posting_date": doc.get("posting_date"),
        "outbound_mode": doc.get("outbound_mode"),
        "pallet_id": doc.get("pallet_id"),
        "source_location_id": doc.get("source_location_id"),
        "item_code": doc.get("item_code"),
        "batch_no": doc.get("batch_no"),
        "qty": doc.get("qty"),
        "uom": doc.get("uom"),
        "machine_id": doc.get("machine_id"),
        "work_order_id": doc.get("work_order_id"),
        "purpose": doc.get("purpose"),
        "machine_required_effective": cint(doc.get("machine_required_effective")),
        "posting": posting,
    }


def _serialize_destination_change(doc):
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "outbound_id": doc.get("outbound_id"),
        "from_machine_id": doc.get("from_machine_id"),
        "to_machine_id": doc.get("to_machine_id"),
        "from_work_order_id": doc.get("from_work_order_id"),
        "to_work_order_id": doc.get("to_work_order_id"),
        "from_purpose": doc.get("from_purpose"),
        "to_purpose": doc.get("to_purpose"),
        "reason": doc.get("reason"),
        "operator": doc.get("operator"),
        "timestamp": doc.get("timestamp"),
    }


@frappe.whitelist(methods=["POST"])
def create_draft(contract_version=None, payload=None, **kwargs):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("RM Outbound", "create")
        if permission_error:
            return permission_error

        doc_fields = [
            "posting_date",
            "pallet_id",
            "source_location_id",
            "item_code",
            "batch_no",
            "qty",
            "uom",
            "machine_id",
            "work_order_id",
            "purpose",
        ]

        draft_data = {"doctype": "RM Outbound"}
        for fieldname in doc_fields:
            if data.get(fieldname) is not None:
                draft_data[fieldname] = data.get(fieldname)

        doc = frappe.get_doc(draft_data)
        doc.insert(ignore_permissions=True)

        return _resp(True, rm_outbound=_serialize_outbound(doc))
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "rm_outbound.create_draft")
        return _resp(False, error=str(ex), error_code=_extract_error_code(ex))


@frappe.whitelist(methods=["POST"])
def submit_and_post(contract_version=None, rm_outbound=None, payload=None, **kwargs):
    submit_done = False
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("RM Outbound", "submit")
        if permission_error and not frappe.has_permission("RM Outbound", ptype="write"):
            return permission_error

        outbound_name = _to_str(rm_outbound) or _to_str(data.get("rm_outbound")) or _to_str(
            data.get("outbound_id")
        )
        if not outbound_name:
            return _resp(
                False,
                error="rm_outbound is required",
                error_code="OUTBOUND_ID_REQUIRED",
                submit_done=False,
            )

        if not frappe.db.exists("RM Outbound", outbound_name):
            return _resp(
                False,
                error=f"RM Outbound not found: {outbound_name}",
                error_code="OUTBOUND_NOT_FOUND",
                submit_done=False,
            )

        doc = frappe.get_doc("RM Outbound", outbound_name)
        if doc.docstatus == 2:
            return _resp(
                False,
                error="RM Outbound is cancelled and cannot be submitted",
                error_code="OUTBOUND_CANCELLED",
                submit_done=False,
            )

        if doc.docstatus == 0:
            doc.submit()
            submit_done = True

        if doc.docstatus != 1:
            return _resp(
                False,
                error="RM Outbound is not submitted",
                error_code="OUTBOUND_NOT_SUBMITTED",
                submit_done=submit_done,
            )

        if not cint(doc.get("is_posted")) and hasattr(doc, "apply_posting"):
            doc.apply_posting()

        doc.reload()

        return _resp(
            True,
            submit_done=submit_done,
            rm_outbound=_serialize_outbound(doc),
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "rm_outbound.submit_and_post")
        return _resp(
            False,
            error=str(ex),
            error_code=_extract_error_code(ex),
            submit_done=submit_done,
        )


@frappe.whitelist(methods=["POST"])
def reroute(
    contract_version=None,
    rm_outbound=None,
    to_machine_id=None,
    to_work_order_id=None,
    to_purpose=None,
    reason=None,
    operator=None,
    timestamp=None,
    payload=None,
    **kwargs,
):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("RM Outbound", "write")
        if permission_error:
            return permission_error

        outbound_name = _to_str(rm_outbound) or _to_str(data.get("rm_outbound")) or _to_str(
            data.get("outbound_id")
        )
        if not outbound_name:
            return _resp(
                False,
                error="rm_outbound is required",
                error_code="OUTBOUND_ID_REQUIRED",
            )

        if not frappe.db.exists("RM Outbound", outbound_name):
            return _resp(
                False,
                error=f"RM Outbound not found: {outbound_name}",
                error_code="OUTBOUND_NOT_FOUND",
            )

        outbound_doc = frappe.get_doc("RM Outbound", outbound_name)
        if outbound_doc.docstatus != 1:
            return _resp(
                False,
                error="reroute only supports submitted RM Outbound",
                error_code="OUTBOUND_NOT_SUBMITTED",
            )

        reason_value = _to_str(reason) or _to_str(data.get("reason"))
        if not reason_value:
            return _resp(
                False,
                error="reason is required",
                error_code="REROUTE_REASON_REQUIRED",
            )

        from_machine_id = outbound_doc.get("machine_id")
        from_work_order_id = outbound_doc.get("work_order_id")
        from_purpose = outbound_doc.get("purpose")

        to_machine_value = _to_str(to_machine_id) or _to_str(data.get("to_machine_id"))
        to_work_order_value = _to_str(to_work_order_id) or _to_str(data.get("to_work_order_id"))
        to_purpose_value = _to_str(to_purpose) or _to_str(data.get("to_purpose"))

        if not to_machine_value:
            to_machine_value = _to_str(from_machine_id)
        if not to_work_order_value:
            to_work_order_value = _to_str(from_work_order_id)
        if not to_purpose_value:
            to_purpose_value = _to_str(from_purpose)

        if (
            _to_str(from_machine_id) == to_machine_value
            and _to_str(from_work_order_id) == to_work_order_value
            and _to_str(from_purpose) == to_purpose_value
        ):
            return _resp(
                False,
                error="from and to destination values are identical",
                error_code="REROUTE_NO_CHANGE",
            )

        operator_value = _to_str(operator) or _to_str(data.get("operator")) or frappe.session.user
        timestamp_raw = _to_str(timestamp) or _to_str(data.get("timestamp"))
        timestamp_value = get_datetime(timestamp_raw) if timestamp_raw else now_datetime()

        change_doc = frappe.get_doc(
            {
                "doctype": "Outbound Destination Change",
                "outbound_id": outbound_doc.name,
                "from_machine_id": from_machine_id,
                "to_machine_id": to_machine_value,
                "from_work_order_id": from_work_order_id,
                "to_work_order_id": to_work_order_value,
                "from_purpose": from_purpose,
                "to_purpose": to_purpose_value,
                "reason": reason_value,
                "operator": operator_value,
                "timestamp": timestamp_value,
            }
        )
        change_doc.insert(ignore_permissions=True)
        change_doc.submit()

        outbound_doc.db_set("machine_id", to_machine_value, update_modified=False)
        outbound_doc.db_set("work_order_id", to_work_order_value, update_modified=False)
        outbound_doc.db_set("purpose", to_purpose_value, update_modified=False)
        outbound_doc.reload()

        return _resp(
            True,
            rm_outbound=_serialize_outbound(outbound_doc),
            destination_change=_serialize_destination_change(change_doc),
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "rm_outbound.reroute")
        return _resp(False, error=str(ex), error_code=_extract_error_code(ex))

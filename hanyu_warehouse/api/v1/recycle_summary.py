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


def _serialize_summary(doc):
    lines = []
    for row in doc.get("summary_lines") or []:
        lines.append(
            {
                "row_id": row.get("row_id") or row.name,
                "source_machine_id": row.get("source_machine_id"),
                "shift": row.get("shift"),
                "source_item_code": row.get("source_item_code"),
                "source_batch_no": row.get("source_batch_no"),
                "source_qty": row.get("source_qty"),
                "grade_usability": row.get("grade_usability"),
            }
        )

    generated_batches = []
    raw_json = doc.get("generated_batches_json")
    if raw_json:
        try:
            generated_batches = json.loads(raw_json)
        except Exception:
            generated_batches = []

    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "posting_date": doc.get("posting_date"),
        "remarks": doc.get("remarks"),
        "summary_lines": lines,
        "generated_batch_count": doc.get("generated_batch_count"),
        "generated_batches": generated_batches,
    }


@frappe.whitelist(methods=["POST"])
def create_draft(contract_version=None, payload=None, summary_lines=None, **kwargs):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("Recycle Summary", "create")
        if permission_error:
            return permission_error

        lines = _parse_list(summary_lines)
        if not lines:
            lines = _parse_list(data.get("summary_lines"))
        if not lines:
            lines = _parse_list(data.get("lines"))

        if not lines:
            return _resp(
                False,
                error="summary_lines must contain at least one row",
                error_code="RECYCLE_SUMMARY_LINES_REQUIRED",
            )

        doc = frappe.get_doc(
            {
                "doctype": "Recycle Summary",
                "posting_date": data.get("posting_date"),
                "remarks": data.get("remarks"),
                "summary_lines": [],
            }
        )

        for line in lines:
            if not isinstance(line, dict):
                continue
            doc.append(
                "summary_lines",
                {
                    "row_id": line.get("row_id"),
                    "source_machine_id": line.get("source_machine_id"),
                    "shift": line.get("shift"),
                    "source_item_code": line.get("source_item_code"),
                    "source_batch_no": line.get("source_batch_no"),
                    "source_qty": line.get("source_qty"),
                    "grade_usability": line.get("grade_usability"),
                },
            )

        doc.insert(ignore_permissions=True)
        return _resp(True, recycle_summary=_serialize_summary(doc))
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "recycle_summary.create_draft")
        error_code = "PERMISSION_DENIED" if isinstance(ex, frappe.PermissionError) else "UNKNOWN_ERROR"
        if "RECYCLE_SUMMARY_LINES_REQUIRED" in _to_str(ex):
            error_code = "RECYCLE_SUMMARY_LINES_REQUIRED"
        if "INVALID_CONTRACT_VERSION" in _to_str(ex):
            error_code = "INVALID_CONTRACT_VERSION"
        return _resp(False, error=str(ex), error_code=error_code)


@frappe.whitelist(methods=["POST"])
def submit_and_generate_batches(
    contract_version=None,
    recycle_summary=None,
    payload=None,
    **kwargs,
):
    try:
        data = _collect_payload(payload, kwargs)
        version = _to_str(contract_version) or _to_str(data.get("contract_version"))

        version_error = _check_contract_version(version)
        if version_error:
            return version_error

        permission_error = _check_permission("Recycle Summary", "submit")
        if permission_error and not frappe.has_permission("Recycle Summary", ptype="write"):
            return permission_error

        summary_name = _to_str(recycle_summary) or _to_str(data.get("recycle_summary"))
        if not summary_name:
            return _resp(
                False,
                error="recycle_summary is required",
                error_code="RECYCLE_SUMMARY_ID_REQUIRED",
            )

        if not frappe.db.exists("Recycle Summary", summary_name):
            return _resp(
                False,
                error=f"Recycle Summary not found: {summary_name}",
                error_code="RECYCLE_SUMMARY_NOT_FOUND",
            )

        doc = frappe.get_doc("Recycle Summary", summary_name)

        submit_done = False
        if doc.docstatus == 0:
            doc.submit()
            submit_done = True

        if hasattr(doc, "generate_batches_if_needed"):
            doc.generate_batches_if_needed()
            doc.reload()

        generated_batches = frappe.get_all(
            "Recycle Batch",
            filters={"created_from_summary": doc.name},
            fields=["name", "source_machine_id", "shift", "source_item_code", "grade_usability"],
            order_by="creation asc",
        )

        return _resp(
            True,
            submit_done=submit_done,
            recycle_summary=_serialize_summary(doc),
            generated_batches=generated_batches,
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "recycle_summary.submit_and_generate_batches")
        error_code = "PERMISSION_DENIED" if isinstance(ex, frappe.PermissionError) else "UNKNOWN_ERROR"
        return _resp(False, error=str(ex), error_code=error_code)

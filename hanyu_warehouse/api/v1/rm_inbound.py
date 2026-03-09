import frappe

from .rm_inbound_fields import get_rm_inbound_value, set_rm_inbound_value


CONTRACT_VERSION = "v1"


def _resp(ok: bool, **kwargs):
    payload = {"contract_version": CONTRACT_VERSION, "ok": ok}
    payload.update(kwargs)
    return payload


def _to_str(value) -> str:
    return str(value or "").strip()


@frappe.whitelist(methods=["POST"])
def attach_pallet(rm_inbound=None, pallet_id=None):
    try:
        rm_inbound_name = _to_str(rm_inbound)
        pallet_name = _to_str(pallet_id)

        if not rm_inbound_name:
            return _resp(False, error="rm_inbound is required")
        if not pallet_name:
            return _resp(False, error="pallet_id is required")
        if not frappe.db.exists("RM Inbound", rm_inbound_name):
            return _resp(False, error=f"RM Inbound not found: {rm_inbound_name}")
        if not frappe.db.exists("Pallet", pallet_name):
            return _resp(False, error=f"Pallet not found: {pallet_name}")

        inbound_doc = frappe.get_doc("RM Inbound", rm_inbound_name)
        pallet_doc = frappe.get_doc("Pallet", pallet_name)

        mismatch_items = []
        for fieldname in ("item_code", "batch_no", "qty", "uom", "location_id"):
            inbound_raw = get_rm_inbound_value(inbound_doc, fieldname)
            pallet_raw = pallet_doc.get(fieldname)
            if fieldname == "qty":
                inbound_cmp = frappe.utils.flt(inbound_raw)
                pallet_cmp = frappe.utils.flt(pallet_raw)
            else:
                inbound_cmp = _to_str(inbound_raw)
                pallet_cmp = _to_str(pallet_raw)

            if inbound_cmp != pallet_cmp:
                mismatch_items.append(
                    {
                        "field": fieldname,
                        "rm_inbound": inbound_raw,
                        "pallet": pallet_raw,
                    }
                )

        if mismatch_items:
            return _resp(
                False,
                error="RM Inbound and Pallet values are inconsistent",
                error_code="PALLET_BIND_MISMATCH",
                mismatches=mismatch_items,
                rm_inbound=rm_inbound_name,
                pallet_id=pallet_name,
            )

        set_rm_inbound_value(inbound_doc, "pallet_id", pallet_name)
        inbound_doc.save(ignore_permissions=True)

        if pallet_doc.get("rm_inbound") != rm_inbound_name:
            pallet_doc.rm_inbound = rm_inbound_name
            pallet_doc.save(ignore_permissions=True)

        return _resp(
            True,
            rm_inbound=inbound_doc.name,
            pallet_id=get_rm_inbound_value(inbound_doc, "pallet_id"),
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "rm_inbound.attach_pallet")
        return _resp(False, error=str(ex))


def _run_posting(doc):
    # Minimal posting: try one existing hook and stop.
    for method_name in ("make_stock_entry", "post_stock_entry"):
        method = getattr(doc, method_name, None)
        if not callable(method):
            continue

        try:
            result = method()
            return {
                "status": "done",
                "hook": method_name,
                "result_type": type(result).__name__,
            }
        except Exception as ex:
            return {
                "status": "skipped",
                "reason": f"{method_name} unavailable",
                "error": str(ex),
            }

    return {"status": "skipped", "reason": "no posting hook on RM Inbound"}


@frappe.whitelist(methods=["POST"])
def submit_and_post(rm_inbound=None):
    submit_done = False
    try:
        rm_inbound_name = _to_str(rm_inbound)
        if not rm_inbound_name:
            return _resp(
                False,
                error="rm_inbound is required",
                submit_done=False,
                posting_skipped=True,
            )
        if not frappe.db.exists("RM Inbound", rm_inbound_name):
            return _resp(
                False,
                error=f"RM Inbound not found: {rm_inbound_name}",
                submit_done=False,
                posting_skipped=True,
            )

        doc = frappe.get_doc("RM Inbound", rm_inbound_name)
        if doc.docstatus == 2:
            return _resp(
                False,
                error="RM Inbound is cancelled and cannot be posted",
                submit_done=False,
                posting_skipped=True,
            )

        if doc.docstatus == 0:
            doc.submit()
            submit_done = True

        post_result = _run_posting(doc)
        posting_skipped = post_result.get("status") == "skipped"
        return _resp(
            True,
            rm_inbound=doc.name,
            submit_done=submit_done,
            posting_skipped=posting_skipped,
            posting=post_result,
        )
    except Exception as ex:
        frappe.log_error(frappe.get_traceback(), "rm_inbound.submit_and_post")
        return _resp(
            False,
            error=str(ex),
            submit_done=submit_done,
            posting_skipped=True,
        )

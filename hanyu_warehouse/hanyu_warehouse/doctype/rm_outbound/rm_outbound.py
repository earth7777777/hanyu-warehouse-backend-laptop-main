# Copyright (c) 2026, Hanyu Factory and contributors

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


MACHINE_REQUIRED_SETTING_KEYS = (
    "rm_outbound_machine_required",
    "machine_required_for_rm_outbound",
    "require_machine_for_rm_outbound",
    "machine_required",
)

RM_INBOUND_BALANCE_DTYPE = "RM Inbound"
RM_INBOUND_FIELD_SOURCE_LOCATION = "f08"
RM_INBOUND_FIELD_ITEM_CODE = "f01"
RM_INBOUND_FIELD_BATCH_NO = "f15"
RM_INBOUND_FIELD_QTY = "f04"


class RMOutbound(Document):
    def validate(self):
        self._sync_outbound_mode()
        self._apply_pallet_context()
        self._validate_qty()
        self._validate_machine_rule()

        if self._is_submit_context():
            self._validate_manual_source_requirement()
            self._validate_manual_stock()

    def before_submit(self):
        self._validate_manual_source_requirement()
        self._validate_manual_stock()

    def on_submit(self):
        self.apply_posting()

    def apply_posting(self):
        if cint(self.get("is_posted")):
            return

        stock_key = self._resolve_stock_key()
        source_location = stock_key["source_location_id"]
        item_code = stock_key["item_code"]
        batch_no = stock_key["batch_no"]
        required_qty = flt(self.get("qty"))

        if required_qty <= 0:
            frappe.throw("INVALID_QTY: qty must be greater than zero")

        if not source_location:
            frappe.throw("SOURCE_LOCATION_REQUIRED: source_location_id is required for posting")

        if not item_code:
            frappe.throw("ITEM_CODE_REQUIRED: item_code is required for posting")

        available_before = self._get_effective_available_qty(
            source_location_id=source_location,
            item_code=item_code,
            batch_no=batch_no,
        )

        if available_before is None:
            frappe.throw(
                "STOCK_VALIDATION_UNAVAILABLE: unable to validate stock balance for posting"
            )

        if available_before + 1e-9 < required_qty:
            frappe.throw(
                "INSUFFICIENT_STOCK: source_location_id/item_code/batch_no available balance is not enough"
            )

        available_after = available_before - required_qty
        posted_at = now_datetime()

        self.db_set("is_posted", 1, update_modified=False)
        self.db_set("posted_at", posted_at, update_modified=False)
        self.db_set("available_qty_before_post", available_before, update_modified=False)
        self.db_set("available_qty_after_post", available_after, update_modified=False)

        if not self.get("source_location_id"):
            self.db_set("source_location_id", source_location, update_modified=False)

        if not self.get("item_code"):
            self.db_set("item_code", item_code, update_modified=False)

        if batch_no and not self.get("batch_no"):
            self.db_set("batch_no", batch_no, update_modified=False)

        self.add_comment(
            "Info",
            (
                "RM Outbound posted. "
                f"source_location_id={source_location}, item_code={item_code}, "
                f"batch_no={batch_no or ''}, qty={required_qty}"
            ),
        )

    def get_posting_snapshot(self):
        return {
            "is_posted": cint(self.get("is_posted")),
            "posted_at": self.get("posted_at"),
            "available_qty_before_post": flt(self.get("available_qty_before_post")),
            "available_qty_after_post": flt(self.get("available_qty_after_post")),
        }

    def _is_submit_context(self):
        return bool(getattr(self.flags, "in_submit", False) or self.docstatus == 1)

    def _sync_outbound_mode(self):
        mode = "Pallet" if self.get("pallet_id") else "Manual"
        self.outbound_mode = mode

    def _apply_pallet_context(self):
        if not self.get("pallet_id"):
            return

        pallet_doc = self._get_pallet_doc()
        if not pallet_doc:
            frappe.throw(f"PALLET_NOT_FOUND: pallet_id not found: {self.get('pallet_id')}")

        contents = pallet_doc.get("contents") or []
        first_row = contents[0] if contents else None

        warehouse = pallet_doc.get("warehouse")
        item_code = pallet_doc.get("item_code") or (first_row.get("material_code") if first_row else None)
        batch_no = pallet_doc.get("batch_no") or (first_row.get("batch_no") if first_row else None)
        uom = pallet_doc.get("uom") or (first_row.get("uom") if first_row else None)
        qty = flt(pallet_doc.get("qty") or (first_row.get("qty") if first_row else 0))

        if warehouse:
            self.source_location_id = warehouse
        if item_code:
            self.item_code = item_code
        if batch_no:
            self.batch_no = batch_no
        if uom and not self.get("uom"):
            self.uom = uom
        if qty > 0 and flt(self.get("qty")) <= 0:
            self.qty = qty

    def _validate_qty(self):
        if flt(self.get("qty")) <= 0:
            frappe.throw("INVALID_QTY: qty must be greater than zero")

    def _validate_machine_rule(self):
        self.machine_required_effective = 1 if self._is_machine_required() else 0
        if cint(self.machine_required_effective) and not self.get("machine_id"):
            frappe.throw("MACHINE_REQUIRED: machine_id is required by current backend rule")

    def _validate_manual_source_requirement(self):
        if self.get("pallet_id"):
            return
        if not self.get("source_location_id"):
            frappe.throw("SOURCE_LOCATION_REQUIRED: source_location_id is required in manual outbound")

    def _validate_manual_stock(self):
        if self.get("pallet_id"):
            return

        source_location = (self.get("source_location_id") or "").strip()
        item_code = (self.get("item_code") or "").strip()
        batch_no = (self.get("batch_no") or "").strip()
        qty = flt(self.get("qty"))

        if not source_location:
            frappe.throw("SOURCE_LOCATION_REQUIRED: source_location_id is required in manual outbound")
        if not item_code:
            frappe.throw("ITEM_CODE_REQUIRED: item_code is required in manual outbound")
        if not batch_no:
            frappe.throw("BATCH_NO_REQUIRED: batch_no is required in manual outbound")

        available_qty = self._get_effective_available_qty(
            source_location_id=source_location,
            item_code=item_code,
            batch_no=batch_no,
        )
        if available_qty is None:
            frappe.throw(
                "STOCK_VALIDATION_UNAVAILABLE: unable to validate stock balance for manual outbound"
            )
        if available_qty + 1e-9 < qty:
            frappe.throw(
                "INSUFFICIENT_STOCK: source_location_id/item_code/batch_no available balance is not enough"
            )

    def _resolve_stock_key(self):
        source_location = (self.get("source_location_id") or "").strip()
        item_code = (self.get("item_code") or "").strip()
        batch_no = (self.get("batch_no") or "").strip()

        if self.get("pallet_id"):
            pallet_doc = self._get_pallet_doc()
            if pallet_doc:
                source_location = source_location or (pallet_doc.get("warehouse") or "").strip()
                item_code = item_code or (pallet_doc.get("item_code") or "").strip()
                batch_no = batch_no or (pallet_doc.get("batch_no") or "").strip()

        return {
            "source_location_id": source_location,
            "item_code": item_code,
            "batch_no": batch_no,
        }

    def _get_effective_available_qty(self, source_location_id, item_code, batch_no):
        raw_qty = self._get_raw_stock_qty(source_location_id, item_code, batch_no)
        if raw_qty is None:
            return None

        consumed_qty = self._get_consumed_outbound_qty(source_location_id, item_code, batch_no)
        return raw_qty - consumed_qty

    def _get_raw_stock_qty(self, source_location_id, item_code, batch_no):
        raw_qty = self._get_rm_inbound_balance_qty(source_location_id, item_code, batch_no)
        if raw_qty is not None:
            return raw_qty

        if self.get("pallet_id"):
            pallet_doc = self._get_pallet_doc()
            if pallet_doc:
                return flt(pallet_doc.get("qty"))

        return None

    def _get_rm_inbound_balance_qty(self, source_location_id, item_code, batch_no):
        exact_conditions = [
            "docstatus=1",
            f"ifnull({RM_INBOUND_FIELD_SOURCE_LOCATION}, '')=%s",
            f"ifnull({RM_INBOUND_FIELD_ITEM_CODE}, '')=%s",
            f"ifnull({RM_INBOUND_FIELD_BATCH_NO}, '')=%s",
        ]
        exact_values = [source_location_id, item_code, batch_no or ""]

        exact_sql = (
            f"select count(*) as row_count, coalesce(sum({RM_INBOUND_FIELD_QTY}), 0) as total_qty "
            f"from `tab{RM_INBOUND_BALANCE_DTYPE}` "
            f"where {' and '.join(exact_conditions)}"
        )

        try:
            exact_result = frappe.db.sql(exact_sql, exact_values, as_dict=True)
        except Exception:
            return None

        if not exact_result:
            return None

        exact_row = exact_result[0] or {}
        if cint(exact_row.get("row_count")) > 0:
            return flt(exact_row.get("total_qty"))

        baseline_conditions = [
            "docstatus=1",
            f"ifnull({RM_INBOUND_FIELD_SOURCE_LOCATION}, '')=%s",
            f"ifnull({RM_INBOUND_FIELD_ITEM_CODE}, '')=%s",
        ]
        baseline_values = [source_location_id, item_code]
        baseline_sql = (
            "select count(*) as row_count "
            f"from `tab{RM_INBOUND_BALANCE_DTYPE}` "
            f"where {' and '.join(baseline_conditions)}"
        )

        try:
            baseline_result = frappe.db.sql(baseline_sql, baseline_values, as_dict=True)
        except Exception:
            return None

        if not baseline_result:
            return None

        baseline_row = baseline_result[0] or {}
        if cint(baseline_row.get("row_count")) > 0:
            return 0

        return None

    def _get_consumed_outbound_qty(self, source_location_id, item_code, batch_no):
        conditions = [
            "docstatus=1",
            "ifnull(is_posted, 0)=1",
            "ifnull(source_location_id, '')=%s",
            "ifnull(item_code, '')=%s",
            "ifnull(batch_no, '')=%s",
        ]
        values = [source_location_id, item_code, batch_no or ""]

        if self.name:
            conditions.append("name != %s")
            values.append(self.name)

        sql = (
            "select coalesce(sum(qty), 0) "
            "from `tabRM Outbound` "
            f"where {' and '.join(conditions)}"
        )
        result = frappe.db.sql(sql, values)
        return flt(result[0][0]) if result else 0

    def _get_pallet_doc(self):
        if not self.get("pallet_id"):
            return None

        cache_doc = getattr(self, "_pallet_doc_cache", None)
        if cache_doc and cache_doc.name == self.get("pallet_id"):
            return cache_doc

        if not frappe.db.exists("Pallet", self.get("pallet_id")):
            return None

        cache_doc = frappe.get_doc("Pallet", self.get("pallet_id"))
        self._pallet_doc_cache = cache_doc
        return cache_doc

    def _is_machine_required(self):
        try:
            meta = frappe.get_meta("Warehouse Settings")
        except Exception:
            return True

        for fieldname in MACHINE_REQUIRED_SETTING_KEYS:
            if not meta.get_field(fieldname):
                continue

            value = frappe.db.get_single_value("Warehouse Settings", fieldname)
            if value in (None, ""):
                continue
            return bool(cint(value))

        return True

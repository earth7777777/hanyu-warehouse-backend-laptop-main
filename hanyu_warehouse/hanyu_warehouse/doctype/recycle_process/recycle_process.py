# Copyright (c) 2026, Hanyu Factory and contributors

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class RecycleProcess(Document):
    def validate(self):
        recycle_batch_id = (self.get("recycle_batch_id") or "").strip()
        if not recycle_batch_id:
            frappe.throw("RECYCLE_BATCH_ID_REQUIRED: recycle_batch_id is required")

        if not frappe.db.exists("Recycle Batch", recycle_batch_id):
            frappe.throw(f"RECYCLE_BATCH_NOT_FOUND: recycle_batch_id not found: {recycle_batch_id}")

        total_cost = flt(self.get("total_cost"))
        if total_cost <= 0:
            frappe.throw("TOTAL_COST_REQUIRED: total_cost must be greater than zero")

    def on_submit(self):
        self.apply_to_batch_if_needed()

    def apply_to_batch_if_needed(self):
        if cint(self.get("is_applied")):
            return

        batch_doc = frappe.get_doc("Recycle Batch", self.get("recycle_batch_id"))
        apply_result = batch_doc.append_process_cost(self.name, flt(self.get("total_cost")))

        self.db_set("is_applied", 1, update_modified=False)
        self.db_set("applied_at", now_datetime(), update_modified=False)
        self.db_set("batch_total_before_apply", apply_result["before"], update_modified=False)
        self.db_set("batch_total_after_apply", apply_result["after"], update_modified=False)

        self.add_comment(
            "Info",
            (
                "Recycle process applied to batch. "
                f"recycle_batch_id={self.get('recycle_batch_id')}, "
                f"total_cost={flt(self.get('total_cost'))}, total_after={apply_result['after']}"
            ),
        )

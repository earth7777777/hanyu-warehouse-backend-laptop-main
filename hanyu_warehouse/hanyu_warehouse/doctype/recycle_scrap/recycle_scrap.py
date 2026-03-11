# Copyright (c) 2026, Hanyu Factory and contributors

import json

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class RecycleScrap(Document):
    def validate(self):
        recycle_batch_id = (self.get("recycle_batch_id") or "").strip()
        if not recycle_batch_id:
            frappe.throw("RECYCLE_BATCH_ID_REQUIRED: recycle_batch_id is required")

        if not frappe.db.exists("Recycle Batch", recycle_batch_id):
            frappe.throw(f"RECYCLE_BATCH_NOT_FOUND: recycle_batch_id not found: {recycle_batch_id}")

    def before_submit(self):
        batch_doc = frappe.get_doc("Recycle Batch", self.get("recycle_batch_id"))
        if cint(batch_doc.get("is_closed")):
            frappe.throw("RECYCLE_BATCH_ALREADY_CLOSED: recycle batch is already closed")

        loss_amount = flt(batch_doc.get("total_cost_accumulated"))
        self.loss_amount = loss_amount
        self.closed_at = now_datetime()

        trace_rows = frappe.get_all(
            "Recycle Process",
            filters={"recycle_batch_id": batch_doc.name, "docstatus": 1},
            fields=["name", "total_cost", "creation"],
            order_by="creation asc",
        )

        self.process_event_trace_json = json.dumps(trace_rows, ensure_ascii=False, default=str)

    def on_submit(self):
        self.close_batch_if_needed()

    def close_batch_if_needed(self):
        if cint(self.get("is_close_applied")):
            return

        batch_doc = frappe.get_doc("Recycle Batch", self.get("recycle_batch_id"))
        batch_doc.close_by_scrap(self.name, flt(self.get("loss_amount")))

        self.db_set("is_close_applied", 1, update_modified=False)

        self.add_comment(
            "Info",
            (
                "Recycle scrap submitted and batch closed. "
                f"recycle_batch_id={self.get('recycle_batch_id')}, "
                f"loss_amount={flt(self.get('loss_amount'))}, closed_at={self.get('closed_at')}"
            ),
        )

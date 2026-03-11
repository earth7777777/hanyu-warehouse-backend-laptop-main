# Copyright (c) 2026, Hanyu Factory and contributors

import json

import frappe
from frappe.model.document import Document


class RecycleSummary(Document):
    def validate(self):
        if not (self.get("summary_lines") or []):
            frappe.throw("RECYCLE_SUMMARY_LINES_REQUIRED: summary_lines must contain at least one row")

    def on_submit(self):
        self.generate_batches_if_needed()

    def generate_batches_if_needed(self):
        existing_batches = frappe.get_all(
            "Recycle Batch",
            filters={"created_from_summary": self.name},
            order_by="creation asc",
            pluck="name",
        )
        if existing_batches:
            self._persist_generated_snapshot(existing_batches)
            return existing_batches

        created_batches = []
        for row in self.get("summary_lines") or []:
            batch_doc = frappe.get_doc(
                {
                    "doctype": "Recycle Batch",
                    "source_machine_id": row.get("source_machine_id"),
                    "shift": row.get("shift"),
                    "source_item_code": row.get("source_item_code"),
                    "source_batch_no": row.get("source_batch_no"),
                    "source_qty": row.get("source_qty"),
                    "grade_usability": row.get("grade_usability"),
                    "process_status": "未处理",
                    "total_cost_accumulated": 0,
                    "is_closed": 0,
                    "created_from_summary": self.name,
                    "created_from_summary_row_id": row.get("row_id") or row.name,
                }
            )
            batch_doc.insert(ignore_permissions=True)
            created_batches.append(batch_doc.name)

        self._persist_generated_snapshot(created_batches)

        self.add_comment(
            "Info",
            (
                "Recycle batches generated from summary submit. "
                f"generated_count={len(created_batches)}"
            ),
        )

        return created_batches

    def _persist_generated_snapshot(self, batch_names):
        self.db_set("generated_batch_count", len(batch_names), update_modified=False)
        self.db_set(
            "generated_batches_json",
            json.dumps(batch_names, ensure_ascii=False),
            update_modified=False,
        )

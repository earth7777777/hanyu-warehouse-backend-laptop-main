# Copyright (c) 2026, Hanyu Factory and contributors

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class OutboundDestinationChange(Document):
    def validate(self):
        outbound_id = (self.get("outbound_id") or "").strip()
        if not outbound_id:
            frappe.throw("OUTBOUND_ID_REQUIRED: outbound_id is required")

        if not frappe.db.exists("RM Outbound", outbound_id):
            frappe.throw(f"OUTBOUND_NOT_FOUND: RM Outbound not found: {outbound_id}")

        outbound_doc = frappe.get_doc("RM Outbound", outbound_id)
        if outbound_doc.docstatus != 1:
            frappe.throw("OUTBOUND_NOT_SUBMITTED: reroute only supports submitted RM Outbound")

        if not self.get("operator"):
            self.operator = frappe.session.user

        if not self.get("timestamp"):
            self.timestamp = now_datetime()

        if not (self.get("reason") or "").strip():
            frappe.throw("REROUTE_REASON_REQUIRED: reason is required")

        if self._no_destination_change():
            frappe.throw("REROUTE_NO_CHANGE: from and to destination values are identical")

    def on_submit(self):
        outbound_doc = frappe.get_doc("RM Outbound", self.get("outbound_id"))
        outbound_doc.add_comment(
            "Info",
            (
                "Outbound destination rerouted. "
                f"from(machine={self.get('from_machine_id')}, work_order={self.get('from_work_order_id')}, purpose={self.get('from_purpose')}) "
                f"to(machine={self.get('to_machine_id')}, work_order={self.get('to_work_order_id')}, purpose={self.get('to_purpose')}). "
                f"reason={self.get('reason')}, operator={self.get('operator')}, timestamp={self.get('timestamp')}"
            ),
        )

    def _no_destination_change(self):
        return (
            (self.get("from_machine_id") or "") == (self.get("to_machine_id") or "")
            and (self.get("from_work_order_id") or "") == (self.get("to_work_order_id") or "")
            and (self.get("from_purpose") or "") == (self.get("to_purpose") or "")
        )

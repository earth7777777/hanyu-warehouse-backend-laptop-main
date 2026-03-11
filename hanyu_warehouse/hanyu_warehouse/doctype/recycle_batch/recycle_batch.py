# Copyright (c) 2026, Hanyu Factory and contributors

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


ALLOWED_GRADE_USABILITY = {"可直接用", "需拉丝后可用"}
ALLOWED_PROCESS_STATUS = {"未处理", "已拉丝", "已报废处置"}


class RecycleBatch(Document):
    def validate(self):
        grade_usability = (self.get("grade_usability") or "").strip()
        if grade_usability not in ALLOWED_GRADE_USABILITY:
            frappe.throw(
                "INVALID_GRADE_USABILITY: grade_usability must be one of 可直接用 / 需拉丝后可用"
            )

        if grade_usability == "报废":
            frappe.throw("INVALID_GRADE_USABILITY: 报废 is not a usability grade")

        process_status = (self.get("process_status") or "").strip() or "未处理"
        if process_status not in ALLOWED_PROCESS_STATUS:
            frappe.throw(
                "INVALID_PROCESS_STATUS: process_status must be one of 未处理 / 已拉丝 / 已报废处置"
            )
        self.process_status = process_status

        self.total_cost_accumulated = flt(self.get("total_cost_accumulated"))

        if cint(self.get("is_closed")):
            if self.process_status != "已报废处置":
                self.process_status = "已报废处置"
            if not self.get("closed_by_scrap"):
                frappe.throw(
                    "SCRAP_CLOSE_ONLY_VIA_RECYCLE_SCRAP: closed recycle batch must reference Recycle Scrap"
                )

        if self.process_status == "已报废处置" and not self.get("closed_by_scrap"):
            frappe.throw(
                "SCRAP_CLOSE_ONLY_VIA_RECYCLE_SCRAP: process_status 已报废处置 can only be set by Recycle Scrap"
            )

    def append_process_cost(self, process_name, total_cost):
        if cint(self.get("is_closed")):
            frappe.throw("RECYCLE_BATCH_CLOSED: recycle batch is already closed")

        amount = flt(total_cost)
        if amount <= 0:
            frappe.throw("TOTAL_COST_REQUIRED: total_cost must be greater than zero")

        before_amount = flt(self.get("total_cost_accumulated"))
        after_amount = before_amount + amount

        self.db_set("total_cost_accumulated", after_amount, update_modified=False)

        if (self.get("process_status") or "") == "未处理":
            self.db_set("process_status", "已拉丝", update_modified=False)

        self.add_comment(
            "Info",
            (
                "Recycle process cost applied. "
                f"process={process_name}, added_cost={amount}, total_cost_accumulated={after_amount}"
            ),
        )

        return {"before": before_amount, "after": after_amount}

    def close_by_scrap(self, scrap_name, loss_amount):
        expected_loss = flt(self.get("total_cost_accumulated"))
        actual_loss = flt(loss_amount)

        if abs(expected_loss - actual_loss) > 1e-9:
            frappe.throw(
                "LOSS_AMOUNT_MISMATCH: loss_amount must equal recycle batch accumulated process cost"
            )

        now_ts = now_datetime()
        self.db_set("process_status", "已报废处置", update_modified=False)
        self.db_set("is_closed", 1, update_modified=False)
        self.db_set("closed_by_scrap", scrap_name, update_modified=False)
        self.db_set("closed_at", now_ts, update_modified=False)

        self.add_comment(
            "Info",
            (
                "Recycle batch closed by Recycle Scrap. "
                f"scrap={scrap_name}, loss_amount={actual_loss}, closed_at={now_ts}"
            ),
        )

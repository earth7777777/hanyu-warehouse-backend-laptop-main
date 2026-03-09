# Copyright (c) 2026, Hanyu Factory and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Pallet(Document):
	def validate(self):
		if self.contents and len(self.contents) > 1:
			frappe.throw("Pallet contents must be 0 or 1 row.")

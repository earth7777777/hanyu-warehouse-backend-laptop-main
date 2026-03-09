# apps/hanyu_warehouse/hanyu_warehouse/api/v1/ai_inbound.py

import json
import frappe

# 这个接口：AI 传 JSON -> 系统生成 RM Inbound 草稿（docstatus=0）-> 返回单据号
@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_rm_inbound_draft(payload=None):
    # 只允许 POST
    if frappe.request.method != "POST":
        frappe.throw("Only POST is allowed")

    # 兼容两种传法：
    # 1) 直接 JSON body
    # 2) 传 payload 参数
    data = None

    if payload:
        data = payload
    else:
        raw = (frappe.request.get_data(as_text=True) or "").strip()
        if raw:
            data = raw
        else:
            # 兜底：form_dict
            data = frappe.local.form_dict.get("payload")

    if data is None:
        frappe.throw("Missing JSON payload")

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            frappe.throw("Payload is not valid JSON")

    # 后端硬旋钮：不允许 AI 入库时，直接拒绝（不创建草稿）
    settings = frappe.get_single("Warehouse Settings")
    if not getattr(settings, "allow_ai_inbound", 0):
        frappe.throw("AI inbound is disabled by Warehouse Settings")

    # 只接收 f01~f11（避免 AI 乱塞字段）
    allowed = [f"f{str(i).zfill(2)}" for i in range(1, 17)]
    doc_dict = {"doctype": "RM Inbound"}

    for k in allowed:
        if k in data:
            doc_dict[k] = data[k]

    # 强制提醒：B2 草稿也会跑 validate（五把锁会拦截）
    # 所以：没照片时必须给 f10(异常说明) 一个占位说明，否则证据锁会拦截
    doc = frappe.get_doc(doc_dict)
    doc.insert(ignore_permissions=True)  # docstatus=0 草稿，不 submit

    return {
        "ok": True,
        "name": doc.name,
        "docstatus": doc.docstatus
    }

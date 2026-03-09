import frappe
from .vision_processor import process_receipt_photo
from .ai_inbound import create_rm_inbound_draft

@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_rm_inbound_draft_from_receipt(receipt_photo=None, exception_reason=None, overrides=None):
    """
    桥接接口（成熟稳法）：
    1) 先跑视觉：receipt_photo -> 稳定 JSON（含预埋键）
    2) 再映射到 RM Inbound 草稿 payload（只写 f01~f11）
    3) 调用 create_rm_inbound_draft 创建草稿（docstatus=0）
    注：overrides 可手工覆盖字段（例如 f01/f02/f08 等关键门禁字段）
    """
    vis = process_receipt_photo(receipt_photo=receipt_photo, exception_reason=exception_reason)
    if not vis.get("ok"):
        return {"ok": False, "stage": "vision", "error": vis.get("error"), "vision": vis}

    overrides = overrides or {}
    if isinstance(overrides, str):
        # 允许前端传 JSON 字符串
        try:
            import json
            overrides = json.loads(overrides)
        except Exception:
            overrides = {}

    # 最小可用映射（视觉未实现前全部留空，让人工/AI补齐）
    payload = {
        "f01": overrides.get("f01"),                 # Material（必须）
        "f02": overrides.get("f02"),                 # Supplier（必须，Link Supplier）
        "f03": vis.get("invoice_no") or overrides.get("f03"),  # 送货单号（必须且查重）
        "f04": overrides.get("f04"),                 # 实测毛重吨（可选）
        "f05": vis.get("package_quantity") or overrides.get("f05"),  # 袋数（可选）
        "f08": overrides.get("f08"),                 # Location（必须，混放锁）
        "f09": overrides.get("f09"),                            # 入库时间（datetime）
        "f10": exception_reason or overrides.get("f10"),         # 异常说明（证据锁）
        "f11": overrides.get("f11"),                 # remarks（可选）
        "f12": overrides.get("f12"),                 # 外部袋码 / 外部条码
        "f13": overrides.get("f13"),                 # 来源类型（新料 / 回料）
        "f14": overrides.get("f14"),                 # 回料分类
        "f15": overrides.get("f15"),                 # 内部批次号
        "f16": overrides.get("f16"),                 # 包级追踪标记
    }

    # 把预埋键回传，先不落库（阶段四约束）
    payload_meta = {
        "batch_no": vis.get("batch_no"),
        "external_bag_code": vis.get("external_bag_code"),
        "external_bag_code_list": vis.get("external_bag_code_list"),
        "material_source_type": vis.get("material_source_type"),
        "regrind_class": vis.get("regrind_class"),
    }

    draft = create_rm_inbound_draft(payload=payload)
    return {"ok": True, "vision": vis, "draft": draft, "meta": payload_meta}

# apps/hanyu_warehouse/hanyu_warehouse/doc_events/rm_inbound.py

import frappe


def validate_rm_inbound(doc, method=None):
    """
    Hook: RM Inbound -> validate
    作用（5 个守卫，顺序按“先精度+混放，再补三把锁”）：
    1) 精度锁：按 (袋数 * 单袋重量kg)/1000 计算预期吨数；偏差>1%则在 f11(备注)写预警
    2) 混放锁：库位(f08)已被其他物料占用时，禁止不同物料混放，直接拦截
    3) 证据锁：f09(签收照片)为空时，必须填写 f10(异常说明)，否则拦截保存
    4) 重复锁：按 f03(送货单号) 查重，已存在则拦截，防止一单多入
    5) 身份锁：校验 f02(供应商) Link 目标中必须存在该供应商，否则拦截
    """

    # 先保留您原来已经跑通的两件事（顺序不动）
    _weight_audit(doc)
    _location_mix_lock(doc)
    _f01_required_lock(doc)
    _f08_required_lock(doc)

    # 再追加三把锁（按您要求“加在下面”）
    _evidence_lock(doc)
    _duplicate_lock(doc)
    _supplier_lock(doc)

    # phase-2 step: source type lock + pallet_id log
    _source_type_lock(doc)
    _bag_code_log(doc)



def _weight_audit(doc):
    """
    精度锁（预警，不拦截）：
    - f01: 入库物料（Material）
    - f04: 实测毛重(吨)
    - f05: 包数/袋数
    - f11: 备注说明（写入预警）
    """
    material_name = doc.get("f01")
    gross_tons = doc.get("f04")
    bag_count = doc.get("f05")
    remark = doc.get("f11") or ""

    if not material_name or gross_tons is None or bag_count is None:
        return

    bag_weight_kg = _get_bag_weight_kg(material_name)
    expected_tons = (float(bag_count) * float(bag_weight_kg)) / 1000.0
    if expected_tons <= 0:
        return

    diff_ratio = abs(float(gross_tons) - expected_tons) / expected_tons

    # 偏差阈值：1%（写预警到备注）
    if diff_ratio > 0.01:
        warning = "[系统预警] 实收吨数与袋数换算偏差超过 1%"
        if warning not in remark:
            doc.f11 = (remark + ("\n" if remark else "") + warning).strip()


def _get_bag_weight_kg(material_name: str) -> float:
    """
    单袋重量kg 取数优先级：
    1) Material.bag_weight_kg（如果您们建了并填了）
    2) Warehouse Settings.default_bag_weight_kg（如果您们建了）
    3) 默认 25（符合“25kg/袋”）
    """
    bag_weight = frappe.db.get_value("Material", material_name, "bag_weight_kg")
    if bag_weight:
        return float(bag_weight)

    settings = frappe.db.get_value("Warehouse Settings", None, "default_bag_weight_kg")
    if settings:
        return float(settings)

    return 25.0


def _location_mix_lock(doc):
    """
    混放锁（拦截）：
    - f08 是库位（Link -> Warehouse Location）
    - 用 f08 去查 Location Occupancy.location_id
    - 若已有占用且 material != 本次 f01，则 frappe.throw 阻断
    """
    location_value = doc.get("f08")  # 库位
    material_name = doc.get("f01")   # 物料（Material）

    if not location_value or not material_name:
        return

    occ = frappe.db.get_value(
        "Location Occupancy",
        {"location_id": location_value},
        ["name", "material"],
        as_dict=True,
    )

    if not occ:
        return

    occupied_material = occ.get("material")
    if occupied_material and occupied_material != material_name:
        frappe.throw("禁止混放：该库位已被其他物料占用")


def _is_f01_required_by_settings() -> bool:
    """
    f01 必填开关（配置驱动）：
    - 读取 Warehouse Settings.field_map 子表中 target_field='f01' 的 required
    - 未配置时默认不强制（保持当前放行行为）
    """
    try:
        settings = frappe.get_single("Warehouse Settings")
    except Exception:
        return False

    for row in (settings.get("field_map") or []):
        target_field = (getattr(row, "target_field", None) or "").strip()
        if target_field != "f01":
            continue
        return int(getattr(row, "required", 0) or 0) == 1

    return False


def _f01_required_lock(doc):
    """
    f01 必填锁（只处理 f01）：
    - 配置为必填时，f01 为空则拦截
    """
    if not _is_f01_required_by_settings():
        return
    if not (doc.get("f01") or "").strip():
        frappe.throw("字段规则：f01(入库物料)不能为空")


def _is_f08_required_by_settings() -> bool:
    """
    f08 必填开关（配置驱动）：
    - 读取 Warehouse Settings.field_map 子表中 target_field='f08' 的 required
    - 未配置时默认不强制（保持当前放行行为）
    """
    try:
        settings = frappe.get_single("Warehouse Settings")
    except Exception:
        return False

    for row in (settings.get("field_map") or []):
        target_field = (getattr(row, "target_field", None) or "").strip()
        if target_field != "f08":
            continue
        return int(getattr(row, "required", 0) or 0) == 1

    return False


def _f08_required_lock(doc):
    """
    f08 必填锁（只处理 f08）：
    - 配置为必填时，f08 为空则拦截
    """
    if not _is_f08_required_by_settings():
        return
    if not (doc.get("f08") or "").strip():
        frappe.throw("字段规则：f08(库位)不能为空")


def _evidence_lock(doc):
    """
    证据锁（拦截）：
    - 若 f09(签收照片/receipt_photo) 为空，则必须填写 f10(exception_reason)
    """
    receipt_photo = doc.get("f09")
    exception_reason = str(doc.get("f10") or "").strip()

    if receipt_photo:
        return

    if not exception_reason:
        frappe.throw("证据锁：未上传签收照片时，必须填写异常说明")


def _duplicate_lock(doc):
    """
    重复锁（拦截）：
    - 用 f03(送货单号) 查 RM Inbound 是否已存在同号记录
    - 若存在，拦截；编辑自己时不拦截
    """
    delivery_no = (doc.get("f03") or "").strip()
    if not delivery_no:
        return

    # new doc 时 doc.name 可能为空；有 name 时要排除自己
    filters = {"f03": delivery_no}
    if doc.name:
        filters["name"] = ["!=", doc.name]

    hit = frappe.get_all("RM Inbound", filters=filters, fields=["name"], limit=1)
    if hit:
        frappe.throw(f"重复锁：送货单号已存在（单据：{hit[0]['name']}）")


def _supplier_lock(doc):
    """
    身份锁（拦截）：
    - f02 是供应商 Link 字段
    - 自动读取 f02 的 Link 目标 DocType（options），检查该值是否存在
    """
    supplier_value = (doc.get("f02") or "").strip()
    if not supplier_value:
        frappe.throw("身份锁：供应商不能为空")

    meta = frappe.get_meta("RM Inbound")
    fld = meta.get_field("f02")
    target_dt = (getattr(fld, "options", None) or "").strip()

    if not target_dt:
        frappe.throw("身份锁：供应商字段(f02)未配置 Link 目标（options 为空）")

    if not frappe.db.exists(target_dt, supplier_value):
        frappe.throw(f"Identity lock: supplier does not exist in {target_dt}")


def _source_type_lock(doc):
    """
    来源类型锁（拦截）：
    - f13 为空视为新料
    - f13 只允许"新料"或"回料"，其他值拦截
    - f13=回料 时，f14 不能为空
    - f13=新料 时，f14 强制置空
    """
    source_type = (doc.get("f13") or "").strip()
    if not source_type:
        source_type = "新料"
        doc.f13 = "新料"

    allowed_types = {"新料", "回料"}
    if source_type not in allowed_types:
        frappe.throw(f"来源类型锁：f13 只允许填写新料或回料，当前值：{source_type}")

    if source_type == "回料":
        regrind_class = (doc.get("f14") or "").strip()
        if not regrind_class:
            frappe.throw("来源类型锁：来源类型为回料时，必须填写回料分类（f14）")
    else:
        doc.f14 = ""


def _bag_code_log(doc):
    """
    pallet_id record (log only, no blocking):
    - f17 is reserved for pallet_id; f12 remains bag/barcode field
    """
    pallet_id = (doc.get("f17") or "").strip()
    if pallet_id:
        frappe.log_error(
            title="[pallet_id record]",
            message=f"doc={doc.name}, f17(pallet_id)={pallet_id}"
        )

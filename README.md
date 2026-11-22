# 澄川焊缝判读评估台账

澄川焊接工艺室用这份离线台账区分同一焊缝的多次采集和同名拼片的换料，并让试验主管使用冻结清册复核两个模型的判读差异。次班可在图像到期后按原号复领已签班报。需要 Python 3.11，使用标准库和单个 SQLite 文件。

## 运行

```text
python3 -B check_project.py
python3 -B shift_demo.py
```

`check_project.py` 由运行环境提供。也可从项目根目录执行 `python3 -B -m unittest discover -s tests -t . -v`。演示从 `samples/shift.json` 装载一班数据，在新临时库中签报、清理并重开领取。装载函数拒绝在已有业务数据的库中重放样例。`samples/early-shift.sql` 是一份可在空 V1 库初始化后载入的旧班数据样例，回归用它检查现有库上的重复初始化。

## 一个工作班

1. 采集员用 `scans.seams.register_seam(db, seam_id, description)` 登记实物，用 `scans.register.register_scan(db, seam_id, scan_id, capture_sheet, pixels, expires_at)` 登记原扫及其初始归属。暂缺归属时用 `intake_unassigned_scan(db, scan_id, capture_sheet, pixels, expires_at)`。像素是非空 `bytes`。`scans.read.read_scan` 读取采集事实和 `PayloadRef`，`retention.payloads.read_payload` 按引用读取像素。
2. 采集员用 `scans.attribution.publish_attribution(db, revision_id, assignments)` 发布具名归属，`assignments` 为扫描号到焊缝号的映射或有序键值对。每个修订单独发布完整映射，缺项为未归属。`read_scan_attribution(db, revision_id, scan_id)` 按所给修订读取。登记时的初始归属从 `read_scan` 读取。
3. 训练岗用 `training.patches.revise_patch(db, patch_id, revision_id, parents, pixels, expires_at)` 登记制作完成的裁片。其中父件由 `training.parents.ParentRef('scan', scan_id)` 或 `ParentRef('patch', revision_id)` 表示。`read_patch_revision` 读取可用的确切版次及有序直接父件。新版登记后，旧版定义可在保留期内继续核对。
4. `training.work_orders.checkout_training_materials(db, training_id, targets)` 按一张工单登记领用。`retention.holds.HoldTarget(kind, key)` 支持 `scan` 像素、`patch` 像素及 `definition` 派生定义。`read_work_order` 返回原领用清单和结案状态。`training.finish.finish_training(db, training_id, revision_ids)` 固定实际消费的非空叶级裁片修订清单。已有工单时，每个实际修订必须领过其像素或定义。像素和定义均须可用才能完工。直接完工也受同样的可用性检查。`training.receipts.read_training_receipt` 按训练号领取完工存值。
5. 质控岗调用 `quality.freeze.freeze_test(db, batch_id, training_ids, roster, labels, predictions)`。`training_ids` 为两个互异的完工训练号，顺序确定模型位置。`roster` 为有序的 `(片键, 原扫号)`，扫描可在不同片键出现。`labels` 按片键提交整数 `0` 或 `1`。`predictions` 有两个按模型位置排列的 `(训练号, 逐片概率记录)`，每组内部按片键配对，行序任意。概率接受 `Fraction`、整数或 `(整数分子, 正整数分母)`。三份逐片输入的片键均须精确覆盖清册。`quality.batches.read_frozen_batch` 读取冻结值。
6. 主管调用 `ratings.issue.issue_report(db, batch_id)` 签存该批的全清册报告。每片先算两个无量纲平方误差，再算第一模型误差减第二模型误差，最终取片差算术平均。示例依序保留 `t9` 和 `t2`，片差为 `-5/36` 和 `-65/144`，均差为 `-85/288`。空清册照常签发，均差为 `None`。每次成功签发有独立报告号及回执。
7. 归档岗用 `retention.sweep.sweep_due(db, cutoff)` 办理到期。截点与期限为 UTC Unix 整秒，等于期限时可纳入办理。直接领用分别保护像素和定义，解除最后一项占用后仍可按原截点重办。只有已被替代的到期定义可注销。`retention.retire.read_retirement_receipt(db, target)` 按资源引用领取注销凭据。扫描事实保留，注销资源的载荷或直接父表停止提供。
8. 次班用 `ratings.read.read_report(db, report_id)` 或 `ratings.export.export_report(db, report_id)` 领取报告存值。导出 JSON 保持清册序，分子及正分母用十进制字符串表示，空均差为 `null`。

## 连接及错误口径

用 `with weldbook.open_ledger(path) as db:` 打开台账，再以 `weldbook.initialize(db)` 补齐结构。初始化可重复执行。登记号是非空、首尾无空白的字符串，报告号是正整数。非法值、重复登记、输入配对冲突或已知但不可用的材料报 `ValueError`。合法未知引用报 `KeyError`。缺实测与显式零分别处理。签存或清理写失败时由事务回滚，可在排除失败条件后重试。各模块中接收已验证值并直接持久化的 `store`、`save`、占用维护和退役写函数由所属业务事务调用。

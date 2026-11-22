# 焊缝判读的去泄漏比较

目前 `ratings.issue.issue_report` 签发全清册班报。`README.md` 记录已有 V1 接口和保留规则。下面是本次要新增的训练证据查询与比较接口。

## 实际训练用料

现有 `finish_training` 和 `read_training_receipt` 继续办理和领取原完工单。新增 `training.receipts.read_training_scans(db, training_id)`，已知训练号的结果是按扫描号排序、去重的字符串元组。证据不全返回 `None`。扫描身份来自完工单实际使用的确切裁片修订及其所有父路径。工单上领过但未用于完工的裁片不计入。同名裁片换版也按原实际耗用修订核对。

间接父定义可在外层裁片完工前注销。原图、派生像素和 V1 生产父表仍按原规则清理，清理后训练证据仍须可领。经原 `initialize` 打开的旧库中，仍可由完整确切谱系证明的交班可以用于新比较。若旧库已有必要父关系丢失，则交班待证，原完工单仍按 V1 办理和读取。

## 比较与领报

- `ratings.clean.issue_clean_report(db, batch_id, training_ids, attribution_id)` 以冻结批、有序训练号对和具名归属修订申请签报。训练号对须与冻结批的顺序一致。对两份训练交班涉及的全部原扫与冻结清册中的全部原扫，均使用所选修订解释焊缝。任一训练谱系不全或任一扫描缺归属，只返回 `{'status': 'pending'}`，本次无报告和回执。
- 在归属齐备时，从两模型共同使用的测试清册移除任一训练交班用过同焊缝的片。每片独立按冻结清册位置处理，清册上的不同片键即使共用原扫仍分别列出。按入选片计算第一模型减第二模型的平均 Brier 分差。均差是 `Fraction`，无入选片时为 `None`，仍签发。
- 成功返回字典，`status` 为 `signed`，`report_id` 为正整数，`receipt_id` 为回执号。`batch_id`、`training_ids`、`attribution_id` 固定实际所用出处，`training_ids` 是列表，`training_scans` 是按同一模型序排列的两个原扫列表。`included` 为入选片键列表，`excluded` 为排除列表，各项有 `piece_id`、`scan_id`、`seam_id`、`matched_training_ids`，后者列全部命中训练号，沿模型序。入选和排除列表均沿冻结清册序。`mean_difference` 是签存均差。
- `ratings.clean.read_clean_report(db, report_id)` 按号返回同一签存字典。`ratings.clean.export_clean_report(db, report_id)` 返回该字典的 JSON 字符串，其中均差沿用 V1 的 `numerator`、`denominator` 十进制字符串对象，空均差为 `null`。

签报正文、资格及回执同时提交。写失败须回滚，排除失败条件后可重办。领取取签存值，发布新归属与重复初始化均不改变已签值。非法参数、无法用于比较的输入或有序训练号错配报 `ValueError`，合法未知引用报 `KeyError`。已知缺谱系或缺归属按待证口径处理。标识和连接约定沿用 `README.md`。

## 样例与交付核验

`python3 -B leakage_shift.py` 走现有入口准备训练、归档并展示旧全清册班报。可用其中的 `seed_shift`、`retire_shift`、`publish_review_revisions` 准备新接口的样例。甲领过乙的裁片但只用了 m1，原扫应为 `('s1', 's2')`。s1 有两条来源路径，p1 在甲完工前注销。乙使用 s3。三片 z、y、w 的分差依次为 0、0、−1/2。

R1 保留 z、y、w，均差为 −1/6。关闭旧定义与像素的保留后，发布 R2，z 命中甲的 W2，y 命中乙的 W3，只留 w，均差为 −1/2。Rwait 缺 s2 归属，应只返回待证。Rall 全部排除，均差为 `None`，其中 y、w 均同时命中甲乙。重开库后，原 R1 报告仍应读到 −1/6。旧全清册签报仍可用原接口读取。

现有 `.pointwise-runtime.json` 的版本 1 和 `cli` 类别继续适用。`setup` 是命令参数数组的列表，本工程为空。`verify` 和 `demo` 各为一个命令参数数组。交付时让核验入口同时跑原回归和本次业务核验，失败以非零状态退出。让演示入口展示实际签出的 R1 与归档后按 R2 签出的结果、排除依据和重开领取的 R1 存值。

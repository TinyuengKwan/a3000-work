# ILCE-3000 (Sony A3000) 固件提取 — 研究记录

目标：从 Sony **ILCE-3000**（2013，E-mount，CXD4132 架构）提取固件。

三套仓库的分工：
- `Sony-PMCA-RE`：老 Sony 相机的 USB 通信 + updater-mode 固件转储 exploit（**核心可用**）
- `a7c2-re` / `a7c2-tools`：针对 A7C II（CXD90045+），架构不同，**不可用于本机**；仅其 vendored `fwtool`（FDAT 解析/加密）可复用

## 已确认的事实

| 项 | 值 |
|---|---|
| USB 身份 | Mass Storage `054c:074d`（`bInterfaceClass=8 SCSI`），设备节点 `/dev/bus/usb/001/006`（root:root） |
| 型号 | `ILCE-3000` |
| modelCode（`getCameraInfo`） | `00 32 82 60 70`（5 字节） |
| 序列号 | `05276511` |
| 固件版本 | 当前 `1.01`，升级槽 `0.00`（`getFirmwareVersion`） |
| 架构 | **CXD4132**（同 NEX-3N/5N/5R/5T/6/7、SLT-A58），FDAT 用 **AES**（`key_cxd4132`） |
| **FDAT model 码** | **`0x31030024`**（经 `checkGuard` 暴力枚举，只有此值通过 model/version 校验后进入 Battery 检查，其余全部 `Invalid model`） |
| 载荷 | `updatershell/fdat/CXD4132.dat`（13264 字节，已含 `libupdaterbody.so` → `usbshell_loop()`） |

## FDAT 头的明文结构（CXD4132，0x30=48 字节）

```
[ 0: 4] block-wrapper 前缀（packBlock 的 2B 校验和 + 2B size/endflag）
[ 4:12] b'UDTRFIRM'
[12:16] checksum（注意：相机 checkGuard 阶段不强制校验，实测可直接通过）
[16:20] b'0100'
[20]    b'U'   [24] b'N'
[36:38] 0x99 0x09  → 版本 "9.99"
[40:44] model (INT32 LE)   ← 0x31030024 = ILCE-3000
[44:48] region (INT32 LE)  = 0
```

## 提取路线（updater-mode exploit）

`pmca-console updatershell` → `updaterShellCommand()`：
1. `getFdat('ILCE-3000')` 找到 `ILCE-3000.hdr` + `CXD4132.dat`
2. `init()` → `checkGuard()`（写入前校验，非破坏）
3. `switchMode()` → 相机重启进入 **updater 模式**（USB 变 `054c:033a`/`03e2`）
4. `writeFirmware()` 写入自定义固件，bootloader 加载 `libupdaterbody.so` → `usbshell_loop()`
5. 得到 USB shell：`SHEL`（交互 shell）、`PULL`（读文件）、`RMEM`（读内存）、`BLDR`（拷 bootloader）

## 已完成的固件提取（2026-11-11）

updater-mode exploit 成功，取得相机 root shell（BusyBox 1.13.4，内核
2.6.29.6-rt24-alp_nl，armv6l，Sony CE Linux 6.0.0.4）。

全部 11 个 NAND 分区已转储（共 152 MiB），每个分区字节数与内核报告一致、
md5 已记录于 `output/manifest.txt`：

| 分区 | 大小 | 内容 |
|---|---|---|
| nflasha0p1 | 4 MiB | FAT12（mkdosfs）|
| nflasha0p2 | 3 MiB | FAT12（= `/setting`）|
| nflasha0p3 | 10 MiB | `TPZL` 容器 |
| nflasha0p4 | 6 MiB | 校准数据（`raG46DSIT` 重复串 + 0xFF 擦除区）|
| nflasha0p5 | 40 MiB | `WBI1` 主固件镜像 |
| nflasha0p6 | 5 MiB | FAT12 |
| nflasha0p7 | 35 MiB | FAT12（含 `_UMDPF` 更新标记）|
| nflasha0p8 | 45 MiB | `TPZL` 容器 |
| nflasha0p10 | 2.75 MiB | FAT12 |
| nflasha0p12 | 1 MiB | 空/保留 |

关键机制：
- 分区大小取自 `/sys/block/nflasha0/nflasha0pN/size`（512B 扇区）
- 大分区走**分块 dd→tmpfs→PULL**（每块 4 MiB，走 `usb_transfer_read` 可靠帧），
  避免 SHEL 大流量中断；小分区直接单流 `cat`
- `nflasha12` md5 双向一致（`b1392783...`）验证了字节级正确性

## 分区表说明（p9/p11 缺失）

`/proc/partitions` 只列出 `nflasha0p1..p8, p10, p12`（**无 p9、p11**）。
`/dev/nflasha9`、`/dev/nflasha11` 等节点只是静态 mknod 空壳，无对应真实分区。

| 项 | 大小 |
|---|---|
| 已命名分区合计 | 155392 KiB ≈ 151.75 MiB |
| 整盘 nflasha0 | 261888 KiB ≈ 255.75 MiB |
| 差额（坏块管理/隐藏分区/保留区）| ≈ 104 MiB |

因此补做**整盘转储** `nflasha-whole.img`（255.75 MiB，md5 `819d029e...`），
覆盖 bootloader、坏块管理区与所有未分配 NAND 区域。

**交叉验证通过**：整盘镜像中 p1 区域（偏移 128 KiB 起，前面是 128 KiB 分区表
保留区）与单独转储的 `nflasha0p1.img` **逐字节一致**，三重校验（结构/大小/md5 +
交叉比对）齐备。

关键签名在整盘镜像中的偏移：
- `mkdosfs` @ 0x20003（p1 FAT12）
- `TPZL` @ 0x720000（p3）
- `WBI1` @ 0xe43c86（p5 主固件）
- `_UMDPF` @ 0x4520000（p7）

## 恢复与清理
相机每次会话后停在升级模式 `054c:03e2`，需断电重启恢复。转储已完成，
相机可正常断电重启回到海量存储。

## 脚本（本目录）
- `read_info.py`      — 只读：modelCode/固件版本
- `confirm_model.py`  — 用 checkGuard 确认 model 码（非破坏）
- `make_header.py`    — 生成 `ILCE-3000.hdr`
- `sanity_check.py`   — 用已知错误 model 验证 checkGuard 不破坏

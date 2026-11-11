# ILCE-3000 固件提取 Runbook（更新版）

前置：相机**已充满电或接 AC**；已在 Mass Storage 模式（USB `054c:074d`）。

## 状态回顾（已验证）

- model 码 = `0x31030024`（`checkGuard` 唯一通过值）
- `ILCE-3000.hdr` 已用 `build_fdat.py` **字节正确重建**（CRC + block wrapper 全对）
- updater-mode exploit **已跑通一次**：`writeFirmware 100%` → 载荷 `usbshell_loop` 启动
  （遗憾：`pmca-console` 的交互 shell 因无 TTY 读 stdin 而 EOF 崩溃，相机停留在
  升级模式非响应状态，需断电重启恢复）

## 幂等恢复（相机卡在 `054c:03e2` 时）

相机若停在升级模式不响应，**断电重启**：
1. 拔 USB → 关机 → 取电池 30 秒 → 装回 → 开机 → 接 USB（Mass Storage）

## 一键 dump（推荐：单进程，无 stdin 问题）

```bash
cd /home/Lunarwall/project/a3000-reverse
# info / uname
echo '<密码>' | sudo -S Sony-PMCA-RE/.venv/bin/python a3000-work/dump_fw.py info
# 跑任意相机内 shell 命令
echo '<密码>' | sudo -S Sony-PMCA-RE/.venv/bin/python a3000-work/dump_fw.py shell 'uname -a'
# 拷 bootloader
echo '<密码>' | sudo -S Sony-PMCA-RE/.venv/bin/python a3000-work/dump_fw.py bootloader a3000-work/output
# 读单文件
echo '<密码>' | sudo -S Sony-PMCA-RE/.venv/bin/python a3000-work/dump_fw.py pull /etc/version a3000-work/output/version.txt
```

`dump_fw.py` 在 `writeFirmware` 完成的 `complete()` 回调里直接用 `UsbPlatformBackend`
下发 `SHEL`/`BLDR`/`PULL` 命令，避免交互式 `input()` 的 EOF 问题。

## 相机内 shell 可用命令（载荷侧 `usbshell.cpp`）

- `SHEL` → 派 `sh -i`；`PULL <path>` → 读文件；`PUSH <path>` → 写文件
- `RMEM <off> <size>` → 读内存；`BLDR` → 拷 bootloader block
- 相机 shell 精简：有 `cat dd grep sed mknod mount ps sleep tar cp gzip` 等

## 转储目标（ILCE-3000 分区 ×2）

进入 `shell` 后先摸清分区：
```
cat /proc/mtd
mount
ls /dev/nflasha* /dev/cnflasha*
```
参考 A7C II 的做法：批量数据写 **SD 卡**（相机内 `/tmp`/`/etc` 共 12 MiB vfat，易写满）。

## 风险与责任
仅用于本人设备与研究；不碰只读分区；断电可恢复本体。作者不对损坏负责。

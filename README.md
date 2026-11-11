# a3000-work — Sony ILCE-3000 (A3000) 固件提取

对 **Sony ILCE-3000**（2013，E-mount，CXD4132 架构）的授权逆向研究。
通过 Sony-PMCA-RE 的 updater-mode exploit 取得相机 root shell，并完整转储整块 NAND 闪存。

> ⚠️ 只在自己的设备、以学术研究为目的使用。作者不对设备损坏/数据丢失负责。
> 详见 [NOTES.md](NOTES.md) 与 [runbook.md](runbook.md)。

## 成果速览

- **模型码** `0x31030024`（历史上悬而未决，本仓库经 `checkGuard` 枚举唯一命中）
- **内核** 2.6.29.6-rt24-alp_nl（armv6l，Sony CE Linux 6.0.0.4）
- **整盘 NAND** `nflasha0` = 256 MiB，11 个分区（p1–p8、p10、p12；无 p9/p11）
- **分区内容**：p5 = `WBI1` 主固件；p3/p8 = `TPZL` 容器；其余多为 FAT12 / 校准数据

## 固件镜像（不在本仓库）

转储出的 NAND 镜像**不进 git**（超 100MiB + 隐私约定），改以 **GitHub Release 附件**提供：

| 附件 | 内容 |
|---|---|
| `ilce3000-firmware-whole.tar.xz` | 整盘 256 MiB 镜像 `nflasha-whole.img` |
| `ilce3000-firmware-partitions.tar.xz` | 10 个分区镜像 `nflasha0p*.img` |

校验值见同一 Release 内的 `SHA256SUMS.txt`。

## 脚本说明

- `read_info.py` — 只读查询相机型号/固件版本（modelCode）
- `confirm_model.py` — 用非破坏 `checkGuard` 确认 model 码
- `build_fdat.py` — 生成字节正确的 `ILCE-3000.hdr`（fwtool）
- `dump_fw.py` — 单进程 dump 驱动（info / shell / inventory / bootloader / pull / dump / dumpbig / dumpwhole）
- `run_bg.sh` — 后台运行 wrapper

## 依赖

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)（updater-mode exploit 主体）
- [fwtool.py](https://github.com/ma1co/fwtool.py)（FDAT 加解密，vendored 于 a7c2-tools）
- Python 3 + `pyusb` + `pycryptodomex` + `pyyaml`

## License

MIT。

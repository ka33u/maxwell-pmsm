# 气隙、定子齿部与定子轭部磁密

在空载、指定电流负载工况的标准结果中加入这三处磁密。下述工具适用于转轴在原点、XY 全圆、均匀分槽、从内向外依次为转子和定子的 Maxwell 2D 瞬态模型。对偏心、外转子、扇区、非均匀槽或转子轭，按实际几何重建取样位置和坐标映射。

## 求解前

从标注尺寸与**已建模型**确定转子最大外半径、定子内半径、槽底最大半径、定子外半径，以及 1 槽中心角。在最后一个完整电周期保留场解。D 盘项目根目录的空载/带载命令行生成器及混合匝数入口默认每电周期保存至少 12 个等间隔；例如步长 3° 时 `--save-fields-every 10` 对应 30° 电角度。显式传 0 关闭周期存场。历史算例以 `.asol` 中有实际二进制场文件的时刻为准。单帧只能给出该时刻的空间结果。对强饱和或局部峰值，缩小存场间隔和网格后再比较。

几何配置示例中长度均为 **半径 mm**，机械角均从全局 +X 轴逆时针计算。按本机模型替换以下参数和对象名称。

```json
{"rotor_tip_mm":146.5,"bore_mm":147.5,"slot_bottom_mm":177.7,"outer_mm":200,
 "slots":72,"poles":12,"slot1_deg":90,"angles":720,"gap_fraction":0.6,
 "tooth_offset_pitch":0.08,"stator":"Stator","steel_material":"REUSE_STEEL",
 "air_bodies":["Region","Band"],"air_materials":["vacuum","air"]}
```

| 区域 | 取样与报告 |
|---|---|
| 气隙 | 在转子最大半径与定子内圆之间取全圆。示例取最小气隙厚度从转子向外的 60%，避开位于 50% 的运动带边界。非圆极靴下这是恒半径圆。输出带符号径向分量 Br、切向分量 Bt 可由原始矢量重算。报告 Br 绝对峰值和全圆按极对数阶提取的 Br 空间基波幅值（峰值 T）。 |
| 定子齿 | 相邻槽中心之间为齿中心，默认在槽深的 20%、50%、80% 取样，每个齿中心及其两侧各取一点，侧点偏移量按槽距给定。报告各齿采样的最大三维矢量模、平均模、P95 和径向分量统计。 |
| 定子轭 | 槽底至外圆的轭厚沿径向取同样的三个比例，每层均匀扫全圆。报告最大矢量模、平均模、P95 和切向分量统计。 |

## 导出与核验

1. 用 `flux_density.py prepare` 指定独立导出目录。工具审查原算例，按 setup 与标称解读取真实存场时刻，复制工程及配套结果，记录哈希和点位。传入本项目标准 `noload` 或 `load` 算例。默认钢体为 `Stator`，如有特殊槽形、通风孔或键槽，必须复核点位。
2. 用 AEDT 原生 `-RunScriptAndExit` 或项目 MCP 的 `run_python_script` 执行生成的 `export_fields.py`。脚本逐点检查气隙或钢体归属，以 Global 坐标导出 Bx、By、Bz；目录采用可写的短英文路径。
3. 用 `flux_density.py summarize` 校验点数、顺序、坐标单位、有限值和完整日志。按 Br=Bx·cosθ+By·sinθ，Bt=−Bx·sinθ+By·cosθ 计算。末时刻另导出 Maxwell 的 `Mag(B)`，记录它与先导出分量再取模的逐点差和区域峰值差。两种取模顺序的点值可能受场插值影响。

```text
python <skill>/scripts/flux_density.py prepare --case <完成的算例> --kind noload --geometry <几何.json> --out <新目录>
ansysedt.exe -ng -RunScriptAndExit <新目录>/export_fields.py
python <skill>/scripts/flux_density.py summarize --export <新目录>
python <skill>/scripts/flux_density.py waveform --export <新目录> --time-index -1 --out <末帧空间波形.csv>
```

`time_metrics.csv` 每个存场时刻、每个区域一行。`summary.json` 记录各区域采样峰值、时刻、位置和末帧交叉检查。`points.csv` 与同序 `B_*.fld` 可重建空间波形。统计平均为采样点等权平均。加密时保持相同取样范围，可增加 `angles`、细分 `depth_fractions`、增加 `tooth_side_subdivisions`。这些结果表征选定截面和离散时刻。齿尖、齿根圆角、轭部局部缺口等热点需额外布点和细化网格。参考本项目 `flux_density_20261122` 下的验证结果。[Ansys 场文件导出接口](https://aedt.docs.pyansys.com/version/dev/API/visualization/_autosummary/ansys.aedt.core.visualization.post.post_common_3d.PostProcessor3D.export_field_file.html)

## 磁密有效值（T）

与瞬时峰值并列显示有效值。下述周期统计取一个完整电周期，沿实际存场时刻对平方值作梯形积分，除以周期后再开方。保留直流及采样可分辨的谐波。存场只覆盖一个时刻、只有周期两个端点或时间窗不完整时，仅给出各帧空间统计，`cycle_rms` 为空。保存帧数决定高次时间谐波的分辨能力。

| 报告量 | 定义与输出 |
|---|---|
| 气隙径向全波 RMS | 每帧对均匀圆周所有 Br 平方取均值并开方，见 `time_metrics.csv` 的 `spatial_rms_component_T`。整周期汇总取 `cycle_rms.gap.component_space_time_rms_T`，对应各帧空间 RMS 平方的时间均值再开方。 |
| 气隙径向基波 RMS | 各帧按极对数提取 Br 空间基波，基波峰值除以 √2。对各帧基波 RMS 的平方作相同时间积分，见 `cycle_rms.gap.fundamental_Br_space_time_rms_T`。全波 RMS 直接使用原始分量。 |
| 齿部、轭部区域 RMS | 各固定采样点对 Bx²+By²+Bz² 求周期均值，再在各区域按点等权取均值后开方，见 `Bmag_space_time_rms_T`。报告中标清点位范围与权重，此量反映离散采样范围。 |
| 固定点周期 RMS 最大值 | 先对每个点分别求整个周期的矢量模 RMS，再在同一区域找出最大的点。坐标和索引在 `summary.json` 的 `cycle_rms` 中，所有点的 Br、Bt、矢量模周期 RMS 见 `point_cycle_rms.csv`。 |

以前已完成原始矢量导出的算例可直接重跑 `summarize` 更新派生表。与设计单核对时，先确认对应栏采用的分量、位置、峰值、平均值或有效值。Ansys Motor-CAD 的永磁无刷电机输出也分别定义了气隙平均和峰值、齿部及轭部峰值。[Ansys 磁密指标定义](https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/flux_densities_bpm_output_data.html)

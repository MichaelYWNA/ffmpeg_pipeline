# ffmpeg_pipeline · 个人维护分支

把 FFmpeg 拆成 ROS 2 可编排积木的音视频流水线：采集 → 解复用 → 解码 → 格式转换 → 编码 →
复用/输出，每一段都是一个 `ros2_control` 插件，用 YAML 连起来，换编码器或换输入源不用改代码。

- **维护者（本分支）**：MichaelYWNA · <https://github.com/MichaelYWNA>
- **上游项目**：<https://github.com/yoshito-n-students/ffmpeg_pipeline> · 作者 **Yoshito Okada**（东北大学）
- **许可证**：MIT。原作者版权与本分支修改版权并列保留，见 [LICENSE](LICENSE) 与 [docs/PROVENANCE.md](docs/PROVENANCE.md)
- **本分支基线**：上游 `jazzy` 分支 `5ffbabbf`（2025-11-28）

> 这个仓库是上游的 **fork**，不是原创项目。`ffmpeg_cpp` / `ffmpeg_controllers` /
> `ffmpeg_hardware` / `ffmpeg_image_transport` / `ffmpeg_pipeline_msgs` 的架构与实现属于
> 原作者；我做的是读通它、在本机跑通、修掉我确认的缺陷、补示例和测量工具。
> 「哪些是我做的」逐条列在下面第 3 节，`git log --author=MichaelYWNA` 可逐条核对。

---

## 1. 这套东西解决什么问题

机器人上把摄像头画面/麦克风音频送到操作端，常见做法是走 `image_transport` 的 JPEG：
每帧都要软编、带宽大、延迟高。上游的思路是把编解码交给 FFmpeg，并把每个处理环节做成
`ros2_control` 的 chainable controller，于是：

- **声明式组网**：`controllers.yaml` 里用 `input_name` 声明数据从哪个 controller 来，
  自动形成 DAG，不写 C++ 节点；
- **零拷贝转发**：帧不序列化，controller 之间通过 state interface 传**对象指针**
  （`reinterpret_cast` 成 `double`），省掉 1080p@30fps 每秒几百 MB 的 DDS 序列化；
- **能力对齐 FFmpeg**：V4L2 / PulseAudio / 文件 / 网络流都能进，H.264 / H.265 / Opus /
  MJPEG 等上百种编码器都能选，硬编（VAAPI/CUDA/Vulkan）只改一个参数。

包结构：

| 包 | 职责 |
|---|---|
| `ffmpeg_cpp` | libav* 的 C++17 RAII 封装（Input/Output/Decoder/Encoder/Frame/Packet/...） |
| `ffmpeg_controllers` | chainable controllers：6 个 filter、4 个 broadcaster、2 个 receiver、2 个 writer |
| `ffmpeg_hardware` | `ros2_control` 硬件插件：`FFmpegInput` / `FFmpegOutput` / `DumpInfoOutput` |
| `ffmpeg_image_transport` | `image_transport` 插件：`ffmpeg_pub` / `ffmpeg_sub` |
| `ffmpeg_pipeline_msgs` | `Frame` / `Packet` 消息定义 |
| `ffmpeg_pipeline_examples` | 可直接 `ros2 launch` 的示例链路（含本分支新增的 `h265_camera`） |

---

## 2. 在本机跑通的环境与结果（实测，非估计）

所有数字都是 2026-10-21 在本机同一条命令跑出来的，复现方法见第 5 节。

| 项目 | 值 |
|---|---|
| 系统 | Ubuntu 24.04.3 LTS（WSL2，kernel 6.6.87.2-microsoft-standard-WSL2） |
| CPU / 内存 | 32 vCPU / 15 GiB |
| 编译器 / CMake | GCC 13.3.0 / CMake 3.28.3 |
| ROS 2 | Jazzy（`/opt/ros/jazzy`，apt 安装） |
| FFmpeg | libavcodec 60.31.102、libavformat 60.16.100、libavutil 58.29.100、libswscale 7.5.100、libswresample 4.12.100（即 FFmpeg 6.1） |
| 全量编译 | 7 个包，**1 分 10–12 秒**（32 workers，`-DCMAKE_BUILD_TYPE=Release`，多次运行区间），0 error |
| 增量编译 | **6.4 秒** |
| `colcon test` | **270 tests, 0 errors, 0 failures, 56 skipped**（干净 clone 上连跑多次一致） |
| 端到端运行 | `webp_file` 链路跑通，`CompressedImage` 话题实测 **2.000 Hz**，抖动 **0.39–0.41 %**，0.581 MB/s |

端到端那一条的原始输出（`scripts/topic_bench.py`，15 秒窗口）：

```
messages=30 window=14.500s hz=2.000 dt_mean=500.00ms dt_min=494.03ms dt_max=506.01ms
dt_std=2.05ms jitter=0.41% payload_mean=290314B bw=0.581MB/s
```

控制器与硬件确实被加载并激活：

```
$ ros2 control list_controllers -c /ros2_control_node
compressed_image_broadcaster  ffmpeg_controllers/CompressedImageBroadcaster  active

$ ros2 control list_hardware_components -c /ros2_control_node
name: image_reader  type: sensor  plugin: ffmpeg_hardware/FFmpegInput  state: active
```

---

## 3. 我在这个分支里做了什么

### 3.1 修掉两个真实缺陷（`ffmpeg_cpp/src/internal.hpp`）

`colcon test` 一开始是 **16 个 failure**，其中 `ffmpeg_cpp` 的 `FrameTest` 忽过忽挂。
逐层查下来是两处：

1. **`ch_layout` 未初始化的未定义行为**
   `to_channel_layout()` 声明了 `AVChannelLayout ch_layout;` 却没初始化；当
   `av_channel_layout_from_string()` 失败（视频消息的 `ch_layout` 就是空串）时只清了
   `nb_channels`，`order` 和 `u` 联合体仍带栈残值。于是视频帧拿到随机声道序 —— 这就是
   "同一份代码有时挂有时过"的来源。改为值初始化 + 失败时 `av_channel_layout_uninit()`。
2. **空布局被描述成 `"0 channels"`**
   `av_channel_layout_describe()` 对清零的布局返回 `ret=11`、`describe="0 channels"`
   （本机用 20 行 C 程序实测确认），导致 `ch_layout_str().empty()` 对视频帧恒为假，
   上游那条断言其实在 FFmpeg 6.1 上不可能成立。改为 `nb_channels <= 0` 时返回空串，
   合法布局（`nb_channels > 0`）行为不变。

修完 `test_frame` 11/11 连续 3 次通过，全量测试从 16 failures 收敛到 **0**。
细节与另外几条我确认但没动的缺陷写在 [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)。

### 3.2 新增示例 `ffmpeg_pipeline_examples/h265_camera`

上游只有 `h264_camera`（依赖相机自带 H.264 编码）。这个示例把输入换成
`input_format: hevc`、1920×1080@30，走同一条 `FFmpegInput → CompressedImageBroadcaster`
直通链路，演示"相机原生 H.265、不做二次编码"的配置方式。
**注意**：本机没有 HEVC 摄像头，这个示例只验证了 `xacro` + `ros2 launch` 能正确解析
（`ros2 launch ... --show-args` 级别）和随包安装，**未做真机联调**，`url` 必须改成你自己的设备。

### 3.3 新增测量工具 `scripts/topic_bench.py`

`ros2 topic hz` / `bw` 只能盯屏幕看。这个脚本订阅话题，用本机单调时钟统计到达间隔，
一次输出一行 CSV（rate、dt 的均值/极值/标准差、抖动百分比、平均载荷、带宽），
可以直接进表格、进 CI、进报告。`--qos-reliability` 可选 `best_effort` / `reliable`，
用来复现 QoS 不匹配导致的"收不到数据"。

### 3.4 工程卫生

| 改动 | 原因 |
|---|---|
| 新增根目录 `LICENSE` | 上游只在各 `package.xml` 声明 MIT，根目录无 LICENSE；examples 里的 LICENSE 缺版权行。MIT 要求保留版权声明，fork 必须补 |
| 新增 `docs/PROVENANCE.md` | 写明上游 commit、哪些是上游代码、哪些是我的改动、为什么改 maintainer |
| 7 个 `package.xml`：maintainer 换成我，新增 `<author>` 保留原作者 | `<maintainer>` 语义是"这个仓库谁负责"，fork 里就是 fork owner；作者身份不隐藏 |
| `.github/workflows/ci.yml`：`repository:` 改为 `${{ github.repository }}` | 上游硬编码了自己的仓库，fork 后 CI 会去构建上游代码 |
| 新增 `scripts/setup_xml_catalog.sh` | `package.xml` 的 `<?xml-model>` 让 `xmllint` 每次联网取 schema，受限网络下会撞 60 s 超时报假红；本地 catalog 后从 60 s+ 降到 62 ms |

### 3.5 文档

`README.md`（本文件）重写为中文主叙述；上游原版 README 完整保留在
[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)，供对照。

---

## 4. 从零复现

```bash
# 1) 依赖（Ubuntu 24.04 / ROS 2 Jazzy）
sudo apt install -y ros-jazzy-desktop ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-image-transport ros-jazzy-xacro ros-jazzy-image-view \
  libavcodec-dev libavdevice-dev libavfilter-dev libavformat-dev libavutil-dev \
  libswresample-dev libswscale-dev python3-colcon-common-extensions

# 2) 建工作区
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
git clone https://github.com/MichaelYWNA/ffmpeg_pipeline.git
cd ~/ros2_ws

# 3) 编译与测试
source /opt/ros/jazzy/setup.bash
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
colcon test && colcon test-result --verbose

# 4) 跑一条不需要摄像头的链路（会循环读一张 webp）
source install/setup.bash
ros2 launch ffmpeg_pipeline_examples webp_file_pipeline.launch.py
# 另一个终端：
ros2 control list_controllers -c /ros2_control_node
python3 src/ffmpeg_pipeline/scripts/topic_bench.py \
  /compressed_image_broadcaster/image/ffmpeg --seconds 15 --qos-reliability reliable
```

有 H.265 摄像头时（`h265_camera` 示例，先把 `url` 改成你的设备）：

```bash
ros2 launch ffmpeg_pipeline_examples h265_camera_pipeline.launch.py
```

---

## 5. 这些数字怎么复现

| 简历/文档里的说法 | 复现命令 |
|---|---|
| 7 包 1 分 12 秒编完 | `time colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release` |
| 270 个测试全绿 | `colcon test && colcon test-result` |
| 单元测试不再随机失败 | `for i in 1 2 3; do ./build/ffmpeg_cpp/test_frame; done` |
| 2.000 Hz / 抖动 0.41 % | `python3 src/ffmpeg_pipeline/scripts/topic_bench.py <topic> --seconds 15` |
| 上游版本与许可证 | `git log -1 --format=%H` / `cat LICENSE docs/PROVENANCE.md` |
| `xmllint` 不再随机假红 | `sudo bash scripts/setup_xml_catalog.sh` 后连跑 `colcon test` |

---

## 6. 已知问题

见 [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)。摘要：已修 2 处 `ch_layout` 缺陷；
确认但未改"每拍只保留最新帧"的丢帧风险；推断 `double` 里塞指针在启用 5 级页表
（LA57，57 bit VA）的机器上会失效 —— 本机 `grep la57 /proc/cpuinfo` 无该标志，
即 4 级页表 47 bit，故该假设在本机成立。

---

## 7. 许可证与致谢

MIT，见 [LICENSE](LICENSE)。

- 原始设计与实现：**Yoshito Okada**（东北大学），<https://github.com/yoshito-n-students/ffmpeg_pipeline>
- 上游文档：<https://github.com/yoshito-n-students/ffmpeg_pipeline#readme>（本地副本 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)）
- 本分支的修改与新增：MichaelYWNA，逐条见第 3 节与 git 历史

如果你要用这套代码，请优先使用上游仓库并给上游点 star；本分支的价值在于多一份
可复现的验证记录和两个已修缺陷。

---

## English abstract

A fork of [`yoshito-n-students/ffmpeg_pipeline`](https://github.com/yoshito-n-students/ffmpeg_pipeline)
(by Yoshito Okada, Tohoku University, MIT): a ROS 2 pipeline that exposes FFmpeg stages as
pluggable `ros2_control` components chained by YAML. This fork adds verified build/test
records (270 tests green on Ubuntu 24.04 + Jazzy + FFmpeg 6.1), fixes two real defects in
`ffmpeg_cpp`'s channel-layout handling (uninitialised `AVChannelLayout`, and an unset layout
being described as `"0 channels"`), contributes an `h265_camera` example and a
`scripts/topic_bench.py` measurement tool, and documents known issues including a
single-latest-frame drop risk and the 47-bit assumption behind pointer tunnelling.
Upstream authorship is preserved in `LICENSE`, `docs/PROVENANCE.md` and every `package.xml`
`<author>` tag.

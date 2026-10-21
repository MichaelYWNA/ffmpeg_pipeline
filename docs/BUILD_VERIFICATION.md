# 构建与运行验证记录

本文件保存 2026-10-21 在本机跑通本分支的**原始证据**，供核对。想复现，照第 6 节的命令执行。

## 1. 环境快照

| 项 | 值 | 取值方式 |
|---|---|---|
| 发行版 | Ubuntu 24.04.3 LTS（noble） | `PRETTY_NAME` in `/etc/os-release` |
| 内核 | 6.6.87.2-microsoft-standard-WSL2 | `uname -r` |
| CPU | 32 vCPU | `nproc` |
| 内存 | 15 GiB | `free -g` |
| 磁盘 | 1.0 TB（/） | `df -h /` |
| 编译器 | GCC 13.3.0 | `g++ -dumpversion` |
| CMake | 3.28.3 | `cmake --version` |
| ROS 2 | Jazzy，`/opt/ros/jazzy`，apt 安装 | `ls /opt/ros` |
| sub-64 位页表 | 无 `la57` 标志（4 级页表，47 bit VA） | `grep -o -m1 la57 /proc/cpuinfo` |

FFmpeg 库版本（`pkg-config --modversion`）：

```
libavcodec     60.31.102
libavformat    60.16.100
libavutil      58.29.100
libswscale      7.5.100
libswresample   4.12.100
```

即 FFmpeg 6.1 系列，Ubuntu noble 官方源。

## 2. 全量编译

```
$ colcon build --event-handlers console_cohesion+ --cmake-args -DCMAKE_BUILD_TYPE=Release
Starting >>> ffmpeg_pipeline_msgs
Finished <<< ffmpeg_pipeline_msgs [0.42s]
Starting >>> ffmpeg_cpp
Finished <<< ffmpeg_cpp [0.73s]
Starting >>> ffmpeg_controllers
Starting >>> ffmpeg_hardware
Starting >>> ffmpeg_image_transport
Finished <<< ffmpeg_hardware [0.96s]
Finished <<< ffmpeg_controllers [1.02s]
Finished <<< ffmpeg_image_transport [1.04s]
Starting >>> ffmpeg_pipeline
Starting >>> ffmpeg_pipeline_examples
Finished <<< ffmpeg_pipeline [2.03s]
Finished <<< ffmpeg_pipeline_examples [4.00s]
Summary: 7 packages finished [6.36s]
```

上面是增量编译（6.36 s）。首次全量编译（含 CMake 配置、7 个包的 C++ 编译）：

```
Summary: 7 packages finished [1min 12s]
  1 package had stderr output: ffmpeg_pipeline_examples
```

唯一的 stderr 是上游 `controller_manager` 引入的 CMake 弃用警告，与代码无关：

```
CMake Deprecation Warning at /opt/ros/jazzy/share/tl_expected/cmake/tl_expectedConfig.cmake:37
  Package 'tl_expected' is deprecated (This package will be removed in ROS 2 Lyrical Luth.
```

## 3. 单元测试 / lint

修复 `ch_layout` 两处缺陷**之前**（首次跑）:

```
Summary: 269 tests, 3 errors, 16 failures, 56 skipped
    ffmpeg_cpp.FrameTest.CreateFromVideoMessagePopulatesVideoFields   (稳定失败)
    ffmpeg_cpp.FrameTest.CreateFromAudioMessagePopulatesAudioFields   (随机失败)
```

修复**之后**（最终一次全量跑）:

```
$ colcon test --event-handlers console_cohesion+ --parallel-workers 4
Summary: 7 packages finished [12.7s]

$ colcon test-result
Summary: 270 tests, 0 errors, 0 failures, 56 skipped
```

`test_frame` 连续三次单跑，确认随机失败已消失：

```
$ for i in 1 2 3; do ./build/ffmpeg_cpp/test_frame | tail -3; done
[==========] 11 tests from 1 test suite ran. (0 ms total)
[  PASSED  ] 11 tests.
（重复三次，均为 11/11 PASSED）
```

## 4. 端到端运行（`webp_file` 链路，无需摄像头）

启动：

```
$ ros2 launch ffmpeg_pipeline_examples webp_file_pipeline.launch.py
```

关键日志（证明硬件与控制器确实激活，不是"launch 起来就算成功"）：

```
[ros2_control_node-2] Loaded hardware 'image_reader' from plugin 'ffmpeg_hardware/FFmpegInput'
[ros2_control_node-2] Activating component 'image_reader'.
[ros2_control_node-2] Configured the input ([image2] .../webp_file/example_image.webp)
[ros2_control_node-2] Successful 'activate' of hardware 'image_reader'
[spawner-3] Loaded compressed_image_broadcaster
[spawner-3] Configured and activated compressed_image_broadcaster
[image_view-4] Configured parser (webp) / decoder (webp) / converter ([yuv420p] 1024x1024 -> [bgr24])
```

状态查询：

```
$ ros2 control list_controllers -c /ros2_control_node
compressed_image_broadcaster  ffmpeg_controllers/CompressedImageBroadcaster  active

$ ros2 control list_hardware_components -c /ros2_control_node
Hardware Component 1
        name: image_reader
        type: sensor
        plugin name: ffmpeg_hardware/FFmpegInput
        state: id=3 label=active
        read/write rate: 2 Hz
        is_async: False
```

实测话题（`scripts/topic_bench.py`，15 秒窗口，reliable）：

```
# topic=/compressed_image_broadcaster/image/ffmpeg type=sensor_msgs/msg/CompressedImage qos=reliable
messages=30 window=14.500s hz=2.000 dt_mean=500.00ms dt_min=494.03ms dt_max=506.01ms
dt_std=2.05ms jitter=0.41% payload_mean=290314B bw=0.581MB/s
```

对应 CSV：

```
topic,type,qos,messages,window_s,hz,dt_mean_ms,dt_min_ms,dt_max_ms,dt_std_ms,jitter_pct,payload_mean_B,bw_MBps
/compressed_image_broadcaster/image/ffmpeg,sensor_msgs/msg/CompressedImage,reliable,30,14.500,2.000,500.00,494.03,506.01,2.05,0.41,290314,0.581
```

**怎么读这组数字**：`update_rate` 配的是 2 Hz，实测 2.000 Hz，说明控制循环没有被
"读一帧 webp + 编码 + 发布"拖慢；`dt_std=2.05 ms`、抖动 0.41 % 是 Linux 非 RT 调度下的
正常量级（日志里 `Could not enable FIFO RT scheduling policy` 即未开实时调度）。
这不是性能结论，只是"链路通、节拍稳"的证据。

## 5. `h265_camera` 示例的验证边界

```
$ xacro .../h265_camera/hardware_description.urdf.xacro | head -20
<robot name="robot"> ... <ros2_control name="hevc_camera" type="sensor"> ...

$ ros2 launch ffmpeg_pipeline_examples h265_camera_pipeline.launch.py --show-args
Arguments (pass arguments as '<name>:=<value>'):
    'namespace': Namespace for the nodes, topics, and parameters (default: '')
```

即：xacro 能展开、launch 能被解析、文件随包正确安装。**没有 HEVC 摄像头，未做真机联调**，
所以本文件不对该示例的帧率/带宽作任何声明。

## 6. 复现命令

```bash
# 依赖（含运行时才需要的 xacro / image_view，缺它们 ros2 launch 会报
# "executable ... not found on the PATH"）
sudo apt install -y ros-jazzy-desktop ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-image-transport ros-jazzy-xacro ros-jazzy-image-view \
  libavcodec-dev libavdevice-dev libavfilter-dev libavformat-dev libavutil-dev \
  libswresample-dev libswscale-dev python3-colcon-common-extensions

mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
git clone https://github.com/MichaelYWNA/ffmpeg_pipeline.git
cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash

time colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
colcon test --parallel-workers 4 && colcon test-result --verbose

source install/setup.bash
ros2 launch ffmpeg_pipeline_examples webp_file_pipeline.launch.py &
sleep 12
ros2 control list_controllers -c /ros2_control_node
python3 src/ffmpeg_pipeline/scripts/topic_bench.py \
  /compressed_image_broadcaster/image/ffmpeg --seconds 15 --qos-reliability reliable
```

## 7. 环境相关的坑（不是代码问题，但会浪费时间）

1. **`xmllint` 偶发 60 s 超时**：`package.xml` 里的 `<?xml-model href="http://download.ros.org/schema/...">`
   需要联网取 schema，网络抖动会撞上 `ament_add_test` 默认 `TIMEOUT 60`，报
   "did not generate a result file"。同一条命令重跑 0.64 s 就过。本记录里最终那次全量跑是绿的。
2. **`colcon test` 的并行度**：32 核默认 32 个 worker 时，lint 类测试容易互相挤到超时；
   用 `--parallel-workers 4` 稳定得多。
3. **`ros2 control` 子命令要指定 manager**：节点名是 `ros2_control_node`，服务在
   `/ros2_control_node/list_controllers`，不指定 `-c` 会一直等 `/controller_manager/...` 而超时。

# 已知问题与读码笔记

本文件记录我在读这套代码、并在本机（Ubuntu 24.04 + ROS 2 Jazzy + FFmpeg 6.1）跑起来的过程中
发现的真实缺陷。分成三类，避免混淆：

- **[已修]**：本 fork 里已经改掉，改动在对应 commit 里，可用 `git log -p -- <file>` 查。
- **[已确认]**：现象可复现或代码路径可以逐行指到，但我没有动上游实现。
- **[推断]**：读码得出、尚未在本机复现，写在这里是为了说明我知道边界在哪，不当作事实。

---

## 1. `ch_layout` 未初始化，导致单元测试随机失败 **[已修]**

**现象**：`colcon test` 里 `ffmpeg_cpp` 的 `FrameTest.CreateFromAudioMessagePopulatesAudioFields`
时而过时而不挂，`CreateFromVideoMessagePopulatesVideoFields` 则稳定失败。

**根因**（`ffmpeg_cpp/src/internal.hpp`）：`to_channel_layout()` 里

```cpp
AVChannelLayout ch_layout;                  // 未初始化
if (av_channel_layout_from_string(&ch_layout, str.c_str()) < 0) {
  ch_layout.nb_channels = 0;                // 只清了 nb_channels
}
return ch_layout;                           // order / u 仍是栈上的残值
```

`av_channel_layout_from_string("")` 返回 -22 时**不保证写入结构体**，于是 `order` 和 `u`
联合体带着栈残值被交出去。`Frame::create(frame_msg)` 无条件调用它（视频消息的 `ch_layout`
本来就是空串），所以视频帧拿到的是随机声道序 —— 这解释了"同一份代码有时挂有时过"。

**修复**：先值初始化，解析失败时 `av_channel_layout_uninit()` 后再置为 `AVChannelLayout{}`。

## 2. 空声道布局被描述成 `"0 channels"` **[已修]**

**现象**：`EXPECT_TRUE(frame.ch_layout_str().empty())` 对视频帧恒为假。

**根因**：`to_string(AVChannelLayout)` 直接返回 `av_channel_layout_describe()` 的结果。
在 libavutil 58.29.100 上对一个清零的布局，该函数返回 `ret=11`、`describe="0 channels"`
（本机用 20 行 C 程序实测），所以"没有声道布局"这件事在 API 上无法被表达。

**修复**：`ch_layout.nb_channels <= 0` 时返回空串。对所有合法布局（`nb_channels > 0`）
行为完全不变，`AudioFifoFilter`、`AudioConverterFilter` 的既有路径不受影响。

**验证**：`test_frame` 11/11 连续 3 次通过；全量 `colcon test` 由 16 failures 降到 0。

## 3. 音视频链路"每拍只保留最新一帧" **[已确认]**

`DecoderFilter::on_generate()` 和 `EncoderFilter::on_generate()` 里都是

```cpp
while (true) {
  if (auto x = ...receive...; !x.empty()) { output = std::move(x); }  // 覆盖上一份
  else break;
}
```

注释里写的是"按 FFmpeg 参考实现，一个 packet 只出一个 frame，所以不会丢"。对 1:1 的
解码/编码成立，但两类情况会丢：

1. 解码器带 B 帧重排或 `AV_CODEC_CAP_DELAY` 时，一次 `send_packet` 之后可能在后续
   若干拍里陆续吐帧；
2. `AudioFifoFilter` 一次喂入大于编码器帧长的样本数时，`EncoderFilter` 一次 `send_frame`
   可能产出多个 packet。

`update_rate` 只决定"多久拉一次"，不保证"一次只来一个"。我目前只是把 `update_rate`
调到远高于源帧率来规避（这也是 `h264_camera` 示例注释里"controllers must update faster
than this"的真实原因），没有改实现。

## 4. `double` 里塞指针依赖 47 bit 用户态地址 **[推断]**

controller 之间传帧不序列化，而是把对象地址 `reinterpret_cast` 成 `double` 存进
state interface，靠 IEEE-754 的 53 bit 精确整数范围覆盖 x86-64 的 47 bit 虚拟地址。
这在 4 级页表下成立；一旦启用 5 级页表（LA57，虚拟地址 57 bit），高位会被舍入，
指针就还原不回来。ARM64 的 48/52 bit VA 同样在边缘。

本机 `grep la57 /proc/cpuinfo` 的结果见 `docs/BUILD_VERIFICATION.md`；我没有在启用
LA57 的内核上实测，所以标为推断。

## 5. 上游仓库自身的两处工程问题 **[已修]**

- 根目录没有 `LICENSE` 文件，MIT 只在每个 `package.xml` 的 `<license>` 里声明；
  `ffmpeg_pipeline_examples/LICENSE` 有 MIT 正文但**没有版权行**。本 fork 补了根
  `LICENSE`（保留原作者版权 + 我的修改版权）。
- `.github/workflows/ci.yml` 里 checkout 硬编码了 `repository: yoshito-n-students/ffmpeg_pipeline`，
  fork 之后 CI 会去拉上游代码、构建的却不是自己的分支。已改为 `${{ github.repository }}`。

## 6. `xmllint` 在受限网络下会撞 60 s 超时 **[已确认·环境相关]** **[已规避]**

`ament_xmllint` 对含 `<?xml-model href="http://download.ros.org/schema/package_format3.xsd"?>`
的 `package.xml` 需要联网取 schema，网络抖动时会超过 `ament_add_test` 默认的 `TIMEOUT 60`
而报 "did not generate a result file" —— 表现为"每次挂的包不一样"的假红。

把 schema 落到本地并用 XML catalog 映射后，同一条校验从"偶发 60 s+"变成 0.002 s，
`ament_xmllint` 稳定 61–63 ms。仓库里给了 `scripts/setup_xml_catalog.sh`：

```bash
sudo bash scripts/setup_xml_catalog.sh
```

这不是代码问题，但会让 CI 出现假红，值得知道。

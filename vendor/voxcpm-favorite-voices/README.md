# VoxCPM 收藏音色包

此包包含 Windows 朗读工具及已收藏的参考音色 WAV，供 Windows 与 Mac 部署和测试。

## 内容

- `favorite_voices/`：收藏的参考音频。
- `favorite_voices.json`：音色名称、WAV 文件和语气描述。
- `VoxCPMReader.py`、`作文朗读网页.py`、`reader_helpers.py`：本地网页朗读工具。

## 使用

安装 VoxCPM2 后，选择收藏音色会使用：

```bash
voxcpm clone --text "要朗读的内容" --control "对应的语气描述" --reference-audio favorite_voices/2.wav --output output.wav
```

Windows 有兼容的 NVIDIA/CUDA 环境时可使用 CUDA；Apple Silicon Mac 建议使用
`--device mps`。两种平台都建议先保持单路 TTS。

此仓库刻意不包含本机设置、日志、缓存、模型文件和生成结果。

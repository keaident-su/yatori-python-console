# ---------- Runtime ----------
# 多架构镜像: 通过 buildx 同时构建 linux/amd64 与 linux/arm64
# (python:3.13-slim 为 Debian 基础镜像, glibc 环境, 与 tls-client/onnxruntime
#  的 manylinux 轮子兼容; 不要改用 Alpine, tls-client 原生库不支持 musl)
FROM python:3.13-slim

# 运行时系统库:
#   tzdata        时区数据(北京时间)
#   libgomp1      onnxruntime(本地OCR)运行所需 OpenMP 运行时
#   libgl1/libglib2.0-0  opencv-python(OCR 依赖)运行所需图形库(无GUI也可运行)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata libgomp1 libgl1 libglib2.0-0 \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 编码与Python运行环境: 统一 UTF-8, 日志实时输出(不缓冲)
ENV TZ=Asia/Shanghai \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 安装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目
COPY . .

# 创建必要运行目录(main.py 运行时也会自动创建, 此处提前创建便于挂载)
RUN mkdir -p assets/sound assets/faces assets/fsces assets/logs

# config.yaml 由运行时挂载提供（不入镜像，避免泄露账号信息）
# 示例: docker run -v $(pwd)/config.yaml:/app/config.yaml -v $(pwd)/assets:/app/assets \
#        ghcr.io/keaident-su/yatori-python-console:latest

ENTRYPOINT ["python", "main.py"]

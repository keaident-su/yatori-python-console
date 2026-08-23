# ---------- Runtime ----------
FROM python:3.13-slim

# 时区设置（北京时间）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 安装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目
COPY . .

# 创建必要运行目录
RUN mkdir -p assets/sound assets/faces logs

# config.yaml 由运行时挂载提供（不入镜像，避免泄露账号信息）
# 示例：docker run -v $(pwd)/config.yaml:/app/config.yaml ghcr.io/keaident-su/yatori-python-console:latest

ENTRYPOINT ["python", "main.py"]

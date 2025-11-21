# ========== Frontend build stage ==========
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend

# 先装依赖（利用缓存）
COPY frontend/package*.json ./
RUN npm ci

# 拷贝源码并构建
COPY frontend/ .
RUN npm run build

# ========== Backend runtime stage ==========
FROM python:3.11-slim AS backend
WORKDIR /backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装后端依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# 从前端阶段拷贝打包产物到后端目录
COPY --from=frontend-builder /frontend/dist ./dist

# 暴露端口
EXPOSE 8080

# # Parameters
# ENV RUN_AS_DEV=False
# ENV USE_LTM=True
# ENV USE_VEC_DB=True
# ENV MAX_TURNS=16

# 拷贝后端源码
COPY backend/trip_planner ./trip_planner
COPY backend/app.py .

# 启动命令
CMD ["python", "app.py"]

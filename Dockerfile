FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir .
ENV HANALPHA_CONFIG_PATH=configs/paper.yaml
EXPOSE 8000
CMD ["hanalpha", "serve", "--host", "0.0.0.0", "--port", "8000"]

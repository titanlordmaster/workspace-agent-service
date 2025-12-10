FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# Install torch CPU wheel first (keeps security scanners happy if you add HF later)
RUN pip install --no-cache-dir \
      torch==2.6.0+cpu \
      --index-url https://download.pytorch.org/whl/cpu

# Now install the rest of your deps (no torch in requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# Hide host GPUs from inside the container so nothing tries to use them
ENV CUDA_VISIBLE_DEVICES=""

COPY app ./app
COPY data ./data
COPY templates ./templates
COPY static ./static

ENV PYTHONPATH=/app

EXPOSE 8082

# NOTE: FastAPI app lives in app.service:app, not app.api
CMD ["uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8082"]

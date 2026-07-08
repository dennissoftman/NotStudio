FROM pytorch/pytorch:2.7.1-cuda12.6-cudnn9-runtime

WORKDIR /app
ENV HF_HOME=/runpod-volume/huggingface

COPY stable-audio-3 /app/stable-audio-3
COPY not-studio/runpod/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir /app/stable-audio-3 -r /app/requirements.txt

COPY not-studio/runpod/handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]

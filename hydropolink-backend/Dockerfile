# Same base image as Jupyter Lab => identical numpy/scikit-learn on s390x,
# so notebook-trained joblib bundles load safely. Already pulled on the VM.
FROM registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
USER root
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY verify_sources.py .
USER 1000
EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

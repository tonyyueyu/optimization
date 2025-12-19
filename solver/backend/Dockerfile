# Dockerfile
FROM --platform=linux/amd64 python:3.9-slim

# ... (Install steps remain the same) ...

# --- UPDATED: Install System Deps for CAD Engine ---
# libgl1-mesa-glx was renamed to libgl1 in newer Debian versions
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*
# -----------------------------------------------

WORKDIR /app
COPY docker-requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m ipykernel install --user --name=math_opt_kernel

COPY . .

# EXPOSE port 8000 for the executor API
EXPOSE 8000

# RUN the executor script, not the main app
CMD ["python", "executor.py"]
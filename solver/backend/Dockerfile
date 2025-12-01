# Dockerfile
FROM python:3.9-slim

# ... (Install steps remain the same) ...

WORKDIR /app
COPY docker-requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m ipykernel install --user --name=math_opt_kernel

COPY . .

# EXPOSE port 8000 for the executor API
EXPOSE 8000

# RUN the executor script, not the main app
CMD ["python", "executor.py"]
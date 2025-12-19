# Use Micromamba for robust binary management (CadQuery + Solvers)
FROM mambaorg/micromamba:latest

# 1. Copy the environment file
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/env.yml

# 2. Install dependencies
# This creates a new environment based on your yaml file and cleans up cache
RUN micromamba install -y -n base -f /tmp/env.yml && \
    micromamba clean --all --yes

# 3. ACTIVATE the environment
# This is crucial: it adds 'ipopt', 'glpsol', and 'highs' to the system PATH
ARG MAMBA_DOCKERFILE_ACTIVATE=1

WORKDIR /app

# 4. Register the kernel
# We install the kernel spec so jupyter_client can find "math_opt_kernel"
RUN python -m ipykernel install --user --name=math_opt_kernel

# 5. Copy your backend code
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# 6. Expose the executor port
EXPOSE 8000

# 7. Start the executor
CMD ["python", "executor.py"]
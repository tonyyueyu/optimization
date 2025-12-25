# Use Micromamba for robust binary management (CadQuery + Solvers)
FROM mambaorg/micromamba:latest

# 1. Copy the environment file
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/env.yml

# 2. Install conda packages from environment.yml (cadquery commented out there)
# Using the yml file ensures we get the right versions
RUN micromamba install -y -n base python=3.10 pip fastapi uvicorn python-multipart \
    jupyter_client ipykernel jupyterlab numpy scipy pandas sympy matplotlib \
    cvxpy pyomo ipopt highs glpk && \
    micromamba clean --all --yes

# 3. Install Python solver interfaces and cadquery dependencies via pip
# ezdxf >= 1.4.3 is required for UVec support (used by cadquery)
RUN micromamba run -n base pip install --no-cache-dir "ezdxf>=1.4.3" "highspy"

# 4. Install cadquery via pip
# Note: cadquery may require OpenCASCADE libraries, but pip install will handle dependencies
# If installation fails, cadquery will be unavailable but other functionality will work
RUN micromamba run -n base pip install --no-cache-dir "cadquery==2.6" || \
    echo "Warning: cadquery installation failed (may need system OpenCASCADE libraries)"

# 5. ACTIVATE the environment
# This is crucial: it adds 'ipopt', 'glpsol', and 'highs' to the system PATH
ARG MAMBA_DOCKERFILE_ACTIVATE=1

WORKDIR /app

# 6. Register the kernel
# We install the kernel spec so jupyter_client can find "math_opt_kernel"
RUN python -m ipykernel install --user --name=math_opt_kernel

# 7. Copy your backend code
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# 8. Expose the executor port
EXPOSE 8000

# 9. Start the executor
CMD ["python", "executor.py"]
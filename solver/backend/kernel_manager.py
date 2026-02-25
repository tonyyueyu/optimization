import queue
import traceback
import base64
from jupyter_client import KernelManager

class PersistentKernel:
    """
    Manages a persistent, headless Jupyter kernel.
    Handles startup, continuous execution, matplotlib headless plotting,
    and capturing execution outputs including code errors.
    """
    def __init__(self, kernel_name='math_kernel'):
        """
        Initializes a persistent Jupyter kernel.
        """
        self.km = KernelManager(kernel_name=kernel_name)
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        
        try:
            # Wait for kernel to be ready
            self.kc.wait_for_ready(timeout=60)
            print(f"✅ Kernel '{kernel_name}' started and ready.")
            
            # Pre-configure the environment for headless plotting and math
            setup_code = (
                "import math as mathlib\n"
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"  # Essential for Docker/Cloud Run
                "import matplotlib.pyplot as plt\n"
            )
            self.execute_code(setup_code, is_init=True)
            
        except Exception as e:
            print(f"❌ Error: Could not start kernel '{kernel_name}': {e}")
            self.shutdown()

    def is_alive(self) -> bool:
        """Checks if the kernel process is still running."""
        return self.km.is_alive()

    def execute_code(self, code_string: str, is_init: bool = False):
        """
        Executes a block of python code and captures all outputs (stdout, stderr, runtime errors, and plots)
        using the Jupyter kernel protocol over ZMQ channels.
        """
        if not code_string or not code_string.strip():
            return {"output": "", "error": "No code provided", "plots": [], "files": []}

        # Prepend mathlib if it's a user request (not internal init)
        full_code = code_string if is_init else f"import math as mathlib\n{code_string}"

        try:
            msg_id = self.kc.execute(full_code)
        except Exception as e:
            return {"output": "", "error": f"Kernel connection error: {str(e)}", "plots": []}

        output_text = []
        error_text = []
        plots = []

        while True:
            try:
                # 120 second timeout for individual messages
                msg = self.kc.get_iopub_msg(timeout=120)
                msg_type = msg['msg_type']
                content = msg['content']

                # Only process messages belonging to our current execution
                if msg.get('parent_header', {}).get('msg_id') != msg_id:
                    continue

                if msg_type == 'stream':
                    if content['name'] == 'stdout':
                        output_text.append(content['text'])
                    elif content['name'] == 'stderr':
                        error_text.append(content['text'])

                elif msg_type == 'error':
                    error_msg = "\n".join(content['traceback'])
                    error_text.append(error_msg)

                elif msg_type in ['display_data', 'execute_result']:
                    data = content.get("data", {})
                    if "image/png" in data:
                        plots.append(data["image/png"])
                    elif "text/plain" in data and msg_type == 'execute_result':
                        output_text.append(data["text/plain"] + "\n")

                if msg_type == 'status' and content['execution_state'] == 'idle':
                    break

            except queue.Empty:
                error_text.append("Timeout: Execution state 'idle' never reached.")
                break
            except Exception as e:
                error_text.append(f"Unexpected error capturing output: {str(e)}")
                break

        return {
            "output": "".join(output_text),
            "error": "".join(error_text),
            "plots": plots
        }

    def shutdown(self):
        """Cleanly shuts down the kernel and channels."""
        try:
            if hasattr(self, 'kc'):
                self.kc.stop_channels()
            if hasattr(self, 'km'):
                self.km.shutdown_kernel(now=True)
            print("Kernel shut down successfully.")
        except Exception as e:
            print(f"Error during kernel shutdown: {e}")

    def cleanup(self):
        """Alias for shutdown used by the executor."""
        self.shutdown()

    def restart(self):
        """Restarts the kernel if it hangs."""
        try:
            self.km.restart_kernel()
            print("Kernel restarted.")
        except Exception as e:
            print(f"Failed to restart kernel: {e}")
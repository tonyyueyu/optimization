import queue
from jupyter_client import KernelManager

class PersistentKernel:
    def __init__(self, kernel_name='math_kernel'): 
        self.km = KernelManager(kernel_name=kernel_name)
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()
        try:
            self.kc.wait_for_ready(timeout=60)
            print(f"Kernel '{kernel_name}' started successfully.")
        except RuntimeError:
            print(f"Error: Could not start kernel '{kernel_name}'.")
            self.shutdown()

    def execute_code(self, code_string):
        if not code_string or not code_string.strip():
            return {"output": "", "error": "No code provided", "plots": []}

        # Prepend mathlib import so users can use math functions without import
        full_code = "import math as mathlib\n" + code_string

        # Send code to the kernel
        try:
            msg_id = self.kc.execute(full_code)
        except Exception as e:
            return {"output": "", "error": f"Connection error: {str(e)}", "plots": []}

        output_text = []
        error_text = []
        plots = []

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=120)

                # 1. Capture standard output
                if msg['msg_type'] == 'stream':
                    content = msg['content']
                    if content['name'] == 'stdout':
                        output_text.append(content['text'])
                    elif content['name'] == 'stderr':
                        error_text.append(content['text'])

                # 2. Capture runtime errors
                elif msg['msg_type'] == 'error':
                    content = msg['content']
                    error_msg = f"{content['ename']}: {content['evalue']}"
                    error_text.append(error_msg)

                # 3. Capture plots
                elif msg['msg_type'] == 'display_data':
                    data = msg['content'].get("data", {})
                    if "image/png" in data:
                        plots.append(data["image/png"])

                # 4. Check if execution is finished
                if msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                    if msg['parent_header'].get('msg_id') == msg_id:
                        break

            except queue.Empty:
                error_text.append("Timeout: Execution took too long.")
                break

        return {
            "output": "".join(output_text),
            "error": "".join(error_text),
            "plots": plots
        }

    def shutdown(self):
        self.km.shutdown_kernel()

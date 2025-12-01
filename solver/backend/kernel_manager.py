import queue
from jupyter_client import KernelManager

class PersistentKernel:
    def __init__(self, kernel_name='math_opt_kernel'):
        # Start the kernel
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
            return {"output": "", "error": "No code provided"}

        # Send code to the kernel
        try:
            msg_id = self.kc.execute(code_string)
        except Exception as e:
            return {"output": "", "error": f"Connection error: {str(e)}"}

        output_text = []
        error_text = []

        while True:
            try:
                # We wait for messages from the kernel
                msg = self.kc.get_iopub_msg(timeout=10)

                # 1. Capture standard output (print statements)
                if msg['msg_type'] == 'stream':
                    content = msg['content']
                    if content['name'] == 'stdout':
                        output_text.append(content['text'])
                    elif content['name'] == 'stderr':
                        error_text.append(content['text'])

                # 2. Capture runtime errors (tracebacks)
                elif msg['msg_type'] == 'error':
                    content = msg['content']
                    # Construct a readable error message
                    error_msg = f"{content['ename']}: {content['evalue']}"
                    error_text.append(error_msg)

                # 3. Check if execution is finished
                if msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                    # Only break if this idle status belongs to OUR execution request
                    if msg['parent_header'].get('msg_id') == msg_id:
                        break
            
            except queue.Empty:
                error_text.append("Timeout: Execution took too long.")
                break

        return {
            "output": "".join(output_text),
            "error": "".join(error_text)
        }

    def shutdown(self):
        self.km.shutdown_kernel()
# executor.py (Runs INSIDE Docker)
from flask import Flask, request, jsonify
from kernel_manager import PersistentKernel

app = Flask(__name__)

# Single global kernel for simplicity (or use a dict for sessions)
# This uses the same class we wrote earlier
kernel = PersistentKernel()

@app.route('/execute', methods=['POST'])
def execute():
    data = request.json
    code = data.get('code', '')
    
    print(f"Executing: {code}") # Log inside container
    
    # Run the code using your existing Logic
    result = kernel.execute_code(code)
    
    return jsonify(result)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ready"})

if __name__ == '__main__':
    # Listen on port 8000 inside the container
    app.run(host='0.0.0.0', port=8000)
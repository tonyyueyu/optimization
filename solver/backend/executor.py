# executor.py (Runs INSIDE Docker)
from flask import Flask, request, jsonify
from kernel_manager import PersistentKernel
import cadquery as cq # Import the CAD engine
import tempfile
import os

app = Flask(__name__)

# Single global kernel for simplicity (or use a dict for sessions)
# This uses the same class we wrote earlier
kernel = PersistentKernel()

def get_cad_info(file_path):
    """Helper to extract volume and bounding box from STEP file"""
    try:
        model = cq.importers.importStep(file_path)
        solid = model.val()
        
        # Calculate properties
        vol = solid.Volume()
        bb = solid.BoundingBox()
        
        return {
            "volume": vol,
            "bbox": {
                "x_len": bb.xlen,
                "y_len": bb.ylen,
                "z_len": bb.zlen
            },
            "summary": f"Volume: {vol:.2f}, BBox: {bb.xlen:.2f}x{bb.ylen:.2f}x{bb.zlen:.2f}"
        }
    except Exception as e:
        return {"error": str(e)}
    
@app.route('/upload_cad', methods=['POST'])
def upload_cad():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    # Save temp file, analyze, then delete
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as temp:
        file.save(temp.name)
        temp_path = temp.name
    
    # Analyze
    result = get_cad_info(temp_path)
    
    # Cleanup
    os.remove(temp_path)
    
    return jsonify(result)

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
"""
Helper script to run Graphify analysis and store knowledge graph outputs cleanly in docs/knowledge/.
"""
import os
import shutil
import subprocess
import sys

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    knowledge_dir = os.path.join(root_dir, "docs", "knowledge")
    os.makedirs(knowledge_dir, exist_ok=True)
    
    print("Running Graphify code analysis...")
    try:
        res = subprocess.run(["graphify", "analyze"], cwd=root_dir, capture_output=True, text=True)
        print(res.stdout)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
    except FileNotFoundError:
        print("graphify CLI is not found in PATH. Install with `pip install graphify` or run graphify directly.")
        return

    # Move any generated root graphify artifacts into docs/knowledge/
    for fname in os.listdir(root_dir):
        if fname.startswith(".graphify_") and fname.endswith(".json"):
            src = os.path.join(root_dir, fname)
            dst = os.path.join(knowledge_dir, fname)
            shutil.move(src, dst)
            print(f"Moved {fname} -> docs/knowledge/")
            
    out_dir = os.path.join(root_dir, "graphify-out")
    if os.path.exists(out_dir):
        dst_out = os.path.join(knowledge_dir, "graphify-out")
        if os.path.exists(dst_out):
            shutil.rmtree(dst_out)
        shutil.move(out_dir, dst_out)
        print("Moved graphify-out -> docs/knowledge/graphify-out")

if __name__ == "__main__":
    main()

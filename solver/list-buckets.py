from google.cloud import storage
import os

# Set this to your actual key filename
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "gcs-key.json"

def list_buckets():
    storage_client = storage.Client()
    buckets = list(storage_client.list_buckets())
    if not buckets:
        print("No buckets found in this project.")
    for bucket in buckets:
        print(f"Bucket Name: {bucket.name}")

if __name__ == "__main__":
    list_buckets()
from app.worker.pipeline.milvus_store import ensure_collection

if __name__ == "__main__":
    ensure_collection()
    print("Milvus collection ready")
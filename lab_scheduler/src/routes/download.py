from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter()

@router.get("/download-db")
def download_db():
    db_path = "lab_scheduler.db"  # ajuste se estiver em outra pasta
    if os.path.exists(db_path):
        return FileResponse(
            path=db_path,
            filename="lab_scheduler.db",
            media_type="application/octet-stream"
        )
    return {"error": "Arquivo lab_scheduler.db não encontrado"}

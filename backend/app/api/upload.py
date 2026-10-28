from fastapi import APIRouter, UploadFile, File, Form
from typing import List
import os
import uuid
import aiofiles

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), \"static\", \"uploads\")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post(\"/upload\")
async def upload_files(work_order_text: str = Form(...), files: List[UploadFile] = File(...)):
    uploaded = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            continue
        filename = f\"{uuid.uuid4()}{ext}\"
        filepath = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(filepath, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
        uploaded.append({
            \"filename\": filename,
            \"url\": f\"/static/uploads/{filename}\",
            \"original_name\": file.filename
        })
    return {
        \"uploaded\": uploaded,
        \"count\": len(uploaded),
        \"work_order_text\": work_order_text
    }

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# from fastapi.staticfiles import StaticFiles

from src.config.config import FASTAPI_AUTH, FASTAPI_BEARER_TOKEN
from src.routers import (
    health_router,
    pdf_router,
    omniai_router,
    docx_router,
    ppt_router,
    mineru_router,
    mineru_sci_router,
    mineru_with_images_router,
    weaviate_router,
)

load_dotenv()

bearer_scheme = HTTPBearer()


def validate_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    if credentials.scheme != "Bearer" or credentials.credentials != FASTAPI_BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return credentials


app = FastAPI(
    title="TianGong AI Unstructure Serve",
    version="1.0",
    description="TianGong AI Unstructure API Server",
    dependencies=[Depends(validate_token)] if FASTAPI_AUTH else None,
)

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router.router)
app.include_router(pdf_router.router)
app.include_router(omniai_router.router)
app.include_router(docx_router.router)
app.include_router(ppt_router.router)
app.include_router(mineru_router.router)
app.include_router(mineru_sci_router.router)
app.include_router(mineru_with_images_router.router)
app.include_router(weaviate_router.router)

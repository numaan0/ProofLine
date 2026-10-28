from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    APP_NAME: str = "ProofLine API"
    META_API_KEY: str = ""
    HF_TOKEN: str = ""
    BASETEN_API_KEY: str = ""
    MODAL_TOKEN: str = ""
    
    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        env_file_encoding = 'utf-8'

settings = Settings()

"""M6 FastAPI: 브라우저 검사 → M2/M3/M5 → MySQL 이력 (기본 로컬 SQLite)."""
from __future__ import annotations
import os, secrets
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel,Field
from typing import Literal
from pipeline import InspectionService
from db import Store

BASE=Path(__file__).resolve().parent
app=FastAPI(title='A1-M6 CSV 기반 검사·근거 검색',version='3.0.0')
security=HTTPBasic(auto_error=False)
service=InspectionService()
store=Store()

class InspectInput(BaseModel):
    html:str=Field(min_length=1,max_length=20000)
    method:Literal['tfidf','bm25']='tfidf'
    k:int=Field(default=2,ge=1,le=5)

def auth(creds:HTTPBasicCredentials | None=Depends(security)):
    user=os.getenv('BASIC_USER'); pwd=os.getenv('BASIC_PASSWORD')
    if not user and not pwd and os.getenv('APP_ENV','development')=='development': return
    if not (user and pwd): raise HTTPException(503,'운영 인증 정보 미설정')
    if not creds or not(secrets.compare_digest(creds.username,user) and secrets.compare_digest(creds.password,pwd)):
        raise HTTPException(401,'인증 필요',headers={'WWW-Authenticate':'Basic'})

@app.get('/')
def home(_=Depends(auth)):
    return FileResponse(BASE/'web'/'index.html')

@app.get('/health')
def health(): return {'status':'ok'}

@app.get('/ready')
def ready():
    try:
        service.cache_info();store.ready()
        return {'status':'ready'}
    except Exception: raise HTTPException(503,'데이터 또는 DB 연결 확인 필요')

@app.post('/api/inspect')
def inspect(body:InspectInput,_=Depends(auth)):
    try:
        result,hit=service.inspect(body.html,body.method,body.k)
        run_id=store.save(result,hit)
        return {**result,'run_id':run_id,'cache_hit':hit,'release_revision':os.getenv('RELEASE_REVISION','local')}
    except (ValueError,KeyError) as exc: raise HTTPException(400,str(exc))

@app.get('/api/history')
def history(_=Depends(auth)): return store.history()

@app.get('/api/history/{run_id}')
def detail(run_id:str,_=Depends(auth)):
    item=store.detail(run_id)
    if not item: raise HTTPException(404,'해당 기록 없음')
    return item

@app.get('/api/cache')
def cache(_=Depends(auth)): return service.cache_info()

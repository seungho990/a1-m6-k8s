"""M6 검사 기록. SQLite는 로컬 테스트 전용, 운영 DB는 별도 MySQL.
원본 HTML은 저장하지 않고 해시와 판정 결과만 저장한다.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON, Boolean, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

class Base(DeclarativeBase):
    pass

class InspectionRun(Base):
    __tablename__ = 'inspection_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda:str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda:datetime.now(timezone.utc))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    rule_hash: Mapped[str] = mapped_column(String(64))
    tree_hash: Mapped[str] = mapped_column(String(64))
    preprocess_version: Mapped[str] = mapped_column(String(32))
    release_revision: Mapped[str] = mapped_column(String(100), default='local')
    method: Mapped[str] = mapped_column(String(16))
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict] = mapped_column(JSON)
    findings: Mapped[list['InspectionFinding']] = relationship(cascade='all, delete-orphan')

class InspectionFinding(Base):
    __tablename__ = 'inspection_findings'
    id: Mapped[int] = mapped_column(Integer,primary_key=True,autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('inspection_runs.id'),index=True)
    target: Mapped[str] = mapped_column(String(128))
    rule_id: Mapped[str] = mapped_column(String(64),index=True)
    scope: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)

class Store:
    def __init__(self,url: str | None = None):
        url = url or os.getenv('DATABASE_URL','sqlite:///./inspect_demo.db')
        opts={'connect_args':{'check_same_thread':False}} if url.startswith('sqlite') else {}
        self.engine=create_engine(url,pool_pre_ping=True,**opts)
        self.Session=sessionmaker(self.engine,expire_on_commit=False)
        Base.metadata.create_all(self.engine) # 교육용; 운영 마이그레이션은 Alembic으로

    def ready(self):
        with self.engine.connect() as conn: conn.execute(text('SELECT 1'))

    def save(self,result: dict,hit: bool) -> str:
        with self.Session.begin() as db:
            run=InspectionRun(input_hash=result['input_sha256'],rule_hash=result['rule_hash'],
                 tree_hash=result['tree_hash'],preprocess_version=result['preprocess_version'],
                 method=result['method'], cache_hit=hit, summary=result['summary'],
                 release_revision=os.getenv('RELEASE_REVISION','local'))
            db.add(run); db.flush()
            review={(i['target'],i['rule_id']):i for i in result['review_items']}
            for f in result['all_findings']:
                matched=review.get((f['target'],f['rule_id']),{})
                db.add(InspectionFinding(run_id=run.id,target=f['target'][:128],
                  rule_id=f['rule_id'],scope=f['scope'],outcome=f['outcome'],message=f['message'],
                  evidence={'rule_version':f['rule_version'], 'reason':f['reason'],
                    'reference_url':f['reference_url'], 'direct_rule':matched.get('direct_rule'),
                    'related_rule_candidates':matched.get('related_rule_candidates',[])}))
            return run.id

    def history(self, limit:int=15):
        with self.Session() as db:
            rows=db.scalars(select(InspectionRun).order_by(InspectionRun.created_at.desc(),InspectionRun.id.desc()).limit(limit)).all()
            return [{'run_id':r.id,'created_at':r.created_at.isoformat(),
                     'rule_hash':r.rule_hash,'tree_hash':r.tree_hash,
                     'preprocess_version':r.preprocess_version,'release_revision':r.release_revision,
                     'method':r.method,'cache_hit':r.cache_hit,'summary':r.summary} for r in rows]

    def detail(self,run_id:str):
        with self.Session() as db:
            r=db.get(InspectionRun,run_id)
            if r is None: return None
            fs=db.scalars(select(InspectionFinding).where(InspectionFinding.run_id==run_id).order_by(InspectionFinding.id)).all()
            return {'run_id':r.id,'created_at':r.created_at.isoformat(),
                    'method':r.method,'release_revision':r.release_revision,
                    'rule_hash':r.rule_hash,'tree_hash':r.tree_hash,
                    'preprocess_version':r.preprocess_version,'cache_hit':r.cache_hit,
                    'input_sha256':r.input_hash,'summary':r.summary,
                    'all_findings':[{'target':f.target,'rule_id':f.rule_id,'scope':f.scope,
                                     'outcome':f.outcome,'message':f.message,'evidence':f.evidence} for f in fs]}

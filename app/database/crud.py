from sqlalchemy import select
from .database import SessionLocal, engine, Base
from . import models as m

HOSPITALS = [("H-VIC", "Victoria Hospital", 12.9634, 77.5755), ("H-STJ", "St. John's Hospital", 12.9300, 77.6190),
             ("H-MAN", "Manipal Hospital", 12.9581, 77.6480), ("H-BBH", "Bangalore Baptist Hospital", 13.0378, 77.5886)]
DEMO_VEHICLES = ["AMB-101", "AMB-102", "AMB-103", "AMB-104", "AMB-105"]


def _d(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


def init_db():
    Base.metadata.create_all(engine)


def seed(vehicles=True):
    with SessionLocal() as db:
        if not db.scalars(select(m.Hospital).limit(1)).first():
            db.add_all([m.Hospital(id=i, name=n, lat=a, lon=b) for i, n, a, b in HOSPITALS])
        if vehicles:
            for v in DEMO_VEHICLES:
                if not db.get(m.Vehicle, v):
                    db.add(m.Vehicle(id=v, name=v))
        db.commit()


def add(obj):
    with SessionLocal() as db:
        db.add(obj); db.commit(); db.refresh(obj)
        return _d(obj)


def rows(model, limit=100, desc_by=None, **flt):
    with SessionLocal() as db:
        q = select(model).filter_by(**flt)
        if desc_by:
            q = q.order_by(getattr(model, desc_by).desc())
        return [_d(x) for x in db.scalars(q.limit(limit))]


def upsert_vehicle(vid, name=None):
    with SessionLocal() as db:
        if not db.get(m.Vehicle, vid):
            db.add(m.Vehicle(id=vid, name=name or vid)); db.commit()


def save_route(rid, vid, dest, dist, dur, src, eta, pts):
    with SessionLocal() as db:
        db.merge(m.Route(id=rid, vehicle_id=vid, destination=dest, distance_m=dist, duration_s=dur, source=src, planned_eta=eta))
        db.query(m.RoutePoint).filter_by(route_id=rid).delete()
        db.bulk_save_objects([m.RoutePoint(route_id=rid, seq=i, lat=a, lon=b) for i, (a, b) in enumerate(pts)])
        db.commit()


def set_incident_active(iid=None, source=None, active=False):
    with SessionLocal() as db:
        q = db.query(m.Incident).filter_by(active=True)
        if iid is not None:
            q = q.filter_by(id=iid)
        if source:
            q = q.filter_by(source=source)
        q.update({"active": active}); db.commit()


def deactivate_recs(primary_id):
    with SessionLocal() as db:
        db.query(m.DispatchRecommendation).filter_by(primary_id=primary_id, active=True).update({"active": False}); db.commit()

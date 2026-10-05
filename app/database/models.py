from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from .database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(String(32), primary_key=True)
    name = Column(String(64))
    kind = Column(String(32), default="ambulance")
    registered_at = Column(DateTime, default=datetime.now)


class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_id = Column(String(32), index=True)
    ts = Column(DateTime, default=datetime.now)
    latitude = Column(Float); longitude = Column(Float)
    speed = Column(Float); heading = Column(Float)
    emergency = Column(Boolean); destination = Column(String(80)); route_id = Column(String(64))


class Route(Base):
    __tablename__ = "routes"
    id = Column(String(64), primary_key=True)
    vehicle_id = Column(String(32), index=True)
    destination = Column(String(80))
    distance_m = Column(Float); duration_s = Column(Float)
    source = Column(String(16))          # osrm | fallback
    planned_eta = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class RoutePoint(Base):
    __tablename__ = "route_points"
    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(String(64), index=True)
    seq = Column(Integer)
    lat = Column(Float); lon = Column(Float)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16))            # congestion | accident | closure
    lat = Column(Float); lon = Column(Float)
    radius_m = Column(Float, default=500); severity = Column(Float, default=0.7)
    description = Column(Text, default="")
    source = Column(String(16), default="OPERATOR")   # OPERATOR | SIMULATION
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)


class Hospital(Base):
    __tablename__ = "hospitals"
    id = Column(String(16), primary_key=True)
    name = Column(String(80)); lat = Column(Float); lon = Column(Float)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.now)
    level = Column(String(8)); vehicle_id = Column(String(32), index=True); message = Column(Text)


class DispatchRecommendation(Base):
    __tablename__ = "dispatch_recommendations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.now)
    primary_id = Column(String(32), index=True); backup_id = Column(String(32))
    distance_km = Column(Float); response_min = Column(Float); delay_min = Column(Float)
    reason = Column(Text); active = Column(Boolean, default=True)

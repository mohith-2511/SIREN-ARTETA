"""python -m app.database.init_db  -> create tables and seed demo hospitals/vehicles."""
from app.core.config import settings
from app.database import crud

if __name__ == "__main__":
    crud.init_db()
    crud.seed(vehicles=settings.SIMULATION_MODE)
    print(f"Database ready: {settings.DATABASE_URL} (hospitals + demo vehicles seeded)")

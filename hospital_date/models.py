# models.py
from sqlalchemy import Column, Integer, String, Date
from database import Base

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    surname = Column(String, nullable=False)
    date = Column(Date, nullable=False, index=True)
    worker = Column(String, nullable=False)
    time = Column(String, nullable=False)